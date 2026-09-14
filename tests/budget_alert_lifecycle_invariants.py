"""Budget migration regressions through main(), real client HTTP and disk manifests.

python tests/budget_alert_lifecycle_invariants.py
The in-memory HTTP transport never contacts a Grafana instance.
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
import urllib.error
import urllib.parse
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from financial_coverage_invariants import fixture  # noqa: E402
import discover  # noqa: E402
import forge_dashboards as f  # noqa: E402
from grafana_client import GrafanaClient, GrafanaError  # noqa: E402

ALERTS = "/api/v1/provisioning/alert-rules"
SCOPE = "budget-lifecycle-test"
BUDGET_UID = f.det_uid("llm-daily-budget", "alr", SCOPE)


class Response:
    status = 200

    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class Transport:
    def __init__(self):
        self.rules = {"unrelated": {"uid": "unrelated", "isPaused": False, "custom": [1, 2]}}
        self.calls = []
        self.fault = None
        self.folder_uid = "resolved-budget-folder"

    def open(self, request, timeout):
        method, path = request.method, urllib.parse.urlsplit(request.full_url).path
        payload = json.loads(request.data) if request.data is not None else None
        self.calls.append((method, path, copy.deepcopy(payload), dict(request.header_items())))
        if self.fault:
            result = self.fault(method, path, payload)
            if result is not None:
                return result
        if path == "/api/org":
            return Response({"id": 7})
        if path.startswith("/api/folders/"):
            return Response({"uid": self.folder_uid, "title": "Resolved folder"})
        if path.startswith("/api/dashboards/uid/"):
            return Response({"meta": {"folderUid": self.folder_uid}})
        if path == "/api/dashboards/db":
            return Response({"uid": payload["dashboard"]["uid"]})
        if path == "/api/v1/provisioning/contact-points":
            return Response([{}])
        if path.startswith(ALERTS + "/") and method == "GET":
            uid = path.rsplit("/", 1)[1]
            if uid not in self.rules:
                raise urllib.error.HTTPError(request.full_url, 404, "missing", {}, io.BytesIO(b"{}"))
            return Response(self.rules[uid])
        if path.startswith(ALERTS) and method in ("POST", "PUT"):
            self.rules[payload["uid"]] = copy.deepcopy(payload)
            self.rules[payload["uid"]].setdefault("isPaused", False)
            return Response(self.rules[payload["uid"]])
        raise AssertionError(f"Unexpected HTTP operation: {method} {path}")

    def alert_calls(self):
        return [call for call in self.calls if call[1].startswith(ALERTS)]


class BudgetLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="forge-budget-lifecycle-")
        self.addCleanup(self.temp.cleanup)
        self.transport = Transport()
        self.client = GrafanaClient(url="http://grafana.invalid", token="synthetic", retries=1)
        self.client._opener = self.transport

    def run_main(self, priced=1, unpriced=0, *, metadata=True,
                 deploy=True, with_alerts=True, dry_run=False, best_effort=False, include_slos=False):
        cap, registry = fixture(priced, unpriced, metadata=metadata)
        signal = cap["signals"]["prom-selftest"]["otel_genai"]
        if not include_slos:
            signal["metric_names"] = [metric for metric in signal["metric_names"] if "token_usage" in metric]
        if metadata:
            signal["discovery_coverage"] = discover.returned_values_coverage(signal)
        root = pathlib.Path(self.temp.name)
        capability = root / "cap.json"
        capability.write_text(json.dumps(cap), encoding="utf-8")
        output = root / "output"
        args = ["forge", "--capability", str(capability), "--out-dir", str(output),
                "--blueprints", "finops", "--cost-mode", "inline", "--uid-scope", SCOPE]
        args += [flag for flag, enabled in (("--deploy", deploy), ("--with-alerts", with_alerts),
                                            ("--dry-run", dry_run), ("--best-effort", best_effort)) if enabled]
        self.transport.calls.clear()
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(f, "GrafanaClient", return_value=self.client), \
                mock.patch.object(f, "load_registry", return_value=registry), \
                mock.patch.object(sys, "argv", args), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = f.main()
        manifest = json.loads((output / "deploy_manifest.json").read_text(encoding="utf-8"))
        return code, manifest, stdout.getvalue() + stderr.getvalue()

    def seed_budget(self):
        code, manifest, output = self.run_main()
        self.assertEqual(code, 0, output)
        self.assertEqual(manifest["deployment_status"], "success")
        self.assertEqual(manifest["budget_alert"]["result"], "upserted")
        self.assertFalse(self.transport.rules[BUDGET_UID]["isPaused"])
        self.transport.rules[BUDGET_UID]["annotations"]["operator_note"] = "retain this note"
        self.transport.rules[BUDGET_UID]["id"] = 42
        self.transport.calls.clear()
        return copy.deepcopy(self.transport.rules[BUDGET_UID])

    def assert_failed(self, result):
        code, manifest, output = result
        self.assertEqual(code, 4, output)
        self.assertEqual(manifest["deployment_status"], "partial")
        self.assertEqual(manifest["budget_alert"]["result"], "failed")
        self.assertIsNone(manifest["budget_alert"]["is_paused"])
        self.assertEqual(manifest["resources"]["alerts"],
                         {"requested": 1, "succeeded": 0, "failed": 1, "skipped": 0})
        self.assertEqual(manifest["errors"][-1]["uid"], BUDGET_UID)
        self.assertEqual(manifest["alerts"][0]["status"], "failed")

    def test_active_to_ineligible_pauses_only_budget_in_resolved_scope(self):
        for kwargs in ({"unpriced": 1}, {"metadata": False}, {"priced": 41}):
            with self.subTest(kwargs=kwargs):
                original = self.seed_budget()
                unrelated = copy.deepcopy(self.transport.rules["unrelated"])
                code, manifest, output = self.run_main(**kwargs)
                self.assertEqual(code, 0, output)
                self.assertEqual(self.transport.rules[BUDGET_UID], dict(original, isPaused=True))
                self.assertEqual(self.transport.rules["unrelated"], unrelated)
                self.assertEqual([(call[0], call[1]) for call in self.transport.alert_calls()],
                                 [("GET", ALERTS + "/" + BUDGET_UID), ("PUT", ALERTS + "/" + BUDGET_UID)])
                budget = manifest["budget_alert"]
                self.assertEqual((budget["action"], budget["result"], budget["is_paused"]),
                                 ("pause", "paused", True))
                self.assertEqual((budget["org_id"], budget["folder_uid"]), (7, self.transport.folder_uid))
                self.assertTrue(budget["reason"])
                self.assertEqual(manifest["resources"]["alerts"],
                                 {"requested": 1, "succeeded": 1, "failed": 0, "skipped": 0})
                for call in self.transport.alert_calls():
                    self.assertEqual(call[3]["X-grafana-org-id"], "7")
                # Restore a clean eligible fixture for the next transition.
                self.transport.rules.pop(BUDGET_UID)

    def test_absent_budget_does_not_create(self):
        code, manifest, output = self.run_main(unpriced=1)
        self.assertEqual(code, 0, output)
        self.assertEqual(manifest["budget_alert"]["result"], "absent")
        self.assertIsNone(manifest["budget_alert"]["is_paused"])
        self.assertNotIn(BUDGET_UID, self.transport.rules)
        self.assertEqual([call[0] for call in self.transport.alert_calls()], ["GET"])

    def test_rerun_is_idempotent_and_recovery_preserves_pause(self):
        self.seed_budget()
        self.assertEqual(self.run_main(unpriced=1)[1]["budget_alert"]["result"], "paused")
        self.assertEqual(self.run_main(unpriced=1)[1]["budget_alert"]["result"], "already_paused")
        self.assertEqual([call[0] for call in self.transport.alert_calls()], ["GET"])
        code, manifest, output = self.run_main()
        self.assertEqual(code, 0, output)
        self.assertEqual(manifest["budget_alert"]["result"], "upserted_paused")
        self.assertTrue(manifest["budget_alert"]["is_paused"])
        self.assertTrue(self.transport.rules[BUDGET_UID]["isPaused"])
        self.assertIn("resume it explicitly in Grafana", output)
        self.assertEqual([call[0] for call in self.transport.alert_calls()], ["GET", "PUT"])

    def test_collision_checks_also_apply_to_already_paused_rules(self):
        original = self.seed_budget()
        corruptions = [{"uid": "foreign"}, {"orgID": 8}, {"orgID": True}, {"orgID": 7.0},
                       {"folderUID": "other"}, {"ruleGroup": "other"},
                       {"labels": dict(original["labels"], origin="other")},
                       {"labels": dict(original["labels"], llmops_rule_identity="other")}]
        for paused in (False, True):
            for corruption in corruptions:
                with self.subTest(paused=paused, corruption=corruption):
                    existing = dict(copy.deepcopy(original), isPaused=paused, **corruption)
                    self.transport.rules[BUDGET_UID] = existing
                    self.assert_failed(self.run_main(unpriced=1))
                    self.assertEqual(self.transport.rules[BUDGET_UID], existing)
                    self.assertEqual([call[0] for call in self.transport.alert_calls()], ["GET"])

    def test_http_and_ambiguous_responses_fail_closed(self):
        original = self.seed_budget()
        for method in ("GET", "PUT"):
            for failure in ("forbidden", "transport", "invalid_json", "empty", "list", "missing_pause",
                            "string_pause", "missing_queries", "wrong_scope", "false_pause"):
                if failure == "false_pause" and method == "GET":
                    continue  # false is the valid active state on GET.
                with self.subTest(method=method, failure=failure):
                    self.transport.rules[BUDGET_UID] = copy.deepcopy(original)
                    def fault(verb, path, payload):
                        if verb != method or path != ALERTS + "/" + BUDGET_UID:
                            return None
                        if failure == "forbidden":
                            raise urllib.error.HTTPError(path, 403, "forbidden", {}, io.BytesIO(b"{}"))
                        if failure == "transport":
                            raise urllib.error.URLError("simulated failure")
                        if failure in ("invalid_json", "empty", "list"):
                            return Response({"invalid_json": b"{", "empty": {}, "list": []}[failure])
                        body = dict(copy.deepcopy(original), isPaused=(method == "PUT"))
                        if failure == "missing_pause":
                            body.pop("isPaused")
                        elif failure == "string_pause":
                            body["isPaused"] = "true"
                        elif failure == "missing_queries":
                            body.pop("data")
                        elif failure == "wrong_scope":
                            body["folderUID"] = "foreign"
                        elif failure == "false_pause":
                            body["isPaused"] = False
                        return Response(body)
                    self.transport.fault = fault
                    self.assert_failed(self.run_main(unpriced=1))
                    calls = self.transport.alert_calls()
                    self.assertEqual([call[0] for call in calls], ["GET"] if method == "GET" else ["GET", "PUT"])
                    self.assertEqual(self.transport.rules[BUDGET_UID], original)
        self.transport.fault = None

    def test_eligible_paused_budget_read_failure_does_not_resume(self):
        original = self.seed_budget()
        self.transport.rules[BUDGET_UID]["isPaused"] = True
        def fault(method, path, payload):
            if method == "GET" and path == ALERTS + "/" + BUDGET_UID:
                raise urllib.error.URLError("simulated failure")
        self.transport.fault = fault
        self.assert_failed(self.run_main())
        self.assertEqual(self.transport.rules[BUDGET_UID], dict(original, isPaused=True))

    def test_unconfirmed_applied_pause_is_failed_then_rerun_confirms_without_put(self):
        original = self.seed_budget()
        def fault(method, path, payload):
            if method == "PUT" and path == ALERTS + "/" + BUDGET_UID:
                self.transport.rules[BUDGET_UID] = copy.deepcopy(payload)
                return Response({})  # The write happened, but its response is ambiguous.
        self.transport.fault = fault
        self.assert_failed(self.run_main(unpriced=1))
        self.assertEqual(self.transport.rules[BUDGET_UID], dict(original, isPaused=True))
        self.transport.fault = None
        code, manifest, output = self.run_main(unpriced=1)
        self.assertEqual(code, 0, output)
        self.assertEqual(manifest["budget_alert"]["result"], "already_paused")
        self.assertEqual([call[0] for call in self.transport.alert_calls()], ["GET"])

    def test_transport_failure_with_remaining_slos_still_writes_failure_manifest(self):
        original = self.seed_budget()
        def fault(method, path, payload):
            if path.startswith("/api/v1/provisioning/"):
                raise urllib.error.URLError("simulated provisioning outage")
        self.transport.fault = fault
        code, manifest, output = self.run_main(unpriced=1, include_slos=True)
        self.assertEqual(code, 4, output)
        self.assertEqual(manifest["deployment_status"], "partial")
        self.assertEqual(manifest["budget_alert"]["result"], "failed")
        stats = manifest["resources"]["alerts"]
        self.assertGreater(stats["requested"], 1)
        self.assertEqual(stats["failed"], stats["requested"])
        self.assertTrue(any(error["operation"] == "pause" for error in manifest["errors"]))
        self.assertEqual(self.transport.rules[BUDGET_UID], original)
        self.assertIn("contact point availability could not be checked", output)
        self.assertNotIn("no contact point configured", output)

    def test_export_dry_run_and_no_alerts_do_not_reconcile_budget(self):
        self.seed_budget()
        for kwargs, expected in (({"deploy": False}, "not_executed"),
                                 ({"dry_run": True}, "not_executed"),
                                 ({"with_alerts": False}, "not_requested")):
            with self.subTest(kwargs=kwargs):
                code, manifest, output = self.run_main(unpriced=1, **kwargs)
                self.assertEqual(code, 0, output)
                self.assertEqual(manifest["budget_alert"]["result"], expected)
                self.assertEqual(self.transport.alert_calls(), [])
                self.assertFalse(self.transport.rules[BUDGET_UID]["isPaused"])
                if kwargs.get("deploy") is False or kwargs.get("dry_run"):
                    self.assertEqual(self.transport.calls, [])

    def test_best_effort_keeps_explicit_failed_manifest(self):
        original = self.seed_budget()
        self.transport.rules[BUDGET_UID]["folderUID"] = "other"
        code, manifest, _ = self.run_main(unpriced=1, best_effort=True)
        self.assertEqual(code, 0)
        self.assertEqual(manifest["budget_alert"]["result"], "failed")
        self.assertEqual(manifest["deployment_status"], "partial")
        self.assertEqual(self.transport.rules[BUDGET_UID], dict(original, folderUID="other"))

    def test_slo_pause_policy_is_unchanged_and_pause_api_rejects_non_budget(self):
        rule = self.seed_budget()
        rule.update(uid="slo-test", labels=dict(rule["labels"], llmops_rule_identity=f.alert_logical_identity("slo")))
        self.transport.rules[rule["uid"]] = dict(copy.deepcopy(rule), isPaused=True)
        rule.pop("isPaused")
        self.client.upsert_alert_rule(rule)
        self.assertNotIn("isPaused", self.transport.alert_calls()[-1][2])
        self.transport.calls.clear()
        with self.assertRaises(GrafanaError):
            self.client.pause_budget_alert_rule(rule)
        self.assertEqual(self.transport.calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
