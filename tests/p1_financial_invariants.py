"""Pricing identity, missing-cost, multi-region joins and burn recovery regressions.

python tests/p1_financial_invariants.py --promtool /path/to/promtool
No server or network is needed. Numerical fixtures use the generated rules.
"""
from __future__ import annotations

import argparse
import copy
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import forge_dashboards as f  # noqa: E402
import pricing_sources as pricing  # noqa: E402


def context():
    cap = f.selftest_capability()
    entry = cap["signals"]["prom-selftest"]["otel_genai"]
    entry["models_seen"] = ["alpha", "beta"]
    entry["discovery_coverage"] = {
        "scope": "backend_returned_values", "local_truncation": False,
        "backend_completeness": "unknown", "counts": {
            "metric_names": len(entry["metric_names"]), "models_seen": 2,
            "providers_seen": len(entry.get("providers_seen", []))}}
    cap["signals"] = {"prom-selftest": {"otel_genai": entry}}
    registry = {"_meta": {"verified_at": "2026-09-01"}, "models": [
        {"id": model, "aliases": [], "input_per_mtok": 2, "output_per_mtok": 3,
         "region": "us", "vendor": "Fixture", "pricing_source_kind": "official"}
        for model in entry["models_seen"]]}
    return f.Ctx(cap, registry, "inline")


class FinancialP1Tests(unittest.TestCase):
    def test_seed_ids_and_aliases_remain_exact_matches(self):
        registry = f.load_registry()
        for model in registry["models"]:
            for name in [model["id"]] + model["aliases"]:
                with self.subTest(name=name):
                    _, actual, status = pricing.resolve_registry_model(name, registry["models"])
                    self.assertEqual((status, actual["id"]), ("matched", model["id"]))

    def test_unknown_names_never_inherit_substring_prices(self):
        registry = f.load_registry()
        for name in ("my-gpt-5.4-production", "gpt-4", "qwen", "gpt-5.4-turbo",
                     "gpt-5.4-mini-custom", "claude-opus-4-820260115"):
            with self.subTest(name=name):
                self.assertEqual(pricing.resolve_registry_model(name, registry["models"])[2], "absent")
                self.assertEqual(pricing.models_needing_fallback([name], registry), [name])
                self.assertEqual(pricing._registry_destinations(name, registry["models"]),
                                 {("new", pricing.normalize_model_name(name))})

    def test_generic_qwen_ids_do_not_inherit_versioned_model_prices(self):
        registry = f.load_registry()
        for generic, versioned in (("qwen-max", "qwen3.7-max"),
                                   ("qwen-plus", "qwen3.6-plus")):
            for suffix in ("", "-20261008", "_20261008", "-2026-10-08"):
                name = generic + suffix
                with self.subTest(name=name):
                    self.assertEqual(pricing.resolve_registry_model(name, registry["models"]),
                                     (None, None, "absent"))
                    self.assertEqual(pricing.models_needing_fallback([name], registry), [name])
                    self.assertEqual(pricing._registry_destinations(name, registry["models"]),
                                     {("new", pricing.normalize_model_name(name))})
                with self.subTest(name=versioned + suffix):
                    _, model, status = pricing.resolve_registry_model(versioned + suffix,
                                                                       registry["models"])
                    self.assertEqual(status, "matched")
                    self.assertEqual(model["id"], versioned)

    def test_only_delimited_calendar_dates_are_compatible(self):
        models = f.load_registry()["models"]
        for suffix in ("-20260115", "_20260115", "-2026-01-15"):
            _, model, status = pricing.resolve_registry_model("claude-opus-4-8" + suffix, models)
            self.assertEqual((status, model["id"]), ("matched", "claude-opus-4.8"))
        for suffix in ("-20260230", "-20261301", "-2026-1-15", "-20260115-preview", "20260115"):
            self.assertEqual(pricing.resolve_registry_model("claude-opus-4-8" + suffix, models)[2], "absent")

    def test_exact_dated_id_wins_and_ambiguous_aliases_are_refused(self):
        models = [{"id": "alpha", "aliases": []}, {"id": "alpha-20260115", "aliases": []}]
        self.assertEqual(pricing.resolve_registry_model("alpha-20260115", models)[1]["id"], "alpha-20260115")
        models[0]["aliases"] = ["duplicate"]
        models[1]["aliases"] = ["duplicate"]
        self.assertEqual(pricing.resolve_registry_model("duplicate", models)[2], "ambiguous")
        self.assertEqual(pricing._registry_destinations("duplicate", models),
                         {("registry", 0), ("registry", 1)})

    def test_burn_and_budget_evaluate_current_expressions(self):
        rules = f.build_alerts(context(), "folder", 100)
        burns = [rule for rule in rules if "llm-burn-" in rule["uid"]]
        self.assertEqual(len(burns), 2)
        for rule in rules:
            model = rule["data"][0]["model"]
            if rule in burns or "llm-daily-budget" in rule["uid"]:
                self.assertTrue(model["instant"])
                self.assertFalse(model["range"])
                self.assertEqual(rule["noDataState"], "OK" if rule in burns else "NoData")
            else:
                self.assertTrue(model["range"])
                self.assertNotIn("instant", model)


def numerical_checks(promtool, directory):
    ctx = context()
    cases = []
    token = ctx.primary.tok + "_sum"

    def series(direction, values, model="alpha", extra=""):
        return {"series": token + '{gen_ai_token_type="' + direction
                + '",gen_ai_request_model="' + model + '"' + extra + '}', "values": values}

    def add(name, inputs, expected, *, expr=None, at="10m"):
        cases.append({"name": name, "interval": "1m", "input_series": inputs,
                      "promql_expr_test": [{"expr": expr or ctx.cost_source.expr(window="5m"),
                                            "eval_time": at, "exp_samples": [] if expected is None
                                            else [{"labels": "{}", "value": expected}]}]})

    for agg in ("rate", "increase"):
        expr = ctx.cost_source.expr(window="5m", agg=agg)
        scale = 300 if agg == "increase" else 1
        add(f"{agg}: total absence stays unknown", [], None, expr=expr)
        add(f"{agg}: real zero stays zero", [series("input", "0+0x10")], 0, expr=expr)
        add(f"{agg}: input only", [series("input", "0+600x10")], 0.00002 * scale, expr=expr)
        add(f"{agg}: output only", [series("output", "0+1200x10")], 0.00006 * scale, expr=expr)
        add(f"{agg}: both directions conserve cost", [series("input", "0+600x10"),
            series("output", "0+1200x10")], 0.00008 * scale, expr=expr)
        add(f"{agg}: another priced model suffices", [series("input", "0+600x10", "beta")],
            0.00002 * scale, expr=expr)
        add(f"{agg}: unrelated model cannot establish coverage", [series("input", "0+600x10", "unknown")],
            None, expr=expr)
        add(f"{agg}: one sample is not calculable", [series("input", "_ _ _ _ _ 0")],
            None, expr=expr, at="5m")
        add(f"{agg}: reset is handled as a counter", [series("input", "0 600 1200 0 600 1200")],
            0.000015 * scale, expr=expr, at="5m")
        add(f"{agg}: expired stale series stays unknown", [series("input", "0+600x4 stale" + " _" * 10)],
            None, expr=expr, at="15m")
        add(f"{agg}: gap with sufficient samples remains calculable", [series("input", "0 600 1200 _ _ 3000")],
            0.00002 * scale, expr=expr, at="5m")

    partial = copy.deepcopy(ctx.registry)
    partial["models"][0]["output_per_mtok"] = None
    partial_ctx = f.Ctx(ctx.cap, partial, "inline")
    add("unpriced direction alone cannot turn missing priced input into zero",
        [series("output", "0+1200x10")], None, expr=partial_ctx.cost_source.expr(window="5m"))
    add("zero-dollar price with real data is still zero", [series("input", "0+600x10")], 0,
        expr=f.cost_rate_expr(ctx.primary, [{"seen": "alpha", "reg": {
            "input_per_mtok": 0, "output_per_mtok": 0}}], window="5m"))

    multiregion = [series(direction, values, extra=',region="' + region + '",vendor="' + vendor + '"')
                  for direction, values in (("input", "0+600x10"), ("output", "0+1200x10"))
                  for region, vendor in (("eu-west", "Deployment-A"), ("us-east", "Deployment-B"))]
    add("recorded total conserves multi-region and multi-vendor usage", multiregion, 0.00016,
        expr=f"sum({f.COST_RECORDED})")
    add("recorded provenance retains provider origin", multiregion, 0.00016,
        expr=f'sum({f.COST_RECORDED}{{region="us",vendor="Fixture"}})')
    add("recorded total retains an input-only model", [series("input", "0+600x10")], 0.00002,
        expr=f"sum({f.COST_RECORDED})")

    duration = ctx.primary.dur + "_count"
    recovery = [{"series": duration + '{error_type="provider_error"}',
                 "values": "0+600x360 " + "216000 " * 60},
                {"series": duration + '{error_type=""}',
                 "values": "0+0x360 " + " ".join(str(600 * n) for n in range(1, 61))}]
    for rule in f.build_alerts(ctx, "folder", 100):
        if "llm-burn-" in rule["uid"]:
            expr = rule["data"][0]["model"]["expr"]
            add(rule["uid"] + ": breach is present", recovery, 1, expr=expr, at="6h")
            add(rule["uid"] + ": recovery is absent immediately", recovery, None, expr=expr, at="7h")

    directory = pathlib.Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rules_path = directory / "p1_cost_rules.yml"
    f.emit_recording_rules(ctx, str(rules_path))
    fixture = directory / "p1_financial_invariants.yml"
    # Ignore last-bit differences from USD-per-token floating-point arithmetic.
    fixture.write_text(json.dumps({"rule_files": [str(rules_path.resolve())], "fuzzy_compare": True,
        "evaluation_interval": "1m", "tests": cases}, indent=2), encoding="utf-8")
    print(f"{len(cases)} numerical P1 cases -> {fixture}", flush=True)
    return subprocess.run([promtool, "test", "rules", str(fixture)], check=False).returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--promtool")
    ap.add_argument("--out-dir")
    args = ap.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(FinancialP1Tests))
    if not result.wasSuccessful():
        return 1
    if args.promtool:
        if args.out_dir:
            return numerical_checks(args.promtool, args.out_dir)
        with tempfile.TemporaryDirectory(prefix="forge-p1-financial-") as directory:
            return numerical_checks(args.promtool, directory)
    return 0


if __name__ == "__main__":
    sys.exit(main())
