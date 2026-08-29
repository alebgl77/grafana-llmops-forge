"""Émetteur de métriques LLM synthétiques — sert /metrics au format Prometheus.

Simule une plateforme IA d'entreprise plausible : plusieurs modèles US/EU/Asie,
des agents et des outils, une passerelle LiteLLM, un vLLM self-hosted et des GPU.
Sert uniquement à la démo, aux captures et au test d'intégration : aucune de ces
valeurs ne vient d'un vrai système.

Aucune dépendance (stdlib). Python 3.8+.
    python3 emitter.py --port 9109
"""
from __future__ import annotations

import argparse
import math
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

MODELS = [  # (nom, part du trafic, latence médiane s, tokens out moyens)
    ("gpt-5.4",           0.26, 2.1, 480),
    ("claude-haiku-4.5",  0.34, 0.9, 320),
    ("claude-sonnet-4.6", 0.11, 2.6, 610),
    ("mistral-small-3.2", 0.12, 0.7, 260),
    ("deepseek-v4-flash", 0.14, 1.1, 540),
    ("modele-maison-x",   0.03, 1.8, 300),  # volontairement hors registre de prix
]
PROVIDER = {"gpt-5.4": "openai", "claude-haiku-4.5": "anthropic",
            "claude-sonnet-4.6": "anthropic", "mistral-small-3.2": "mistral_ai",
            "deepseek-v4-flash": "deepseek", "modele-maison-x": "self_hosted"}
PRICE = {"gpt-5.4": (2.5, 15), "claude-haiku-4.5": (0.8, 4),
         "claude-sonnet-4.6": (3, 15), "mistral-small-3.2": (0.1, 0.3),
         "deepseek-v4-flash": (0.14, 0.28), "modele-maison-x": (0, 0)}
SERVICES = ["support-bot", "sales-copilot", "doc-search", "code-review", "rh-screening"]
TEAMS = ["platform", "sales", "support", "data", "rh"]
OPS = [("chat", 0.62), ("embeddings", 0.22), ("invoke_agent", 0.10), ("execute_tool", 0.06)]
TOOLS = ["web_search", "sql_query", "crm_lookup", "vector_search", "send_email"]
AGENTS = ["support-router", "quote-builder", "doc-indexer"]
ERRORS = ["rate_limit", "timeout", "content_filter", "server_error"]
DUR_BUCKETS = [0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32]
TOK_BUCKETS = [16, 64, 256, 1024, 4096, 16384, 65536]

S = {"t0": time.time(), "dur": {}, "tok": {}, "ttft": {}, "spend": {}, "req": {},
     "fail": {}, "lin": {}, "lout": {}, "vllm_p": 0.0, "vllm_g": 0.0,
     "vllm_ttft": {}, "vllm_e2e": {}, "evals": {}, "guard": 0.0, "preempt": 0.0}
LOCK = threading.Lock()


def _hist(store, key, value, buckets):
    h = store.setdefault(key, {"c": 0, "s": 0.0, "b": [0] * len(buckets)})
    h["c"] += 1
    h["s"] += value
    for i, b in enumerate(buckets):
        if value <= b:
            h["b"][i] += 1


def simulate(step: float):
    """Une itération de trafic. Cycle jour/nuit + bruit, pour des courbes lisibles."""
    phase = (time.time() - S["t0"]) / 900.0            # ~15 min = une "journée"
    load = 22 * (0.55 + 0.45 * math.sin(phase * 2 * math.pi)) * step
    with LOCK:
        for name, share, med, avg_out in MODELS:
            n = max(0, int(random.gauss(load * share, load * share * 0.18)))
            prov, (pin, pout) = PROVIDER[name], PRICE[name]
            for _ in range(n):
                op = random.choices([o for o, _ in OPS], [w for _, w in OPS])[0]
                svc = random.choice(SERVICES)
                err = random.choice(ERRORS) if random.random() < 0.021 else ""
                lat = max(0.02, random.lognormvariate(math.log(med), 0.45))
                if op == "embeddings":
                    lat *= 0.2
                _hist(S["dur"], (name, prov, op, svc, err), lat, DUR_BUCKETS)
                if err:
                    continue
                tin = max(20, int(random.lognormvariate(math.log(900), 0.6)))
                tout = max(5, int(random.lognormvariate(math.log(avg_out), 0.5)))
                _hist(S["tok"], (name, prov, "input", svc), tin, TOK_BUCKETS)
                _hist(S["tok"], (name, prov, "output", svc), tout, TOK_BUCKETS)
                _hist(S["ttft"], (name, prov), lat * random.uniform(0.15, 0.4),
                      DUR_BUCKETS)
                team = TEAMS[SERVICES.index(svc)]
                k = (name, prov, team)
                S["spend"][k] = S["spend"].get(k, 0.0) + (tin * pin + tout * pout) / 1e6
                S["req"][k] = S["req"].get(k, 0) + 1
                S["lin"][k] = S["lin"].get(k, 0) + tin
                S["lout"][k] = S["lout"].get(k, 0) + tout
                if op in ("invoke_agent", "execute_tool") and random.random() < 0.5:
                    _hist(S["evals"], (name, random.choice(["ragas", "llm-judge"])),
                          min(1.0, max(0.0, random.gauss(0.82, 0.12))),
                          [0.2, 0.4, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0])
                if random.random() < 0.012:
                    S["guard"] += 1
        for k in list(S["req"]):
            if random.random() < 0.02:
                S["fail"][k] = S["fail"].get(k, 0) + 1
        pt = load * 640
        S["vllm_p"] += pt
        S["vllm_g"] += pt * 0.36
        for _ in range(max(1, int(load * 0.3))):
            _hist(S["vllm_ttft"], ("Qwen/Qwen3.6-32B",),
                  max(0.01, random.lognormvariate(math.log(0.22), 0.5)), DUR_BUCKETS)
            _hist(S["vllm_e2e"], ("Qwen/Qwen3.6-32B",),
                  max(0.05, random.lognormvariate(math.log(2.4), 0.4)), DUR_BUCKETS)
        if random.random() < 0.08:
            S["preempt"] += 1


def _emit_hist(out, metric, unit, labels_names, store, buckets):
    out.append(f"# TYPE {metric} histogram")
    for key, h in store.items():
        lab = ",".join(f'{n}="{v}"' for n, v in zip(labels_names, key))
        for b, c in zip(buckets, h["b"]):
            out.append(f'{metric}_bucket{{{lab},le="{b}"}} {c}')
        out.append(f'{metric}_bucket{{{lab},le="+Inf"}} {h["c"]}')
        out.append(f"{metric}_sum{{{lab}}} {h['s']:.4f}")
        out.append(f"{metric}_count{{{lab}}} {h['c']}")


def render() -> str:
    o: list = []
    with LOCK:
        _emit_hist(o, "gen_ai_client_operation_duration_seconds", "s",
                   ["gen_ai_request_model", "gen_ai_provider_name",
                    "gen_ai_operation_name", "service_name", "error_type"],
                   S["dur"], DUR_BUCKETS)
        _emit_hist(o, "gen_ai_client_token_usage_token", "1",
                   ["gen_ai_request_model", "gen_ai_provider_name",
                    "gen_ai_token_type", "service_name"], S["tok"], TOK_BUCKETS)
        _emit_hist(o, "gen_ai_server_time_to_first_token_seconds", "s",
                   ["gen_ai_request_model", "gen_ai_provider_name"],
                   S["ttft"], DUR_BUCKETS)
        _emit_hist(o, "gen_ai_evaluation_score", "1",
                   ["gen_ai_request_model", "evaluator"], S["evals"],
                   [0.2, 0.4, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0])
        o.append("# TYPE guardrail_blocked_total counter")
        o.append(f"guardrail_blocked_total {int(S['guard'])}")
        for metric, src, typ in (("litellm_spend_metric_total", S["spend"], "counter"),
                                 ("litellm_proxy_total_requests_metric_total", S["req"], "counter"),
                                 ("litellm_proxy_failed_requests_metric_total", S["fail"], "counter"),
                                 ("litellm_input_tokens_metric_total", S["lin"], "counter"),
                                 ("litellm_output_tokens_metric_total", S["lout"], "counter")):
            o.append(f"# TYPE {metric} {typ}")
            for (m, p, t), v in src.items():
                o.append(f'{metric}{{model="{m}",api_provider="{p}",team="{t}"}} '
                         f"{v:.6f}")
        o.append("# TYPE litellm_remaining_requests_metric gauge")
        for prov in set(PROVIDER.values()):
            o.append(f'litellm_remaining_requests_metric{{api_provider="{prov}"}} '
                     f"{random.randint(400, 5000)}")
        _emit_hist(o, "vllm:time_to_first_token_seconds", "s", ["model_name"],
                   S["vllm_ttft"], DUR_BUCKETS)
        _emit_hist(o, "vllm:e2e_request_latency_seconds", "s", ["model_name"],
                   S["vllm_e2e"], DUR_BUCKETS)
        m = 'model_name="Qwen/Qwen3.6-32B"'
        o += ["# TYPE vllm:prompt_tokens_total counter",
              f"vllm:prompt_tokens_total{{{m}}} {int(S['vllm_p'])}",
              "# TYPE vllm:generation_tokens_total counter",
              f"vllm:generation_tokens_total{{{m}}} {int(S['vllm_g'])}",
              "# TYPE vllm:num_preemptions_total counter",
              f"vllm:num_preemptions_total{{{m}}} {int(S['preempt'])}",
              "# TYPE vllm:num_requests_running gauge",
              f"vllm:num_requests_running{{{m}}} {random.randint(2, 28)}",
              "# TYPE vllm:num_requests_waiting gauge",
              f"vllm:num_requests_waiting{{{m}}} {random.randint(0, 9)}",
              "# TYPE vllm:gpu_cache_usage_perc gauge",
              f"vllm:gpu_cache_usage_perc{{{m}}} {random.uniform(0.45, 0.88):.3f}",
              "# TYPE DCGM_FI_DEV_GPU_UTIL gauge"]
        for g in (0, 1):
            o += [f'DCGM_FI_DEV_GPU_UTIL{{gpu="{g}"}} {random.uniform(55, 96):.1f}',
                  f'DCGM_FI_DEV_FB_USED{{gpu="{g}"}} {random.uniform(38000, 74000):.0f}',
                  f'DCGM_FI_DEV_POWER_USAGE{{gpu="{g}"}} {random.uniform(210, 390):.0f}']
    return "\n".join(o) + "\n"


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/metrics"):
            body = render().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(200); self.end_headers()
            self.wfile.write(b"llmops-forge demo emitter - see /metrics\n")

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9109)
    ap.add_argument("--seed-minutes", type=float, default=45,
                    help="Historique pré-généré pour que les graphes ne soient pas vides")
    a = ap.parse_args()
    for _ in range(int(a.seed_minutes * 4)):   # amorçage rapide
        simulate(1.5)
    def loop():
        while True:
            simulate(1.0)
            time.sleep(1)
    threading.Thread(target=loop, daemon=True).start()
    print(f"emitter → http://0.0.0.0:{a.port}/metrics", flush=True)
    HTTPServer(("0.0.0.0", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
