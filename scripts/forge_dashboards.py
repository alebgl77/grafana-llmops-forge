"""Forge : generation + déploiement de dashboards LLMOps sur Grafana.

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
from grafana_client import GrafanaClient, GrafanaError, det_uid  # noqa: E402

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
        self.group_card = groups[0]["cardinality"] if groups else 0

    def find(self, substr: str, suffix: str | None = None) -> str | None:
        """Recherche par sous-chaîne, insensible au séparateur : un nom conservé
        en UTF-8 (`gen_ai.client.operation.duration`) doit répondre aux mêmes
        clés que sa forme classique. On compare une forme normalisée mais on
        retourne toujours le nom RÉEL, seul interrogeable."""
        key = substr.replace(".", "_")
        cands = [n for n in self.names if key in n.replace(".", "_")]
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


RE2_META = set(r".+*?()[]{}|\\^$")
_LEGACY = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:]*")
Q1, B1, B2 = chr(34), chr(123), chr(125)


def msel(metric: str, sel: str = "") -> str:
    """Rend `metric{...}` ou, pour un nom UTF-8 (points conservés par
    translation_strategy: NoTranslation), la forme `{"metric",...}`, un nom
    pointé nu fait renvoyer 400 par Prometheus. Vérifié sur instance réelle."""
    if not metric:
        return metric
    if _LEGACY.fullmatch(metric):
        return metric + sel
    inner = sel[1:-1].strip() if sel.startswith("{") and sel.endswith("}") else ""
    return '{"' + metric + '"' + ("," + inner if inner else "") + "}"


def qlbl(label: str | None) -> str:
    """Nom de label utilisable dans by()/matcher : quoté s'il n'est pas legacy."""
    if not label:
        return ""
    return label if _LEGACY.fullmatch(label) else '"' + label + '"'


def _rx(s: str) -> str:
    r"""Échappe une valeur pour une regex RE2 placée dans un littéral PromQL.

    Deux couches empilées : la chaîne entre guillemets consomme un niveau
    d'échappement avant que RE2 ne voie la regex. D'où le doublement. Et la
    valeur vient d'un label applicatif : un guillemet non échappé permettrait
    de sortir du sélecteur et d'injecter du PromQL arbitraire dans un panneau.
    """
    out = []
    for c in s:
        if c == '"':
            out.append('\\"')            # ferme la chaîne : échappement chaîne seul
        elif c == "\\":
            out.append("\\" * 4)         # backslash littéral à travers les deux couches
        elif c in RE2_META:
            out.append("\\" * 2 + c)     # méta RE2, échappé pour la regex
        else:
            out.append(c)
    return "".join(out)


def _md(s: str) -> str:
    """Neutralise ce qui casserait un tableau markdown de panneau texte."""
    return s.replace("|", "\\|").replace("`", "'").replace("\n", " ")


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
        return f" by({qlbl(label)})" if label else ""

    def pXX(self, base: str, q: float, sel: str = "", by: str | None = None,
            w: str = RATE) -> str:
        grp = f"le,{qlbl(by)}" if by else "le"
        return (f"histogram_quantile({q}, sum by({grp})"
                f"(rate({msel(base + '_bucket', sel)}[{w}])))")

    def req_rate(self, by: str | None = None, sel: str = "", w: str = RATE) -> str | None:
        d = self.s.dialect
        if d in ("otel_genai", "tgi") and getattr(self, "dur", None):
            return f"sum{self.by(by)}(rate({msel(self.dur + chr(95) + 'count', sel)}[{w}]))"
        if d == "litellm" and getattr(self, "req", None):
            return f"sum{self.by(by)}(rate({msel(self.req, sel)}[{w}]))"
        if d == "vllm" and getattr(self, "e2e", None):
            return f"sum{self.by(by)}(rate({msel(self.e2e + chr(95) + 'count', sel)}[{w}]))"
        return None

    def err_rate(self, by: str | None = None, w: str = RATE) -> str | None:
        d = self.s.dialect
        if d == "otel_genai" and self.dur:
            return f'sum{self.by(by)}(rate({msel(self.dur + chr(95) + "count", chr(123) + "error_type!=" + chr(34)*2 + chr(125))}[{w}]))'
        if d == "litellm" and getattr(self, "fail", None):
            return f"sum{self.by(by)}(rate({msel(self.fail)}[{w}]))"
        return None

    def error_ratio(self, w: str = RATE) -> str | None:
        e, r = self.err_rate(w=w), self.req_rate(w=w)
        if e and r:
            return f"({e}) / clamp_min({r}, 1e-9)"
        return None

    def tokens_rate(self, direction: str, by: str | None = None, sel_extra: str = "",
                    w: str = RATE) -> str | None:
        d = self.s.dialect
        if d == "otel_genai" and self.tok:
            sel = f'{{{qlbl(self.s.token_type_label)}="{direction}"{sel_extra}}}'
            return f"sum{self.by(by)}(rate({msel(self.tok + chr(95) + 'sum', sel)}[{w}]))"
        if d == "litellm":
            m = self.tok_in if direction == "input" else self.tok_out
            if m:
                sel = f"{{{sel_extra.lstrip(',')}}}" if sel_extra else ""
                return f"sum{self.by(by)}(rate({msel(m, sel)}[{w}]))"
        if d == "vllm":
            m = self.tok_prompt if direction == "input" else self.tok_gen
            if m:
                return f"sum{self.by(by)}(rate({msel(m)}[{w}]))"
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
    ex. claude-opus-4-8-20260115) > observé ⊂ clé. Le match le plus long gagne ;
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


COST_RECORDED = "llm:cost_usd_per_second"
PRICE_IN, PRICE_OUT = "llm:price_input_usd_per_token", "llm:price_output_usd_per_token"
INLINE_MODEL_CAP = 40


def cost_rate_expr(q: Q, matched: list, region: str | None = None,
                   window: str = RATE, agg: str = "rate",
                   recorded: bool = False) -> str | None:
    """Coût USD/s. Trois voies, par ordre de préférence :

    1. recording rules `llm:cost_usd_per_second` (O(1) séries, prix modifiables
       sans regénérer les dashboards, aucune limite de modèles) ;
    2. spend natif de la passerelle LiteLLM (USD déjà agrégé) ;
    3. on-the-fly composition depuis le registre (bootstrap ; coûteux au-delà
       de ~15 modèles, d'où la voie 1).
    """
    if recorded:
        sel = f'{{region="{region}"}}' if region else ""
        if agg == "increase":  # intégrer un taux enregistré sur la période
            return f"sum(increase(({COST_RECORDED}{sel})[{window}:])) or vector(0)"
        return f"sum({COST_RECORDED}{sel}) or vector(0)"
    if q.s.dialect == "litellm" and getattr(q, "spend", None):
        if region:
            return None  # la ventilation régionale passe par la voie otel/registre
        return f"sum({agg}({q.spend}[{window}])) or vector(0)"
    if q.s.dialect != "otel_genai" or not q.tok or not q.s.model_label:
        return None
    terms = []
    for it in matched[:INLINE_MODEL_CAP]:
        if region and it["reg"].get("region") != region:
            continue
        m, lbl = it["reg"], _esc(it["seen"])
        for direction, price in (("input", m.get("input_per_mtok")),
                                 ("output", m.get("output_per_mtok"))):
            if price is None:
                continue
            sel = (f'{{{qlbl(q.s.token_type_label)}="{direction}",'
                   f'{qlbl(q.s.model_label)}="{lbl}"}}')
            terms.append(f'(sum({agg}({msel(q.tok + "_sum", sel)}[{window}])) '
                         f"or vector(0)) * {price / 1e6:.9g}")
    return "(" + " + ".join(terms) + ")" if terms else None


RULES_HEADER = """# Generated by grafana-llmops-forge: LLM cost recording rules.
# Price registry verified {verified}.
#
# ONE GROUP, deliberately: rules inside a group evaluate sequentially, so the
# price series exist before the cost rule joins them. Two groups evaluate
# concurrently with staggered starts and the cost rule would emit nothing.
#
# Compatibility: this is the portable rule-file format, accepted by:
#   Prometheus            rule_files: [prometheus_rules_llmops.yml]
#   Thanos Ruler          --rule-file=prometheus_rules_llmops.yml
#   Grafana Mimir/Cortex  mimirtool rules load prometheus_rules_llmops.yml
#   VictoriaMetrics       vmalert -rule=prometheus_rules_llmops.yml
#   AWS AMP               aws amp create-rule-groups-namespace --data file://...
#   Grafana Cloud         mimirtool, same as Mimir
# On Kubernetes with the Prometheus Operator (kube-prometheus-stack) apply the
# PrometheusRule manifest emitted alongside this file instead.
#
# WINDOW: rate() uses [{window}]. Keep it at four times your scrape interval or
# more; at a 60s scrape, 5m gives five points, which is the practical floor.
# Regenerate with --rules-window if your scrape interval is longer.
# INTERVAL: the group evaluates every {interval}. Managed backends enforce
# minimums (AMP and Mimir reject sub-minute groups on default limits).
"""


def _rule_lines(ctx, indent: str, window: str) -> list:
    """Corps des règles, indenté pour un fichier plat ou pour un CRD."""
    q = ctx.primary
    ml, tt = q.s.model_label, q.s.token_type_label
    ml_q = qlbl(ml)
    L, n = [], 0
    for it in ctx.matched:
        m, seen = it["reg"], it["seen"]
        lab = ("{" + json.dumps(ml) + ": " + json.dumps(seen)
               + ", region: " + json.dumps(m.get("region", "?"))
               + ", vendor: " + json.dumps(m.get("vendor", "?")) + "}")
        for rec, key in ((PRICE_IN, "input_per_mtok"), (PRICE_OUT, "output_per_mtok")):
            if m.get(key) is None:
                continue
            L += [f"{indent}- record: {rec}", f"{indent}  expr: {m[key] / 1e6:.12g}",
                  f"{indent}  labels: {lab}"]
            n += 1
    if not n:
        return [], 0

    def side(direction):
        sel = B1 + qlbl(tt) + "=" + Q1 + direction + Q1 + B2
        price = PRICE_IN if direction == "input" else PRICE_OUT
        return [f"{indent}    sum by({ml_q}, region, vendor) (",
                f"{indent}      rate({msel(q.tok + '_sum', sel)}[{window}])",
                f"{indent}    ) * on({ml_q}) group_left(region, vendor) {price}"]

    L += [f"{indent}- record: {COST_RECORDED}:input", f"{indent}  expr: |"] + side("input")
    L += [f"{indent}- record: {COST_RECORDED}:output", f"{indent}  expr: |"] + side("output")
    # somme tolérante aux séries manquantes : `X or Y * 0` fabrique un zéro
    # portant les labels de Y quand X n'existe pas pour ce modèle.
    L += [f"{indent}- record: {COST_RECORDED}", f"{indent}  expr: |",
          f"{indent}    ({COST_RECORDED}:input or {COST_RECORDED}:output * 0)",
          f"{indent}    + ({COST_RECORDED}:output or {COST_RECORDED}:input * 0)"]
    return L, n


def emit_recording_rules(ctx, path: str, window: str = "5m",
                         interval: str = "1m") -> tuple[str, int]:
    """Écrit le fichier de règles portable ET le manifeste PrometheusRule.

    Le format plat couvre Prometheus, Thanos, Mimir, VictoriaMetrics et les
    offres managées. Kubernetes sous Prometheus Operator attend un CRD : c'est
    la majorité des déploiements d'entreprise, et le même contenu ne s'y
    applique pas tel quel.
    """
    q = ctx.primary
    if not q or q.s.dialect != "otel_genai" or not q.tok or not q.s.model_label:
        return "", 0
    body, n = _rule_lines(ctx, "      ", window)
    if not n:
        return "", 0
    head = RULES_HEADER.format(verified=ctx.verified, window=window, interval=interval)
    flat = (head + "groups:\n"
            + f"  - name: llmops-forge-cost\n    interval: {interval}\n    rules:\n"
            + "\n".join(body) + "\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write(flat)

    crd_body, _ = _rule_lines(ctx, "          ", window)
    crd = ("# Generated by grafana-llmops-forge: Kubernetes Prometheus Operator.\n"
           "# kubectl apply -f prometheusrule_llmops.yaml\n"
           "# The labels below must match your Prometheus ruleSelector; on\n"
           "# kube-prometheus-stack that is usually `release: <helm release name>`.\n"
           "apiVersion: monitoring.coreos.com/v1\n"
           "kind: PrometheusRule\n"
           "metadata:\n"
           "  name: llmops-forge-cost\n"
           "  labels:\n"
           "    app.kubernetes.io/name: grafana-llmops-forge\n"
           "    app.kubernetes.io/component: recording-rules\n"
           "    prometheus: kube-prometheus\n"
           "    role: alert-rules\n"
           "spec:\n"
           "  groups:\n"
           f"    - name: llmops-forge-cost\n      interval: {interval}\n      rules:\n"
           + "\n".join(crd_body) + "\n")
    crd_path = os.path.join(os.path.dirname(path) or ".", "prometheusrule_llmops.yaml")
    with open(crd_path, "w", encoding="utf-8") as f:
        f.write(crd)
    return flat, n


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
        metric = msel(metric)
        self.d["templating"]["list"].append({
            "name": "model", "label": "Model", "type": "query",
            "datasource": {"type": "prometheus", "uid": q.s.ds_uid},
            "query": {"query": f"label_values({metric}, {qlbl(q.s.model_label)})",
                      "refId": "V"},
            "includeAll": True, "multi": True, "refresh": 2,
            "current": {"selected": True, "text": ["All"], "value": ["$__all"]}})

    def model_sel(self, q: Q) -> str:
        if any(v["name"] == "model" for v in self.d["templating"]["list"]):
            return f'{{{qlbl(q.s.model_label)}=~"$model"}}'
        return ""

    def panel(self, ptype: str, title: str, w: int, h: int, ds_uid: str | None,
              targets: list | None = None, unit: str | None = None,
              description: str = "", options: dict | None = None,
              overrides: dict | None = None, dstype: str | None = None) -> dict:
        self._id += 1
        p = {"id": self._id, "type": ptype, "title": title,
             "gridPos": self._place(w, h), "description": description,
             "fieldConfig": {"defaults": {}, "overrides": []},
             "options": options or {}, "targets": targets or []}
        if ds_uid:
            dstype = dstype or ("loki" if ptype == "logs" else
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

    def ts(self, title, ds, exprs, w=12, h=8, unit=None, stacked=False, desc="",
           exemplar=False, trace_link=None, dstype=None, topk=0):
        if topk:
            exprs = [((f"topk({topk}, {e[0]})" if e[0] else None), e[1]) for e in exprs]
        targets = [{"refId": chr(65 + i), "expr": e[0], "legendFormat": e[1],
                    "range": True, "instant": False,
                    **({"exemplar": True} if exemplar else {})}
                   for i, e in enumerate(exprs) if e[0]]
        if not targets:
            return None
        p = self.panel("timeseries", title, w, h, ds, targets, unit, desc,
                       dstype=dstype)
        p["maxDataPoints"] = 500   # borne le coût de requête sur les longues plages
        if trace_link:
            p["links"] = [trace_link]
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
#  Contexte de generation                                                     #
# --------------------------------------------------------------------------- #

def tempo_link(tempo_uid: str | None, traceql: str, title: str = "Voir les traces",
               major: int = 12) -> dict | None:
    """Lien de panel vers Explore/Tempo. Format `panes` (Grafana >= 10)."""
    if not tempo_uid or major < 10:
        return None
    import urllib.parse
    panes = json.dumps({"a": {"datasource": tempo_uid,
                              "queries": [{"refId": "A", "datasource":
                                           {"type": "tempo", "uid": tempo_uid},
                                           "queryType": "traceql", "query": traceql}],
                              "range": {"from": "now-1h", "to": "now"}}},
                       separators=(",", ":"))
    return {"title": title, "targetBlank": True,
            "url": "/explore?schemaVersion=1&panes="
                   + urllib.parse.quote(panes, safe="")}


CARDINALITY_LIMIT = 300   # au-delà, un group-by fabrique plus de séries que de sens


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
        self.major = int(cap.get("instance", {}).get("major") or 12)
        self.frameworks = ["eu-ai-act", "iso-42001", "nist-rmf"]
        self.recorded = "recorded" in self.q and any(
            n.startswith("llm:cost") for n in self.q["recorded"].s.names)
        self.exemplars = any(m.get("exemplars") for m in dss.get("prometheus", []))
        self.org_id = 1
        for qq in self.q.values():
            if qq.s.group_card > CARDINALITY_LIMIT:
                qq.s.group_label = None   # cardinalité subie : pas de group-by
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
    b = Board(det_uid("ai-executive-finops"), "AI · Executive FinOps & Cost",
              f"Multi-provider LLM cost. Price registry verified {ctx.verified} "
              f"(USD per 1M tokens). Cost source: "
              f"{'recording rules (llm:cost_usd_per_second)' if ctx.recorded else 'on-the-fly composition'}. "
              f"Generated by grafana-llmops-forge.", ["finops"])
    ds = q.s.ds_uid
    R = ctx.recorded
    spend_range = cost_rate_expr(q, ctx.matched, window="$__range", agg="increase",
                                 recorded=R)
    spend_rate = cost_rate_expr(q, ctx.matched, recorded=R)
    b.stat("Spend (selected range)", ds, spend_range, 6, 5, "currencyUSD",
           "Total over the dashboard's time range.")
    b.stat("Spend rate per day", ds,
           f"({spend_rate}) * 86400" if spend_rate else None, 6, 5, "currencyUSD",
           "Projection: instantaneous rate × 86400.")
    rr = q.req_rate()
    b.stat("Average cost per request", ds,
           f"({spend_rate}) / clamp_min({rr}, 1e-9)" if spend_rate and rr else None,
           6, 5, "currencyUSD")
    tok_out = q.tokens_rate("output")
    b.stat("Generated tokens/s", ds, tok_out, 6, 5, "short")
    b.row_break()
    regions = [("eu", "🇪🇺 EU providers"), ("us", "🇺🇸 US providers"),
               ("asia", "🌏 Asia providers")]
    region_exprs = [(cost_rate_expr(q, ctx.matched, region=r, recorded=R), lbl)
                    for r, lbl in regions]
    if any(e for e, _ in region_exprs):
        b.ts("Spend by provider sovereignty (USD/s)", ds, region_exprs, 12, 8,
             "currencyUSD", stacked=True,
             desc="Split by provider region: sovereignty and AI Act steering.")
    if q.s.dialect == "litellm" and getattr(q, "spend", None) and q.s.group_label:
        b.ts("Spend by team (USD/s)", ds,
             [(f"sum by({qlbl(q.s.group_label)})(rate({msel(q.spend)}[{RATE}]))",
               "{{" + q.s.group_label + "}}")], 12, 8, "currencyUSD", stacked=True,
             topk=12)
    elif q.s.model_label:
        ti = q.tokens_rate("input", by=q.s.model_label)
        b.ts("Input tokens by model (cost proxy)", ds,
             [(ti, "{{" + q.s.model_label + "}}")], 12, 8, "short", stacked=True)
    b.row_break()
    if q.s.model_label:
        b.ts("Output tokens by model/s", ds,
             [(q.tokens_rate("output", by=q.s.model_label),
               "{{" + q.s.model_label + "}}")], 12, 8, "short", stacked=True)
        top = (f"topk(10, sum by({qlbl(q.s.model_label)})"
               f"(increase({msel(q.tok + chr(95) + 'sum')}[$__range])))" if q.s.dialect == "otel_genai" and q.tok
               else None)
        b.table("Top models (tokens, range)", ds, top, 12, 8)
    if ctx.unmatched:
        b.text("Models missing from the price registry",
               "Ces modèles sont observés mais **exclus du calcul de coût** "
               "(prix inconnu) :\n\n"
               + "\n".join(f"- `{_md(m)}`" for m in ctx.unmatched[:20])
               + "\n\nAjouter leur prix dans `references/model_registry.json` "
                 "puis relancer la forge.", 24, 6)
    return b


def bp_gateway(ctx: Ctx) -> Board | None:
    q = ctx.primary
    if not q:
        return None
    b = Board(det_uid("ai-gateway-operations"), "AI · Gateway Operations",
              "Latency, errors and throughput of LLM traffic (SRE). Generated by grafana-llmops-forge.",
              ["gateway", "sre"])
    ds = q.s.ds_uid
    b.add_model_variable(q)
    sel = b.model_sel(q)
    ratio = q.error_ratio()
    b.stat("Availability (1 − error ratio)", ds,
           f"1 - ({ratio})" if ratio else None, 6, 5, "percentunit")
    b.stat("Requests/s", ds, q.req_rate(sel=sel), 6, 5, "reqps")
    dur = getattr(q, "dur", None)
    b.stat("Latency p95", ds, q.pXX(dur, 0.95, sel) if dur else None, 6, 5, "s")
    ttft = getattr(q, "ttft", None)
    b.stat("TTFT p95 (server)", ds, q.pXX(ttft, 0.95) if ttft else None, 6, 5, "s",
           "Time-to-first-token: the first sign of saturation.")
    b.row_break()
    if q.s.model_label:
        b.ts("Requests/s by model", ds,
             [(q.req_rate(by=q.s.model_label, sel=sel), "{{" + q.s.model_label + "}}")],
             12, 8, "reqps", stacked=True)
    if dur:
        b.ts("Latency p50 / p95 / p99", ds,
             [(q.pXX(dur, 0.50, sel), "p50"), (q.pXX(dur, 0.95, sel), "p95"),
              (q.pXX(dur, 0.99, sel), "p99")], 12, 8, "s",
             exemplar=ctx.exemplars,
             trace_link=tempo_link(ctx.tempo, '{span.gen_ai.operation.name="chat"}',
                                   "Traces of slow requests", ctx.major),
             desc=("Clickable exemplars jump to the matching trace."
                   if ctx.exemplars else ""))
    b.row_break()
    if q.s.dialect == "otel_genai" and dur:
        b.ts("Errors/s by type", ds,
             [(f'sum by(error_type)(rate('
               f'{msel(dur + "_count", B1 + "error_type!=" + Q1*2 + B2)}[{RATE}]))',
               "{{error_type}}")], 12, 8, "short")
    elif q.err_rate():
        b.ts("Errors/s", ds, [(q.err_rate(), "errors")], 12, 8, "short")
    if q.s.dialect == "litellm" and getattr(q, "remaining_req", None):
        b.ts("Remaining quota (min per provider)", ds,
             [(f"min by({q.s.provider_label or 'api_provider'})({q.remaining_req})",
               "{{" + (q.s.provider_label or "api_provider") + "}}")], 12, 8, "short",
             desc="Remaining provider rate limits: anticipate throttling.")
    elif q.s.provider_label:
        b.ts("Requests/s by provider", ds,
             [(q.req_rate(by=q.s.provider_label), "{{" + q.s.provider_label + "}}")],
             12, 8, "reqps", stacked=True)
    return b


def bp_agents(ctx: Ctx) -> Board | None:
    q = ctx.q.get("otel_genai")
    if not q or not q.dur:
        return None
    b = Board(det_uid("ai-agents-rag"), "AI · Agents & RAG",
              "Agentic workflows: invocations, tools, tokens per agent, traces. "
              "Conventions OTel GenAI (gen_ai.operation.name). Generated by grafana-llmops-forge.",
              ["agents", "rag"])
    ds = q.s.ds_uid
    op = "gen_ai_operation_name"
    b.stat("Agent invocations/s", ds,
           f'sum(rate({msel(q.dur + "_count", "{" + op + chr(61) + chr(34) + "invoke_agent" + chr(34) + "}")}[{RATE}]))', 6, 5, "reqps")
    b.stat("Tool calls/s", ds,
           f'sum(rate({msel(q.dur + "_count", "{" + op + chr(61) + chr(34) + "execute_tool" + chr(34) + "}")}[{RATE}]))', 6, 5, "reqps")
    b.stat("Agent duration p95", ds,
           q.pXX(q.dur, 0.95, f'{{{op}="invoke_agent"}}'), 6, 5, "s")
    b.stat("Tool errors/s", ds,
           f'sum(rate({msel(q.dur + "_count", "{" + op + chr(61) + chr(34) + "execute_tool" + chr(34) + ",error_type!=" + chr(34)*2 + "}")}[{RATE}]))',
           6, 5, "short")
    b.row_break()
    b.ts("GenAI operation mix", ds,
         [(f"sum by({qlbl(op)})(rate({msel(q.dur + chr(95) + chr(99)+chr(111)+chr(117)+chr(110)+chr(116))}[{RATE}]))", "{{" + op + "}}")],
         12, 8, "reqps", stacked=True,
         desc="chat / embeddings / invoke_agent / execute_tool…")
    b.ts("Calls per tool (execute_tool)", ds,
         [(f'sum by({qlbl("gen_ai_tool_name")})(rate({msel(q.dur + "_count", "{" + op + chr(61) + chr(34) + "execute_tool" + chr(34) + "}")}[{RATE}]))',
           "{{gen_ai_tool_name}}")], 12, 8, "reqps", stacked=True, topk=15,
         exemplar=ctx.exemplars,
         trace_link=tempo_link(ctx.tempo,
                               '{span.gen_ai.operation.name="execute_tool"}',
                               "Tool-call traces", ctx.major))
    b.row_break()
    if q.tok:
        b.ts("Tokens per agent/s", ds,
             [(f"sum by({qlbl(chr(103)+'en_ai_agent_name')})(rate({msel(q.tok + '_sum')}[{RATE}]))",
               "{{gen_ai_agent_name}}")], 12, 8, "short", stacked=True, topk=12)
    b.ts("Embeddings latency p95 (RAG pipeline)", ds,
         [(q.pXX(q.dur, 0.95, f'{{{op}="embeddings"}}'), "p95 embeddings")],
         12, 8, "s", exemplar=ctx.exemplars,
         trace_link=tempo_link(ctx.tempo, '{span.gen_ai.operation.name="embeddings"}',
                               "Embedding traces", ctx.major))
    if ctx.tempo:
        b.traces("Latest agent traces (TraceQL)", ctx.tempo,
                 '{span.gen_ai.operation.name="invoke_agent"}',
                 desc="Click a trace to unfold the full workflow "
                      "(LLM → tools → responses).")
    return b


def bp_adoption(ctx: Ctx) -> Board | None:
    q = ctx.primary
    if not q:
        return None
    b = Board(det_uid("ai-adoption"), "AI · Internal Adoption",
              "Who uses what: active teams and apps, model mix, new adopters. "
              "Generated by grafana-llmops-forge.", ["adoption"])
    ds, g = q.s.ds_uid, q.s.group_label
    rr_by_g = q.req_rate(by=g) if g else None
    base_cnt = None
    if q.s.dialect == "otel_genai" and getattr(q, "dur", None):
        base_cnt = f"{q.dur}_count"
    elif q.s.dialect == "litellm" and getattr(q, "req", None):
        base_cnt = q.req
    if g and base_cnt:
        b.stat(f"Active entities ({g})", ds,
               f"count(sum by({qlbl(g)})(rate({msel(base_cnt)}[1h])) > 0)", 6, 5, "short")
        b.stat("New adopters (7d)", ds,
               f"count(sum by({qlbl(g)})(increase({msel(base_cnt)}[7d])) > 0) - "
               f"count(sum by({qlbl(g)})(increase({msel(base_cnt)}[7d] offset 7d)) > 0)",
               6, 5, "short",
               "Entities emitting LLM traffic this week but not the previous one.")
    if q.s.model_label and base_cnt:
        b.stat("Distinct models in use", ds,
               f"count(count by({qlbl(q.s.model_label)})(rate({msel(base_cnt)}[1h])))", 6, 5)
    b.stat("Requests/s (total)", ds, q.req_rate(), 6, 5, "reqps")
    b.row_break()
    if q.s.model_label:
        b.ts("Model mix (share of traffic)", ds,
             [(q.req_rate(by=q.s.model_label), "{{" + q.s.model_label + "}}")],
             12, 9, "reqps", stacked=True,
             desc="The shape of the mix tells you the real strategy: a cheaper "
                  "model gaining share is a FinOps trade-off that works.")
    if rr_by_g:
        b.ts(f"Trafic par {g}", ds, [(rr_by_g, "{{" + g + "}}")], 12, 9,
             "reqps", stacked=True, topk=12,
             desc=(f"Top 12 of {q.s.group_card} values of {g}."
                   if q.s.group_card > 12 else ""))
    b.row_break()
    if g and q.s.dialect == "otel_genai" and q.tok:
        b.table("Top consumers (tokens, range)", ds,
                f"topk(15, sum by({qlbl(g)})(increase({msel(q.tok + chr(95) + 'sum')}[$__range])))", 24, 9)
    return b


def bp_inference(ctx: Ctx) -> Board | None:
    qv = ctx.q.get("vllm") or ctx.q.get("tgi")
    gpu = ctx.gpu()
    if not qv and not gpu:
        return None
    b = Board(det_uid("ai-inference-selfhosted"), "AI · Self-hosted Inference",
              "Moteurs d'inference (vLLM/TGI) + GPU. Les 4 signaux d'or : TTFT, TPOT, "
              "file d'attente, KV cache. Generated by grafana-llmops-forge.", ["inference", "gpu"])
    if qv and qv.s.dialect == "vllm":
        ds, ml = qv.s.ds_uid, qv.s.model_label or "model_name"
        b.stat("TTFT p95", ds, qv.pXX(qv.ttft, 0.95) if qv.ttft else None, 6, 5, "s")
        b.stat("TPOT p95 (inter-token)", ds,
               qv.pXX(qv.tpot, 0.95) if qv.tpot else None, 6, 5, "s")
        b.stat("Queued requests", ds,
               f"sum({qv.waiting})" if qv.waiting else None, 6, 5)
        b.stat("KV cache (max)", ds, f"max({qv.kv})" if qv.kv else None, 6, 5,
               "percentunit", "≥ 0.90 means preemptions are imminent and latency degrades.")
        b.row_break()
        if qv.e2e:
            b.ts("End-to-end latency p50/p95/p99", ds,
                 [(qv.pXX(qv.e2e, 0.50, by=ml), "p50 {{" + ml + "}}"),
                  (qv.pXX(qv.e2e, 0.95, by=ml), "p95 {{" + ml + "}}"),
                  (qv.pXX(qv.e2e, 0.99, by=ml), "p99 {{" + ml + "}}")], 12, 8, "s")
        b.ts("Token throughput (prompt vs generation)", ds,
             [(qv.tokens_rate("input"), "prompt"),
              (qv.tokens_rate("output"), "generation")], 12, 8, "short")
        b.row_break()
        b.ts("Queue and running", ds,
             [(f"sum({qv.running})" if qv.running else None, "running"),
              (f"sum({qv.waiting})" if qv.waiting else None, "waiting")], 12, 8)
        b.ts("Preemptions/s (KV cache pressure)", ds,
             [(f"sum(rate({qv.preempt}[{RATE}]))" if qv.preempt else None,
               "preemptions")], 12, 8,
             desc="A preemption recomputes context: correct, but expensive. A "
                  "non-zero plateau under normal load means undersizing.")
    if qv and qv.s.dialect == "tgi":
        ds = qv.s.ds_uid
        b.ts("Inference latency p95 (TGI)", ds,
             [(qv.pXX(qv.dur, 0.95) if getattr(qv, "dur", None) else None, "p95")],
             12, 8, "s")
        b.ts("Queue (TGI)", ds,
             [(f"sum({qv.queue})" if getattr(qv, "queue", None) else None, "queue")],
             12, 8)
    if gpu:
        b.row_break()
        ds = gpu.s.ds_uid
        b.ts("GPU utilisation (%)", ds,
             [(f"avg by(gpu)({gpu.gpu_util})" if gpu.gpu_util else None,
               "GPU {{gpu}}")], 12, 8, "percent")
        b.ts("VRAM used", ds,
             [(f"sum by(gpu)({gpu.vram})" if gpu.vram else None, "GPU {{gpu}}")],
             12, 8, "decmbytes")
    if ctx.registry.get("models"):
        api_refs = [m for m in ctx.registry["models"]
                    if m.get("output_per_mtok") is not None][:6]
        rows = "\n".join(f"| {m['id']} | {m.get('region','?').upper()} | "
                         f"{m['input_per_mtok']}$ | {m['output_per_mtok']}$ |"
                         for m in sorted(api_refs, key=lambda m: m['output_per_mtok']))
        b.text("Reference: API cost per 1M tokens (self-hosted benchmark)",
               "Compare your GPU cost per 1M generated tokens against these API prices "
               f"(registry dated {ctx.verified}) :\n\n"
               "| Model | Region | Input | Output |\n|---|---|---|---|\n" + rows,
               24, 7)
    return b


ISO_42001_MD = """### ISO/IEC 42001:2023: where these panels serve as evidence

Certification audits management-system clauses 4–10 plus every Annex A control
declared applicable in your Statement of Applicability (38 controls across nine
groups, A.2 to A.10). Most of those are satisfied by documents. A handful are
not: an auditor at Stage 2 wants to see the system **was actually monitored**,
and that is what this dashboard produces.

| Control | What the auditor asks for | Panel here |
|---|---|---|
| A.6.2.6: AI system operation and monitoring | Evidence that production systems are monitored continuously, not just documented | The whole board, plus the gateway and quality dashboards |
| A.6.2.8: AI system recording of event logs | Logs enabled at the declared lifecycle phases, retained, retrievable | Logging evidence panel; retention is a Loki config check |
| A.9: Use of AI systems | Responsible and intended use, human oversight | Adoption dashboard (who uses what) + override counters if instrumented |
| A.10: Third parties and suppliers | Which providers you depend on, and how that dependency is governed | Model inventory and the sovereignty split |
| Clause 9.1: Monitoring, measurement, analysis, evaluation | Defined metrics, measured, reviewed | Every panel; the review record is yours to keep |

Two cautions. Annex A numbering differs between secondary sources; confirm each
reference against your own copy of the standard before it enters a Statement of
Applicability. And a dashboard is evidence of monitoring, not of a management
system: clauses 4–10 remain organisational work no tool performs for you."""


NIST_RMF_MD = """### NIST AI RMF 1.0: which subcategories these signals feed

The framework (NIST AI 100-1) is voluntary and organises work into GOVERN, MAP,
MEASURE and MANAGE, about seventy subcategories in all. It is the de facto
reference for US programmes and crosswalks closely to ISO/IEC 42001. Runtime
telemetry speaks mostly to MEASURE and MANAGE.

| Subcategory | Outcome sought | Panel here |
|---|---|---|
| MEASURE 2.x: performance and trustworthiness evaluated | Systems evaluated on chosen metrics, regularly | Quality & Evaluations dashboard; gateway latency and error panels |
| MEASURE 3.x: mechanisms for tracking identified risks | Risks tracked over time, not assessed once | Trend panels across the whole suite |
| MEASURE 4.x: measurement efficacy reviewed | Feedback on whether the measurements still mean anything | Evaluation volume panel: flat-lined scores are stale scores |
| MANAGE 4.1: post-deployment monitoring | Monitoring, appeal and override, decommissioning, change management | This board plus the provisioned SLO alerts |
| MANAGE 2.x: maximise benefit, minimise negative impact | Documented treatment of residual risk | Cost and adoption boards inform the trade-offs |
| GOVERN 1.1: legal and regulatory requirements understood | Applicable obligations known and tracked | Regulatory timeline panel |
| GOVERN 6.1/6.2: third-party risk | Supply-chain and vendor dependency governed | Model inventory and sovereignty split |

For generative AI specifically, NIST AI 600-1 (the Generative AI Profile, July
2024) adds twelve risk categories mapped back to these four functions; the cost,
adoption and quality boards are the measurement layer several of them assume."""


# Le crosswalk est une donnée, pas un bloc de texte : n'afficher que les
# colonnes demandées, et ajouter un référentiel devient une clé de plus.
CROSSWALK_ROWS = [
    ("Logs exist continuously and are retained",
     {"eu-ai-act": "Art. 12 · Art. 26(6)", "iso-42001": "A.6.2.8",
      "nist-rmf": "MANAGE 4.1"}),
    ("Production systems are monitored",
     {"eu-ai-act": "Art. 72 post-market", "iso-42001": "A.6.2.6 · Cl. 9.1",
      "nist-rmf": "MEASURE 3.x · MANAGE 4.1"}),
    ("Inventory of models actually consumed",
     {"eu-ai-act": "Art. 26 · GPAI chain", "iso-42001": "A.10",
      "nist-rmf": "GOVERN 6.1 · MAP 4.1"}),
    ("Provider dependency and jurisdiction",
     {"eu-ai-act": "GPAI contractual terms", "iso-42001": "A.10",
      "nist-rmf": "GOVERN 6.2"}),
    ("Quality and drift measured",
     {"eu-ai-act": "Art. 15 accuracy/robustness", "iso-42001": "A.6.2.6",
      "nist-rmf": "MEASURE 2.x"}),
    ("Incidents detected and escalated",
     {"eu-ai-act": "Art. 73", "iso-42001": "A.8", "nist-rmf": "MANAGE 4.x"}),
    ("Who uses the systems, and how",
     {"eu-ai-act": "Art. 4 · Art. 26", "iso-42001": "A.9",
      "nist-rmf": "GOVERN 1.x"}),
]


def crosswalk_md(picked: list) -> str:
    """Table de correspondance restreinte aux référentiels demandés."""
    heads = [FRAMEWORKS[f][0] for f in picked]
    lines = [
        "### One signal, several frameworks",
        "",
        "Compliance regimes differ in vocabulary and in what they oblige. They",
        "agree almost entirely on what has to be observable. This is the same",
        "telemetry, read several ways; build the runtime layer once.",
        "",
        "| Observable signal | " + " | ".join(heads) + " |",
        "|---|" + "---|" * len(heads),
    ]
    for signal, refs in CROSSWALK_ROWS:
        lines.append(f"| {signal} | " + " | ".join(refs[f] for f in picked) + " |")
    lines += ["",
              "*Support for compliance evidence. Not a legal opinion, and not a "
              "certification.*"]
    return "\n".join(lines)




AI_ACT_TIMELINE_MD = """### Calendrier AI Act : état vérifié juillet 2026 (post-Digital Omnibus)

| Échéance | Obligation | Statut |
|---|---|---|
| 2 fév. 2025 | Pratiques interdites (Art. 5) + maîtrise de l'IA (Art. 4) | ✅ en vigueur |
| 2 août 2025 | Obligations GPAI (Art. 51-56) : documentation, transparence, incidents | ✅ en vigueur |
| **2 août 2026** | **Activation des pouvoirs de sanction** ; transparence Art. 50 (chatbots : information des utilisateurs) | ⚠️ imminent |
| 2 déc. 2026 | Marquage machine-réadable des contenus synthétiques (Art. 50§2, reporté) | à préparer |
| 2 déc. 2027 | Systèmes haut risque Annexe III (RH, crédit, biométrie…), reporté par l'Omnibus (accord provisoire du 7 mai 2026, adoption formelle en cours) | à cartographier |
| 2 août 2028 | Haut risque intégré aux produits (Annexe I) | horizon |

**Ce que ce dashboard prouve** : journalisation active (Art. 12), rétention côté
déployeur ≥ 6 mois (Art. 26§6), veille incidents (Art. 73, signalement des
incidents graves), inventaire des systèmes. Sanctions : jusqu'à 35 M€ / 7 % CA.
*Support d'aide à la conformité ; ne constitue pas un avis juridique.*"""


FRAMEWORKS = {
    "eu-ai-act": ("EU AI Act", "Regulatory timeline", lambda: AI_ACT_TIMELINE_MD, 11),
    "iso-42001": ("ISO/IEC 42001", "ISO/IEC 42001 evidence map", lambda: ISO_42001_MD, 10),
    "nist-rmf": ("NIST AI RMF", "NIST AI RMF signal map", lambda: NIST_RMF_MD, 11),
}


def bp_governance(ctx: Ctx) -> Board:
    """Le même socle de preuves, lu selon un ou plusieurs référentiels.

    Les panneaux mesurés sont identiques quel que soit le cadre : c'est le même
    volume de logs qui atteste l'Art. 12, le contrôle A.6.2.8 et MANAGE 4.1.
    Seule la lecture change, et c'est elle qui décide si un DSI à Singapour ou
    à Chicago se reconnaît dans le tableau de bord.
    """
    picked = [f for f in ctx.frameworks if f in FRAMEWORKS] or ["eu-ai-act"]
    names = ", ".join(FRAMEWORKS[f][0] for f in picked)
    title = ("AI · Governance & EU AI Act" if picked == ["eu-ai-act"]
             else "AI · Governance & Compliance Evidence")
    b = Board(det_uid("ai-governance-eu-ai-act"), title,
              f"Observability evidence for {names}: logging, inventory, "
              "sovereignty, incidents. Generated by grafana-llmops-forge, "
              "not legal advice.", ["governance"] + picked)
    if len(picked) > 1:
        b.text("One signal, several frameworks", crosswalk_md(picked),
               24, 5 + len(CROSSWALK_ROWS))
    for f in picked:
        _, panel_title, md, h = FRAMEWORKS[f]
        b.text(panel_title, md(), 24, h)
    q = ctx.primary
    if q:
        ds = q.s.ds_uid
        regions = [("eu", "EU share"), ("us", "US share"), ("asia", "Asia share")]
        exprs = []
        for r, lbl in regions:
            ids = [_esc(it["seen"]) for it in ctx.matched if it["reg"].get("region") == r]
            if ids and q.s.model_label:
                rx = "|".join(_rx(i) for i in ids)
                exprs.append((q.req_rate(
                    sel=f'{{{qlbl(q.s.model_label)}=~"{rx}"}}'), lbl))
        if exprs:
            b.ts("Traffic by provider sovereignty", ds, exprs, 12, 8,
                 "reqps", stacked=True,
                 desc="Actual dependency on providers by region: sovereignty "
                      "steering and GPAI contractual clauses.")
    if ctx.loki:
        lbl = (ctx.loki.get("labels") or ["service_name"])[0]
        b.ts("Logging evidence (log volume)", ctx.loki["uid"],
             [(f'sum by({lbl})(rate({{{lbl}=~".+"}}[{RATE}]))', "{{" + lbl + "}}")],
             12, 8, "short", dstype="loki", topk=12,
             desc="Art. 12 (logging) and Art. 26(6) (deployer retention of at "
                  "least six months). Check Loki retention ≥ 4320h.")
    b.row_break()
    if ctx.matched or ctx.unmatched:
        rows = []
        for it in ctx.matched:
            m = it["reg"]
            rows.append(f"| `{_md(it['seen'])}` | {_md(str(m.get('vendor','?')))} | "
                        f"{m.get('region','?').upper()} | "
                        f"{'open-weights' if m.get('open_weights') else 'proprietary'} | "
                        f"{'oui' if m.get('gpai_in_scope', True) else 'non'} |")
        for s in ctx.unmatched:
            rows.append(f"| `{_md(s)}` | ? | ? | ? | to qualify |")
        b.text("Observed model inventory (feeds your AI system register)",
               "Models actually in use (auto-detected):\n\n"
               "| Observed model | Vendor | Region | Licence | GPAI |\n"
               "|---|---|---|---|---|\n" + "\n".join(rows) +
               "\n\nÀ rapprocher de votre registre interne des systèmes d'IA "
               "(cartographie fournisseur/déployeur).", 12, 10)
    b.alertlist("Incident watch (AI Act Art. 73 · ISO A.8 · NIST MANAGE 4.x)", 12, 10)
    return b


def bp_quality(ctx: Ctx) -> Board | None:
    """Signaux qualité (evals, guardrails). Généré uniquement s'ils existent."""
    qe = ctx.q.get("evals")
    if not qe:
        return None
    ds, names = qe.s.ds_uid, qe.s.names
    b = Board(det_uid("ai-quality-evals"), "AI · Quality & Evaluations",
              "Scores d'évaluation, garde-fous et dérive qualité. Un système peut "
              "être vert en latence et faux en sortie : c'est ce que ce dashboard "
              "regarde. Generated by grafana-llmops-forge.", ["quality", "evals"])
    ml = qe.s.model_label
    sb = qe.s.find("score", "_bucket") or qe.s.find("evaluation", "_bucket")
    score = sb or qe.s.find("score") or qe.s.find("evaluation")
    guard = qe.s.find("guard") or qe.s.find("blocked")
    if score:
        base = score[:-len("_bucket")] if score.endswith("_bucket") else score
        is_hist = f"{base}_bucket" in names
        avg = (f"histogram_quantile(0.5, sum by(le)(rate({base}_bucket[{RATE}])))"
               if is_hist else f"avg({score})")
        b.stat("Median score", ds, avg, 6, 5, "percentunit")
        low = (f"histogram_quantile(0.1, sum by(le)(rate({base}_bucket[{RATE}])))"
               if is_hist else f"min({score})")
        b.stat("Low decile (p10)", ds, low, 6, 5, "percentunit",
               "The low tail is the real signal; the mean hides the failures.")
    if guard:
        b.stat("Guardrail blocks/s", ds,
               f"sum(rate({guard}[{RATE}]))" if guard.endswith("_total")
               else f"sum({guard})", 6, 5, "short")
    b.row_break()
    if score and ml:
        base = score[:-len("_bucket")] if score.endswith("_bucket") else score
        if f"{base}_bucket" in names:
            b.ts("Score by model (p50)", ds,
                 [(f"histogram_quantile(0.5, sum by(le,{ml})"
                   f"(rate({base}_bucket[{RATE}])))", "{{" + ml + "}}")],
                 12, 8, "percentunit",
                 desc="A model switch that lowers this panel is a cost/quality "
                      "trade-off worth documenting.")
    if score:
        base = score[:-len("_bucket")] if score.endswith("_bucket") else score
        cnt = f"{base}_count" if f"{base}_count" in names else None
        if cnt:
            b.ts("Evaluation volume/s", ds,
                 [(f"sum(rate({cnt}[{RATE}]))", "evaluations")], 12, 8, "short",
                 desc="If this volume falls to zero, the scores shown elsewhere are stale.")
    b.text("What this dashboard does not prove",
           "An evaluation score measures what your evaluator knows how to measure. "
           "Documentez la méthode (juge LLM ? jeu de référence ? échantillonnage ?) "
           "à côté de ces courbes, sans quoi la métrique se retourne contre vous "
           "en revue. Pour l'AI Act, ces signaux alimentent la surveillance "
           "post-commercialisation (Art. 72), pas la conformité à eux seuls.", 24, 5)
    return b


BLUEPRINTS = {"finops": bp_finops, "gateway": bp_gateway, "agents": bp_agents,
              "adoption": bp_adoption, "inference": bp_inference,
              "quality": bp_quality, "governance": bp_governance}


# --------------------------------------------------------------------------- #
#  Alertes SLO (provisioning API)                                             #
# --------------------------------------------------------------------------- #

def _rule(uid_name, title, prom_uid, expr, threshold, op, folder_uid,
          summary, severity="warning", for_="10m", nodata="OK", org_id=1,
          runbook=""):
    ann = {"summary": summary}
    if runbook:
        ann["__dashboardUid__"] = ""
        ann["runbook_url"] = runbook
    return {"uid": det_uid(uid_name, "alr"), "title": title, "orgID": org_id,
            "folderUID": folder_uid, "ruleGroup": "llmops-slo",
            "condition": "C", "for": for_, "noDataState": nodata,
            "execErrState": "Error",
            "labels": {"severity": severity, "origin": "llmops-forge"},
            "annotations": ann,
            "data": [
                {"refId": "A", "relativeTimeRange": {"from": 21600, "to": 0},
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


def build_alerts(ctx: Ctx, folder_uid: str, daily_budget: float,
                 slo_target: float = 0.99) -> list:
    """Règles SLO. Fenêtres explicites (pas de $__rate_interval : l'intervalle
    d'une règle d'alerte n'est pas celui d'un panel), et burn-rate multi-fenêtres
    pour le taux d'erreur ; un seuil unique sur la dernière valeur alerte trop
    tard sur les pannes lentes et trop souvent sur les pics inoffensifs."""
    alert_rules, org = [], ctx.org_id
    q = ctx.primary
    budget = max(1 - slo_target, 1e-4)
    if q:
        # --- burn-rate 2 fenêtres (Google SRE) : page rapide + ticket lent
        for name, fast, slow, factor, sev, dur in (
                ("llm-burn-fast", "5m", "1h", 14.4, "critical", "2m"),
                ("llm-burn-slow", "30m", "6h", 6.0, "warning", "15m")):
            r_fast, r_slow = q.error_ratio(w=fast), q.error_ratio(w=slow)
            if not (r_fast and r_slow):
                continue
            thr = factor * budget
            alert_rules.append(_rule(
                name, f"LLM · {'Fast' if factor > 10 else 'Slow'} error-budget burn "
                      f"({fast}/{slow}), SLO {slo_target:.1%}",
                q.s.ds_uid,
                f"min(({r_fast}) > {thr:.6g}) and min(({r_slow}) > {thr:.6g})",
                0, "gt", folder_uid,
                f"The {slo_target:.1%} SLO error budget is burning {factor}x too "
                f"fast over both {fast} and {slow}.",
                sev, dur, "OK", org))
        # --- signal perdu : NoData DOIT alerter, c'est le cas qu'on veut attraper
        rr = q.req_rate(w="10m")
        if rr:
            alert_rules.append(_rule(
                "llm-signal-lost", "LLM · Telemetry signal lost",
                q.s.ds_uid, f"({rr}) or vector(0)", 1e-9, "lt", folder_uid,
                "No LLM traffic measured at all, or the datasource is unreachable: "
                "instrumentation or collector is most likely down.",
                "warning", "15m", "Alerting", org))
        spend = cost_rate_expr(q, ctx.matched, window="10m", recorded=ctx.recorded)
        if spend:
            alert_rules.append(_rule(
                "llm-daily-budget", "LLM · Daily budget exceeded", q.s.ds_uid,
                f"({spend}) * 86400", daily_budget, "gt", folder_uid,
                f"Spend rate above {daily_budget} USD per day.",
                "warning", "30m", "OK", org))
        ttft = getattr(q, "ttft", None)
        if ttft:
            alert_rules.append(_rule(
                "llm-ttft-p95", "LLM · TTFT p95 > 3 s", q.s.ds_uid,
                q.pXX(ttft, 0.95, w="10m"), 3, "gt", folder_uid,
                "First token takes over 3s at p95: saturation is likely.",
                "warning", "10m", "OK", org))
    qv = ctx.q.get("vllm")
    if qv and qv.kv:
        alert_rules.append(_rule(
            "vllm-kv-cache", "vLLM · KV cache > 92 %", qv.s.ds_uid,
            f"max({qv.kv})", 0.92, "gt", folder_uid,
            "KV cache saturated: preemptions and latency degradation ahead.",
            "critical", "5m", "OK", org))
    qe = ctx.q.get("evals")
    if qe:
        sc = (qe.s.find("score", "_bucket") or qe.s.find("evaluation", "_bucket"))
        if sc:
            base = sc[:-len("_bucket")]
            alert_rules.append(_rule(
                "llm-quality-drop", "LLM · Evaluation score p50 below 0.7",
                qe.s.ds_uid,
                f"histogram_quantile(0.5, sum by(le)(rate({base}_bucket[30m])))",
                0.7, "lt", folder_uid,
                "Median quality of evaluated responses has dropped below threshold.",
                "warning", "30m", "OK", org))
    return alert_rules


# --------------------------------------------------------------------------- #
#  Validation, self-test, CLI                                                 #
# --------------------------------------------------------------------------- #

def localize(obj, table: dict):
    """Traduit récursivement les libellés utilisateur d'un dashboard.

    L'anglais est la source : c'est ce que lit une DSI à Chicago comme à
    Singapour. Le français reste disponible pour les organisations qui
    l'exigent, sans dupliquer le code des blueprints.
    """
    if isinstance(obj, dict):
        return {k: (table.get(v, v) if k in ("title", "description", "legendFormat",
                                             "content", "summary") and isinstance(v, str)
                    else localize(v, table))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [localize(v, table) for v in obj]
    return obj


def load_locale(code: str) -> dict:
    if code == "en":
        return {}
    p = os.path.join(HERE, "..", "references", f"locale.{code}.json")
    if not os.path.exists(p):
        print(f"[warn] locale « {code} » introuvable, sortie en anglais", file=sys.stderr)
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def to_portable(dash: dict) -> dict:
    """Rend le dashboard importable par n'importe qui : UID de datasource
    remplacés par des ${DS_*} déclarés en __inputs. Prérequis de publication
    sur grafana.com/dashboards, le premier canal de découverte des admins."""
    d = json.loads(json.dumps(dash))
    found, inputs = {}, []
    TYPES = {"prometheus": "DS_PROMETHEUS", "loki": "DS_LOKI", "tempo": "DS_TEMPO"}
    def walk(node):
        if isinstance(node, dict):
            ds = node.get("datasource")
            if isinstance(ds, dict) and ds.get("uid") and ds.get("type") in TYPES:
                name = TYPES[ds["type"]]
                found[name] = ds["type"]
                node["datasource"] = {"type": ds["type"], "uid": "${%s}" % name}
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(d)
    for name, typ in sorted(found.items()):
        inputs.append({"name": name, "label": typ.capitalize(), "type": "datasource",
                       "pluginId": typ, "pluginName": typ.capitalize(),
                       "description": f"Datasource {typ} portant vos signaux LLM"})
    d["__inputs"] = inputs
    d["__requires"] = [{"type": "grafana", "id": "grafana", "name": "Grafana",
                        "version": "9.0.0"}]
    d["uid"] = ""      # laisser Grafana attribuer à l'import
    d["id"] = None
    return d


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
            "datasources": {"prometheus": [{"uid": prom, "name": "Prom",
                                            "exemplars": True}],
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
                "evals": {
                    "metric_names": ["gen_ai_evaluation_score_bucket",
                                     "gen_ai_evaluation_score_sum",
                                     "gen_ai_evaluation_score_count",
                                     "guardrail_blocked_total"],
                    "model_label": "gen_ai_request_model",
                    "models_seen": ["gpt-5.4"]},
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
    ap.add_argument("--slo-target", type=float, default=0.99,
                    help="Cible SLO pour le burn-rate (défaut 0.99)")
    ap.add_argument("--cost-mode", choices=["auto", "recorded", "inline"],
                    default="auto",
                    help="auto: recording rules si détectées, sinon composition")
    ap.add_argument("--framework", default="eu-ai-act,iso-42001,nist-rmf",
                    help="Référentiels de gouvernance à cartographier : "
                         "eu-ai-act, iso-42001, nist-rmf (liste séparée par des "
                         "virgules). Les panneaux mesurés sont les mêmes ; seule "
                         "la lecture change.")
    ap.add_argument("--rules-window", default="5m",
                    help="Fenêtre rate() des recording rules. Au moins 4x "
                         "l'intervalle de scrape (défaut 5m).")
    ap.add_argument("--rules-interval", default="1m",
                    help="Intervalle d'évaluation du groupe de règles (défaut 1m). "
                         "Les backends managés refusent souvent le sous-minute.")
    ap.add_argument("--locale", default="en",
                    help="Langue des libellés générés : en (défaut) ou fr. "
                         "Les tables vivent dans references/locale.<code>.json")
    ap.add_argument("--export-portable", action="store_true",
                    help="Écrit aussi des JSON portables (${DS_*}) publiables")
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
    _failed = []
    ctx.frameworks = [f.strip() for f in args.framework.split(",") if f.strip()]
    _unknown = [f for f in ctx.frameworks if f not in FRAMEWORKS]
    if _unknown:
        print(f"[warn] unknown framework(s): {_unknown}; known: "
              f"{sorted(FRAMEWORKS)}", file=sys.stderr)
    if args.cost_mode == "recorded":
        ctx.recorded = True
    elif args.cost_mode == "inline":
        ctx.recorded = False
    if args.deploy and not args.dry_run:
        try:
            ctx.org_id = GrafanaClient(insecure=args.insecure).org_id()
        except SystemExit:
            pass
    wanted = (list(BLUEPRINTS) if args.blueprints == "auto"
              else [b.strip() for b in args.blueprints.split(",")])
    boards, skipped, errors = [], [], []
    for name in wanted:
        fn = BLUEPRINTS.get(name)
        if not fn:
            skipped.append((name, "unknown blueprint"))
            continue
        board = fn(ctx)
        if board is None or not board.d["panels"]:
            skipped.append((name, "required signals absent from the capability map"))
            continue
        errors.extend(validate(board))
        boards.append((name, board))

    if errors:
        print("VALIDATION FAILED:", file=sys.stderr)
        for e in errors:
            print("  -", e, file=sys.stderr)
        return 2

    _loc = load_locale(args.locale)
    if _loc:
        for _, board in boards:
            board.d = localize(board.d, _loc)

    os.makedirs(args.out_dir, exist_ok=True)
    manifest = {"generated_at": datetime.now(timezone.utc).isoformat(),
                "deployed": False, "dashboards": []}
    for name, board in boards:
        path = os.path.join(args.out_dir, f"{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(board.d, f, indent=2, ensure_ascii=False)
        if args.export_portable:
            pp = os.path.join(args.out_dir, f"{name}.portable.json")
            with open(pp, "w", encoding="utf-8") as f:
                json.dump(to_portable(board.d), f, indent=2, ensure_ascii=False)
        manifest["dashboards"].append(
            {"blueprint": name, "uid": board.d["uid"], "title": board.d["title"],
             "url": None,
             "panels": [{"id": p["id"], "title": p.get("title", ""),
                         "type": p["type"]} for p in board.d["panels"]]})
        print(f"[ok] {board.d['title']}  ({len(board.d['panels'])} panels) → {path}")
    for name, why in skipped:
        print(f"[skip] {name}: {why}")

    def _perm_hint(op, err):
        """Un 403 en production est une question de rôle, pas un bug : le dire."""
        if getattr(err, "status", None) == 403:
            need = {"folder": "Editor (or a role allowed to create folders)",
                    "dashboard": "Editor on the target folder",
                    "alert": "alert.provisioning:write (Admin on OSS)"}[op]
            return (f"HTTP 403 while {op == 'folder' and 'creating the folder' or op}"
                    f"; the service account needs: {need}.")
        return f"{err}"

    if args.deploy and not args.dry_run:
        client = GrafanaClient(insecure=args.insecure)
        try:
            folder = client.ensure_folder(args.folder)
        except GrafanaError as e:
            print(f"\n[fail] {_perm_hint('folder', e)}\n"
                  f"       Nothing was written. The dashboards are on disk in "
                  f"{args.out_dir} and can be imported by hand.", file=sys.stderr)
            return 3
        print(f"\nFolder « {folder.get('title')} » (uid {folder.get('uid')})")
        manifest["deployed"] = True
        # Un échec sur un dashboard n'annule pas les autres : l'exploitant doit
        # savoir exactement ce qui est en place, pas se retrouver dans un état
        # partiel non décrit.
        for i, (name, board) in enumerate(boards):
            try:
                res = client.upsert_dashboard(
                    board.d, folder["uid"],
                    f"llmops-forge {datetime.now(timezone.utc):%Y-%m-%d}")
            except GrafanaError as e:
                _failed.append((name, _perm_hint("dashboard", e)))
                manifest["dashboards"][i]["error"] = str(e)
                print(f"  ✗ {name}: {_perm_hint('dashboard', e)}", file=sys.stderr)
                continue
            manifest["dashboards"][i]["url"] = client.dashboard_url(res, board.d)
            print(f"  ↗ {manifest['dashboards'][i]['url']}")
        if _failed:
            print(f"\n[partial] {len(boards) - len(_failed)}/{len(boards)} dashboards "
                  f"deployed; {len(_failed)} refused. Re-running after fixing the "
                  f"role is safe: deterministic UIDs make it an update.",
                  file=sys.stderr)
        if args.with_alerts:
            alert_rules = build_alerts(ctx, folder["uid"], args.daily_budget,
                                 args.slo_target)
            if not client.contact_points():
                print("  ⚠ no contact point configured: alerts will fire with no "
                      "recipient (Alerting → Contact points).")
            for r in alert_rules:
                try:
                    client.upsert_alert_rule(r)
                    print(f"  ⚑ alerte : {r['title']}")
                except Exception as e:  # 403 fréquent selon rôle/édition
                    fb = os.path.join(args.out_dir, f"alert_{r['uid']}.json")
                    with open(fb, "w", encoding="utf-8") as f:
                        json.dump(r, f, indent=2, ensure_ascii=False)
                    print(f"  ⚠ alerte '{r['title']}' non provisionnée ({e}) ; "
                          f"export : {fb} (import manuel possible)")
    elif args.with_alerts:
        folder_uid = det_uid(args.folder, "fold")
        for r in build_alerts(ctx, folder_uid, args.daily_budget, args.slo_target):
            fb = os.path.join(args.out_dir, f"alert_{r['uid']}.json")
            with open(fb, "w", encoding="utf-8") as f:
                json.dump(r, f, indent=2, ensure_ascii=False)
            print(f"[ok] alerte (non déployée) → {fb}")

    rules_path = os.path.join(args.out_dir, "prometheus_rules_llmops.yml")
    _, nprices = emit_recording_rules(ctx, rules_path, args.rules_window,
                                      args.rules_interval)
    if nprices:
        print(f"[ok] recording rules ({nprices} prices) → {rules_path}"
              f"\n     + PrometheusRule CRD → "
              f"{os.path.join(os.path.dirname(rules_path) or '.', 'prometheusrule_llmops.yaml')}"
              + ("" if ctx.recorded else
                 "\n     ↳ copier dans Prometheus (rule_files) puis relancer "
                 "discover+forge : les panels de coût passeront en O(1)."))
    elif os.path.exists(rules_path):
        os.remove(rules_path)

    with open(os.path.join(args.out_dir, "deploy_manifest.json"), "w",
              encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    if args.deploy and not args.dry_run and _failed:
        return 4
    print(f"\n{len(boards)} dashboard(s) generated, {len(skipped)} skipped, "
          f"registry verified {ctx.verified}.")
    if ctx.unmatched:
        print(f"Models without a price ({len(ctx.unmatched)}): "
              + ", ".join(ctx.unmatched[:8]))
    if manifest["deployed"]:
        print("CONTRÔLE VISUEL (recommandé) : "
              f"python3 scripts/visual_audit.py --dashboards {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
