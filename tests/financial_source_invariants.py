"""Financial scope/CLI regressions; optional real-promtool absence/zero checks.

python tests/financial_source_invariants.py --promtool /path/to/promtool
No live Grafana or external pricing endpoint is contacted.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import forge_dashboards as f  # noqa: E402

REGISTRY = {"_meta": {"verified_at": "2026-09-01"}, "models": [{
    "id": "gpt-5.4", "aliases": [], "input_per_mtok": 2.5, "output_per_mtok": 15,
    "vendor": "Test", "region": "us", "pricing_source_kind": "official"}]}


def signals(*dialects):
    original = f.selftest_capability()["signals"]["prom-selftest"]
    result = {dialect: copy.deepcopy(original[dialect]) for dialect in dialects}
    if "otel_genai" in result:
        result["otel_genai"]["models_seen"] = ["gpt-5.4"]
    return result


def recorded(name=f.COST_RECORDED):
    return {"recorded": {"metric_names": [name]}}


def capability(sources, names=None):
    return {"org_id": 1, "signals": sources, "datasources": {
        "prometheus": [{"uid": uid, "name": (names or {}).get(uid, uid)} for uid in sources],
        "loki": [], "tempo": []}, "instance": {"major": 13}}


def budget(ctx):
    return next(rule for rule in f.build_alerts(ctx, "folder", 100)
                if rule["title"] == "LLM · Daily budget exceeded")


class FinancialSourceTests(unittest.TestCase):
    def cli(self, cap, *extra, fallback=None):
        with tempfile.TemporaryDirectory(prefix="forge-financial-cli-") as temp:
            directory = pathlib.Path(temp)
            path = directory / "capability.json"
            path.write_text(json.dumps(cap), encoding="utf-8")
            output = directory / "output"
            argv = ["forge", "--capability", str(path), "--out-dir", str(output), *extra]
            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                    f, "GrafanaClient", side_effect=AssertionError("remote client before validation")) as remote, \
                    mock.patch.object(f.pricing_sources, "apply_artificial_analysis_fallback",
                                      side_effect=fallback or AssertionError("pricing network attempted")) as pricing, \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = f.main()
            files = {item.name: item.read_text(encoding="utf-8") for item in output.glob("*")}
            return code, stdout.getvalue(), stderr.getvalue(), files, remote.call_count, pricing.call_args_list

    def test_recorded_b_with_otel_a_never_crosses_scopes(self):
        ctx = f.Ctx(capability({"a": signals("otel_genai"), "b": recorded()}), REGISTRY)
        self.assertEqual(ctx.primary.s.ds_uid, "a")
        self.assertEqual((ctx.cost_source.mode, ctx.cost_source.ds_uid), ("recorded", "b"))
        board = f.bp_finops(ctx).d
        self.assertNotIn("Average cost per request", [p["title"] for p in board["panels"]])
        self.assertIn("Cost per request unavailable", [p["title"] for p in board["panels"]])
        self.assertTrue(all(p["datasource"]["uid"] == "b" for p in board["panels"] if p.get("targets")))
        self.assertEqual(budget(ctx)["data"][0]["datasourceUid"], "b")
        self.assertEqual(budget(ctx)["noDataState"], "NoData")

    def test_native_cost_does_not_replace_otel_gateway_or_rules(self):
        cap = capability({"a": signals("otel_genai"), "b": signals("litellm")})
        ctx = f.Ctx(cap, REGISTRY)
        self.assertEqual((ctx.cost_source.mode, ctx.cost_source.ds_uid), ("native", "b"))
        self.assertEqual(ctx.primary.s.ds_uid, "a")
        self.assertEqual(f.bp_gateway(ctx).d["panels"][0]["datasource"]["uid"], "a")
        self.assertIn("rate(gen_ai_client_token_usage_token_sum", "\n".join(f._rule_lines(ctx, "", "5m")[0]))
        self.assertEqual(budget(ctx)["data"][0]["datasourceUid"], "b")
        result = self.cli(cap, "--blueprints", "finops")
        self.assertEqual(result[0], 0, result[2])
        manifest = json.loads(result[3]["deploy_manifest.json"])
        self.assertEqual(manifest["financial_source"]["datasource_uid"], "b")
        self.assertEqual(manifest["recording_rules"]["datasource_uid"], "a")

    def test_recorded_exact_metric_is_found_beyond_first_dialect_entry(self):
        cap = capability({"a": signals("otel_genai"), "b": {
            "custom": {"metric_names": [f.COST_RECORDED]}}})
        ctx = f.Ctx(cap, REGISTRY)
        self.assertEqual((ctx.cost_source.mode, ctx.cost_source.ds_uid), ("recorded", "b"))

    def test_recorded_only_produces_cost_and_budget(self):
        ctx = f.Ctx(capability({"b": recorded()}), REGISTRY)
        self.assertIsNone(ctx.primary)
        self.assertIsNotNone(f.bp_finops(ctx))
        self.assertEqual(budget(ctx)["data"][0]["datasourceUid"], "b")

    def test_budget_is_instant_while_operational_slo_queries_are_unchanged(self):
        ctx = f.Ctx(capability({"a": signals("otel_genai", "litellm")}), REGISTRY)
        rule = budget(ctx)
        self.assertTrue(rule["data"][0]["model"]["instant"])
        self.assertFalse(rule["data"][0]["model"]["range"])
        self.assertIn("[10m]", rule["data"][0]["model"]["expr"])
        self.assertEqual(rule["noDataState"], "NoData")
        for operational in f.build_alerts(ctx, "folder", 100):
            if operational["uid"] != rule["uid"]:
                self.assertTrue(operational["data"][0]["model"]["range"])
                self.assertNotIn("instant", operational["data"][0]["model"])

    def test_component_is_not_total_and_recorded_mode_requires_exact_name(self):
        cap = capability({"b": recorded(f.COST_RECORDED + ":input")})
        self.assertIsNone(f.Ctx(cap, REGISTRY).cost_source)
        with self.assertRaisesRegex(ValueError, "exact total"):
            f.bp_finops(f.Ctx(cap, REGISTRY, "recorded"))
        code, _, err, files, calls, _ = self.cli(cap, "--blueprints", "finops", "--cost-mode", "recorded", "--deploy")
        self.assertEqual((code, calls, files), (2, 0, {}))
        self.assertIn("exact total", err)

    def test_every_priority_rejects_multiple_sources(self):
        for source in (recorded(), signals("litellm"), signals("otel_genai")):
            with self.subTest(source=next(iter(source))):
                ctx = f.Ctx(capability({"a": copy.deepcopy(source), "b": source}), REGISTRY)
                self.assertEqual(ctx.financial_status, "ambiguous")
                with self.assertRaisesRegex(ValueError, "--datasource"):
                    ctx.require_financial_source()

    def test_preflight_ambiguity_before_remote_client_or_pricing(self):
        cap = capability({"a": recorded(), "b": recorded()})
        for extra in (("--blueprints", "finops"), ("--blueprints", "gateway", "--with-alerts")):
            with self.subTest(extra=extra):
                result = self.cli(cap, *extra, "--deploy", "--pricing-fallback", "artificial-analysis")
                self.assertEqual((result[0], result[3], result[4], result[5]), (2, {}, 0, []))
                self.assertIn("Ambiguous recorded", result[2])

    def test_pure_operations_do_not_require_financial_selection(self):
        cap = capability({"a": signals("otel_genai") | recorded(), "b": recorded()})
        result = self.cli(cap, "--blueprints", "gateway,governance")
        self.assertEqual(result[0], 0, result[2])
        self.assertIn("gateway.json", result[3])
        self.assertEqual(json.loads(result[3]["deploy_manifest.json"])["financial_source"]["status"], "ambiguous")

    def test_filter_by_uid_or_unique_name_and_manifest(self):
        cap = capability({"a": recorded(), "b": recorded()}, {"a": "Production", "b": "Staging"})
        original = copy.deepcopy(cap)
        for selector in ("b", "Staging"):
            filtered = f.filter_capability_datasource(cap, selector)
            self.assertEqual(set(filtered["signals"]), {"b"})
            self.assertEqual(f.Ctx(filtered, REGISTRY).cost_source.ds_uid, "b")
            filtered["signals"]["b"]["recorded"]["metric_names"].append("test")
        self.assertEqual(cap, original)
        result = self.cli(cap, "--blueprints", "finops", "--datasource", "Production")
        self.assertEqual(result[0], 0, result[2])
        selected = json.loads(result[3]["deploy_manifest.json"])["financial_source"]
        self.assertEqual((selected["status"], selected["mode"], selected["datasource_uid"]), ("selected", "recorded", "a"))
        self.assertEqual(selected["availability"], "not_checked")

    def test_filter_unknown_and_duplicate_name_fail_before_remote(self):
        cap = capability({"a": recorded(), "b": recorded()}, {"a": "Same", "b": "Same"})
        for selector in ("unknown", "Same"):
            result = self.cli(cap, "--datasource", selector, "--deploy")
            self.assertEqual((result[0], result[3], result[4]), (2, {}, 0))
            self.assertIn("--datasource", result[2])
            self.assertNotIn("Traceback", result[2])

    def test_legacy_map_without_datasource_metadata_supports_uid(self):
        cap = {"signals": {"legacy": recorded()}, "org_id": 1}
        ctx = f.Ctx(f.filter_capability_datasource(cap, "legacy"), REGISTRY)
        self.assertEqual(ctx.cost_source.ds_uid, "legacy")
        self.assertIsNone(f.Ctx({"signals": {}}, REGISTRY).cost_source)

    def test_inline_ignores_recorded_but_keeps_native_priority(self):
        cap = capability({"a": recorded(), "b": signals("otel_genai", "litellm")})
        ctx = f.Ctx(cap, REGISTRY, "inline")
        self.assertEqual((ctx.cost_source.mode, ctx.cost_source.ds_uid), ("native", "b"))

    def test_native_or_recorded_never_claim_registry_fallback_provenance(self):
        registry = copy.deepcopy(REGISTRY)
        registry["models"][0]["pricing_source_kind"] = "artificial_analysis"
        for extra in (signals("litellm"), recorded()):
            cap = capability({"a": signals("otel_genai"), "b": extra})
            before = copy.deepcopy(cap)
            ctx = f.Ctx(cap, registry)
            self.assertIn("artificial_analysis", "\n".join(f._rule_lines(ctx, "", "5m")[0]))
            text = json.dumps(f.bp_finops(ctx).d)
            self.assertNotIn("Artificial Analysis", text)
            self.assertNotIn("Models missing from the price registry", text)
            self.assertEqual(ctx.pricing_models(), ["gpt-5.4"])
            self.assertEqual(cap, before)

    def test_fallback_filters_models_first_and_remains_useful_to_otel_rules(self):
        cap = capability({"a": signals("otel_genai"), "b": signals("otel_genai", "litellm")})
        cap["signals"]["a"]["otel_genai"]["models_seen"] = ["must-not-price"]
        def fallback(registry, seen, *args, **kwargs):
            self.assertEqual(seen, ["gpt-5.4"])
            return {"registry": registry, "warnings": [], "priced": [], "cache_used": False, "fetched": False}
        result = self.cli(cap, "--datasource", "b", "--blueprints", "finops",
                          "--pricing-fallback", "artificial-analysis", fallback=fallback)
        self.assertEqual(result[0], 0, result[2])
        self.assertEqual(len(result[5]), 1)
        self.assertIn("prometheus_rules_llmops.yml", result[3])
        self.assertEqual(json.loads(result[3]["deploy_manifest.json"])["financial_source"]["mode"], "native")


def numerical_absence_checks(promtool, out_dir):
    cases = []
    for mode, data in (("recorded", recorded()), ("native", signals("litellm"))):
        source = f.Ctx(capability({"p": data}), REGISTRY).cost_source
        metric = f.COST_RECORDED if mode == "recorded" else source.q.spend
        for agg in ("rate", "increase"):
            expr = source.expr(window="5m", agg=agg)
            for absent in (True, False):
                cases.append({"name": f"{mode}/{agg}: {'absent' if absent else 'real zero'}",
                              "interval": "1m", "input_series": [] if absent else [
                                  {"series": metric, "values": "0+0x10"}],
                              "promql_expr_test": [{"expr": expr, "eval_time": "10m",
                                  "exp_samples": [] if absent else [{"labels": "{}", "value": 0}]}]})
        cases.append({"name": f"{mode}: historical points expired, current cost is absent",
                      "interval": "1m", "input_series": [{
                          "series": metric, "values": "0+0x4 " + " ".join(["_"] * 11)}],
                      "promql_expr_test": [{"expr": source.expr(window="10m"),
                                            "eval_time": "15m", "exp_samples": []}]})
    path = pathlib.Path(out_dir) / "financial_source_absence.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"evaluation_interval": "1m", "tests": cases}, indent=2), encoding="utf-8")
    print(f"{len(cases)} numerical absence/zero cases -> {path}", flush=True)
    return subprocess.run([promtool, "test", "rules", str(path)], check=False).returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--promtool")
    ap.add_argument("--out-dir")
    args = ap.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(FinancialSourceTests))
    if not result.wasSuccessful():
        return 1
    if args.promtool:
        if args.out_dir:
            return numerical_absence_checks(args.promtool, args.out_dir)
        with tempfile.TemporaryDirectory(prefix="forge-financial-promtool-") as temp:
            return numerical_absence_checks(args.promtool, temp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
