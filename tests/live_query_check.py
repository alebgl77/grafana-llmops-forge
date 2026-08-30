"""Contrôle « requêtes vivantes » : chaque expression générée est-elle exécutable
ET retourne-t-elle des données sur un vrai Prometheus ?

Le harnais hors ligne valide la structure ; celui-ci valide la sémantique. Il
sonde un Prometheus réel (alimenté par demo/emitter.py), construit la capability
map à partir de ce qu'il y trouve, lance la forge, puis exécute chaque requête
de chaque panneau et de chaque règle d'alerte.

    python3 tests/live_query_check.py --prometheus http://localhost:9090

Sortie : nombre d'expressions vides / en erreur, avec le panneau fautif. Codes :
0 = tout renvoie des données, 1 = au moins une expression vide ou invalide.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import discover  # noqa: E402

# Expressions dont un résultat vide est le comportement CORRECT.
EXPECTED_EMPTY = (
    re.compile(r"llm:cost_usd_per_second"),      # tant que les rules ne tournent pas
    re.compile(r"offset \d+[smhd]"),             # comparaison à une période inexistante
    re.compile(r"error_type!=\"\""),             # aucun échec sur une fenêtre courte
)


def q(base: str, expr: str) -> tuple[str, int]:
    url = base + "/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return "error:" + json.load(e)["error"][:110], 0
        except Exception:
            return f"http {e.code}", 0
    except Exception as e:
        return f"unreachable: {e}", 0
    if d.get("status") != "success":
        return "error:" + str(d.get("error"))[:110], 0
    res = d["data"]["result"]
    return ("ok" if res else "empty"), len(res)


def names(base: str, pattern: str) -> list:
    url = (base + "/api/v1/label/__name__/values?"
           + urllib.parse.urlencode({"match[]": '{__name__=~"%s"}' % pattern}))
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return sorted(json.load(r)["data"])
    except Exception:
        return []


def label_values(base: str, label: str, match: str) -> list:
    url = (base + f"/api/v1/label/{label}/values?"
           + urllib.parse.urlencode({"match[]": match}))
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.load(r)["data"]
    except Exception:
        return []


def build_map(base: str) -> dict:
    """Même logique que discover.py, mais directement contre Prometheus."""
    sig = {}
    for dialect, pattern in discover.DIALECT_SIGNATURES.items():
        found = names(base, pattern)
        if not found:
            continue
        e = {"metric_names": found}
        sample = '{__name__=~"%s"}' % pattern
        for cand in discover.MODEL_LABEL_CANDIDATES.get(dialect, []):
            v = label_values(base, cand, sample)
            if v:
                e["model_label"], e["models_seen"] = cand, v[:60]
                break
        for cand in discover.PROVIDER_LABEL_CANDIDATES.get(dialect, []):
            v = label_values(base, cand, sample)
            if v:
                e["provider_label"], e["providers_seen"] = cand, v[:40]
                break
        if dialect == "otel_genai":
            for cand in ("gen_ai_token_type", "gen_ai.token.type", "token_type"):
                if set(label_values(base, cand, sample)) & {"input", "output"}:
                    e["token_type_label"] = cand
                    break
        for cand in discover.TEAM_LABEL_CANDIDATES:
            v = label_values(base, cand, sample)
            if v and len(v) <= 500:
                e.setdefault("group_labels", []).append(
                    {"label": cand, "cardinality": len(v)})
        sig[dialect] = e
    return {"instance": {"version": "0.0.0", "major": 12, "edition": "oss"},
            "datasources": {"prometheus": [{"uid": "live", "exemplars": False}],
                            "loki": [], "tempo": [], "other": []},
            "signals": {"live": sig}, "gaps": []}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prometheus", default="http://localhost:9090")
    ap.add_argument("--wait-for-data", type=float, default=120,
                    help="Secondes d'attente d'un premier trafic scrapé. Un "
                         "nombre de scrapes deviné est un pile ou face : on "
                         "attend la donnée.")
    ap.add_argument("--out-dir", default="/tmp/live_forge")
    ap.add_argument("--capability", default="/tmp/live_cap.json")
    a = ap.parse_args()
    base = a.prometheus.rstrip("/")

    # Attendre que Prometheus ait effectivement ingéré du trafic : sans cela on
    # mesure la lenteur du démarrage plutôt que la justesse des requêtes.
    probe = 'count({__name__=~".*gen_ai[._].*|litellm.*|vllm:.*"})'
    deadline = time.time() + a.wait_for_data
    while not q(base, probe)[1] and time.time() < deadline:
        time.sleep(3)
    waited = a.wait_for_data - (deadline - time.time())
    print(f"premières séries visibles après {waited:.0f}s")

    cap = build_map(base)
    dialects = sorted(cap["signals"]["live"])
    print(f"Dialectes vus dans Prometheus : {dialects}")
    if not dialects:
        print("Aucun signal — l'émetteur tourne-t-il ?", file=sys.stderr)
        return 1
    json.dump(cap, open(a.capability, "w"), indent=2)

    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "forge_dashboards.py"),
                        "--capability", a.capability, "--blueprints", "auto",
                        "--with-alerts", "--out-dir", a.out_dir],
                       capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr, file=sys.stderr)
        return 1
    print(r.stdout.strip().splitlines()[-1])

    checks, empty, errors = 0, [], []
    for f in sorted(os.listdir(a.out_dir)):
        if not f.endswith(".json") or f.startswith("deploy_"):
            continue
        d = json.load(open(os.path.join(a.out_dir, f)))
        items = []
        if f.startswith("alert_"):
            items = [(d["title"], d["data"][0]["model"]["expr"])]
        else:
            items = [(p.get("title", ""), t["expr"])
                     for p in d.get("panels", []) for t in p.get("targets", [])
                     if t.get("expr") and p.get("datasource", {}).get("type")
                     == "prometheus"]
        for title, expr in items:
            e = expr.replace("$__rate_interval", "5m").replace("$__range", "30m")
            e = e.replace("$__interval", "1m").replace('=~"$model"', '=~".+"')
            status, n = q(base, e)
            checks += 1
            if status.startswith("error"):
                errors.append((f, title, status, e[:120]))
            elif status == "empty" and not any(p.search(e) for p in EXPECTED_EMPTY):
                empty.append((f, title, e[:120]))

    print(f"\n{checks} expressions exécutées contre {base}")
    for f, t, s, e in errors:
        print(f"  ❌ ERREUR  [{f}] {t}\n      {s}\n      {e}")
    for f, t, e in empty:
        print(f"  ⚠ VIDE    [{f}] {t}\n      {e}")
    if not errors and not empty:
        print("  ✅ toutes les expressions renvoient des données")
    return 1 if (errors or empty) else 0


if __name__ == "__main__":
    sys.exit(main())
