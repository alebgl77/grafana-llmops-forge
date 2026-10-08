"""Per-metric OTel label bindings and fail-closed metric-family selection."""
from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import discover
import forge_dashboards as forge
from grafana_client import promql_matcher


def fixture(dotted=False, legacy=False):
    stem = "gen_ai.client." if dotted else "gen_ai_client_"
    dur = stem + ("operation.duration" if dotted else "operation_duration")
    tok = stem + ("token.usage" if dotted else "token_usage")
    labels = {role: candidates[1] if dotted and len(candidates) > 1 else candidates[0]
              for role, candidates in discover.OTEL_LABEL_CANDIDATES.items()}
    metric_labels = {}
    for metric in (dur + "_count", dur + "_bucket"):
        metric_labels[metric] = {labels[role]: ["m" if role == "model" else "v"]
                                 for role in ("model", "provider", "operation", "error", "tool")}
    metric_labels[tok + "_sum"] = {labels[role]: ["m" if role == "model" else "v"]
                                   for role in ("model", "provider", "agent", "token_type")}
    metric_labels[tok + "_sum"][labels["token_type"]] = ["input", "output"]
    exact = {promql_matcher("__name__", "=", metric): values
             for metric, values in metric_labels.items()}

    def values(label, selector):
        if selector in exact:
            return exact[selector].get(label, [])
        return sorted({v for item in metric_labels.values() for v in item.get(label, [])})

    entry = {"metric_names": [base + suffix for base in (dur, tok)
                               for suffix in ("_bucket", "_count", "_sum")]}
    discover.enrich_signal_entry(entry, "otel_genai", values, "all")
    assert entry["label_bindings"][dur + "_count"]["error"] == [labels["error"]]
    assert entry["label_bindings"][tok + "_sum"]["agent"] == [labels["agent"]]
    if legacy:
        entry.pop("label_bindings")
        entry.pop("binding_gaps")
    score = "gen_ai.evaluation.score" if dotted else "gen_ai_evaluation_score"
    cap = {"org_id": 1, "datasources": {"prometheus": [{"uid": "p"}]},
           "signals": {"p": {"otel_genai": entry, "evals": {
               "metric_names": [score + suffix for suffix in ("_bucket", "_count", "_sum")],
               "model_label": labels["model"]}}}}
    return cap, dur, tok, score, labels


def context(cap):
    return forge.Ctx(cap, {"models": []})


def panel_expr(board, title):
    return next(p["targets"][0]["expr"] for p in board.d["panels"] if p["title"] == title)


def expr_test(expr, value, labels="{}"):
    return {"expr": expr.replace(forge.RATE, "5m"), "eval_time": "10m",
            "exp_samples": [{"labels": labels, "value": value}]}


def series(name, labels, step):
    selector = "{" + ",".join(f'{forge.qlbl(k)}={json.dumps(v)}' for k, v in labels.items()) + "}"
    return {"series": forge.msel(name, selector), "values": f"0+{step}x10"}


def check_unknown_bindings(out_dir):
    cap, dur, tok, _, _ = fixture()
    entry = cap["signals"]["p"]["otel_genai"]
    entry["label_bindings"][dur + "_count"]["error"] = []
    entry["label_bindings"][dur + "_count"]["operation"] = []
    entry["label_bindings"][tok + "_sum"]["agent"] = []
    ctx = context(cap)
    assert ctx.primary.err_rate() is None
    board = forge.bp_agents(ctx)
    assert board is None or all(p["title"] not in (
        "Agent invocations/s", "Tool calls/s", "Tokens per agent/s") for p in board.d["panels"])
    assert not any("burn" in a["uid"] for a in forge.build_alerts(ctx, "folder", 100))
    empty = {"metric_names": entry["metric_names"]}
    discover.enrich_signal_entry(empty, "otel_genai", lambda *_: [], "all")
    assert empty["binding_gaps"] and empty["label_bindings"][dur + "_count"]["error"] == []
    assert context({"org_id": 1, "signals": {"p": {"otel_genai": empty}}}).primary.err_rate() is None
    cap, dur, tok, _, _ = fixture()
    cap["signals"]["p"]["otel_genai"]["label_bindings"][tok + "_sum"]["token_type"] = []
    registry = {"models": [{"id": "m", "vendor": "v", "input_per_mtok": 1, "output_per_mtok": 2}]}
    ctx = forge.Ctx(cap, registry)
    assert ctx.cost_source is None and ctx.primary.tokens_rate("input") is None
    assert forge.cost_rate_expr(ctx.primary, ctx.matched) is None
    assert forge._rule_lines(ctx, "  ", "5m") == ([], 0)
    rules_path = out_dir / "missing-token-type-rules.yml"
    assert forge.emit_recording_rules(ctx, str(rules_path)) == ("", 0)
    assert not rules_path.exists()
    assert not any("budget" in a["uid"] for a in forge.build_alerts(ctx, "folder", 100))
    assert forge.bp_gateway(ctx) and any("token_type" in gap for gap in ctx.telemetry_gaps)
    path = out_dir / "unknown-token-type.json"
    path.write_text(json.dumps(cap), encoding="utf-8")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/forge_dashboards.py"),
                             "--capability", str(path), "--blueprints", "auto", "--with-alerts",
                             "--out-dir", str(out_dir / "unknown-token-type-export")],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "token_type label unknown" in result.stdout
    for role in ("model", "provider"):
        cap, dur, _, _, _ = fixture()
        cap["signals"]["p"]["otel_genai"]["label_bindings"][dur + "_count"][role] = []
        ctx = forge.Ctx(cap, registry)
        assert getattr(ctx.primary.s, role + "_label") is None
        assert forge.bp_gateway(ctx) and forge.bp_agents(ctx)
        assert any(f"{role} label unknown" in gap for gap in ctx.telemetry_gaps)
        if role == "model":
            assert ctx.cost_source is None
            assert forge.cost_rate_expr(ctx.primary, ctx.matched) is None


def check_ambiguity(out_dir):
    cap, dur, tok, _, _ = fixture()
    entry = cap["signals"]["p"]["otel_genai"]
    variants = []
    for extra in ("a_", "long_production_"):
        ambiguous = copy.deepcopy(cap)
        ambiguous["signals"]["p"]["otel_genai"]["metric_names"] += [extra + dur + suffix
                                                                    for suffix in ("_bucket", "_count", "_sum")]
        variants.append(ambiguous)
    crossed = copy.deepcopy(cap)
    crossed_entry = crossed["signals"]["p"]["otel_genai"]
    crossed_entry["metric_names"] = ["other_" + m if m.startswith(tok) else m
                                     for m in entry["metric_names"]]
    crossed_entry["label_bindings"] = {"other_" + m if m.startswith(tok) else m: v
                                       for m, v in entry["label_bindings"].items()}
    variants.append(crossed)
    mixed_labels = copy.deepcopy(cap)
    mixed_labels["signals"]["p"]["otel_genai"]["label_bindings"][tok + "_sum"]["model"] = ["model"]
    variants.append(mixed_labels)
    both_labels = copy.deepcopy(cap)
    both_labels["signals"]["p"]["otel_genai"]["label_bindings"][dur + "_count"]["error"] = ["error_type", "error.type"]
    variants.append(both_labels)
    variants.append({"org_id": 1, "signals": {"p": {"litellm": {"metric_names": [
        "litellm_proxy_total_requests_metric_total", "litellm_requests_metric_total",
        "litellm_proxy_failed_requests_metric_total"]}}}})
    for index, candidate in enumerate(variants):
        messages = []
        for reverse in (False, True):
            candidate = copy.deepcopy(candidate)
            if reverse:
                for entry in candidate["signals"]["p"].values():
                    entry["metric_names"].reverse()
            try:
                context(candidate)
                raise AssertionError("ambiguous telemetry was accepted")
            except ValueError as exc:
                message = str(exc)
                assert "p" in message and next(iter(candidate["signals"]["p"])) in message and "rediscover" in message.lower(), message
                messages.append(message)
        assert messages[0] == messages[1], messages
        path = out_dir / f"ambiguous-{index}.json"
        path.write_text(json.dumps(candidate), encoding="utf-8")
        with mock.patch.object(sys, "argv", ["forge", "--capability", str(path), "--blueprints", "gateway", "--deploy"]), \
             mock.patch.object(forge, "GrafanaClient", side_effect=AssertionError("client created before validation")), \
             contextlib.redirect_stderr(io.StringIO()):
            assert forge.main() == 2
    # Members of a single histogram are not independent metric families.
    for name in (dur, "long_namespace_" + dur):
        single = forge.Signals("otel_genai", {"metric_names": [name+s for s in ("_count", "_sum", "_bucket")]}, "p")
        assert single.hist_base("operation_duration") == name
    # Independent server telemetry is not required to share the client namespace.
    server = copy.deepcopy(cap)
    server["signals"]["p"]["otel_genai"]["metric_names"].append("server_gen_ai_server_time_to_first_token_seconds_bucket")
    assert context(server).primary.ttft
    lite = forge.Q(forge.Signals("litellm", {"metric_names": [
        "litellm_proxy_total_requests_metric_total", "litellm_proxy_failed_requests_metric_total",
        "litellm_remaining_requests_metric", "litellm_success_requests_metric_total"]}, "p"))
    assert lite.req == "litellm_proxy_total_requests_metric_total"
    assert lite.fail == "litellm_proxy_failed_requests_metric_total"
    assert lite.remaining_req == "litellm_remaining_requests_metric"
    for prefix in ("", "team_"):
        legacy = forge.Q(forge.Signals("litellm", {"metric_names": [
            prefix + "litellm_requests_metric_total", prefix + "litellm_requests_metric_created",
            prefix + "litellm_remaining_requests_metric", prefix + "litellm_proxy_failed_requests_metric_total"]}, "p"))
        assert legacy.req == prefix + "litellm_requests_metric_total"
    dotted_name = "litellm.proxy.total.requests.metric.total"
    dotted = forge.Q(forge.Signals("litellm", {"metric_names": [dotted_name]}, "p"))
    assert dotted.req == dotted_name
    both_models = copy.deepcopy(cap)
    for binding in both_models["signals"]["p"]["otel_genai"]["label_bindings"].values():
        binding["model"].append("gen_ai_response_model")
    assert context(both_models).primary.s.model_label == "gen_ai_request_model"


def run(promtool, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    check_unknown_bindings(out_dir)
    check_ambiguity(out_dir)
    tests = []
    for dotted in (False, True):
        for legacy in (False, True):
            cap, dur, tok, score, lbl = fixture(dotted, legacy)
            ctx = context(cap)
            agents, quality = forge.bp_agents(ctx), forge.bp_quality(ctx)
            model = {lbl["model"]: "m"}
            inputs = []
            for op in ("invoke_agent", "execute_tool"):
                labels = {**model, lbl["operation"]: op, lbl["error"]: "timeout", lbl["tool"]: "search"}
                inputs.append(series(dur + "_count", labels, 60))
                for le in ("1", "+Inf"):
                    inputs.append(series(dur + "_bucket", {**labels, "le": le}, 60))
            inputs.append(series(tok + "_sum", {**model, lbl["agent"]: "alpha", lbl["token_type"]: "input"}, 600))
            for le in ("1", "+Inf"):
                inputs.append(series(score + "_bucket", {**model, "le": le}, 60))
            inputs.append(series(score + "_count", model, 60))
            tests.append({"name": f"dotted={dotted} legacy={legacy}", "interval": "1m", "input_series": inputs,
                          "promql_expr_test": [
                              expr_test(ctx.primary.error_ratio(w="5m"), 1),
                              expr_test(panel_expr(agents, "Agent invocations/s"), 1),
                              expr_test(panel_expr(agents, "Tool calls/s"), 1),
                              expr_test(panel_expr(agents, "Tool errors/s"), 1),
                              expr_test(panel_expr(agents, "Calls per tool (execute_tool)"), 1,
                                        "{" + forge.qlbl(lbl["tool"]) + '="search"}'),
                              expr_test(panel_expr(agents, "Tokens per agent/s"), 10,
                                        "{" + forge.qlbl(lbl["agent"]) + '="alpha"}'),
                              expr_test(panel_expr(quality, "Median score"), .5),
                              expr_test(panel_expr(quality, "Score by model (p50)"), .5,
                                        "{" + forge.qlbl(lbl["model"]) + '="m"}'),
                              expr_test(panel_expr(quality, "Evaluation volume/s"), 1)]})
            alerts = forge.build_alerts(ctx, "folder", 100)
            burn = next(a for a in alerts if "burn-fast" in a["uid"])
            tests[-1]["promql_expr_test"].append(expr_test(burn["data"][0]["model"]["expr"], 1))
            alert = next(a for a in alerts if "quality-drop" in a["uid"])
            tests[-1]["promql_expr_test"].append(expr_test(alert["data"][0]["model"]["expr"], .5))
    lite = forge.Q(forge.Signals("litellm", {"metric_names": [
        "litellm_proxy_total_requests_metric_total", "litellm_proxy_failed_requests_metric_total",
        "litellm_remaining_requests_metric", "litellm_success_requests_metric_total"]}, "p"))
    tests.append({"name": "LiteLLM adjacent request roles", "interval": "1m", "input_series": [
        series(lite.req, {}, 120), series(lite.fail, {}, 60),
        {"series": lite.remaining_req, "values": "1000+0x10"},
        series("litellm_success_requests_metric_total", {}, 60)], "promql_expr_test": [
            expr_test(lite.req_rate(w="5m"), 2), expr_test(lite.err_rate(w="5m"), 1),
            expr_test(lite.error_ratio(w="5m"), .5)]})
    dotted = forge.Q(forge.Signals("litellm", {"metric_names": ["litellm.proxy.total.requests.metric.total"]}, "p"))
    tests.append({"name": "LiteLLM fully dotted counter", "interval": "1m",
                  "input_series": [series(dotted.req, {}, 60)],
                  "promql_expr_test": [expr_test(dotted.req_rate(w="5m"), 1)]})
    path = out_dir / "p1_telemetry_invariants.json"
    path.write_text(json.dumps({"evaluation_interval": "1m", "tests": tests}, indent=2), encoding="utf-8")
    result = subprocess.run([promtool, "test", "rules", str(path)], check=False)
    print("Telemetry: 6 naming/legacy/role scenarios, 48 query assertions; ambiguity and unknown-label checks passed.")
    return result.returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--promtool", default=os.environ.get("PROMTOOL", "promtool"))
    ap.add_argument("--out-dir")
    args = ap.parse_args()
    if args.out_dir:
        return run(args.promtool, pathlib.Path(args.out_dir))
    with tempfile.TemporaryDirectory(prefix="forge-telemetry-") as tmp:
        return run(args.promtool, pathlib.Path(tmp))


if __name__ == "__main__":
    sys.exit(main())
