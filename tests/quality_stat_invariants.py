"""Quality statistics retain their meaning in generated EN/FR dashboards.

python tests/quality_stat_invariants.py --promtool /path/to/promtool
The CLI exports are checked before their actual queries run in Prometheus.
No server, network, or third-party Python dependency is required.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCORE = "gen_ai_evaluation_score"
MODEL = "gen_ai_request_model"
RATE = "$__rate_interval"

GAUGE_TEXT = {
    "en": [
        ("Mean score", "Unweighted mean across current score series; not an "
         "observation-weighted mean or a population quantile."),
        ("Minimum score", "Minimum across current score series; not a population quantile.")],
    "fr": [
        ("Score moyen", "Moyenne non pondérée des séries de scores courantes ; ce n'est "
         "ni une moyenne pondérée des observations ni un quantile de population."),
        ("Score minimum", "Minimum des séries de scores courantes ; ce n'est pas "
         "un quantile de population.")]}
HISTOGRAM_TEXT = {
    "en": [("Median score", ""),
           ("Low decile (p10)", "The low tail is the real signal; the mean hides the failures."),
           ("Score by model (p50)", "A model switch that lowers this panel is a "
            "cost/quality trade-off worth documenting.")],
    "fr": [("Score médian", ""),
           ("Décile bas (p10)", "La queue basse est le vrai signal : la moyenne masque les échecs."),
           ("Score par modèle (p50)", "Une bascule de modèle qui fait baisser ce panel "
            "est un arbitrage coût/qualité à documenter.")]}


def generate_dashboards(out_dir):
    boards = {}
    for histogram in (False, True):
        mode = "histogram" if histogram else "gauge"
        metrics = ([SCORE + suffix for suffix in ("_bucket", "_sum", "_count")]
                   if histogram else [SCORE, SCORE + "_count"])
        cap = {"org_id": 1, "instance": {"major": 13}, "signals": {
            "quality-test": {"evals": {"metric_names": metrics + ["guardrail_blocked_total"],
                                       "model_label": MODEL}}}}
        for locale in ("en", "fr"):
            directory = pathlib.Path(out_dir) / f"{mode}-{locale}"
            directory.mkdir(parents=True, exist_ok=True)
            capability = directory / "capability.json"
            capability.write_text(json.dumps(cap), encoding="utf-8")
            result = subprocess.run([
                sys.executable, str(ROOT / "scripts" / "forge_dashboards.py"),
                "--capability", str(capability), "--blueprints", "quality",
                "--locale", locale, "--out-dir", str(directory)],
                capture_output=True, text=True, check=False)
            assert result.returncode == 0, result.stdout + result.stderr
            boards[mode, locale] = json.loads((directory / "quality.json").read_text(encoding="utf-8"))
    return boards


def check_panels(boards):
    for (mode, locale), board in boards.items():
        panels = board["panels"]
        expected = HISTOGRAM_TEXT[locale] if mode == "histogram" else GAUGE_TEXT[locale]
        score_panels = panels[:2] + ([panels[3]] if mode == "histogram" else [])
        actual = [(p["title"], p["description"]) for p in score_panels]
        assert actual == expected, f"{mode}/{locale}: {actual!r} != {expected!r}"
        assert len(panels) == (6 if mode == "histogram" else 5)
        for panel in panels[:2]:
            assert panel["fieldConfig"]["defaults"]["unit"] == "percentunit"
            assert panel["targets"][0]["instant"] is True
            assert panel["targets"][0]["range"] is False
        if mode == "gauge":
            assert [p["targets"][0]["expr"] for p in panels[:2]] == [
                f"avg({SCORE})", f"min({SCORE})"]
            assert not any("p50" in p["title"] for p in panels)
        else:
            for panel, quantile, labels in ((panels[0], "0.5", "le"),
                                             (panels[1], "0.1", "le"),
                                             (panels[3], "0.5", f"le,{MODEL}")):
                assert panel["targets"][0]["expr"] == (
                    f"histogram_quantile({quantile}, sum by({labels})"
                    f"(rate({SCORE}_bucket[{RATE}])))")
        assert panels[2]["targets"][0]["expr"] == f"sum(rate(guardrail_blocked_total[{RATE}]))"
        assert panels[-2]["targets"][0]["expr"] == f"sum(rate({SCORE}_count[{RATE}]))"
    print("4 CLI exports passed: gauge mean/minimum and histogram p50/p10, EN/FR.", flush=True)


def numerical_checks(promtool, boards, out_dir):
    def query(panel, value, labels="{}"):
        return {"expr": panel["targets"][0]["expr"].replace(RATE, "5m"),
                "eval_time": "10m", "exp_samples": [{"labels": labels, "value": value}]}

    gauge = boards["gauge", "en"]["panels"]
    histogram = boards["histogram", "en"]["panels"]
    gauge_checks = [query(gauge[0], 0.4), query(gauge[1], 0.1),
                    query(gauge[2], 2), query(gauge[-2], 3)]
    # Controls make the naming error discriminating: the same gauge series
    # have median 0.2 and interpolated p10 0.12, not mean 0.4/minimum 0.1.
    # Bound interpolation roundoff explicitly, far below the 0.02 minimum
    # separation from the statistics being distinguished. Exported queries stay exact.
    for quantile, value in ((0.5, 0.2), (0.1, 0.12)):
        gauge_checks.append({"expr": f"abs(quantile({quantile}, {SCORE}) - {value}) <= bool 1e-12",
                             "eval_time": "10m",
                             "exp_samples": [{"labels": "{}", "value": 1}]})
    cases = [{
        "name": "gauge: current series mean/minimum differ from quantiles",
        "interval": "1m", "input_series": [
            {"series": f'{SCORE}{{{MODEL}="{model}"}}', "values": f"{score}+0x10"}
            for model, score in (("a", 0.1), ("b", 0.2), ("c", 0.9))] + [
                {"series": SCORE + "_count", "values": "0+180x10"},
                {"series": "guardrail_blocked_total", "values": "0+120x10"}],
        "promql_expr_test": gauge_checks}, {
        "name": "histogram: p50/p10, per-model p50, volume and guardrails preserved",
        "interval": "1m", "input_series": [
            {"series": f'{SCORE}_bucket{{{MODEL}="a",le="{bound}"}}',
             "values": f"0+{increment}x10"}
            for bound, increment in (("0.2", 60), ("1", 300), ("+Inf", 300))] + [
                {"series": SCORE + "_count", "values": "0+300x10"},
                {"series": "guardrail_blocked_total", "values": "0+120x10"}],
        "promql_expr_test": [query(histogram[0], 0.5), query(histogram[1], 0.1),
                             query(histogram[2], 2), query(histogram[3], 0.5, f'{{{MODEL}="a"}}'),
                             query(histogram[-2], 5)]}]
    path = pathlib.Path(out_dir) / "quality_stat_invariants.yml"
    path.write_text(json.dumps({"evaluation_interval": "1m", "fuzzy_compare": True,
                               "tests": cases}, indent=2),
                    encoding="utf-8")
    print(f"9 exported queries + 2 quantile controls -> {path}", flush=True)
    return subprocess.run([promtool, "test", "rules", str(path)], check=False).returncode


def run(promtool, out_dir):
    boards = generate_dashboards(out_dir)
    check_panels(boards)
    return numerical_checks(promtool, boards, out_dir)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--promtool", default=os.environ.get("PROMTOOL", "promtool"))
    ap.add_argument("--out-dir", help="Keep generated CLI exports and Prometheus fixtures here")
    args = ap.parse_args()
    if args.out_dir:
        return run(args.promtool, args.out_dir)
    with tempfile.TemporaryDirectory(prefix="forge-quality-") as temp:
        return run(args.promtool, temp)


if __name__ == "__main__":
    sys.exit(main())
