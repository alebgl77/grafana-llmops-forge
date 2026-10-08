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
import math
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

class PrometheusCheckError(RuntimeError):
    """An unavailable or malformed backend is never interpreted as no data."""


def _json_response(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:
        raise PrometheusCheckError(f"HTTP {error.code}") from None
    except Exception as error:
        raise PrometheusCheckError(f"request failed ({type(error).__name__})") from None
    if not isinstance(body, dict) or body.get("status") != "success" or "data" not in body:
        raise PrometheusCheckError("invalid or unsuccessful Prometheus response")
    return body


def _finite_sample(sample) -> bool:
    if not isinstance(sample, list) or len(sample) != 2:
        return False
    timestamp, value = sample
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not isinstance(value, str):
        return False
    try:
        finite = math.isfinite(timestamp) and math.isfinite(float(value))
    except (ValueError, OverflowError):
        return False
    if not finite:
        raise PrometheusCheckError("non-finite sample")
    return True


def _result_count(data) -> int:
    if not isinstance(data, dict):
        raise PrometheusCheckError("query data is not an object")
    kind, result = data.get("resultType"), data.get("result")
    if kind == "scalar":
        if _finite_sample(result):
            return 1
        raise PrometheusCheckError("scalar is malformed or non-finite")
    if kind not in {"vector", "matrix"} or not isinstance(result, list):
        raise PrometheusCheckError("unsupported or malformed query result")
    for item in result:
        if not isinstance(item, dict) or not isinstance(item.get("metric"), dict):
            raise PrometheusCheckError("sample has invalid labels")
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in item["metric"].items()):
            raise PrometheusCheckError("sample has invalid labels")
        samples = [item.get("value")] if kind == "vector" else item.get("values")
        if not isinstance(samples, list) or not samples or not all(_finite_sample(s) for s in samples):
            raise PrometheusCheckError("sample is malformed or non-finite")
    return len(result)


def expected_empty(filename: str, title: str, expression: str) -> bool:
    """Explicit conditional outputs, never a metric-name-wide exception."""
    if filename.startswith(("alert_alr-llm-burn-fast-", "alert_alr-llm-burn-slow-")):
        return title.startswith("LLM · ") and "error-budget burn" in title and " and " in expression
    # The synthetic emitter creates an error-labelled series only after the
    # first failed execute_tool call; an empty error-only rate is normal before.
    if filename == "agents.json" and title == "Tool errors/s":
        return (expression.startswith("sum(rate(") and expression.endswith("[5m]))")
                and '="execute_tool"' in expression and '!=""' in expression)
    return (filename == "adoption.json" and title == "New adopters (7d)"
            and re.search(r"\boffset\s+7d\b", expression) is not None)


def q(base: str, expr: str) -> tuple[str, int]:
    url = base + "/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    try:
        count = _result_count(_json_response(url)["data"])
    except PrometheusCheckError as error:
        return "error:" + str(error), 0
    return ("ok" if count else "empty"), count


def names(base: str, pattern: str) -> list:
    url = (base + "/api/v1/label/__name__/values?"
           + urllib.parse.urlencode({"match[]": '{__name__=~"%s"}' % pattern}))
    values = _json_response(url)["data"]
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise PrometheusCheckError("metric names are not a string list")
    return sorted(set(values))


def label_values(base: str, label: str, match: str) -> list:
    url = (base + f"/api/v1/label/{label}/values?"
           + urllib.parse.urlencode({"match[]": match}))
    values = _json_response(url)["data"]
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise PrometheusCheckError("label values are not a string list")
    return sorted(set(values))


def msel_probe(metric: str) -> str:
    """Un nom UTF-8 doit être quoté ; un nom classique s'écrit tel quel."""
    import re as _re
    return metric if _re.fullmatch(r"[a-zA-Z_:][a-zA-Z0-9_:]*", metric) \
        else '{"' + metric + '"}'


def build_map(base: str) -> dict:
    """Même logique que discover.py, mais directement contre Prometheus."""
    sig = {}
    for dialect, pattern in discover.DIALECT_SIGNATURES.items():
        found = names(base, pattern)
        if not found:
            continue
        e = {"metric_names": found}
        sample = '{__name__=~"%s"}' % pattern
        discover.enrich_signal_entry(
            e, dialect, lambda label, match: label_values(base, label, match), sample)
        sig[dialect] = e
    return {"org_id": 1,
            "instance": {"version": "0.0.0", "major": 12, "edition": "oss"},
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

    # La découverte d'abord : elle n'a besoin que d'un seul scrape (API de
    # labels), et elle donne un NOM DE MÉTRIQUE RÉEL sur lequel sonder.
    # Sonder par regex balayait tous les buckets d'histogramme et dépassait le
    # délai de la requête, si bien que l'attente ne se terminait jamais.
    deadline = time.time() + a.wait_for_data
    try:
        cap = build_map(base)
        while not cap["signals"]["live"] and time.time() < deadline:
            time.sleep(3)
            cap = build_map(base)
    except PrometheusCheckError as error:
        print(f"Discovery failed: {error}", file=sys.stderr)
        return 1

    # Puis attendre que rate() soit calculable : une série existe dès le premier
    # scrape, mais rate() exige deux points dans sa fenêtre.
    counters = [n for sig in cap["signals"]["live"].values()
                for n in sig["metric_names"]
                if n.endswith("_count") or n.endswith("_total")]
    if counters:
        probe = f"sum(rate({msel_probe(counters[0])}[2m])) > 0"
        while True:
            status, count = q(base, probe)
            if status not in {"ok", "empty"}:
                print(f"Traffic probe failed: {status}", file=sys.stderr)
                return 1
            if status == "ok" and count > 0:
                break
            if time.time() >= deadline:
                print("No usable traffic before the deadline", file=sys.stderr)
                return 1
            time.sleep(3)
    waited = a.wait_for_data - (deadline - time.time())
    print(f"données exploitables après {waited:.0f}s")

    dialects = sorted(cap["signals"]["live"])
    print(f"Dialectes vus dans Prometheus : {dialects}")
    if not dialects:
        print("Aucun signal : l'émetteur tourne-t-il ?", file=sys.stderr)
        return 1
    with open(a.capability, "w", encoding="utf-8") as handle:
        json.dump(cap, handle, indent=2)

    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "forge_dashboards.py"),
                        "--capability", a.capability, "--blueprints", "auto",
                        "--with-alerts", "--out-dir", a.out_dir],
                       capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr, file=sys.stderr)
        return 1
    if r.stdout.strip():
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
            e = (expr.replace("$__rate_interval", "5m")
                 .replace("$__range_s", "1800").replace("$__range", "30m"))
            e = e.replace("$__interval", "1m").replace('=~"$model"', '=~".+"')
            status, n = q(base, e)
            # The first global counter becoming ready does not guarantee two
            # samples for every model histogram. Wait within the same startup
            # budget; transport/schema failures always fail immediately.
            intentional_empty = expected_empty(f, title, e)
            while ((status == "empty" and not intentional_empty)
                   or status == "error:non-finite sample") and time.time() < deadline:
                time.sleep(min(1, max(0, deadline - time.time())))
                status, n = q(base, e)
            checks += 1
            if status not in {"ok", "empty"} or (status == "ok" and n <= 0):
                errors.append((f, title, status, e[:120]))
            elif status == "empty" and not intentional_empty:
                empty.append((f, title, e[:120]))

    print(f"\n{checks} expressions exécutées contre {base}")
    for f, t, s, e in errors:
        print(f"  ❌ ERREUR  [{f}] {t}\n      {s}\n      {e}")
    for f, t, e in empty:
        print(f"  ⚠ VIDE    [{f}] {t}\n      {e}")
    if not checks:
        print("  ❌ aucune expression Prometheus vérifiée", file=sys.stderr)
    elif not errors and not empty:
        print("  ✅ toutes les expressions renvoient des données")
    return 1 if (not checks or errors or empty) else 0


if __name__ == "__main__":
    sys.exit(main())
