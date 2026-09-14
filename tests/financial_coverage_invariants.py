"""Offline discovery preservation, pricing coverage and omission regressions.

python tests/financial_coverage_invariants.py
No network, Grafana or Prometheus server is contacted. Numerical expressions
remain covered separately by recorded_cost/financial_source_invariants.py.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import discover  # noqa: E402
import forge_dashboards as f  # noqa: E402


def fixture(priced=1, unpriced=0, *, metadata=True):
    cap = f.selftest_capability()
    entry = copy.deepcopy(cap["signals"]["prom-selftest"]["otel_genai"])
    entry["models_seen"] = [f"model-{i:03d}" for i in range(priced + unpriced)]
    entry.pop("discovery_coverage", None)
    if metadata:
        entry["discovery_coverage"] = discover.returned_values_coverage(entry)
    cap["signals"] = {"prom-selftest": {"otel_genai": entry}}
    registry = {"_meta": {"verified_at": "2026-09-01"}, "models": [
        {"id": f"model-{i:03d}", "aliases": [], "input_per_mtok": i + 1,
         "output_per_mtok": (i + 1) * 2, "region": "eu", "vendor": "Fixture",
         "pricing_source_kind": "official"} for i in range(priced)]}
    return cap, registry


def budget(ctx):
    return [rule for rule in f.build_alerts(ctx, "folder", 100)
            if "llm-daily-budget" in rule["uid"]]


def monetary(board):
    return [p for p in board["panels"]
            if p.get("fieldConfig", {}).get("defaults", {}).get("unit") == "currencyUSD"]


class FinancialCoverageTests(unittest.TestCase):
    def test_discovery_keeps_401_metrics_61_models_41_providers(self):
        names = [f"gen_ai_metric_{i:03d}" for i in reversed(range(401))]
        models = [f"model-{i:03d}" for i in reversed(range(61))]
        providers = [f"provider-{i:03d}" for i in reversed(range(41))]
        original = copy.deepcopy((names, models, providers))
        client = mock.Mock()
        client.prom_metric_names.side_effect = lambda ds, pattern: (
            names if pattern == discover.DIALECT_SIGNATURES["otel_genai"] else [])
        client.prom_label_values.side_effect = lambda ds, label, **kw: {
            "gen_ai_request_model": models, "gen_ai_provider_name": providers,
            "gen_ai_token_type": ["output", "input"]}.get(label, [])
        result = discover.probe_prometheus(client, {"uid": "prom"})
        entry = result["otel_genai"]
        for key, returned in (("metric_names", names), ("models_seen", models),
                              ("providers_seen", providers)):
            self.assertEqual(entry[key], sorted(returned))
        self.assertEqual(entry["discovery_coverage"], {
            "scope": "backend_returned_values", "local_truncation": False,
            "backend_completeness": "unknown",
            "counts": {"metric_names": 401, "models_seen": 61, "providers_seen": 41}})
        self.assertEqual((names, models, providers), original)
        names.reverse()
        models.reverse()
        providers.reverse()
        self.assertEqual(discover.probe_prometheus(client, {"uid": "prom"}), result)

    def test_empty_discovery_remains_empty(self):
        client = mock.Mock()
        client.prom_metric_names.return_value = []
        self.assertEqual(discover.probe_prometheus(client, {"uid": "prom"}), {})
        client.prom_label_values.assert_not_called()

    def test_41_priced_models_refuse_all_inline_amounts_and_budget(self):
        ctx = f.Ctx(*fixture(41))
        source = ctx.cost_source
        for agg, region in (("rate", None), ("increase", None), ("rate", "eu")):
            self.assertIsNone(source.expr(agg=agg, region=region))
        board = f.bp_finops(ctx).d
        self.assertEqual(monetary(board), [])
        self.assertEqual(budget(ctx), [])
        self.assertEqual(source.coverage["status"], "inline_limit_exceeded")
        note = source.coverage_note()
        for expected in ("41", "40", "--datasource", "prometheus_rules_llmops.yml", "discover"):
            self.assertIn(expected, note)
        self.assertIn(note, json.dumps(board))

    def test_rules_retain_every_price_at_41_and_61_models(self):
        for count in (41, 61):
            with self.subTest(count=count), tempfile.TemporaryDirectory(prefix="forge-coverage-rules-") as temp:
                ctx = f.Ctx(*fixture(count))
                path = pathlib.Path(temp) / "rules.yml"
                _, prices = f.emit_recording_rules(ctx, str(path))
                content = path.read_text(encoding="utf-8")
                self.assertEqual(prices, 2 * count)
                self.assertEqual(content.count("- record:"), 2 * count + 3)
                for model in ctx.primary.s.models_seen:
                    self.assertEqual(content.count(f'"{model}"'), 2)
                self.assertTrue((path.parent / "prometheusrule_llmops.yaml").exists())

    def test_40_fully_priced_models_keep_every_term_and_scoped_budget(self):
        ctx = f.Ctx(*fixture(40))
        source = ctx.cost_source
        expr = source.expr()
        self.assertEqual(expr.count("rate("), 80)
        for model in source.q.s.models_seen:
            self.assertEqual(expr.count(f'gen_ai_request_model="{model}"'), 2)
        self.assertEqual(source.coverage["status"], "all_returned_models_priced")
        self.assertEqual(source.coverage["backend_completeness"], "unknown")
        self.assertTrue(source.coverage["budget_eligible"])
        rules = budget(ctx)
        self.assertEqual(len(rules), 1)
        self.assertIn("returned models", rules[0]["title"])
        self.assertIn("Missing inline counters may return zero", rules[0]["annotations"]["summary"])
        self.assertNotIn("cost is unknown, not zero", rules[0]["annotations"]["summary"])
        self.assertTrue(all("listed models" in p["title"] or "Estimated spend by" in p["title"]
                            for p in monetary(f.bp_finops(ctx).d)))

    def test_zero_input_and_output_prices_are_valid_prices(self):
        cap, registry = fixture()
        registry["models"][0].update(input_per_mtok=0, output_per_mtok=0)
        ctx = f.Ctx(cap, registry)
        coverage = ctx.cost_source.coverage
        self.assertEqual((coverage["priced_models"], coverage["partially_priced_models"],
                          coverage["unpriced_models"]), (1, 0, 0))
        self.assertEqual(ctx.cost_source.expr().count("* 0"), 2)
        self.assertTrue(coverage["budget_eligible"])
        self.assertEqual(len(budget(ctx)), 1)

    def test_missing_models_are_a_labeled_subtotal_with_exact_hidden_count(self):
        ctx = f.Ctx(*fixture(1, 25))
        source = ctx.cost_source
        coverage = source.coverage
        self.assertEqual((coverage["models_seen"], coverage["priced_models"],
                          coverage["unpriced_models"]), (26, 1, 25))
        self.assertEqual(coverage["status"], "partial_prices")
        self.assertIsNotNone(source.expr())
        self.assertEqual(budget(ctx), [])
        board = f.bp_finops(ctx).d
        self.assertTrue(monetary(board))
        for panel in monetary(board):
            self.assertIn("subtotal", panel["title"].lower())
            self.assertIn("subtotal, not overall spend", panel["description"])
        self.assertIn("Showing 20 of 25 models; 5 not displayed", json.dumps(board))
        self.assertIn("Budget omitted", json.dumps(board))

    def test_missing_output_price_is_partial_including_zero_input(self):
        cap, registry = fixture()
        registry["models"][0].update(input_per_mtok=0, output_per_mtok=None)
        ctx = f.Ctx(cap, registry)
        source = ctx.cost_source
        self.assertTrue(source.is_subtotal)
        self.assertEqual((source.coverage["priced_models"], source.coverage["partially_priced_models"]), (0, 1))
        self.assertIn("* 0", source.expr())
        self.assertEqual(budget(ctx), [])

    def test_unpriced_or_no_models_never_get_amounts_or_budget(self):
        for unpriced in (0, 5):
            with self.subTest(unpriced=unpriced):
                ctx = f.Ctx(*fixture(0, unpriced))
                self.assertIsNone(ctx.cost_source.expr())
                self.assertEqual(monetary(f.bp_finops(ctx).d), [])
                self.assertEqual(budget(ctx), [])
                self.assertEqual(ctx.cost_source.coverage["status"], "unpriced")

    def test_legacy_maps_estimate_only_listed_models_without_budget(self):
        ctx = f.Ctx(*fixture(metadata=False))
        source = ctx.cost_source
        self.assertIsNotNone(source.expr())
        self.assertEqual(source.coverage["status"], "discovery_unknown")
        self.assertEqual(source.coverage["local_preservation"], "unknown")
        self.assertIn("Re-run discover", source.coverage_note())
        self.assertEqual(budget(ctx), [])
        self.assertIn("listed models", monetary(f.bp_finops(ctx).d)[0]["title"])

    def test_inconsistent_or_malformed_metadata_does_not_certify_preservation(self):
        cap, registry = fixture()
        info = cap["signals"]["prom-selftest"]["otel_genai"]["discovery_coverage"]
        invalid = [None, "unknown", {}, {**info, "local_truncation": True},
                   {**info, "local_truncation": 0}, {**info, "backend_completeness": "complete"},
                   {**info, "counts": {**info["counts"], "models_seen": 60}},
                   {**info, "counts": {**info["counts"], "models_seen": True}}]
        for value in invalid:
            with self.subTest(info=value):
                cap["signals"]["prom-selftest"]["otel_genai"]["discovery_coverage"] = value
                source = f.Ctx(cap, registry).cost_source
                self.assertEqual(source.coverage["status"], "discovery_unknown")
                self.assertFalse(source.coverage["budget_eligible"])

    def test_native_and_recorded_coverage_are_independent_of_registry(self):
        for mode in ("native", "recorded"):
            with self.subTest(mode=mode):
                cap, registry = fixture(0, 65)
                extra = ({"litellm": copy.deepcopy(f.selftest_capability()["signals"]["prom-selftest"]["litellm"])}
                         if mode == "native" else {"recorded": {"metric_names": [f.COST_RECORDED]}})
                cap["signals"]["prom-selftest"].update(extra)
                ctx = f.Ctx(cap, registry)
                coverage = ctx.cost_source.coverage
                self.assertEqual(coverage["status"], f"{mode}_upstream_unverified")
                self.assertFalse(coverage["registry_applicable"])
                self.assertIsNone(coverage["priced_models"])
                self.assertTrue(coverage["budget_eligible"])
                self.assertEqual(len(budget(ctx)), 1)
                self.assertIn("cost is unknown, not zero", budget(ctx)[0]["annotations"]["summary"])
                self.assertNotIn("Models missing from the price registry", json.dumps(f.bp_finops(ctx).d))

    def test_cli_dashboard_manifest_and_rules_agree_without_mutating_map(self):
        cap, registry = fixture(41)
        before = copy.deepcopy(cap)
        with tempfile.TemporaryDirectory(prefix="forge-coverage-cli-") as temp:
            directory = pathlib.Path(temp)
            path = directory / "capability.json"
            path.write_text(json.dumps(cap), encoding="utf-8")
            output = directory / "output"
            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.object(sys, "argv", ["forge", "--capability", str(path),
                                   "--out-dir", str(output), "--blueprints", "finops", "--with-alerts"]), \
                    mock.patch.object(f, "load_registry", return_value=registry), \
                    mock.patch.object(f, "GrafanaClient", side_effect=AssertionError("network attempted")), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = f.main()
            self.assertEqual(code, 0, stderr.getvalue())
            manifest = json.loads((output / "deploy_manifest.json").read_text(encoding="utf-8"))
            coverage = manifest["financial_source"]["coverage"]
            self.assertEqual((coverage["models_seen"], coverage["priced_models"], coverage["unpriced_models"]), (41, 41, 0))
            self.assertIn("inline_limit_exceeded", stdout.getvalue())
            self.assertIn("Budget omitted", stdout.getvalue())
            self.assertFalse(any("llm-daily-budget" in rule["uid"] for rule in manifest["alerts"]))
            self.assertIn("model-040", (output / "prometheus_rules_llmops.yml").read_text(encoding="utf-8"))
            self.assertEqual(monetary(json.loads((output / "finops.json").read_text(encoding="utf-8"))), [])
        self.assertEqual(cap, before)

    def test_new_panel_titles_have_french_translations(self):
        board = f.bp_finops(f.Ctx(*fixture(1, 1))).d
        localized = f.localize(copy.deepcopy(board), f.load_locale("fr"))
        titles = [p["title"] for p in localized["panels"]]
        self.assertIn("Couverture financière", titles)
        self.assertTrue(any("Sous-total" in title for title in titles))


if __name__ == "__main__":
    unittest.main(verbosity=2)
