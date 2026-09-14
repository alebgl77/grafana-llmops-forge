"""Numerical recorded-cost regressions, evaluated by a real Prometheus engine.

    python tests/recorded_cost_invariants.py --promtool /path/to/promtool

Fixtures are generated from cost_rate_expr itself; JSON is valid YAML accepted
by promtool. All input series start at t=0 with explicit sampling intervals.
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
sys.path.insert(0, str(ROOT / "scripts"))
import forge_dashboards as forge  # noqa: E402

COST = forge.COST_RECORDED


def expression(window="1h", cadence="1m", region=None):
    return forge.cost_rate_expr(None, [], region=region, window=window,
                                agg="increase", recorded=True,
                                recorded_interval=cadence)


def series(values, labels=""):
    return {"series": COST + labels, "values": values}


def sequence(*parts):
    return " ".join(str(value) for value, count in parts for _ in range(count))


def fixture_cases():
    cases = []

    def add(name, inputs, expected, *, window="1h", cadence="1m",
            interval="1m", at="1h", tolerance=0, region=None,
            grafana_range="1h", grafana_seconds=3600):
        expr = expression(window, cadence, region)
        # Expand the longer macro FIRST: replacing $__range first corrupts _s.
        expr = expr.replace("$__range_s", str(grafana_seconds)).replace(
            "$__range", grafana_range)
        if tolerance:
            # Step fixtures have a known continuous integral. A jump may land
            # in one grid cell or at an aligned boundary: error <= step*jump.
            expr = f"abs(({expr}) - {expected}) <= bool {tolerance}"
            expected = 1
        samples = [] if expected is None else [{"labels": "{}", "value": expected}]
        cases.append({"name": name, "interval": interval, "input_series": inputs,
                      "promql_expr_test": [{"expr": expr, "eval_time": at,
                                            "exp_samples": samples}]})

    constant = [series("1+0x62")]
    add("constant 1 USD/s, t=0..60m, exactly 3600 USD", constant, 3600)
    add("Grafana range macros preserve seconds", constant, 3600, window="$__range")
    add("unaligned range end t=60m30s has no extra-sample charge", constant, 3600,
        at="60m30s")
    add("two models conserve their sum", [series("1+0x60", '{model="a"}'),
                                          series("2+0x60", '{model="b"}')], 10800)
    add("real zero is zero", [series("0+0x60")], 0)
    add("complete absence is absent, not zero", [], None)
    add("regional selection is preserved", [series("1+0x60", '{region="eu"}'),
                                             series("2+0x60", '{region="us"}')],
        3600, region="eu")
    add("rate or price jumps 1 to 3 at t=30m; integral=7200 +/-120 USD",
        [series(sequence((1, 30), (3, 31)))], 7200, tolerance=120)
    add("second model starts at t=30m, no whole-hour extrapolation",
        [series("1+0x60", '{model="a"}'),
         series(sequence(("_", 30), (2, 31)), '{model="b"}')], 7200, tolerance=120)
    add("only model starts at t=30m; incomplete range stays absent",
        [series(sequence(("_", 30), (1, 31)))], None)
    add("ten-minute collection gap t=20..29m invalidates coverage",
        [series(sequence((1, 20), ("_", 10), (1, 31)))], None)
    add("even one missing aggregate grid cell is incomplete",
        [series(sequence((1, 30), ("_", 1), (1, 30)))], None)
    add("stale series does not silently become a complete partial bill",
        [series(sequence((1, 30), ("stale", 1), ("_", 30)))], None)
    add("one-minute window is exactly 60 USD", constant, 60, window="1m")
    add("window below one grid cell is absent", constant, None, window="59s")
    add("non-multiple duration is normalized in seconds", constant, 90, window="90s")
    add("fractional second duration keeps its units", constant, 90.5, window="1m30s500ms")
    add("composite duration is supported", [series("1+0x90")], 5400,
        window="1h30m", at="1h30m")
    add("configured 2m recording cadence integrates to 3600 USD",
        [series("1+0x30")], 3600, cadence="2m", interval="2m")
    add("gap exceeding configured 2m cadence is incomplete",
        [series(sequence((1, 10), ("_", 3), (1, 18)))], None,
        cadence="2m", interval="2m")
    add("window below configured 2m cadence is absent",
        [series("1+0x30")], None, window="1m", cadence="2m", interval="2m")
    add("30s recording cadence keeps a bounded minimum 1m query grid",
        [series("1+0x120")], 3600, cadence="30s", interval="30s")
    return cases


def check_generator_contract():
    for value in ("", "0m", "-1m", "1m1h", "1m2m", "NaN", "1e3s", "١m",
                  "1m] or vector(99) #", "1m\n", "$__rate_interval", "9" * 65 + "s"):
        for field in ("window", "cadence"):
            try:
                expression(**{field: value})
            except ValueError:
                pass
            else:
                raise AssertionError(f"invalid {field} accepted: {value!r}")
    assert "$__range_s" in expression("$__range")
    assert "[1h:1m]" in expression(cadence="30s")
    assert "[1h:2m]" in expression(cadence="2m")
    assert forge.cost_rate_expr(None, [], recorded=True) == (
        "sum(llm:cost_usd_per_second)")
    cap = forge.selftest_capability()
    ctx = forge.Ctx(cap, {"models": []})
    lite = ctx.q["litellm"]
    assert forge.cost_rate_expr(lite, [], window="1h", agg="increase") == (
        f"sum(increase({lite.spend}[1h]))")
    matched = [{"seen": "test", "reg": {"input_per_mtok": 1, "output_per_mtok": 2}}]
    inline = forge.cost_rate_expr(ctx.primary, matched, window="1h", agg="increase")
    assert "increase(" in inline and "_sum{" in inline and "avg_over_time" not in inline
    cap["signals"]["prom-selftest"]["recorded"] = {"metric_names": [COST]}
    ctx = forge.Ctx(cap, {"models": []})
    ctx.rules_interval = "2m"
    budget = next(rule for rule in forge.build_alerts(ctx, "folder", 100)
                  if rule["title"] == "LLM · Daily budget exceeded")
    assert budget["data"][0]["model"]["expr"] == (
        "(sum(llm:cost_usd_per_second)) * 86400")


def run(promtool, out_dir):
    check_generator_contract()
    cases = fixture_cases()
    path = pathlib.Path(out_dir) / "recorded_cost_invariants.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"evaluation_interval": "1m", "tests": cases}, indent=2),
                    encoding="utf-8")
    print(f"{len(cases)} numerical cases, generated from cost_rate_expr -> {path}", flush=True)
    result = subprocess.run([promtool, "test", "rules", str(path)], check=False)
    if result.returncode == 0:
        print("Recorded-cost invariants passed (plus duration/counter/budget contracts).")
    return result.returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--promtool", default=os.environ.get("PROMTOOL", "promtool"))
    ap.add_argument("--out-dir", help="Keep generated fixtures in this directory")
    args = ap.parse_args()
    if args.out_dir:
        return run(args.promtool, args.out_dir)
    with tempfile.TemporaryDirectory(prefix="forge-recorded-cost-") as tmp:
        return run(args.promtool, tmp)


if __name__ == "__main__":
    sys.exit(main())
