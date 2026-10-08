"""Real Grafana alert lifecycle with a controlled Prometheus datasource.

Run only against the disposable CI Compose Grafana. Expressions and query models
come unchanged from build_alerts(); only the pending duration and evaluation
interval are shortened. The fixture preserves historical firing samples after
recovery, so a range query plus last() cannot accidentally pass this test.
PromQL calculations themselves are covered separately by promtool invariants.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import pathlib
import sys
import threading
import time
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import forge_dashboards as forge
from grafana_client import GrafanaClient, det_uid


class ControlledDatasource:
    def __init__(self, expressions):
        self.expressions = set(expressions)
        self.lock = threading.Lock()
        self.phase = "normal"
        self.since = time.time()
        self.historical_at = None
        self.requests = []

    def transition(self, phase):
        with self.lock:
            self.phase, self.since = phase, time.time()
            if phase == "firing":
                self.historical_at = self.since

    def query(self, endpoint, parameters):
        expression = parameters.get("query", [""])[0]
        with self.lock:
            phase, historical = self.phase, self.historical_at
            self.requests.append({"phase": phase, "endpoint": endpoint, "expression": expression})
            if expression not in self.expressions:
                return 422, {"status": "error", "errorType": "bad_data", "error": "unexpected expression"}
            if endpoint == "/api/v1/query":
                result = ([{"metric": {}, "value": [time.time(), "1"]}]
                          if phase == "firing" else [])
                kind = "vector"
            elif endpoint == "/api/v1/query_range":
                # An older firing point survives even when the current result
                # disappears. This is the actual range+last regression shape.
                result = ([{"metric": {}, "values": [[historical, "1"]]}]
                          if historical is not None else [])
                kind = "matrix"
            else:
                return 404, {"status": "error", "error": "unexpected endpoint"}
        return 200, {"status": "success", "data": {"resultType": kind, "result": result}}

    def phase_requests(self):
        with self.lock:
            return [dict(item) for item in self.requests if item["phase"] == self.phase]


def server_for(fixture, bind):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond()

        def do_POST(self):
            self.respond()

        def respond(self):
            parsed = urllib.parse.urlsplit(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            if self.command == "POST":
                body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode()
                params.update(urllib.parse.parse_qs(body))
            if parsed.path == "/api/v1/status/buildinfo":
                status, payload = 200, {"status": "success", "data": {"version": "3.14.0"}}
            else:
                status, payload = fixture.query(parsed.path, params)
            encoded = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer((bind, 0), Handler)


def generated_burn_rules(org_id, folder_uid, datasource_uid):
    cap = forge.selftest_capability()
    old_uid = cap["datasources"]["prometheus"][0]["uid"]
    entry = copy.deepcopy(cap["signals"][old_uid]["otel_genai"])
    cap["signals"] = {datasource_uid: {"otel_genai": entry}}
    cap["datasources"]["prometheus"] = [{"uid": datasource_uid, "name": "Controlled CI datasource"}]
    cap["org_id"] = org_id
    registry = json.loads((ROOT / "references" / "model_registry.json").read_text(encoding="utf-8"))
    ctx = forge.Ctx(cap, registry)
    ctx.org_id, ctx.uid_scope = org_id, "ci-burn-recovery"
    rules = [rule for rule in forge.build_alerts(ctx, folder_uid, 500, .99)
             if "error-budget burn" in rule["title"]]
    assert len(rules) == 2, "both generated burn rules are required"
    for rule in rules:
        assert rule["noDataState"] == "OK"
        assert rule["data"][0]["model"].get("instant") is True
        assert rule["data"][0]["model"].get("range") is False
        rule["for"] = "0s"  # CI only: preserve production expression and model.
    return rules


def evaluation_timestamp(rule):
    value = rule.get("lastEvaluation")
    if not isinstance(value, str):
        return 0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0


def wait_for_state(client, rules, fixture, expected, timeout):
    titles = {rule["title"] for rule in rules}
    deadline = time.monotonic() + timeout
    observed = {}
    while time.monotonic() < deadline:
        body = client.get("/api/prometheus/grafana/api/v1/rules")
        groups = body.get("data", {}).get("groups", [])
        observed = {rule["name"]: rule for group in groups for rule in group.get("rules", [])
                    if rule.get("name") in titles}
        requests = fixture.phase_requests()
        queried = {item["expression"] for item in requests}
        if (set(observed) == titles and fixture.expressions <= queried
                and all(rule.get("state") == expected and not rule.get("lastError")
                        and evaluation_timestamp(rule) >= fixture.since
                        for rule in observed.values())):
            assert all(item["endpoint"] == "/api/v1/query" for item in requests), requests
            print(f"{fixture.phase}: {expected}; both generated burn rules evaluated", flush=True)
            return
        time.sleep(1)
    diagnostics = {name: {key: rule.get(key) for key in
                   ("state", "health", "lastError", "lastEvaluation")} for name, rule in observed.items()}
    raise AssertionError(json.dumps({"phase": fixture.phase, "expected": expected,
                                    "rules": diagnostics, "requests": fixture.phase_requests()}, indent=2))


def fixture_selftest():
    fixture = ControlledDatasource({"generated expression"})
    query = {"query": ["generated expression"]}
    assert fixture.query("/api/v1/query", query)[1]["data"]["result"] == []
    assert fixture.query("/api/v1/query_range", query)[1]["data"]["result"] == []
    fixture.transition("firing")
    assert fixture.query("/api/v1/query", query)[1]["data"]["result"][0]["value"][1] == "1"
    fixture.transition("recovered")
    assert fixture.query("/api/v1/query", query)[1]["data"]["result"] == []
    assert fixture.query("/api/v1/query_range", query)[1]["data"]["result"][0]["values"][0][1] == "1"
    assert fixture.query("/api/v1/query", {"query": ["changed expression"]})[0] == 422
    rules = generated_burn_rules(1, "fixture-folder", "fixture-prometheus")
    assert all(rule["data"][0]["relativeTimeRange"]["from"] == 21600 for rule in rules)
    print("Controlled datasource selftest PASS; historical firing retained only after firing")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--datasource-host", help="Docker host gateway reachable from disposable Grafana")
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()
    if args.selftest:
        fixture_selftest()
        return 0
    if os.environ.get("CI") != "true" or not args.datasource_host:
        parser.error("writes are restricted to CI with an explicit --datasource-host")
    target = urllib.parse.urlsplit(os.environ.get("GRAFANA_URL", ""))
    if target.hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("only the disposable loopback Grafana is supported")
    client = GrafanaClient()
    org = client.resolve_org()
    folder_uid = det_uid("CI controlled burn recovery", "fold", "ci-burn-recovery")
    datasource_uid = "forge-ci-burn-controlled"
    rules = generated_burn_rules(org, folder_uid, datasource_uid)
    fixture = ControlledDatasource({rule["data"][0]["model"]["expr"] for rule in rules})
    server = server_for(fixture, args.bind)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client.post("/api/datasources", {"uid": datasource_uid, "name": "CI controlled burn recovery",
                    "type": "prometheus", "access": "proxy", "isDefault": False,
                    "url": f"http://{args.datasource_host}:{server.server_port}",
                    "jsonData": {"httpMethod": "POST", "prometheusType": "Prometheus", "prometheusVersion": "3.14.0"}})
        client.ensure_folder("CI controlled burn recovery", folder_uid)
        for rule in rules:
            client.upsert_alert_rule(rule)
        client.put(f"/api/v1/provisioning/folder/{folder_uid}/rule-groups/llmops-slo",
                   {"folderUid": folder_uid, "title": "llmops-slo", "interval": 10, "rules": rules})
        for phase, expected in (("normal", "inactive"), ("firing", "firing"),
                                ("recovered", "inactive"), ("no_traffic", "inactive"),
                                ("absent", "inactive")):
            fixture.transition(phase)
            wait_for_state(client, rules, fixture, expected, args.timeout)
        print("Grafana controlled-datasource recovery PASS: Normal -> Alerting -> Normal; absent/no-traffic OK")
        return 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
