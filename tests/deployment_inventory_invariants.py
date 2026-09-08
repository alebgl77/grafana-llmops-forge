"""Offline inventory schema, side-effect boundary, scope and HTML/locale tests.

python tests/deployment_inventory_invariants.py
No Grafana or pricing endpoint is contacted. No PromQL expression is changed.
"""
from __future__ import annotations

import contextlib
import copy
from html.parser import HTMLParser
import io
import json
import pathlib
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import forge_dashboards as f  # noqa: E402

REGISTRY = {"_meta": {"verified_at": "2026-09-01"}, "models": [
    {"id": "model-us", "vendor": "US model vendor", "region": "us", "aliases": [],
     "input_per_mtok": 1, "output_per_mtok": 2, "pricing_source_kind": "official"}]}


def capability():
    cap = f.selftest_capability()
    entry = copy.deepcopy(cap["signals"]["prom-selftest"]["otel_genai"])
    entry["models_seen"] = ["model-us", "model-unknown"]
    cap["signals"] = {"prom-a": {"otel_genai": entry}, "prom-b": {"otel_genai": copy.deepcopy(entry)}}
    cap["datasources"]["prometheus"] = [{"uid": "prom-a", "name": "Production"},
                                           {"uid": "prom-b", "name": "Staging"},
                                           {"uid": "prom-empty", "name": "No metrics"}]
    return cap


def deployment(**extra):
    return {"deployment_id": "deployment-a", "datasource_uid": "prom-a", "model": "model-us", **extra}


def inventory(*records):
    return {"schema_version": 1, "deployments": list(records)}


def panel(board):
    return next(p for p in board["panels"] if p["title"] in (
        "Deployment locations (declarations)", "Lieux de déploiement (déclarations)"))


class HTMLText(HTMLParser):
    def __init__(self, content):
        super().__init__(convert_charrefs=True)
        self.tags, self.data, self.attributes = [], [], []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)

    def handle_data(self, data):
        self.data.append(data)


class DeploymentInventoryTests(unittest.TestCase):
    def cli(self, payload=None, *, raw=None, extra=(), fallback=None):
        with tempfile.TemporaryDirectory(prefix="forge-deployment-cli-") as temp:
            directory = pathlib.Path(temp)
            cap_path = directory / "capability.json"
            cap_path.write_text(json.dumps(capability()), encoding="utf-8")
            output = directory / "output"
            argv = ["forge", "--capability", str(cap_path), "--out-dir", str(output),
                    "--blueprints", "governance", *extra]
            if payload is not None or raw is not None:
                inventory_path = directory / "inventory.json"
                inventory_path.write_bytes(raw if raw is not None else json.dumps(payload).encode("utf-8"))
                argv.extend(["--deployment-inventory", str(inventory_path)])
            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(f, "GrafanaClient", side_effect=AssertionError("Grafana side effect")) as client, \
                    mock.patch.object(f.pricing_sources, "apply_artificial_analysis_fallback",
                                      side_effect=fallback or AssertionError("pricing side effect")) as pricing, \
                    mock.patch.object(f, "load_registry", return_value=copy.deepcopy(REGISTRY)) as registry, \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = f.main()
            files = {p.name: p.read_text(encoding="utf-8") for p in output.glob("*")}
            return {"code": code, "stdout": stdout.getvalue(), "stderr": stderr.getvalue(), "files": files,
                    "client_calls": client.call_count, "pricing_calls": pricing.call_count,
                    "registry_calls": registry.call_count, "cache_exists": (directory / f.pricing_sources.CACHE_FILENAME).exists()}

    def invalid_before_side_effects(self, payload=None, raw=None):
        for dry in ((), ("--dry-run",)):
            result = self.cli(payload, raw=raw, extra=("--deploy", "--pricing-fallback", "artificial-analysis", *dry))
            self.assertEqual(result["code"], 2, result)
            self.assertEqual(result["files"], {})
            self.assertEqual((result["client_calls"], result["pricing_calls"], result["registry_calls"]), (0, 0, 0))
            self.assertFalse(result["cache_exists"])
            self.assertNotIn("Traceback", result["stderr"])
        return result

    def test_absent_inventory_keeps_locations_unknown_in_en_and_fr_cli(self):
        for locale, word in (("en", "unknown"), ("fr", "inconnus")):
            with self.subTest(locale=locale):
                result = self.cli(extra=("--locale", locale))
                self.assertEqual(result["code"], 0, result["stderr"])
                board = json.loads(result["files"]["governance.json"])
                location_panel = panel(board)
                self.assertEqual(location_panel["options"]["mode"], "html")
                self.assertIn(word, location_panel["options"]["content"])
                self.assertNotIn("<table>", location_panel["options"]["content"])
                manifest = json.loads(result["files"]["deploy_manifest.json"])["deployment_inventory"]
                self.assertEqual((manifest["provided"], manifest["location_status"], manifest["records_in_scope"]),
                                 (False, "unknown", 0))

    def test_us_origin_and_declared_fr_processing_coexist(self):
        payload = inventory(deployment(processing_region="FR", storage_region="DE", serving_provider="EU host",
                                       endpoint_host="ollama", evidence_ref="contract-section-4", evidence_date="2024-02-29"))
        cap = capability()
        ctx = f.Ctx(cap, REGISTRY, deployment_inventory=f.validate_deployment_inventory(payload, cap))
        location_panel = panel(f.bp_governance(ctx).d)
        text = " ".join(HTMLText(location_panel["options"]["content"]).data)
        for expected in ("US / US model vendor", "FR (declared)", "DE (declared)",
                         "observed_in_capability_map", "ollama", "contract-section-4", "2024-02-29"):
            self.assertIn(expected, text)
        self.assertNotIn("verified", text.lower())
        manifest = ctx.deployment_manifest()
        self.assertEqual(manifest["fields"]["processing_region"], {"declared": 1, "unknown": 0})
        self.assertEqual(manifest["independent_checks"], "not_performed")
        self.assertNotIn("contract-section-4", json.dumps(manifest))
        self.assertNotIn("ollama", json.dumps(manifest))

    def test_exact_observation_never_supplies_a_location(self):
        payload = inventory(deployment(), deployment(deployment_id="variant", model="model-us-variant"),
                            deployment(deployment_id="no-metrics", datasource_uid="prom-empty"))
        ctx = f.Ctx(capability(), REGISTRY, deployment_inventory=payload)
        self.assertEqual([ctx.deployment_model_status(r) for r in ctx.deployments],
                         ["observed_in_capability_map", "not_observed_in_capability_map", "not_observed_in_capability_map"])
        manifest = ctx.deployment_manifest()
        self.assertEqual(manifest["location_status"], "unknown")
        self.assertEqual(manifest["fields"]["processing_region"], {"declared": 0, "unknown": 3})
        self.assertEqual(manifest["fields"]["storage_region"], {"declared": 0, "unknown": 3})

    def test_multiple_deployments_same_model_and_scope_are_preserved_without_mutation(self):
        cap = capability()
        payload = inventory(deployment(), deployment(deployment_id="replica", endpoint_host="replica.local"),
                            deployment(deployment_id="staging", datasource_uid="prom-b", processing_region="US"))
        before = copy.deepcopy((cap, payload))
        validated = f.validate_deployment_inventory(payload, cap)
        selected = f.filter_capability_datasource(cap, "Production")
        ctx = f.Ctx(selected, REGISTRY, deployment_inventory=validated, deployment_datasource_filter=True)
        self.assertEqual([r["deployment_id"] for r in ctx.deployments], ["deployment-a", "replica"])
        self.assertEqual(ctx.deployment_manifest()["records_excluded_by_scope"], 1)
        self.assertEqual(ctx.deployment_manifest()["records_with_observed_model"], 2)
        self.assertEqual(ctx.deployment_manifest()["declared_datasource_uids_in_scope"], ["prom-a"])
        self.assertEqual((cap, payload), before)
        for selector in ("prom-a", "Production"):
            result = self.cli(payload, extra=("--datasource", selector))
            self.assertEqual(result["code"], 0, result["stderr"])
            manifest = json.loads(result["files"]["deploy_manifest.json"])["deployment_inventory"]
            self.assertEqual((manifest["records_loaded"], manifest["records_in_scope"]), (3, 2))
            self.assertNotIn("staging", panel(json.loads(result["files"]["governance.json"]))["options"]["content"])

    def test_filter_to_empty_scope_has_unknown_locations(self):
        result = self.cli(inventory(deployment()), extra=("--datasource", "prom-b"))
        self.assertEqual(result["code"], 0)
        manifest = json.loads(result["files"]["deploy_manifest.json"])["deployment_inventory"]
        self.assertEqual((manifest["records_in_scope"], manifest["records_excluded_by_scope"], manifest["location_status"]),
                         (0, 1, "unknown"))
        self.assertIn("No deployment declarations", panel(json.loads(result["files"]["governance.json"]))["options"]["content"])

    def test_invalid_schema_types_unknown_fields_and_duplicates_fail_before_any_effect(self):
        for payload in ([], {}, {"schema_version": True, "deployments": []}, inventory() | {"secret": "not-output"},
                        {"schema_version": 2, "deployments": []}, {"schema_version": 1, "deployments": {}},
                        inventory("not-a-record"), inventory({"deployment_id": "a"}),
                        inventory(deployment(unknown="field")), inventory(deployment(model=None)),
                        inventory(deployment(model=1)), inventory(deployment(serving_provider="  ")),
                        inventory(deployment(), deployment()), inventory(deployment(datasource_uid="unknown"))):
            with self.subTest(payload=payload):
                self.invalid_before_side_effects(payload)

    def test_invalid_dates_and_control_characters_are_rejected(self):
        for value in ("2025-02-29", "2026-13-01", "2026-2-01", "0000-01-01", "2026-W01-1", "２０２６-01-01"):
            with self.subTest(date=value):
                self.invalid_before_side_effects(inventory(deployment(evidence_date=value)))
        for value in ("line\r\nbreak", "tab\ttext", "nul\0", "bidi\u202e", "surrogate\ud800"):
            with self.subTest(control=repr(value)):
                self.invalid_before_side_effects(inventory(deployment(evidence_ref=value)))

    def test_hostnames_reject_urls_secrets_and_markup_without_echoing_values(self):
        for host in ("https://user:secret@host/path?token=secret", "user:secret@host", "host:443",
                     "host/path", "host?token=secret", "host#fragment", "<script>", "host\\share",
                     "127.0.0.1", "[::1]", "a..b", "-bad.example", "bad-.example", "a" * 64 + ".example"):
            with self.subTest(host=host):
                result = self.invalid_before_side_effects(inventory(deployment(endpoint_host=host)))
                self.assertNotIn("secret", result["stderr"])
        for host in ("ollama", "api.example.invalid", "xn--bcher-kva.example", "api.example.invalid."):
            f.validate_deployment_inventory(inventory(deployment(endpoint_host=host)), capability())

    def test_json_duplicates_invalid_encoding_and_file_size_are_rejected(self):
        for raw in (b'{"schema_version":1,"schema_version":1,"deployments":[]}',
                    b'{"schema_version":1,"deployments":[{"model":"x","model":"y"}]}',
                    b'not-json', b'\xff', b' ' * (f.INVENTORY_MAX_BYTES + 1)):
            with self.subTest(raw_length=len(raw)):
                self.invalid_before_side_effects(raw=raw)

    def test_unc_device_and_uri_paths_are_rejected_before_filesystem_access(self):
        for path in (r"\\server\share\inventory.json", "//server/share/inventory.json",
                     r"\\?\C:\inventory.json", r"\\.\PIPE\inventory", r"\??\C:\inventory.json",
                     "NUL", "folder/CON.txt", "COM1", "LPT²", "CONIN$", "C:relative.json",
                     "C:/inventory.json:stream", "https://example.invalid/inventory.json"):
            with self.subTest(path=path), mock.patch.object(f.os, "lstat") as inspect, \
                    mock.patch("builtins.open") as opened:
                with self.assertRaisesRegex(ValueError, "local file path"):
                    f.load_deployment_inventory(path, capability())
                inspect.assert_not_called()
                opened.assert_not_called()

    def test_nonregular_files_are_rejected_before_open_without_real_special_files(self):
        for mode in (stat.S_IFIFO, stat.S_IFDIR, stat.S_IFSOCK, stat.S_IFLNK):
            with self.subTest(mode=mode), mock.patch.object(f.os, "lstat", return_value=SimpleNamespace(st_mode=mode)):
                with mock.patch("builtins.open") as opened, self.assertRaisesRegex(ValueError, "regular JSON file"):
                    f.load_deployment_inventory("inventory.json", capability())
                opened.assert_not_called()

    def test_opened_file_is_checked_again(self):
        before = SimpleNamespace(st_mode=stat.S_IFREG, st_size=10)
        after = SimpleNamespace(st_mode=stat.S_IFIFO)
        with mock.patch.object(f.os, "lstat", return_value=before), \
                mock.patch.object(f.os, "fstat", return_value=after), \
                mock.patch("builtins.open", mock.mock_open()) as opened:
            with self.assertRaisesRegex(ValueError, "regular JSON file"):
                f.load_deployment_inventory("inventory.json", capability())
            opened.return_value.read.assert_not_called()

    def test_record_and_field_bounds(self):
        records = [deployment(deployment_id=f"d-{i}") for i in range(f.INVENTORY_MAX_DEPLOYMENTS)]
        self.assertEqual(len(f.validate_deployment_inventory(inventory(*records), capability())["deployments"]), 500)
        self.invalid_before_side_effects(inventory(*records, deployment(deployment_id="extra")))
        for key, maximum in f.INVENTORY_FIELDS.items():
            with self.subTest(field=key):
                self.invalid_before_side_effects(inventory(deployment(**{key: "x" * (maximum + 1)})))

    def test_markup_and_evidence_links_are_plain_text_in_html(self):
        malicious = '<img src=x onerror="alert(1)"> | [click](https://example.invalid) `code` & <a href="x">x</a>'
        record = deployment(deployment_id=malicious, model=malicious, serving_provider=malicious,
                            processing_region=malicious, storage_region=malicious,
                            evidence_ref='https://example.invalid/?token=synthetic <script>alert(1)</script> | [x](y)')
        result = self.cli(inventory(record))
        self.assertEqual(result["code"], 0, result["stderr"])
        location_panel = panel(json.loads(result["files"]["governance.json"]))
        content = location_panel["options"]["content"]
        parsed = HTMLText(content)
        self.assertEqual(location_panel["options"]["mode"], "html")
        self.assertLessEqual(set(parsed.tags), {"p", "table", "thead", "tbody", "tr", "th", "td", "code"})
        self.assertEqual(parsed.attributes, [])
        self.assertIn(malicious, parsed.data)
        self.assertIn(record["evidence_ref"], parsed.data)
        self.assertNotIn("<a ", content)
        self.assertNotIn("<script>", content)
        self.assertNotIn("<img ", content)
        self.assertIn("&#124;", content)
        self.assertEqual((result["client_calls"], result["pricing_calls"]), (0, 0))

    def test_inventory_survives_pricing_fallback_and_french_cli(self):
        def fallback(registry, *args, **kwargs):
            return {"registry": registry, "warnings": [], "priced": [], "cache_used": False, "fetched": False}
        result = self.cli(inventory(deployment(processing_region="FR", evidence_date="2026-09-08")),
                          extra=("--locale", "fr", "--pricing-fallback", "artificial-analysis", "--deploy", "--dry-run"),
                          fallback=fallback)
        self.assertEqual((result["code"], result["pricing_calls"], result["client_calls"]), (0, 1, 0))
        location_panel = panel(json.loads(result["files"]["governance.json"]))
        content = location_panel["options"]["content"]
        for expected in ("Lieu de traitement", "Lieu de stockage", "FR (déclaré)", "inconnu"):
            self.assertIn(expected, content)
        self.assertNotIn("vérifié", content)
        self.assertEqual(json.loads(result["files"]["deploy_manifest.json"])["deployment_inventory"]["records_in_scope"], 1)

    def test_region_rules_and_queries_preserve_compatibility_with_renamed_panels(self):
        cap = f.filter_capability_datasource(capability(), "prom-a")
        ctx = f.Ctx(cap, REGISTRY)
        before = copy.deepcopy(REGISTRY)
        rules, count = f._rule_lines(ctx, "", "5m")
        self.assertEqual(count, 2)
        self.assertIn('"region": "us"', "\n".join(rules))
        recorded = f.cost_rate_expr(ctx.primary, ctx.matched, region="us", recorded=True)
        self.assertEqual(recorded, 'sum(llm:cost_usd_per_second{region="us"})')
        for board in (f.bp_finops(ctx).d, f.bp_governance(ctx).d):
            self.assertNotIn("sovereignty", json.dumps(board).lower())
            self.assertTrue(any("provider origin" in p["title"].lower() for p in board["panels"]))
        self.assertEqual(REGISTRY, before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
