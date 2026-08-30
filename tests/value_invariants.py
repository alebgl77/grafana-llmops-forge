"""Invariants de valeur sur données réelles.

`live_query_check.py` prouve que les requêtes renvoient quelque chose. Celui-ci
prouve que ce quelque chose est cohérent : des quantiles ordonnés, des ratios
bornés, et surtout les deux chemins de calcul du coût (composition à la volée
vs recording rules) qui doivent converger. Un tableau de bord plausible et faux
est le mode de défaillance propre à l'observabilité — c'est celui-ci qu'on
attrape ici.

    python3 tests/value_invariants.py --prometheus http://localhost:9090
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request

FAILS = []


def check(name, ok, detail=""):
    print(("  ✅ " if ok else "  ❌ ") + name + ("" if ok else f" — {detail}"))
    if not ok:
        FAILS.append(name)


def q(base: str, expr: str, at: float | None = None):
    params = {"query": expr}
    if at is not None:
        params["time"] = repr(at)
    u = base + "/api/v1/query?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(u, timeout=25) as r:
            return json.load(r)["data"]["result"]
    except Exception:
        return None


def scalar(base: str, expr: str, at: float | None = None):
    r = q(base, expr, at)
    if not r:
        return None
    try:
        return float(r[0]["value"][1])
    except (KeyError, IndexError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prometheus", default="http://localhost:9090")
    ap.add_argument("--wait-for-rules", type=float, default=210,
                    help="Secondes d'attente de la matérialisation des recording "
                         "rules. Prometheus décale la première évaluation d'un "
                         "groupe jusqu'à l'intervalle du groupe : attendre une "
                         "durée devinée est un pile ou face, on attend la série.")
    ap.add_argument("--tolerance", type=float, default=0.25,
                    help="Écart relatif toléré entre les deux chemins de coût. "
                         "Large à dessein : deux expressions rate() évaluées à "
                         "des instants différents sur une charge variable ne "
                         "s'accordent pas au pourcent près. Ce seuil attrape "
                         "une erreur de formule (facteur ~6 quand le coût des "
                         "tokens de sortie disparaissait), pas du bruit.")
    a = ap.parse_args()
    b = a.prometheus.rstrip("/")

    COST = "llm:cost_usd_per_second"
    D = "gen_ai_client_operation_duration_seconds"
    T = "gen_ai_client_token_usage_token"

    print("--- quantiles ordonnés ---")
    p = {}
    for lvl in (0.50, 0.95, 0.99):
        p[lvl] = scalar(b, f"histogram_quantile({lvl}, sum by(le)"
                           f"(rate({D}_bucket[5m])))")
    if all(v is not None for v in p.values()):
        check("p50 <= p95 <= p99", p[0.50] <= p[0.95] + 1e-9 <= p[0.99] + 1e-9,
              f"{p[0.50]:.3f} / {p[0.95]:.3f} / {p[0.99]:.3f}")
    else:
        check("quantiles disponibles", False, str(p))

    print("--- ratios bornés ---")
    ratio = scalar(b, f'sum(rate({D}_count{{error_type!=""}}[5m])) '
                      f"/ clamp_min(sum(rate({D}_count[5m])), 1e-9)")
    check("taux d'erreur dans [0,1]", ratio is not None and 0 <= ratio <= 1,
          str(ratio))
    avail = None if ratio is None else 1 - ratio
    check("disponibilité dans [0,1]", avail is not None and 0 <= avail <= 1,
          str(avail))

    print("--- conservation des tokens ---")
    tin = scalar(b, f'sum(rate({T}_sum{{gen_ai_token_type="input"}}[5m]))')
    tout = scalar(b, f'sum(rate({T}_sum{{gen_ai_token_type="output"}}[5m]))')
    check("tokens input et output strictement positifs",
          (tin or 0) > 0 and (tout or 0) > 0, f"in={tin} out={tout}")
    check("input > output (les prompts pèsent plus que les réponses ici)",
          (tin or 0) > (tout or 0), f"in={tin} out={tout}")

    print("--- convergence des deux chemins de coût ---")
    deadline = time.time() + a.wait_for_rules
    _rec = q(b, f"sum({COST})")
    while not _rec and time.time() < deadline:
        time.sleep(5)
        _rec = q(b, f"sum({COST})")
    if _rec:
        waited = a.wait_for_rules - (deadline - time.time())
        print(f"  (recording rules matérialisées après {waited:.0f}s)")
    recorded = float(_rec[0]["value"][1]) if _rec else None
    # La série enregistrée date de la dernière évaluation de la règle (jusqu'à
    # un intervalle de retard). Comparer à un calcul « maintenant » mesurerait
    # la variation de charge, pas un désaccord de formule : on évalue donc le
    # chemin composé À L'HORODATAGE du point enregistré.
    at = float(_rec[0]["value"][0]) if _rec else None
    if recorded is None:
        check("recording rules chargées", False,
              f"{COST} absent après {a.wait_for_rules:.0f}s — le fichier de "
              "règles est-il bien monté, et le groupe évalué ?")
    else:
        # même formule, composée à la volée depuis le registre de prix enregistré
        inline = scalar(
            b,
            f'sum(sum by(gen_ai_request_model)(rate({T}_sum'
            f'{{gen_ai_token_type="input"}}[5m])) * on(gen_ai_request_model) '
            f"llm:price_input_usd_per_token) + "
            f'sum(sum by(gen_ai_request_model)(rate({T}_sum'
            f'{{gen_ai_token_type="output"}}[5m])) * on(gen_ai_request_model) '
            f"llm:price_output_usd_per_token)", at=at)
        if inline is None:
            check("chemin composé calculable", False, "expression vide")
        else:
            ecart = abs(inline - recorded) / max(abs(recorded), 1e-12)
            check(f"coût recorded == coût composé (écart {ecart:.4%})",
                  ecart <= a.tolerance,
                  f"recorded={recorded:.8f} composé={inline:.8f}")
        # Invariant exact, lui : la règle composite doit être la somme de ses
        # deux composantes. C'est ce contrôle qui aurait attrapé le `or` fautif.
        ci = scalar(b, f"sum({COST}:input)", at=at)
        co = scalar(b, f"sum({COST}:output)", at=at)
        if ci is not None and co is not None:
            check("total == coût(input) + coût(output), exactement",
                  abs((ci + co) - recorded) / max(recorded, 1e-12) < 1e-9,
                  f"{ci:.8f} + {co:.8f} != {recorded:.8f}")
            check("le coût de sortie n'est pas absorbé (piège du `or`)",
                  co > 0 and ci > 0 and recorded > max(ci, co) * 1.05,
                  f"input={ci:.8f} output={co:.8f} total={recorded:.8f}")
        check("coût strictement positif", recorded > 0, str(recorded))
        parts = q(b, "sum by(region)(llm:cost_usd_per_second)", at=at)
        total_parts = sum(float(x["value"][1]) for x in parts) if parts else 0
        check("somme des régions == total",
              abs(total_parts - recorded) / max(recorded, 1e-12) <= 1e-6,
              f"{total_parts} vs {recorded}")

    print("--- cohérence inter-panneaux ---")
    reqs = scalar(b, f"sum(rate({D}_count[5m]))")
    if reqs and recorded:
        cpr = recorded / reqs
        check("coût par requête plausible (entre 1e-7 et 1 USD)",
              1e-7 <= cpr <= 1, f"{cpr:.8f} USD/req")

    print("\n" + "=" * 54)
    print("✅ INVARIANTS RESPECTÉS" if not FAILS else f"❌ {len(FAILS)} invariant(s) violé(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
