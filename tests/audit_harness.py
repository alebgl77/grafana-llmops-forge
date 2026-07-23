"""Harnais d'audit grafana-llmops-forge — vérifie les chemins hors selftest."""
import json, os, re, subprocess, sys, shutil

import pathlib
SK = str(pathlib.Path(__file__).resolve().parent.parent)
SC = f"{SK}/scripts"
sys.path.insert(0, SC)
import tempfile; os.chdir(tempfile.gettempdir())
FAIL = []

def check(name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(f"{name}: {detail}")

def run_forge(cap, outdir, bps="auto", extra=()):
    cpath = f"/tmp/{outdir}.json"
    json.dump(cap, open(cpath, "w"))
    r = subprocess.run([sys.executable, f"{SC}/forge_dashboards.py",
                        "--capability", cpath, "--blueprints", bps,
                        "--out-dir", f"/tmp/{outdir}", "--with-alerts",
                        *extra], capture_output=True, text=True)
    return r, f"/tmp/{outdir}"

def load_boards(d):
    out = {}
    for f in os.listdir(d):
        if f.endswith(".json") and not f.startswith(("alert_", "deploy_")):
            out[f[:-5]] = json.load(open(os.path.join(d, f)))
    return out

def all_exprs(board):
    for p in board["panels"]:
        for t in p.get("targets", []):
            if "expr" in t:
                yield p["title"], t["expr"]

def promql_sane(e):
    if "None" in e: return "contient 'None'"
    for a, b in (("(", ")"), ("{", "}"), ("[", "]")):
        if e.count(a) != e.count(b): return f"déséquilibre {a}{b}"
    if re.search(r'\{\s*\}', e): return "sélecteur vide {}"
    if re.search(r'\brate\([^[]+\)\s*(?!\[)', e) and "[" not in e: return "rate sans fenêtre"
    return None

# ---------------------------------------------------------------- 1. litellm-only
print("\n[1] Topologie litellm-only")
cap_l = {"instance": {"version": "10.4.2", "edition": "oss"},
         "datasources": {"prometheus": [{"uid": "p1"}], "loki": [], "tempo": [], "other": []},
         "signals": {"p1": {"litellm": {
             "metric_names": ["litellm_spend_metric_total",
                              "litellm_proxy_total_requests_metric_total",
                              "litellm_proxy_failed_requests_metric_total",
                              "litellm_request_total_latency_metric_bucket",
                              "litellm_input_tokens_metric_total",
                              "litellm_output_tokens_metric_total",
                              "litellm_remaining_requests_metric"],
             "model_label": "model", "models_seen": ["gpt-4.1", "mistral-small-3.2"],
             "provider_label": "api_provider",
             "group_labels": [{"label": "team", "cardinality": 4}]}}},
         "gaps": []}
r, d = run_forge(cap_l, "audit_litellm")
check("forge exit 0", r.returncode == 0, r.stderr[-300:])
bs = load_boards(d)
check("blueprints attendus", set(bs) == {"finops", "gateway", "adoption", "governance"},
      str(set(bs)))
check("agents/inference skippés proprement",
      "agents : signaux requis" in r.stdout and "inference : signaux requis" in r.stdout)
sp = [e for t, e in all_exprs(bs["finops"]) if "Dépense (période" in t or "période" in t]
check("spend = litellm natif (pas de composition registre)",
      sp and "litellm_spend_metric_total" in sp[0] and "2.5e" not in sp[0], str(sp[:1]))
bad = [(t, e, w) for b in bs.values() for t, e in all_exprs(b) if (w := promql_sane(e))]
check("PromQL sain (aucune expr)", not bad, str(bad[:2]))
al = [f for f in os.listdir(d) if f.startswith("alert_")]
check("alertes exportées (litellm: erreurs+signal+budget)", len(al) == 3, str(al))
man = json.load(open(f"{d}/deploy_manifest.json"))
check("manifeste cohérent", len(man["dashboards"]) == 4 and man["deployed"] is False)

# ---------------------------------------------------------------- 2. vllm+gpu-only
print("\n[2] Topologie vllm+GPU (self-hosted pur)")
cap_v = {"instance": {"version": "12.1.0", "edition": "enterprise"},
         "datasources": {"prometheus": [{"uid": "p1"}], "loki": [{"uid": "l1", "labels": ["job"]}],
                         "tempo": [], "other": []},
         "signals": {"p1": {
             "vllm": {"metric_names": ["vllm:time_to_first_token_seconds_bucket",
                                       "vllm:e2e_request_latency_seconds_bucket",
                                       "vllm:e2e_request_latency_seconds_count",
                                       "vllm:num_requests_waiting", "vllm:num_requests_running",
                                       "vllm:gpu_cache_usage_perc",
                                       "vllm:generation_tokens_total",
                                       "vllm:prompt_tokens_total"],
                      "model_label": "model_name", "models_seen": ["Qwen/Qwen3.6-32B"]},
             "gpu_dcgm": {"metric_names": ["DCGM_FI_DEV_GPU_UTIL", "DCGM_FI_DEV_FB_USED"]}}},
         "gaps": []}
r, d = run_forge(cap_v, "audit_vllm")
bs = load_boards(d)
check("forge exit 0", r.returncode == 0, r.stderr[-300:])
check("inference + governance seulement", set(bs) == {"inference", "governance"}, str(set(bs)))
check("governance dégradée mais debout (timeline+loki+alertlist)",
      len(bs["governance"]["panels"]) >= 3)
check("alerte KV cache présente",
      any("vllm-kv" in f for f in os.listdir(d) if f.startswith("alert_")))
bad = [(t, w) for b in bs.values() for t, e in all_exprs(b) if (w := promql_sane(e))]
check("PromQL sain", not bad, str(bad[:2]))

# ---------------------------------------------------------------- 3. dégradé total
print("\n[3] Topologie dégradée (Loki seul, zéro signal LLM)")
cap_0 = {"instance": {"version": "11.0.0", "edition": "oss"},
         "datasources": {"prometheus": [{"uid": "p1"}],
                         "loki": [{"uid": "l1", "labels": ["service_name"]}],
                         "tempo": [], "other": []},
         "signals": {}, "gaps": ["aucun signal LLM"]}
r, d = run_forge(cap_0, "audit_zero")
bs = load_boards(d)
check("forge exit 0 (pas de crash)", r.returncode == 0, r.stderr[-300:])
check("governance seule, ≥2 panels", set(bs) == {"governance"}
      and len(bs["governance"]["panels"]) >= 2, str(set(bs)))
check("aucune alerte générée (rien à surveiller)",
      not [f for f in os.listdir(d) if f.startswith("alert_")])

# --------------------------------------------------- 4. capability map minimaliste
print("\n[4] Capability map faite main (clés manquantes)")
r, d = run_forge({"signals": {}}, "audit_minimal")
check("tolérance clés absentes", r.returncode == 0, r.stderr[-300:])

# ---------------------------------------------------------------- 5. discover stub
print("\n[5] discover.build_capability_map (client simulé)")
import discover
class FakeDS(dict): pass
class FakeClient:
    base = "http://fake:3000"
    def version(self): return "13.0.0"
    def major_version(self): return 13
    def edition(self): return "oss"
    def namespace(self): return "default"
    def has_resource_api(self): return True
    def datasources(self): return [{"uid": "p1", "name": "Prom", "type": "prometheus", "isDefault": True},
                                   {"uid": "l1", "name": "Loki", "type": "loki"}]
    def prometheus_like(self): return [d for d in self.datasources() if d["type"] == "prometheus"]
    def prom_metric_names(self, ds, match):
        if match.startswith("gen_ai"):
            return ["gen_ai_client_operation_duration_seconds_bucket",
                    "gen_ai_client_token_usage_token_sum"]
        return []
    def prom_label_values(self, ds, label, match=None):
        return {"gen_ai_request_model": ["gpt-5.4"],
                "gen_ai_provider_name": ["openai"],
                "gen_ai_token_type": ["input", "output"],
                "service_name": ["app-a", "app-b"]}.get(label, [])
    def loki_labels(self, ds): return ["service_name", "level"]
cap = discover.build_capability_map(FakeClient())
sig = cap["signals"]["p1"]["otel_genai"]
check("dialecte otel détecté + modèle", sig["model_label"] == "gen_ai_request_model")
check("token_type_label sondé", sig.get("token_type_label") == "gen_ai_token_type")
check("gap Tempo signalé", any("Tempo" in g for g in cap["gaps"]))
check("labels Loki filtrés", "service_name" in cap["datasources"]["loki"][0]["labels"])

# ------------------------------------------------------------------ 6. invariants
print("\n[6] Invariants unitaires")
from grafana_client import det_uid
uids = [det_uid(s) for s in ("ai-executive-finops", "x" * 200, "Éé àç !!", "a")]
check("det_uid ≤40, format, déterminisme",
      all(len(u) <= 40 and re.fullmatch(r"[a-z0-9-]+", u) for u in uids)
      and det_uid("abc") == det_uid("abc"))
from forge_dashboards import match_models, load_registry
reg = load_registry(f"{SK}/references/model_registry.json")
m, u = match_models(["gpt-5.4", "gpt-5.4-mini", "claude-opus-4-8-20260115", "inconnu-x9"], reg)
pairs = {it["seen"]: it["reg"]["id"] for it in m}
check("matching exact vs variante", pairs.get("gpt-5.4") == "gpt-5.4"
      and pairs.get("gpt-5.4-mini") == "gpt-5.4-mini", str(pairs))
check("alias date-suffixée matchée", pairs.get("claude-opus-4-8-20260115") == "claude-opus-4.8", str(pairs))
check("inconnu → unmatched", u == ["inconnu-x9"])
rq = [(mm["id"], k) for mm in reg["models"] for k in ("id", "vendor", "region")
      if k not in mm or mm[k] in (None, "")]
check("registre : champs requis présents", not rq, str(rq[:3]))
check("registre : régions valides",
      all(mm["region"] in ("us", "eu", "asia") for mm in reg["models"]))

# ---------------------------------------------------------------- 7. visual_audit
print("\n[7] visual_audit plan (mode uids, sans réseau)")
r = subprocess.run([sys.executable, f"{SC}/visual_audit.py", "--uids",
                    "llmops-x-1,llmops-y-2", "--dashboards", "/nonexistent",
                    "--list-only"], capture_output=True, text=True)
check("uids mode OK", r.returncode == 0 and "llmops-x-1" in r.stdout, r.stderr[-200:])

# --------------------------------------------------------------------- 8. SKILL.md
print("\n[8] SKILL.md")
txt = open(f"{SK}/SKILL.md").read()
desc = re.search(r"description: (.+)", txt).group(1)
check(f"description {len(desc)} ≤ 1024", len(desc) <= 1024)
check("SKILL.md < 500 lignes", txt.count("\n") < 500, str(txt.count("\n")))
refs = re.findall(r"references/[a-z_]+\.(?:md|json)", txt)
missing = [f for f in set(refs) if not os.path.exists(f"{SK}/{f}")]
check("toutes les références citées existent", not missing, str(missing))

print("\n" + ("=" * 60))
print(f"RÉSULTAT : {'✅ AUDIT PROPRE' if not FAIL else '❌ ' + str(len(FAIL)) + ' échec(s)'}")
for f in FAIL:
    print("  •", f)
sys.exit(1 if FAIL else 0)
