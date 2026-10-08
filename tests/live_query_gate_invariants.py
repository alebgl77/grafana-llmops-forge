"""Offline contract tests for the live Prometheus gate, including its CLI flow."""
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
from unittest.mock import patch

import live_query_check as live


def response(data):
    return io.BytesIO(data if isinstance(data, bytes) else json.dumps(data).encode())


def vector(value="1"):
    return {"status": "success", "data": {"resultType": "vector", "result": [
        {"metric": {"model": "fixture"}, "value": [100, value]}]}}


class QueryContractTests(unittest.TestCase):
    def query(self, body):
        with patch.object(live.urllib.request, "urlopen", return_value=response(body)):
            return live.q("http://fixture.invalid", "up")

    def test_finite_vector_scalar_and_matrix_are_accepted(self):
        self.assertEqual(self.query(vector("0")), ("ok", 1))
        self.assertEqual(self.query({"status": "success", "data": {
            "resultType": "scalar", "result": [100, "1.5"]}}), ("ok", 1))
        self.assertEqual(self.query({"status": "success", "data": {
            "resultType": "matrix", "result": [{"metric": {}, "values": [[100, "0"], [101, "2"]]}]}}), ("ok", 1))

    def test_nonfinite_values_are_rejected(self):
        for value in ("NaN", "+Inf", "-Inf", "1e999"):
            with self.subTest(value=value):
                self.assertTrue(self.query(vector(value))[0].startswith("error:"))

    def test_malformed_envelopes_and_samples_are_rejected(self):
        cases = [None, [], {}, {"status": "error", "error": "bad"},
                 {"status": "success"}, {"status": "success", "data": []},
                 {"status": "success", "data": {"resultType": "unknown", "result": []}}]
        for bad in ({}, {"metric": {}, "value": [100]},
                    {"metric": {}, "value": [True, "1"]},
                    {"metric": {}, "value": [100, 1]},
                    {"metric": {"model": 1}, "value": [100, "1"]},
                    {"metric": {}, "value": [float("inf"), "1"]}):
            cases.append({"status": "success", "data": {"resultType": "vector", "result": [bad]}})
        for body in cases:
            with self.subTest(body=body):
                self.assertTrue(self.query(body)[0].startswith("error:"))

    def test_transport_http_and_invalid_json_have_error_status(self):
        failures = [TimeoutError(), urllib.error.URLError("offline"),
                    urllib.error.HTTPError("http://fixture.invalid", 502, "bad", {}, io.BytesIO(b"<html>bad</html>"))]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), patch.object(
                    live.urllib.request, "urlopen", side_effect=failure):
                self.assertTrue(live.q("http://fixture.invalid", "up")[0].startswith("error:"))
        with patch.object(live.urllib.request, "urlopen", return_value=io.BytesIO(b"not JSON")):
            self.assertTrue(live.q("http://fixture.invalid", "up")[0].startswith("error:"))

    def test_empty_vector_is_distinct_from_failure(self):
        self.assertEqual(self.query({"status": "success", "data": {
            "resultType": "vector", "result": []}}), ("empty", 0))

    def test_discovery_failure_and_malformed_values_are_not_silenced(self):
        for function, arguments in ((live.names, ("up",)), (live.label_values, ("model", "up"))):
            with self.subTest(function=function.__name__), patch.object(
                    live.urllib.request, "urlopen", side_effect=TimeoutError()):
                with self.assertRaises(live.PrometheusCheckError):
                    function("http://fixture.invalid", *arguments)
            for data in ({}, [1]):
                with self.subTest(function=function.__name__, data=data), patch.object(
                        live.urllib.request, "urlopen", return_value=response({"status": "success", "data": data})):
                    with self.assertRaises(live.PrometheusCheckError):
                        function("http://fixture.invalid", *arguments)


class MainFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="live-gate-")
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.capability = {"signals": {"live": {"fixture": {"metric_names": ["fixture_gauge"]}}}}

    def run_main(self, *, body=None, query_status=None, board=None, discovery=None,
                 outputs=True, wait=0, filename="fixture.json"):
        out = self.root / "generated"
        out.mkdir(exist_ok=True)
        default_board = {"panels": [{"title": "Fixture", "datasource": {"type": "prometheus"},
                                     "targets": [{"expr": "fixture_gauge"}]}]}
        def forge(*args, **kwargs):
            if outputs:
                (out / filename).write_text(json.dumps(board or default_board), encoding="utf-8")
            return type("Result", (), {"returncode": 0, "stdout": "generated\n", "stderr": ""})()
        argv = ["live_query_check.py", "--wait-for-data", str(wait), "--out-dir", str(out),
                "--capability", str(self.root / "cap.json")]
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(sys, "argv", argv))
            if isinstance(discovery, Exception):
                stack.enter_context(patch.object(live, "build_map", side_effect=discovery))
            else:
                stack.enter_context(patch.object(live, "build_map", return_value=discovery or self.capability))
            stack.enter_context(patch.object(live.subprocess, "run", side_effect=forge))
            if query_status is not None:
                setting = {"side_effect": query_status} if isinstance(query_status, list) else {"return_value": query_status}
                stack.enter_context(patch.object(live, "q", **setting))
            elif isinstance(body, Exception):
                stack.enter_context(patch.object(live.urllib.request, "urlopen", side_effect=body))
            else:
                stack.enter_context(patch.object(live.urllib.request, "urlopen", side_effect=lambda *a, **k: response(body)))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            stack.enter_context(patch.object(live.time, "sleep"))
            return live.main()

    def test_healthy_generated_query_passes(self):
        self.assertEqual(self.run_main(body=vector()), 0)

    def test_cli_rejects_timeout_http_malformed_json_and_nonfinite_values(self):
        cases = [TimeoutError(), urllib.error.HTTPError("http://fixture.invalid", 502, "bad", {}, io.BytesIO(b"bad")),
                 b"not JSON", [], {"status": "success", "data": {}}, vector("NaN"), vector("+Inf")]
        for body in cases:
            with self.subTest(body=body):
                self.assertEqual(self.run_main(body=body), 1)

    def test_cli_status_allowlist_rejects_unknown_statuses(self):
        for status in ("http 502", "unreachable: timeout", "unexpected", "error:bad"):
            with self.subTest(status=status):
                self.assertEqual(self.run_main(query_status=(status, 0)), 1)

    def test_empty_results_do_not_escape_by_matching_old_broad_patterns(self):
        for expression in ('sum(llm:cost_usd_per_second)', 'up offset 1h', 'sum(errors{error_type!=""})'):
            board = {"panels": [{"title": "Fixture", "datasource": {"type": "prometheus"}, "targets": [{"expr": expression}]}]}
            with self.subTest(expression=expression):
                self.assertEqual(self.run_main(query_status=("empty", 0), board=board), 1)

    def test_no_checks_or_dead_discovery_fails(self):
        self.assertEqual(self.run_main(outputs=False), 1)
        self.assertEqual(self.run_main(discovery={"signals": {"live": {}}}), 1)
        self.assertEqual(self.run_main(discovery=live.PrometheusCheckError("backend unavailable")), 1)

    def test_no_usable_counter_traffic_fails(self):
        cap = copy.deepcopy(self.capability)
        cap["signals"]["live"]["fixture"]["metric_names"] = ["fixture_total"]
        self.assertEqual(self.run_main(discovery=cap, query_status=("empty", 0)), 1)

    def test_startup_waits_for_finite_samples_but_not_transport_errors(self):
        self.assertEqual(self.run_main(query_status=[("empty", 0), ("error:non-finite sample", 0), ("ok", 1)], wait=1), 0)
        self.assertEqual(self.run_main(query_status=[("error:HTTP 502", 0)], wait=1), 1)

    def test_cli_accepts_only_the_intentional_tool_error_empty_panel(self):
        expression = 'sum(rate(requests_total{operation="execute_tool",error_type!=""}[5m]))'
        board = {"panels": [{"title": "Tool errors/s", "datasource": {"type": "prometheus"},
                             "targets": [{"expr": expression}]}]}
        self.assertEqual(self.run_main(query_status=("empty", 0), board=board, filename="agents.json"), 0)
        board["panels"][0]["title"] = "Tool calls/s"
        self.assertEqual(self.run_main(query_status=("empty", 0), board=board, filename="agents.json"), 1)

    def test_intentional_empty_exception_is_narrow(self):
        self.assertTrue(live.expected_empty("alert_alr-llm-burn-fast-abc.json", "LLM · Fast error-budget burn", "a and b"))
        self.assertFalse(live.expected_empty("gateway.json", "LLM · Fast error-budget burn", "a and b"))
        self.assertTrue(live.expected_empty("adoption.json", "New adopters (7d)", "a unless (a offset 7d)"))
        self.assertFalse(live.expected_empty("adoption.json", "Other panel", "a offset 7d"))
        tool = 'sum(rate(requests_total{operation="execute_tool",error_type!=""}[5m]))'
        self.assertTrue(live.expected_empty("agents.json", "Tool errors/s", tool))
        self.assertFalse(live.expected_empty("agents.json", "Tool errors/s", tool.replace("execute_tool", "chat")))
        self.assertFalse(live.expected_empty("gateway.json", "Tool errors/s", tool))
        self.assertFalse(live.expected_empty("agents.json", "Tool errors/s", 'sum(rate(requests_total[5m]))'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
