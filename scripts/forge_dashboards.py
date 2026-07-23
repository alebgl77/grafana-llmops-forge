"""Forge : génération + déploiement de dashboards LLMOps sur Grafana.

Traduit 6 blueprints (finops, gateway, agents, adoption, inference, governance)
dans le dialecte de télémétrie détecté par discover.py, compose les expressions
de coût à partir du registre de modèles, déploie (API legacy, fallback resource),
et provisionne les alertes SLO. Schéma classique v41 = compatible OSS/Cloud/
Enterprise, Grafana 9 → 13+. Python stdlib uniquement.

Usage :
    python3 forge_dashboards.py --capability capability_map.json --blueprints auto --deploy --with-alerts
    python3 forge_dashboards.py --selftest
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grafana_client import GrafanaClient, det_uid  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY_PATHS = ["model_registry.local.json",
                  os.path.join(HERE, "..", "references", "model_registry.json")]
FOLDER_TITLE_DEFAULT = "AI Observability"
RATE = "$__rate_interval"

# --------------------------------------------------------------------------- #
#  Résolution des signaux : la capability map fait foi, pas la théorie.       #
# --------------------------------------------------------------------------- #

class Signals:
    """Résout les noms réels de métriques + labels pour un dialecte donné."""

    def __init__(self, dialect: str, entry: dict, ds_uid: str):
        self.dialect = dialect
        self.ds_uid = ds_uid
        self.names = entry.get("metric_names", [])
        self.model_label = entry.get("model_label")
        self.provider_label = entry.get("provider_label")
        self.token_type_label = entry.get("token_type_label") or "gen_ai_token_type"
        self.models_seen = entry.get("models_seen", [])
        self.providers_seen = entry.get("providers_seen", [])
        groups = sorted(entry.get("group_labels", []), key=lambda g: g["cardinality"])
        self.group_label = groups[0]["label"] if groups else None

    def find(self, substr: str, suffix: str | None = None) -> str | None:
        cands = [n for n in self.names if substr in n]
        if suffix:
            cands = [n for n in cands if n.endswith(suffix)]
        return sorted(cands, key=len)[0] if cands else None

    def hist_base(self, substr: str) -> str | None:
        b = self.find(substr, "_bucket")
        return b[:-len("_bucket")] if b else None

    def counter(self, substr: str) -> str | None:
        return self.find(substr, "_total") or self.find(substr)


def _esc(v: str) -> str:
    return re.sub(r'([\\"])', r"\\\1", v)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


class Q:
    """Fabrique de requêtes canoniques par dialecte. None = signal indisponible."""

    def __init__(self, sig: Signals):
        self.s = sig
        d = sig.dialect
        if d == "otel_genai":
            self.dur = sig.hist_base("client_operation_duration") or sig.hist_base("operation_duration")
            self.tok = sig.hist_base("client_token_usage") or sig.hist_base("token_usage")
            self.ttft = sig.hist_base("server_time_to_first_token") or sig.hist_base("time_to_first_token")
            self.tpot = sig.hist_base("time_per_output_token")
        elif d == "litellm":
            self.dur = sig.hist_base("request_total_latency") or sig.hist_base("llm_api_latency")
            self.spend = sig.counter("spend")
            self.req = sig.counter("proxy_total_requests") or sig.counter("requests_metric")
            self.fail = sig.counter("proxy_failed_requests") or sig.counter("api_failed_requests")
            self.tok_in = sig.counter("input_tokens")
            self.tok_out = sig.counter("output_tokens")
            self.remaining_req = sig.find("remaining_requests")
        elif d == "vllm":
            self.ttft = sig.hist_base("time_to_first_token_seconds")
            self.tpot = sig.hist_base("time_per_output_token_seconds")
            self.e2e = sig.hist_base("e2e_request_latency_seconds")
            self.running = sig.find("num_requests_running")
            self.waiting = sig.find("num_requests_waiting")
            self.preempt = sig.counter("num_preemptions")
            self.kv = sig.find("gpu_cache_usage_perc") or sig.find("kv_cache_usage")
            self.tok_prompt = sig.counter("prompt_tokens")
            self.tok_gen = sig.counter("generation_tokens")
        elif d == "tgi":
            self.dur = sig.hist_base("request_inference_duration") or sig.hist_base("request_duration")
            self.tpot = sig.hist_base("request_mean_time_per_token_duration")
            self.queue = sig.find("queue_size")
        elif d in ("gpu_dcgm", "gpu_smi"):
            self.gpu_util = sig.find("GPU_UTIL") or sig.find("utilization")
            self.vram = sig.find("FB_USED") or sig.find("memory_used")
            self.power = sig.find("POWER_USAGE") or sig.find("power")

    # -- primitives --------------------------------------------------------
    def by(self, label: str | None) -> str:
        return f" by({label})" if label else ""

    def pXX(self, base: str, q: float, sel: str = "", by: str | None = None) -> str:
        grp = f"le,{by}" if by else "le"
        return (f"histogram_quantile({q}, sum by({grp})"
                f"(rate({base}_bucket{sel}[{RATE}])))")

    def req_rate(self, by: str | None = None, sel: str = "") -> str | None:
        d = self.s.dialect
        if d in ("otel_genai", "tgi") and getattr(self, "dur", None):
            return f"sum{self.by(by)}(rate({self.dur}_count{sel}[{RATE}]))"
        if d == "litellm" and getattr(self, "req", None):
            return f"sum{self.by(by)}(rate({self.req}{sel}[{RATE}]))"
        if d == "vllm" and getattr(self, "e2e", None):
            return f"sum{self.by(by)}(rate({self.e2e}_count{sel}[{RATE}]))"
        return None

    def err_rate(self, by: str | None = None) -> str | None:
        d = self.s.dialect
        if d == "otel_genai" and self.dur:
            return f'sum{self.by(by)}(rate({self.dur}_count{{error_type!=""}}[{RATE}]))'
        if d == "litellm" and getattr(self, "fail", None):
            return f"sum{self.by(by)}(rate({self.fail}[{RATE}]))"
        return None

    def error_ratio(self) -> str | None:
        e, r = self.err_rate(), self.req_rate()
        if e and r:
            return f"({e}) / clamp_min({r}, 1e-9)"
        return None

    def tokens_rate(self, direction: str, by: str | None = None, sel_extra: str = "") -> str | None:
        d = self.s.dialect
        if d == "otel_genai" and self.tok:
            sel = f'{{{self.s.token_type_label}="{direction}"{sel_extra}}}'
            return f"sum{self.by(by)}(rate({self.tok}_sum{sel}[{RATE}]))"
        if d == "litellm":
            m = self.tok_in if direction == "input" else self.tok_out
            if m:
                sel = f"{{{sel_extra.lstrip(',')}}}" if sel_extra else ""
                return f"sum{self.by(by)}(rate({m}{sel}[{RATE}]))"
        if d == "vllm":
            m = self.tok_prompt if direction == "input" else self.tok_gen
            if m:
                return f"sum{self.by(by)}(rate({m}[{RATE}]))"
        return None


# --------------------------------------------------------------------------- #
#  Registre de modèles → expressions de coût                                  #
# --------------------------------------------------------------------------- #

def load_registry(path_override: str | None = None) -> dict:
    paths = ([path_override] if path_override else []) + REGISTRY_PATHS
    for p in paths:
        if p and os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    return {"_meta": {"verified_at": "unknown"}, "models": []}


def match_models(models_seen: list, registry: dict) -> tuple[list, list]:
    """Associe les modèles observés aux entrées du registre. → (matched, unmatched).

    Scoring par spécificité : égalité exacte > clé ⊂ observé (variante datée,
    ex. claude-opus-4-8-20260115) > observé ⊂ clé. Le match le plus long gagne —
    sinon gpt-5.4-mini serait facturé au prix de gpt-5.4 (audit #6).
    """
    matched, unmatched = [], []
    for seen in models_seen:
        ns = _norm(seen)
        best, best_score = None, 0
        for m in registry.get("models", []):
            for k in [m["id"]] + m.get("aliases", []):
                nk = _norm(k)
                if len(nk) < 4:
                    continue
                if nk == ns:
                    score = 10000 + len(nk)
                elif nk in ns:
                    score = 1000 + len(nk)
                elif ns in nk:
                    score = len(nk)
                else:
                    continue
                if score > best_score:
                    best, best_score = m, score
        if best and best.get("input_per_mtok") is not None:
            matched.append({"seen": seen, "reg": best})
        else:
            unmatched.append(seen)
    return matched, unmatched


def cost_rate_expr(q: Q, matched: list, region: str | None = None,
                   window: str = RATE, agg: str = "rate") -> str | None:
    """Σ_modèles (tokens/s × prix/token), robuste aux séries absentes (or vector(0)).

    litellm : spend natif en USD (prioritaire). otel : composition depuis le registre.
    """
    if q.s.dialect == "litellm" and getattr(q, "spend", None):
        if region:
            return None  # la ventilation régionale passe par la voie otel/registre
        return f"sum({agg}({q.spend}[{window}])) or vector(0)"
    if q.s.dialect != "otel_genai" or not q.tok or not q.s.model_label:
        return None
    terms = []
    for it in matched[:14]:
        if region and it["reg"].get("region") != region:
            continue
        m, lbl = it["reg"], _esc(it["seen"])
        for direction, price in (("input", m.get("input_per_mtok")),
                                 ("output", m.get("output_per_mtok"))):
            if price is None:
                continue
            sel = (f'{{{q.s.token_type_label}="{direction}",'
                   f'{q.s.model_label}="{lbl}"}}')
            terms.append(f'(sum({agg}({q.tok}_sum{sel}[{window}])) or vector(0)) '
                         f"* {price / 1e6:.9g}")
    return "(" + " + ".join(terms) + ")" if terms else None


# --------------------------------------------------------------------------- #
#  Fabrique de panels / dashboards (schéma classique v41)                     #
# --------------------------------------------------------------------------- #

class Board:
    def __init__(self, uid: str, title: str, description: str, tags: list):
        self.d = {"uid": uid, "title": title, "description": description,
                  "tags": ["llmops-forge"] + tags, "timezone": "", "editable": True,
                  "schemaVersion": 41, "version": 0, "refresh": "1m",
                  "time": {"from": "now-24h", "to": "now"},
                  "templating": {"list": []}, "annotations": {"list": []},
                  "panels": []}
        self._id = 0
        self._x, self._y, self._rowh = 0, 0, 0

    def _place(self, w: int, h: int) -> dict:
        if self._x + w > 24:
            self._x, self._y = 0, self._y + self._rowh
            self._rowh = 0
        pos = {"x": self._x, "y": self._y, "w": w, "h": h}
        self._x += w
        self._rowh = max(self._rowh, h)
        return pos

    def row_break(self):
        if self._x:
            self._x, self._y = 0, self._y + self._rowh
            self._rowh = 0

    def add_model_variable(self, q: Q):
        if q.s.dialect not in ("otel_genai", "litellm") or not q.s.model_label:
            return
        base = getattr(q, "dur", None) or getattr(q, "req", None)
        if not base:
            return
        metric = base + ("_count" if q.s.dialect == "otel_genai" else "")
        self.d["templating"]["list"].append({
            "name": "model", "label": "Modèle", "type": "query",
            "datasource": {"type": "prometheus", "uid": q.s.ds_uid},
            "query": {"query": f"label_values({metric}, {q.s.model_label})", "refId": "V"},
            "includeAll": True, "multi": True, "refresh": 2,
            "current": {"selected": True, "text": ["All"], "value": ["$__all"]}})

    def model_sel(self, q: Q) -> str:
        if any(v["name"] == "model" for v in self.d["templating"]["list"]):
            return f'{{{q.s.model_label}=~"$model"}}'
        return ""

    def panel(self, ptype: str, title: str, w: int, h: int, ds_uid: str | None,
              targets: list | None = None, unit: str | None = None,
              description: str = "", options: dict | None = None,
              overrides: dict | None = None) -> dict:
        self._id += 1
        p = {"id": self._id, "type": ptype, "title": title,
             "gridPos": self._place(w, h), "description": description,
             "fieldConfig": {"defaults": {}, "overrides": []},
             "options": options or {}, "targets": targets or []}
        if ds_uid:
            dstype = ("loki" if ptype == "logs" else
                      "tempo" if ptype == "traces" else "prometheus")
            p["datasource"] = {"type": dstype, "uid": ds_uid}
        if unit:
            p["fieldConfig"]["defaults"]["unit"] = unit
        if overrides:
            p["fieldConfig"]["defaults"].update(overrides)
        if ptype == "stat":
            p["options"].setdefault("reduceOptions",
                                    {"calcs": ["lastNotNull"], "fields": "", "values": False})
            p["options"].setdefault("graphMode", "area")
        if ptype == "timeseries":
            p["fieldConfig"]["defaults"].setdefault(
                "custom", {"fillOpacity": 12, "lineWidth": 1, "showPoints": "never"})
        self.d["panels"].append(p)
        return p

    def ts(self, title, ds, exprs, w=12, h=8, unit=None, stacked=False, desc=""):
        targets = [{"refId": chr(65 + i), "expr": e[0], "legendFormat": e[1],
                    "range": True, "instant": False}
                   for i, e in enumerate(exprs) if e[0]]
        if not targets:
            return None
        p = self.panel("timeseries", title, w, h, ds, targets, unit, desc)
        if stacked:
            p["fieldConfig"]["defaults"]["custom"]["stacking"] = {"mode": "normal"}
            p["fieldConfig"]["defaults"]["custom"]["fillOpacity"] = 55
        return p

    def stat(self, title, ds, expr, w=6, h=5, unit="short", desc="", instant=True):
        if not expr:
            return None
        t = [{"refId": "A", "expr": expr, "instant": instant, "range": not instant}]
        return self.panel("stat", title, w, h, ds, t, unit, desc)

    def table(self, title, ds, expr, w=12, h=9, unit="short", desc=""):
        if not expr:
            return None
        t = [{"refId": "A", "expr": expr, "instant": True, "range": False,
              "format": "table"}]
        return self.panel("table", title, w, h, ds, t, unit, desc)

    def text(self, title, markdown, w=24, h=8):
        return self.panel("text", title, w, h, None,
                          options={"mode": "markdown", "content": markdown})

    def traces(self, title, tempo_uid, traceql, w=24, h=10, desc=""):
        t = [{"refId": "A", "queryType": "traceql", "query": traceql, "limit": 20}]
        return self.panel("traces", title, w, h, tempo_uid, t, description=desc)

    def alertlist(self, title, w=12, h=9):
        return self.panel("alertlist", title, w, h, None,
                          options={"maxItems": 20, "sortOrder": 1,
                                   "stateFilter": {"firing": True, "pending": True,
                                                   "noData": False, "normal": False,
                                                   "error": True}})


# --------------------------------------------------------------------------- #
#  Contexte de génération                                                     #
# --------------------------------------------------------------------------- #

class Ctx:
    def __init__(self, cap: dict, registry: dict):
        self.cap = cap
        self.registry = registry
        self.q: dict[str, Q] = {}
        for ds_uid, sigs in cap.get("signals", {}).items():
            for dialect, entry in sigs.items():
                key = dialect
                if key not in self.q:  # première datasource porteuse du dialecte
                    self.q[key] = Q(Signals(dialect, entry, ds_uid))
        dss = cap.get("datasources", {})
        self.loki = (dss.get("loki") or [None])[0]
        self.tempo = ((dss.get("tempo") or [{}])[0] or {}).get("uid")
        self.primary = self.q.get("otel_genai") or self.q.get("litellm")
        seen = self.primary.s.models_seen if self.primary else []
        self.matched, self.unmatched = match_models(seen, registry)
        self.verified = registry.get("_meta", {}).get("verified_at", "?")

    def gpu(self) -> Q | None:
        return self.q.get("gpu_dcgm") or self.q.get("gpu_smi")


# --------------------------------------------------------------------------- #
#  Blueprints                                                                 #
# --------------------------------------------------------------------------- #

def bp_finops(ctx: Ctx) -> Board | None:
    q = ctx.primary
    if not q:
        return None
    b = Board(det_uid("ai-executive-finops"), "AI · Executive FinOps & Coûts",
              f"Coûts LLM multi-providers. Registre de prix vérifié le {ctx.verified} "
              f"(USD/1M tokens). Généré par grafana-llmops-forge.", ["finops"])
    ds = q.s.ds_uid
    spend_range = cost_rate_expr(q, ctx.matched, window="$__range", agg="increase")
    spend_rate = cost_rate_expr(q, ctx.matched)
    b.stat("Dépense (période affichée)", ds, spend_range, 6, 5, "currencyUSD",
           "Somme sur l'intervalle du dashboard.")
    b.stat("Rythme de dépense / jour", ds,
           f"({spend_rate}) * 86400" if spend_rate else None, 6, 5, "currencyUSD",
           "Projection : rythme instantané × 86400.")
    rr = q.req_rate()
    b.stat("Coût moyen / requête", ds,
           f"({spend_rate}) / clamp_min({rr}, 1e-9)" if spend_rate and rr else None,
           6, 5, "currencyUSD")
    tok_out = q.tokens_rate("output")
    b.stat("Tokens générés / s", ds, tok_out, 6, 5, "short")
    b.row_break()
    regions = [("eu", "🇪🇺 Providers UE"), ("us", "🇺🇸 Providers US"),
               ("asia", "🌏 Providers Asie")]
    region_exprs = [(cost_rate_expr(q, ctx.matched, region=r), lbl)
                    for r, lbl in regions]
    if any(e for e, _ in region_exprs):
        b.ts("Dépense par souveraineté (USD/s)", ds, region_exprs, 12, 8,
             "currencyUSD", stacked=True,
             desc="Ventilation par région du fournisseur — pilotage souveraineté/AI Act.")
    if q.s.dialect == "litellm" and getattr(q, "spend", None) and q.s.group_label:
        b.ts("Dépense par équipe (USD/s)", ds,
             [(f"sum by({q.s.group_label})(rate({q.spend}[{RATE}]))",
               "{{" + q.s.group_label + "}}")], 12, 8, "currencyUSD", stacked=True)
    elif q.s.model_label:
        ti = q.tokens_rate("input", by=q.s.model_label)
        b.ts("Tokens input par modèle (proxy de coût)", ds,
             [(ti, "{{" + q.s.model_label + "}}")], 12, 8, "short", stacked=True)
    b.row_break()
    if q.s.model_label:
        b.ts("Tokens output par modèle / s", ds,
             [(q.tokens_rate("output", by=q.s.model_label),
               "{{" + q.s.model_label + "}}")], 12, 8, "short", stacked=True)
        top = (f"topk(10, sum by({q.s.model_label})"
               f"(increase({q.tok}_sum[$__range])))" if q.s.dialect == "otel_genai" and q.tok
               else None)
        b.table("Top modèles (tokens, période)", ds, top, 12, 8)
    if ctx.unmatched:
        b.text("Modèles hors registre de prix",
               "Ces modèles sont observés mais **exclus du calcul de coût** "
               "(prix inconnu) :\n\n"
               + "\n".join(f"- `{m}`" for m in ctx.unmatched[:20])
               + "\n\nAjouter leur prix dans `references/model_registry.json` "
                 "puis relancer la forge.", 24, 6)
    return b


def bp_gateway(ctx: Ctx) -> Board | None:
    q = ctx.primary
    if not q:
        return None
    b = Board(det_uid("ai-gateway-operations"), "AI · Gateway Operations",
              "Latence, erreurs, débit du trafic LLM (SRE). Généré par grafana-llmops-forge.",
              ["gateway", "sre"])
    ds = q.s.ds_uid
    b.add_model_variable(q)
    sel = b.model_sel(q)
    ratio = q.error_ratio()
    b.stat("Disponibilité (1 − erreurs)", ds,
           f"1 - ({ratio})" if ratio else None, 6, 5, "percentunit")
    b.stat("Requêtes / s", ds, q.req_rate(sel=sel), 6, 5, "reqps")
    dur = getattr(q, "dur", None)
    b.stat("Latence p95", ds, q.pXX(dur, 0.95, sel) if dur else None, 6, 5, "s")
    ttft = getattr(q, "ttft", None)
    b.stat("TTFT p95 (serveur)", ds, q.pXX(ttft, 0.95) if ttft else None, 6, 5, "s",
           "Time-to-first-token : premier signal de saturation.")
    b.row_break()
    if q.s.model_label:
        b.ts("Requêtes/s par modèle", ds,
             [(q.req_rate(by=q.s.model_label, sel=sel), "{{" + q.s.model_label + "}}")],
             12, 8, "reqps", stacked=True)
    if dur:
        b.ts("Latence p50 / p95 / p99", ds,
             [(q.pXX(dur, 0.50, sel), "p50"), (q.pXX(dur, 0.95, sel), "p95"),
              (q.pXX(dur, 0.99, sel), "p99")], 12, 8, "s")
    b.row_break()
    if q.s.dialect == "otel_genai" and dur:
        b.ts("Erreurs/s par type", ds,
             [(f'sum by(error_type)(rate({dur}_count{{error_type!=""}}[{RATE}]))',
               "{{error_type}}")], 12, 8, "short")
    elif q.err_rate():
        b.ts("Erreurs/s", ds, [(q.err_rate(), "erreurs")], 12, 8, "short")
    if q.s.dialect == "litellm" and getattr(q, "remaining_req", None):
        b.ts("Quota restant (min par provider)", ds,
             [(f"min by({q.s.provider_label or 'api_provider'})({q.remaining_req})",
               "{{" + (q.s.provider_label or "api_provider") + "}}")], 12, 8, "short",
             desc="Rate limits restants côté providers — anticiper le throttling.")
    elif q.s.provider_label:
        b.ts("Requêtes/s par provider", ds,
             [(q.req_rate(by=q.s.provider_label), "{{" + q.s.provider_label + "}}")],
             12, 8, "reqps", stacked=True)
    return b


def bp_agents(ctx: Ctx) -> Board | None:
    q = ctx.q.get("otel_genai")
    if not q or not q.dur:
        return None
    b = Board(det_uid("ai-agents-rag"), "AI · Agents & RAG",
              "Workflows agentiques : invocations, outils, tokens par agent, traces. "
              "Conventions OTel GenAI (gen_ai.operation.name). Généré par grafana-llmops-forge.",
              ["agents", "rag"])
    ds = q.s.ds_uid
    op = "gen_ai_operation_name"
    b.stat("Invocations d'agents / s", ds,
           f'sum(rate({q.dur}_count{{{op}="invoke_agent"}}[{RATE}]))', 6, 5, "reqps")
    b.stat("Appels d'outils / s", ds,
           f'sum(rate({q.dur}_count{{{op}="execute_tool"}}[{RATE}]))', 6, 5, "reqps")
    b.stat("Durée agent p95", ds,
           q.pXX(q.dur, 0.95, f'{{{op}="invoke_agent"}}'), 6, 5, "s")
    b.stat("Erreurs outils / s", ds,
           f'sum(rate({q.dur}_count{{{op}="execute_tool",error_type!=""}}[{RATE}]))',
           6, 5, "short")
    b.row_break()
    b.ts("Mix d'opérations GenAI", ds,
         [(f"sum by({op})(rate({q.dur}_count[{RATE}]))", "{{" + op + "}}")],
         12, 8, "reqps", stacked=True,
         desc="chat / embeddings / invoke_agent / execute_tool…")
    b.ts("Appels par outil (execute_tool)", ds,
         [(f'sum by(gen_ai_tool_name)(rate({q.dur}_count{{{op}="execute_tool"}}[{RATE}]))',
           "{{gen_ai_tool_name}}")], 12, 8, "reqps", stacked=True)
    b.row_break()
    if q.tok:
        b.ts("Tokens par agent / s", ds,
             [(f"sum by(gen_ai_agent_name)(rate({q.tok}_sum[{RATE}]))",
               "{{gen_ai_agent_name}}")], 12, 8, "short", stacked=True)
    b.ts("Latence embeddings p95 (pipeline RAG)", ds,
         [(q.pXX(q.dur, 0.95, f'{{{op}="embeddings"}}'), "p95 embeddings")],
         12, 8, "s")
    if ctx.tempo:
        b.traces("Dernières traces d'agents (TraceQL)", ctx.tempo,
                 '{span.gen_ai.operation.name="invoke_agent"}',
                 desc="Cliquer une trace pour dérouler le workflow complet "
                      "(LLM → outils → réponses).")
    return b


def bp_adoption(ctx: Ctx) -> Board | None:
    q = ctx.primary
    if not q:
        return None
    b = Board(det_uid("ai-adoption"), "AI · Adoption interne",
              "Qui utilise quoi : équipes/apps actives, mix de modèles, nouveaux entrants. "
              "Généré par grafana-llmops-forge.", ["adoption"])
    ds, g = q.s.ds_uid, q.s.group_label
    rr_by_g = q.req_rate(by=g) if g else None
    base_cnt = None
    if q.s.dialect == "otel_genai" and getattr(q, "dur", None):
        base_cnt = f"{q.dur}_count"
    elif q.s.dialect == "litellm" and getattr(q, "req", None):
        base_cnt = q.req
    if g and base_cnt:
        b.stat(f"Entités actives ({g})", ds,
               f"count(sum by({g})(rate({base_cnt}[1h])) > 0)", 6, 5, "short")
        b.stat("Nouveaux adoptants (7j)", ds,
               f"count(sum by({g})(increase({base_cnt}[7d])) > 0) - "
               f"count(sum by({g})(increase({base_cnt}[7d] offset 7d)) > 0)",
               6, 5, "short",
               "Entités émettant du trafic LLM cette semaine mais pas la précédente.")
    if q.s.model_label and base_cnt:
        b.stat("Modèles distincts en usage", ds,
               f"count(count by({q.s.model_label})(rate({base_cnt}[1h])))", 6, 5)
    b.stat("Requêtes / s (total)", ds, q.req_rate(), 6, 5, "reqps")
    b.row_break()
    if q.s.model_label:
        b.ts("Mix de modèles (part du trafic)", ds,
             [(q.req_rate(by=q.s.model_label), "{{" + q.s.model_label + "}}")],
             12, 9, "reqps", stacked=True,
             desc="La forme du mix raconte la stratégie réelle : montée d'un modèle "
                  "économique = arbitrage FinOps qui fonctionne.")
    if rr_by_g:
        b.ts(f"Trafic par {g}", ds, [(rr_by_g, "{{" + g + "}}")], 12, 9,
             "reqps", stacked=True)
    b.row_break()
    if g and q.s.dialect == "otel_genai" and q.tok:
        b.table("Top consommateurs (tokens, période)", ds,
                f"topk(15, sum by({g})(increase({q.tok}_sum[$__range])))", 24, 9)
    return b


def bp_inference(ctx: Ctx) -> Board | None:
    qv = ctx.q.get("vllm") or ctx.q.get("tgi")
    gpu = ctx.gpu()
    if not qv and not gpu:
        return None
    b = Board(det_uid("ai-inference-selfhosted"), "AI · Inference self-hosted",
              "Moteurs d'inference (vLLM/TGI) + GPU. Les 4 signaux d'or : TTFT, TPOT, "
              "file d'attente, KV cache. Généré par grafana-llmops-forge.", ["inference", "gpu"])
    if qv and qv.s.dialect == "vllm":
        ds, ml = qv.s.ds_uid, qv.s.model_label or "model_name"
        b.stat("TTFT p95", ds, qv.pXX(qv.ttft, 0.95) if qv.ttft else None, 6, 5, "s")
        b.stat("TPOT p95 (inter-token)", ds,
               qv.pXX(qv.tpot, 0.95) if qv.tpot else None, 6, 5, "s")
        b.stat("Requêtes en attente", ds,
               f"sum({qv.waiting})" if qv.waiting else None, 6, 5)
        b.stat("KV cache (max)", ds, f"max({qv.kv})" if qv.kv else None, 6, 5,
               "percentunit", "≥ 0.90 = préemptions imminentes, latence dégradée.")
        b.row_break()
        if qv.e2e:
            b.ts("Latence E2E p50/p95/p99", ds,
                 [(qv.pXX(qv.e2e, 0.50, by=ml), "p50 {{" + ml + "}}"),
                  (qv.pXX(qv.e2e, 0.95, by=ml), "p95 {{" + ml + "}}"),
                  (qv.pXX(qv.e2e, 0.99, by=ml), "p99 {{" + ml + "}}")], 12, 8, "s")
        b.ts("Débit tokens/s (prompt vs génération)", ds,
             [(qv.tokens_rate("input"), "prompt"),
              (qv.tokens_rate("output"), "génération")], 12, 8, "short")
        b.row_break()
        b.ts("File d'attente & running", ds,
             [(f"sum({qv.running})" if qv.running else None, "running"),
              (f"sum({qv.waiting})" if qv.waiting else None, "waiting")], 12, 8)
        b.ts("Préemptions/s (pression KV cache)", ds,
             [(f"sum(rate({qv.preempt}[{RATE}]))" if qv.preempt else None,
               "préemptions")], 12, 8,
             desc="Préemption = recalcul de contexte : correct mais coûteux. "
                  "Un plateau non nul en régime nominal = sous-dimensionnement.")
    if qv and qv.s.dialect == "tgi":
        ds = qv.s.ds_uid
        b.ts("Latence inference p95 (TGI)", ds,
             [(qv.pXX(qv.dur, 0.95) if getattr(qv, "dur", None) else None, "p95")],
             12, 8, "s")
        b.ts("File d'attente (TGI)", ds,
             [(f"sum({qv.queue})" if getattr(qv, "queue", None) else None, "queue")],
             12, 8)
    if gpu:
        b.row_break()
        ds = gpu.s.ds_uid
        b.ts("Utilisation GPU (%)", ds,
             [(f"avg by(gpu)({gpu.gpu_util})" if gpu.gpu_util else None,
               "GPU {{gpu}}")], 12, 8, "percent")
        b.ts("VRAM utilisée", ds,
             [(f"sum by(gpu)({gpu.vram})" if gpu.vram else None, "GPU {{gpu}}")],
             12, 8, "decmbytes")
    if ctx.registry.get("models"):
        api_refs = [m for m in ctx.registry["models"]
                    if m.get("output_per_mtok") is not None][:6]
        rows = "\n".join(f"| {m['id']} | {m.get('region','?').upper()} | "
                         f"{m['input_per_mtok']}$ | {m['output_per_mtok']}$ |"
                         for m in sorted(api_refs, key=lambda m: m['output_per_mtok']))
        b.text("Référentiel : coût API/1M tokens (benchmark self-hosted)",
               "Comparer votre coût GPU/1M tokens générés à ces prix API "
               f"(registre du {ctx.verified}) :\n\n"
               "| Modèle | Région | Input | Output |\n|---|---|---|---|\n" + rows,
               24, 7)
    return b


AI_ACT_TIMELINE_MD = """### Calendrier AI Act — état vérifié juillet 2026 (post-Digital Omnibus)

| Échéance | Obligation | Statut |
|---|---|---|
| 2 fév. 2025 | Pratiques interdites (Art. 5) + maîtrise de l'IA (Art. 4) | ✅ en vigueur |
| 2 août 2025 | Obligations GPAI (Art. 51-56) : documentation, transparence, incidents | ✅ en vigueur |
| **2 août 2026** | **Activation des pouvoirs de sanction** ; transparence Art. 50 (chatbots : information des utilisateurs) | ⚠️ imminent |
| 2 déc. 2026 | Marquage machine-réadable des contenus synthétiques (Art. 50§2, reporté) | à préparer |
| 2 déc. 2027 | Systèmes haut risque Annexe III (RH, crédit, biométrie…) — reporté par l'Omnibus (accord provisoire du 7 mai 2026, adoption formelle en cours) | à cartographier |
| 2 août 2028 | Haut risque intégré aux produits (Annexe I) | horizon |

**Ce que ce dashboard prouve** : journalisation active (Art. 12), rétention côté
déployeur ≥ 6 mois (Art. 26§6), veille incidents (Art. 73 — signalement des
incidents graves), inventaire des systèmes. Sanctions : jusqu'à 35 M€ / 7 % CA.
*Support d'aide à la conformité — ne constitue pas un avis juridique.*"""


def bp_governance(ctx: Ctx) -> Board:
    b = Board(det_uid("ai-governance-eu-ai-act"), "AI · Gouvernance & EU AI Act",
              "Preuves d'observabilité pour la conformité AI Act : journalisation, "
              "inventaire, souveraineté, incidents. Généré par grafana-llmops-forge — "
              "n'est pas un avis juridique.", ["governance", "ai-act"])
    b.text("Échéances réglementaires", AI_ACT_TIMELINE_MD, 24, 11)
    q = ctx.primary
    if q:
        ds = q.s.ds_uid
        regions = [("eu", "Part UE"), ("us", "Part US"), ("asia", "Part Asie")]
        exprs = []
        for r, lbl in regions:
            ids = [_esc(it["seen"]) for it in ctx.matched if it["reg"].get("region") == r]
            if ids and q.s.model_label:
                rx = "|".join(re.escape(i) for i in ids)
                exprs.append((q.req_rate(sel=f'{{{q.s.model_label}=~"{rx}"}}'), lbl))
        if exprs:
            b.ts("Trafic par souveraineté du fournisseur", ds, exprs, 12, 8,
                 "reqps", stacked=True,
                 desc="Dépendance réelle aux providers par région — pilotage "
                      "souveraineté & clauses contractuelles GPAI.")
    if ctx.loki:
        lbl = (ctx.loki.get("labels") or ["service_name"])[0]
        b.ts("Preuve de journalisation (volume de logs)", ctx.loki["uid"],
             [(f'sum by({lbl})(rate({{{lbl}=~".+"}}[{RATE}]))', "{{" + lbl + "}}")],
             12, 8, "short",
             desc="Art. 12 (journalisation) / Art. 26§6 (rétention ≥ 6 mois par le "
                  "déployeur). Vérifier la rétention Loki ≥ 4320h.")
    b.row_break()
    if ctx.matched or ctx.unmatched:
        rows = []
        for it in ctx.matched:
            m = it["reg"]
            rows.append(f"| `{it['seen']}` | {m.get('vendor','?')} | "
                        f"{m.get('region','?').upper()} | "
                        f"{'open-weights' if m.get('open_weights') else 'propriétaire'} | "
                        f"{'oui' if m.get('gpai_in_scope', True) else '—'} |")
        for s in ctx.unmatched:
            rows.append(f"| `{s}` | ? | ? | ? | à qualifier |")
        b.text("Inventaire des modèles observés (base du registre AI Act)",
               "Modèles réellement utilisés (détection automatique) :\n\n"
               "| Modèle observé | Fournisseur | Région | Licence | GPAI |\n"
               "|---|---|---|---|---|\n" + "\n".join(rows) +
               "\n\nÀ rapprocher de votre registre interne des systèmes d'IA "
               "(cartographie fournisseur/déployeur).", 12, 10)
    b.alertlist("Veille incidents (Art. 73 : incidents graves → signalement)", 12, 10)
    return b


BLUEPRINTS = {"finops": bp_finops, "gateway": bp_gateway, "agents": bp_agents,
              "adoption": bp_adoption, "inference": bp_inference,
              "governance": bp_governance}


# --------------------------------------------------------------------------- #
#  Alertes SLO (provisioning API)                                             #
# --------------------------------------------------------------------------- #

def _rule(uid_name, title, prom_uid, expr, threshold, op, folder_uid,
          summary, severity="warning", for_="10m", nodata="OK"):
    return {"uid": det_uid(uid_name, "alr"), "title": title, "orgID": 1,
            "folderUID": folder_uid, "ruleGroup": "llmops-slo",
            "condition": "C", "for": for_, "noDataState": nodata,
            "execErrState": "Error",
            "labels": {"severity": severity, "origin": "llmops-forge"},
            "annotations": {"summary": summary},
            "data": [
                {"refId": "A", "relativeTimeRange": {"from": 900, "to": 0},
                 "datasourceUid": prom_uid,
                 "model": {"refId": "A", "expr": expr, "range": True,
                           "intervalMs": 60000, "maxDataPoints": 500}},
                {"refId": "B", "datasourceUid": "__expr__",
                 "model": {"refId": "B", "type": "reduce", "expression": "A",
                           "reducer": "last"}},
                {"refId": "C", "datasourceUid": "__expr__",
                 "model": {"refId": "C", "type": "threshold", "expression": "B",
                           "conditions": [{"evaluator": {"type": op,
                                                         "params": [threshold]}}]}},
            ]}


def build_alerts(ctx: Ctx, folder_uid: str, daily_budget: float) -> list:
    rules = []
    q = ctx.primary
    if q:
        ratio = q.error_ratio()
        if ratio:
            rules.append(_rule("llm-error-ratio", "LLM · Taux d'erreur > 5 %",
                               q.s.ds_uid, ratio, 0.05, "gt", folder_uid,
                               "Le trafic LLM dépasse 5 % d'erreurs sur 10 min.",
                               "critical"))
        rr = q.req_rate()
        if rr:
            rules.append(_rule("llm-signal-lost", "LLM · Signal perdu (pipeline télémétrie)",
                               q.s.ds_uid, f"({rr}) or vector(0)", 1e-9, "lt",
                               folder_uid,
                               "Plus aucun trafic LLM mesuré : instrumentation ou "
                               "collecteur probablement en panne.", "warning", "15m"))
        spend = cost_rate_expr(q, ctx.matched)
        if spend:
            rules.append(_rule("llm-daily-budget", "LLM · Budget quotidien dépassé",
                               q.s.ds_uid, f"({spend}) * 86400", daily_budget, "gt",
                               folder_uid,
                               f"Rythme de dépense > {daily_budget} USD/jour.",
                               "warning", "30m"))
        ttft = getattr(q, "ttft", None)
        if ttft:
            rules.append(_rule("llm-ttft-p95", "LLM · TTFT p95 > 3 s",
                               q.s.ds_uid, q.pXX(ttft, 0.95), 3, "gt", folder_uid,
                               "Le premier token met > 3 s (p95) : saturation probable."))
    qv = ctx.q.get("vllm")
    if qv and qv.kv:
        rules.append(_rule("vllm-kv-cache", "vLLM · KV cache > 92 %",
                           qv.s.ds_uid, f"max({qv.kv})", 0.92, "gt", folder_uid,
                           "Saturation KV cache : préemptions et latence en vue.",
                           "critical", "5m"))
    return rules


# --------------------------------------------------------------------------- #
#  Validation, self-test, CLI                                                 #
# --------------------------------------------------------------------------- #

def validate(board: Board) -> list:
    errs, ids = [], set()
    for p in board.d["panels"]:
        if p["id"] in ids:
            errs.append(f"{board.d['title']}: id panel dupliqué {p['id']}")
        ids.add(p["id"])
        gp = p["gridPos"]
        if gp["x"] + gp["w"] > 24 or gp["w"] <= 0 or gp["h"] <= 0:
            errs.append(f"{board.d['title']}: gridPos invalide panel {p['id']}")
        if p["type"] in ("timeseries", "stat", "table") and not p["targets"]:
            errs.append(f"{board.d['title']}: panel sans target '{p['title']}'")
        for t in p.get("targets", []):
            if "expr" in t and not t["expr"]:
                errs.append(f"{board.d['title']}: expr vide '{p['title']}'")
    return errs


def selftest_capability() -> dict:
    prom = "prom-selftest"
    return {"instance": {"url": "http://selftest", "version": "13.0.0",
                         "major": 13, "edition": "oss", "namespace": "default",
                         "apis": {"legacy": True, "resource": True}},
            "datasources": {"prometheus": [{"uid": prom, "name": "Prom"}],
                            "loki": [{"uid": "loki-1", "name": "Loki",
                                      "labels": ["service_name"]}],
                            "tempo": [{"uid": "tempo-1", "name": "Tempo"}],
                            "other": []},
            "signals": {prom: {
                "otel_genai": {
                    "metric_names": [
                        "gen_ai_client_operation_duration_seconds_bucket",
                        "gen_ai_client_operation_duration_seconds_sum",
                        "gen_ai_client_operation_duration_seconds_count",
                        "gen_ai_client_token_usage_token_bucket",
                        "gen_ai_client_token_usage_token_sum",
                        "gen_ai_client_token_usage_token_count",
                        "gen_ai_server_time_to_first_token_seconds_bucket"],
                    "model_label": "gen_ai_request_model",
                    "models_seen": ["gpt-5.4", "claude-sonnet-4.6", "mistral-small-3.2",
                                    "deepseek-v4-flash", "qwen3.7-max", "modele-maison-x"],
                    "provider_label": "gen_ai_provider_name",
                    "providers_seen": ["openai", "anthropic", "mistral_ai", "deepseek"],
                    "token_type_label": "gen_ai_token_type",
                    "group_labels": [{"label": "service_name", "cardinality": 9}]},
                "litellm": {
                    "metric_names": ["litellm_spend_metric_total",
                                     "litellm_proxy_total_requests_metric_total",
                                     "litellm_proxy_failed_requests_metric_total",
                                     "litellm_request_total_latency_metric_bucket",
                                     "litellm_input_tokens_metric_total",
                                     "litellm_output_tokens_metric_total",
                                     "litellm_remaining_requests_metric"],
                    "model_label": "model",
                    "models_seen": ["gpt-5.4", "claude-haiku-4.5"],
                    "provider_label": "api_provider",
                    "group_labels": [{"label": "team", "cardinality": 6}]},
                "vllm": {
                    "metric_names": ["vllm:time_to_first_token_seconds_bucket",
                                     "vllm:time_per_output_token_seconds_bucket",
                                     "vllm:e2e_request_latency_seconds_bucket",
                                     "vllm:e2e_request_latency_seconds_count",
                                     "vllm:num_requests_running",
                                     "vllm:num_requests_waiting",
                                     "vllm:num_preemptions_total",
                                     "vllm:gpu_cache_usage_perc",
                                     "vllm:prompt_tokens_total",
                                     "vllm:generation_tokens_total"],
                    "model_label": "model_name",
                    "models_seen": ["meta-llama/Llama-4-Maverick"]},
                "gpu_dcgm": {"metric_names": ["DCGM_FI_DEV_GPU_UTIL",
                                              "DCGM_FI_DEV_FB_USED",
                                              "DCGM_FI_DEV_POWER_USAGE"]}}},
            "gaps": []}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capability", default="capability_map.json")
    ap.add_argument("--blueprints", default="auto",
                    help="auto | liste: finops,gateway,agents,adoption,inference,governance")
    ap.add_argument("--deploy", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--with-alerts", action="store_true")
    ap.add_argument("--daily-budget", type=float, default=100.0,
                    help="Seuil d'alerte budget USD/jour (défaut 100)")
    ap.add_argument("--folder", default=FOLDER_TITLE_DEFAULT)
    ap.add_argument("--out-dir", default="generated_dashboards")
    ap.add_argument("--registry", default=None)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--insecure", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        cap = selftest_capability()
        args.out_dir = "selftest_output"
        args.deploy = False
    else:
        with open(args.capability, encoding="utf-8") as f:
            cap = json.load(f)

    ctx = Ctx(cap, load_registry(args.registry))
    wanted = (list(BLUEPRINTS) if args.blueprints == "auto"
              else [b.strip() for b in args.blueprints.split(",")])
    boards, skipped, errors = [], [], []
    for name in wanted:
        fn = BLUEPRINTS.get(name)
        if not fn:
            skipped.append((name, "blueprint inconnu"))
            continue
        board = fn(ctx)
        if board is None or not board.d["panels"]:
            skipped.append((name, "signaux requis absents de la capability map"))
            continue
        errors.extend(validate(board))
        boards.append((name, board))

    if errors:
        print("ÉCHEC VALIDATION :", file=sys.stderr)
        for e in errors:
            print("  -", e, file=sys.stderr)
        return 2

    os.makedirs(args.out_dir, exist_ok=True)
    manifest = {"generated_at": datetime.now(timezone.utc).isoformat(),
                "deployed": False, "dashboards": []}
    for name, board in boards:
        path = os.path.join(args.out_dir, f"{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(board.d, f, indent=2, ensure_ascii=False)
        manifest["dashboards"].append(
            {"blueprint": name, "uid": board.d["uid"], "title": board.d["title"],
             "url": None,
             "panels": [{"id": p["id"], "title": p.get("title", ""),
                         "type": p["type"]} for p in board.d["panels"]]})
        print(f"[ok] {board.d['title']}  ({len(board.d['panels'])} panels) → {path}")
    for name, why in skipped:
        print(f"[skip] {name} : {why}")

    if args.deploy and not args.dry_run:
        client = GrafanaClient(insecure=args.insecure)
        folder = client.ensure_folder(args.folder)
        print(f"\nFolder « {folder.get('title')} » (uid {folder.get('uid')})")
        manifest["deployed"] = True
        for i, (name, board) in enumerate(boards):
            res = client.upsert_dashboard(board.d, folder["uid"],
                                          f"llmops-forge {datetime.now(timezone.utc):%Y-%m-%d}")
            manifest["dashboards"][i]["url"] = client.dashboard_url(res, board.d)
            print(f"  ↗ {manifest['dashboards'][i]['url']}")
        if args.with_alerts:
            rules = build_alerts(ctx, folder["uid"], args.daily_budget)
            for r in rules:
                try:
                    client.upsert_alert_rule(r)
                    print(f"  ⚑ alerte : {r['title']}")
                except Exception as e:  # 403 fréquent selon rôle/édition
                    fb = os.path.join(args.out_dir, f"alert_{r['uid']}.json")
                    with open(fb, "w", encoding="utf-8") as f:
                        json.dump(r, f, indent=2, ensure_ascii=False)
                    print(f"  ⚠ alerte '{r['title']}' non provisionnée ({e}) — "
                          f"export : {fb} (import manuel possible)")
    elif args.with_alerts:
        folder_uid = det_uid(args.folder, "fold")
        for r in build_alerts(ctx, folder_uid, args.daily_budget):
            fb = os.path.join(args.out_dir, f"alert_{r['uid']}.json")
            with open(fb, "w", encoding="utf-8") as f:
                json.dump(r, f, indent=2, ensure_ascii=False)
            print(f"[ok] alerte (non déployée) → {fb}")

    with open(os.path.join(args.out_dir, "deploy_manifest.json"), "w",
              encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"\n{len(boards)} dashboard(s) générés, {len(skipped)} ignoré(s), "
          f"registre vérifié le {ctx.verified}.")
    if ctx.unmatched:
        print(f"Modèles sans prix ({len(ctx.unmatched)}) : "
              + ", ".join(ctx.unmatched[:8]))
    if manifest["deployed"]:
        print("CONTRÔLE VISUEL (recommandé) : "
              f"python3 scripts/visual_audit.py --dashboards {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
