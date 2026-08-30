"""Harnais d'audit grafana-llmops-forge — vérifie les chemins hors selftest."""
import json, os, re, subprocess, sys, shutil

import pathlib
SK = str(pathlib.Path(__file__).resolve().parent.parent)
SC = f"{SK}/scripts"
sys.path.insert(0, SC)
import forge_dashboards
import tempfile; os.chdir(tempfile.gettempdir())
FAIL = []

def check(name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(f"{name}: {detail}")

def run_forge(cap, outdir, bps="auto", extra=()):
    shutil.rmtree(f"/tmp/{outdir}", ignore_errors=True)   # pas de résidu inter-run
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
        if (f.endswith(".json") and not f.endswith(".portable.json")
                and not f.startswith(("alert_", "deploy_"))):
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
check("alertes litellm (burn×2 + signal + budget)", len(al) == 4, str(sorted(al)))
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
        if "gen_ai" in match and "evaluation" not in match:
            return ["gen_ai_client_operation_duration_seconds_bucket",
                    "gen_ai_client_token_usage_token_sum"]
        return []
    def prom_label_values(self, ds, label, match=None):
        return {"gen_ai_request_model": ["gpt-5.4"],
                "gen_ai_provider_name": ["openai"],
                "gen_ai_token_type": ["input", "output"],
                "service_name": ["app-a", "app-b"]}.get(label, [])
    def loki_labels(self, ds): return ["service_name", "level"]
    def has_exemplar_link(self, ds): return ds.get("uid") == "p1"
    def contact_points(self): return []
    def org_id(self): return 3
cap = discover.build_capability_map(FakeClient())
sig = cap["signals"]["p1"]["otel_genai"]
check("dialecte otel détecté + modèle", sig["model_label"] == "gen_ai_request_model")
check("token_type_label sondé", sig.get("token_type_label") == "gen_ai_token_type")
check("gap Tempo signalé", any("Tempo" in g for g in cap["gaps"]))
check("labels Loki filtrés", "service_name" in cap["datasources"]["loki"][0]["labels"])
check("exemplars détectés sur la datasource", cap["datasources"]["prometheus"][0]["exemplars"])
check("gap recording rules signalé", any("Recording rules" in g for g in cap["gaps"]))
cap2 = discover.build_capability_map(FakeClient(), ds_filter="inexistante")
check("filtre --datasource inconnu → gap explicite",
      any("--datasource" in g for g in cap2["gaps"]))

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
print("\n[16] Packaging du livrable")
_pkg = "/tmp/audit_pkg.skill"
r = subprocess.run([sys.executable, os.path.join(SK, "tools", "package.py"),
                    "--out", _pkg], capture_output=True, text=True)
check("le dépôt sait construire son propre .skill", r.returncode == 0, r.stderr[-160:])
r2 = subprocess.run([sys.executable, os.path.join(SK, "tools", "package.py"),
                     "--out", _pkg + "2"], capture_output=True, text=True)
import hashlib as _hl
_h = lambda p: _hl.sha256(open(p, "rb").read()).hexdigest()
check("build reproductible (deux builds, même sha256)",
      os.path.exists(_pkg) and os.path.exists(_pkg + "2") and _h(_pkg) == _h(_pkg + "2"))
r3 = subprocess.run([sys.executable, os.path.join(SK, "tools", "package.py"),
                     "--out", _pkg, "--verify"], capture_output=True, text=True)
check("archive identique aux sources du dépôt", r3.returncode == 0, r3.stdout[-200:])
import zipfile as _zf
_names = _zf.ZipFile(_pkg).namelist()
check("aucun bytecode embarqué",
      not [n for n in _names if "__pycache__" in n or n.endswith(".pyc")])
check("SKILL.md + 4 scripts + 7 références",
      len([n for n in _names if n.endswith(".py")]) == 4
      and len([n for n in _names if "/references/" in n]) == 7, str(len(_names)))
check("le paquet n'est pas versionné (artefact de build)",
      "dist/grafana-llmops-forge.skill" not in subprocess.run(
          ["git", "ls-files"], cwd=SK, capture_output=True, text=True).stdout)

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

# ------------------------------------------------- 9. correctifs v1.2 (régressions)
print("\n[9] Correctifs v1.2")
import subprocess as sp, glob as gl
r, d = run_forge(json.load(open(f"{SK}/scripts/_st.json")) if os.path.exists(f"{SK}/scripts/_st.json") else forge_dashboards.selftest_capability(), "audit_v12", extra=("--export-portable",))
check("forge selftest-like exit 0", r.returncode == 0, r.stderr[-200:])
bs = load_boards(d)
check("7 blueprints dont quality", "quality" in bs and len(bs) == 7, str(sorted(bs)))
al = {f: json.load(open(os.path.join(d, f))) for f in os.listdir(d) if f.startswith("alert_")}
sl = [a for a in al.values() if "Signal perdu" in a["title"]]
check("signal-lost alerte sur NoData (bug v1.1)",
      sl and sl[0]["noDataState"] == "Alerting", str([a["noDataState"] for a in sl]))
burn = [a for a in al.values() if "Burn-rate" in a["title"]]
check("burn-rate 2 fenêtres (rapide+lent)", len(burn) == 2, str(len(burn)))
check("burn-rate sans $__rate_interval (invalide en alerting)",
      all("$__rate_interval" not in a["data"][0]["model"]["expr"] for a in al.values()))
check("toute alerte à base de rate() porte une fenêtre explicite",
      all("[" in a["data"][0]["model"]["expr"]
          for a in al.values() if "rate(" in a["data"][0]["model"]["expr"]))
rules = os.path.join(d, "prometheus_rules_llmops.yml")
check("recording rules émises", os.path.exists(rules))
if os.path.exists(rules):
    txt = open(rules).read()
    check("prix + coût par vector matching",
          "llm:price_input_usd_per_token" in txt and "group_left" in txt)
port = gl.glob(os.path.join(d, "*.portable.json"))
check("export portable avec __inputs", bool(port) and
      all(json.load(open(p)).get("__inputs") for p in port), str(len(port)))
gov = bs.get("governance", {})
lk = [p for p in gov.get("panels", []) if "journalisation" in p.get("title", "")]
check("panel Loki typé loki (bug v1.1)",
      not lk or lk[0]["datasource"]["type"] == "loki",
      str(lk[0]["datasource"] if lk else ""))
gw = bs.get("gateway", {})
ex = [t for p in gw.get("panels", []) for t in p.get("targets", []) if t.get("exemplar")]
check("exemplars posés quand la datasource les route", bool(ex))
# mode recorded : requêtes O(1)
r2, d2 = run_forge(json.load(open(f"/tmp/audit_v12.json")), "audit_rec",
                   extra=("--cost-mode", "recorded"))
fin = load_boards(d2).get("finops", {})
ex2 = [t["expr"] for p in fin.get("panels", []) for t in p.get("targets", [])
       if "cost_usd" in t.get("expr", "")]
check("mode recorded → llm:cost_usd_per_second", bool(ex2), "aucune expr recorded")
check("recorded = expressions courtes", all(len(e) < 200 for e in ex2),
      str(max((len(e) for e in ex2), default=0)))

# ------------------------------------------------ 10. bornage cardinalité
print("\n[10] Cardinalité & coût de requête")
cap_hi = json.loads(json.dumps(forge_dashboards.selftest_capability()))
prom = list(cap_hi["signals"])[0]
cap_hi["signals"][prom]["otel_genai"]["group_labels"] = [
    {"label": "end_user_id", "cardinality": 4200}]
r, d = run_forge(cap_hi, "audit_card")
check("forge exit 0 sur cardinalité extrême", r.returncode == 0, r.stderr[-200:])
bs = load_boards(d)
exprs = [e for b in bs.values() for _, e in all_exprs(b)]
check("aucun group-by sur un label à 4200 valeurs",
      not any("end_user_id" in e for e in exprs))
r, d = run_forge(forge_dashboards.selftest_capability(), "audit_topk")
bs = load_boards(d)
grouped = [(p["title"], tg["expr"]) for b in bs.values() for p in b["panels"]
           if p["type"] == "timeseries" for tg in p.get("targets", [])
           if re.search(r"sum by\((service_name|team|gen_ai_agent_name|"
                        r"gen_ai_tool_name)\)", tg.get("expr", ""))]
check("panels groupés bornés par topk", grouped and
      all(e.startswith("topk(") for _, e in grouped),
      str([t for t, e in grouped if not e.startswith("topk(")]))
mdp = [p.get("maxDataPoints") for b in bs.values() for p in b["panels"]
       if p["type"] == "timeseries"]
check("maxDataPoints posé sur toutes les séries temporelles",
      mdp and all(v == 500 for v in mdp), str(set(mdp)))

# --------------------------------------------- 11. échappement regex PromQL/RE2
print("\n[11] Echappement regex PromQL (bug trouve par le controle live)")
from forge_dashboards import _rx
BS = chr(92)
r = _rx("mistral-small-3.2")
check("tiret NON echappe (RE2 rejette le backslash-tiret)", BS + "-" not in r, r)
check("point echappe en double (la chaine PromQL consomme un niveau)",
      r == "mistral-small-3" + BS * 2 + ".2", r)
check("metacaracteres RE2 couverts",
      _rx("a+b(c)") == "a" + BS*2 + "+b" + BS*2 + "(c" + BS*2 + ")", _rx("a+b(c)"))
r2, d2 = run_forge(forge_dashboards.selftest_capability(), "audit_re2")
rx_exprs = [e for _, e in all_exprs(load_boards(d2)["governance"]) if "=~" in e]
check("aucune sequence backslash-tiret dans les regex generees",
      not any(BS + "-" in e for e in rx_exprs), str(rx_exprs[:1]))

# ------------------------------------------- 12. cohérence doc / réalité
# ------------------------- 13. variantes de chemin d'export (exporters Prometheus)
print("\n[13] Variantes d'export (namespace, UTF-8)")
import copy as _copy
from forge_dashboards import msel, qlbl
_base = forge_dashboards.selftest_capability()
_prom = list(_base["signals"])[0]

def _variant(transform, label_transform=lambda x: x):
    c = _copy.deepcopy(_base)
    sig = c["signals"][_prom]
    for d in list(sig):
        if d != "otel_genai":
            del sig[d]
    e = sig["otel_genai"]
    e["metric_names"] = [transform(n) for n in e["metric_names"]]
    e["model_label"] = label_transform(e["model_label"])
    e["token_type_label"] = label_transform(e["token_type_label"])
    return c

# namespace ajouté par l'exporter (les regex Prometheus sont ancrées)
r, d = run_forge(_variant(lambda n: "myapp_" + n), "audit_prefix")
check("préfixe namespace : dashboards générés", r.returncode == 0 and load_boards(d),
      r.stderr[-160:])
_ex = [e for b in load_boards(d).values() for _, e in all_exprs(b)]
check("préfixe conservé dans les requêtes",
      any("myapp_gen_ai" in e for e in _ex))

# translation_strategy: NoTranslation -> noms et labels UTF-8 pointés
_dot = lambda n: n.replace("gen_ai_client_", "gen_ai.client.").replace(
    "gen_ai_server_", "gen_ai.server.")
r, d = run_forge(_variant(_dot, lambda l: l.replace("gen_ai_", "gen_ai.").replace("_", ".")
                          if l.startswith("gen_ai_") else l), "audit_utf8")
check("noms UTF-8 : dashboards générés", r.returncode == 0 and load_boards(d),
      r.stderr[-160:])
_ex = [e for b in load_boards(d).values() for _, e in all_exprs(b)]
_dotted = [e for e in _ex if "gen_ai.client" in e]
check("nom pointé toujours entre guillemets (nom nu = 400)",
      _dotted and all('{"gen_ai.client' in e for e in _dotted),
      str([e[:70] for e in _dotted if '{"gen_ai.client' not in e][:1]))
check("label pointé quoté dans by()/matchers",
      not any(re.search(r"by\(gen_ai\.[a-z.]+\)", e) or re.search(r"\{gen_ai\.[a-z.]+=", e)
              for e in _ex))
check("helpers msel/qlbl corrects",
      msel("a.b", '{x="1"}') == '{"a.b",x="1"}' and msel("a_b", '{x="1"}') == 'a_b{x="1"}'
      and qlbl("a.b") == '"a.b"' and qlbl("a_b") == "a_b")

# ----------------------------- 14. recording rules : ordre d'évaluation
print("\n[14] Recording rules")
import yaml as _yaml
r, d = run_forge(forge_dashboards.selftest_capability(), "audit_rules")
_rp = os.path.join(d, "prometheus_rules_llmops.yml")
check("fichier de règles émis", os.path.exists(_rp))
if os.path.exists(_rp):
    _g = _yaml.safe_load(open(_rp))["groups"]
    check("un seul groupe (les groupes séparés s'évaluent en parallèle)",
          len(_g) == 1, str([x["name"] for x in _g]))
    _r = _g[0]["rules"]
    _prices = [i for i, x in enumerate(_r) if "price" in x["record"]]
    _costs = [i for i, x in enumerate(_r) if x["record"].startswith("llm:cost")]
    check("tous les prix déclarés AVANT toute règle de coût qui les joint",
          _prices and _costs and max(_prices) < min(_costs),
          f"dernier prix #{max(_prices) if _prices else '-'} / "
          f"premier coût #{min(_costs) if _costs else '-'}")
    _recs = [x["record"] for x in _r]
    check("coût décomposé en input / output / total",
          _recs[-3:] == ["llm:cost_usd_per_second:input",
                         "llm:cost_usd_per_second:output",
                         "llm:cost_usd_per_second"], str(_recs[-3:]))
    check("input et output joignent les prix par vector matching",
          all("group_left" in x["expr"] and "on(" in x["expr"] for x in _r[-3:-1]))
    check("le total additionne les deux composantes (jamais un `or` seul, "
          "qui absorberait le coût de sortie)",
          "+" in _r[-1]["expr"] and _r[-1]["expr"].count("or") == 2,
          _r[-1]["expr"][:90])
    check("chaque prix porte modèle + région + vendor",
          all({"region", "vendor"} <= set(_r[i].get("labels", {})) for i in _prices))

# --------------------------- 15. entrées hostiles (labels applicatifs)
print("\n[15] Entrees hostiles")
import yaml as _y2
_cap = forge_dashboards.selftest_capability()
_pk = list(_cap["signals"])[0]
_cap["signals"][_pk]["otel_genai"]["models_seen"] = [
    'gpt-5.4"} or vector(99) #', "a" + chr(92) + "b", 'mod"el', "a{b}c",
    "unicode-e", "x" * 180, "a|b.*c", "pipe|in|md", "gpt-5.4", "line\nbreak"]
r, d = run_forge(_cap, "audit_hostile")
check("noms de modeles hostiles : generation sans crash", r.returncode == 0,
      r.stderr[-160:])

def _balanced(e):
    """Equilibre parentheses/accolades EN IGNORANT le contenu des chaines."""
    depth = {"(": 0, "{": 0}
    inq = False
    i = 0
    while i < len(e):
        c = e[i]
        if inq:
            if c == chr(92):
                i += 2
                continue
            if c == '"':
                inq = False
        elif c == '"':
            inq = True
        elif c in "({":
            depth[c] += 1
        elif c == ")":
            depth["("] -= 1
        elif c == "}":
            depth["{"] -= 1
        i += 1
    return not inq and depth["("] == 0 and depth["{"] == 0

_ex = [e for b in load_boards(d).values() for _, e in all_exprs(b)]
check("expressions equilibrees hors chaines (pas d'evasion de selecteur)",
      all(_balanced(e) for e in _ex),
      str([e[:70] for e in _ex if not _balanced(e)][:1]))
check("aucun saut de ligne injecte", not any(chr(10) in e for e in _ex))
_rp = os.path.join(d, "prometheus_rules_llmops.yml")
_ok = True
if os.path.exists(_rp):
    try:
        _ok = _y2.safe_load(open(_rp)) is not None
    except Exception:
        _ok = False
check("recording rules restent du YAML valide", _ok)
_gov = load_boards(d).get("governance", {})
_md = [p["options"]["content"] for p in _gov.get("panels", []) if p["type"] == "text"]
check("pipe neutralise dans les tableaux markdown",
      all("pipe|in|md" not in m for m in _md))

# ------------------------------------------------- 17. couverture du .gitignore
print("\n[17] Couverture du .gitignore")
def _ignored(p):
    return subprocess.run(["git", "check-ignore", "-q", p], cwd=SK).returncode == 0
_outputs = ["capability_map.json", "demo/capability_map.json",
            "generated_dashboards/finops.json", "demo/generated/finops.json",
            "demo/generated/prometheus_rules_llmops.yml",
            "demo/rules/prometheus_rules_llmops.yml", "demo/shots/d/full.png",
            "selftest_output/f.json", "scripts/selftest_output/f.json",
            "visual_audit/audit_manifest.json", "dist/x.skill",
            "model_registry.local.json", "scripts/__pycache__/x.pyc"]
_missed = [p for p in _outputs if not _ignored(p)]
check("toute sortie d'outil est ignoree", not _missed, str(_missed))
_secrets = [".env", ".env.local", ".env.production", "secrets.env", "demo/.env"]
_leaky = [p for p in _secrets if not _ignored(p)]
check("toutes les variantes de fichier de secrets sont ignorees", not _leaky, str(_leaky))
_keep = ["SKILL.md", "scripts/forge_dashboards.py", "tools/package.py",
         "demo/emitter.py", "demo/docker-compose.yml", "demo/rules/.gitkeep",
         "tests/audit_harness.py", "Makefile"]
_lost = [p for p in _keep if _ignored(p)]
check("aucun fichier du projet ignore a tort", not _lost, str(_lost))
check("aucun fichier suivi n'est masque par un motif",
      not subprocess.run(["git", "ls-files", "-i", "-c", "--exclude-standard"],
                         cwd=SK, capture_output=True, text=True).stdout.strip())
_gi = open(os.path.join(SK, ".gitignore")).read().splitlines()
_inline = [l for l in _gi if re.search(r"\S\s+#", l) and not l.lstrip().startswith("#")]
check("aucun commentaire en fin de ligne (git ne les interprete pas)",
      not _inline, str(_inline[:1]))

# ------------------------------- 18. chaine d'approvisionnement CI
print("\n[18] Durcissement des workflows")
import yaml as _y3
_wf = sorted(pathlib.Path(os.path.join(SK, ".github", "workflows")).glob("*.yml"))
check("des workflows sont presents", len(_wf) >= 3, str(len(_wf)))
_txt = {f.name: f.read_text() for f in _wf}
_uses = [(n, u) for n, s in _txt.items()
         for u in re.findall(r"uses:\s*(\S+)", s)]
_unpinned = [(n, u) for n, u in _uses if not re.search(r"@[0-9a-f]{40}$", u)]
check("toute action est epinglee a un SHA de commit (tag mutable = reprise possible)",
      not _unpinned, str(_unpinned[:2]))
_docs = {n: _y3.safe_load(s) for n, s in _txt.items()}
check("jeton en lecture seule par defaut (permissions: {} au niveau workflow)",
      all(d.get("permissions") == {} for d in _docs.values()),
      str({n: d.get("permissions") for n, d in _docs.items()}))
check("chaque job declare ses permissions",
      all(j.get("permissions") is not None
          for d in _docs.values() for j in d["jobs"].values()))
check("aucun declencheur pull_request_target",
      not any("pull_request_target" in s for s in _txt.values()))
check("checkout sans credentials persistants",
      all("persist-credentials: false" in s
          for n, s in _txt.items() if "actions/checkout" in s))
_runs = [(n, r) for n, d in _docs.items() for j in d["jobs"].values()
         for st in j["steps"] for r in [st.get("run", "")] if r]
_inj = [(n, r[:60]) for n, r in _runs if re.search(r"\$\{\{\s*(github|inputs|steps)\.", r)]
check("aucune interpolation d'expression dans un bloc run (injection de script)",
      not _inj, str(_inj[:1]))
check("dependabot suit les actions epinglees",
      os.path.exists(os.path.join(SK, ".github", "dependabot.yml")))
check("CODEOWNERS present (revue obligatoire des chemins sensibles)",
      os.path.exists(os.path.join(SK, ".github", "CODEOWNERS")))

# --------------------------------- 19. aucun secret en dur dans l'arbre
print("\n[19] Fuite de secrets")
_SECRET_RX = "|".join([
    r"glsa_[A-Za-z0-9]{10}", r"gh[pousr]_[A-Za-z0-9]{20}",
    r"sk-ant-[A-Za-z0-9_-]{20}", r"sk-[A-Za-z0-9]{32}",
    r"AKIA[0-9A-Z]{16}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}",
    r"xox[baprs]-[A-Za-z0-9-]{10}",
])
_leak = subprocess.run(["grep", "-rIlE", _SECRET_RX, "--exclude-dir=.git",
                        "--exclude-dir=dist", "--exclude-dir=__pycache__", "."],
                       cwd=SK, capture_output=True, text=True).stdout.strip()
check("aucun jeton, cle API, cle privee ou JWT en dur", not _leak, _leak[:140])
_env_reads = subprocess.run(
    ["grep", "-rInE", r"os\.environ|os\.getenv", "--include=*.py", "scripts", "tools"],
    cwd=SK, capture_output=True, text=True).stdout
check("les identifiants ne viennent que de l'environnement",
      "GRAFANA_TOKEN" in _env_reads and "GRAFANA_URL" in _env_reads)
_logged = subprocess.run(
    ["grep", "-rnE", r"print\(.*(token|TOKEN|password|PASSWORD)", "--include=*.py",
     "scripts", "tools"], cwd=SK, capture_output=True, text=True).stdout.strip()
check("aucun identifiant imprime sur la sortie", not _logged, _logged[:120])

print("\n[12] Coherence documentation")
_readme = open(os.path.join(SK, "README.md")).read()
_ci = open(os.path.join(SK, ".github", "workflows", "ci.yml")).read()
check("badge CI dynamique (pas un compteur fige)",
      "img.shields.io/github/actions/workflow/status" in _readme
      and "img.shields.io/badge/CI-" not in _readme, "badge statique residuel")
check("aucun compte de tests fige dans README/CI",
      not re.search(r"\\d+ checks", _readme + _ci),
      str(re.findall(r"[^ ]* \\d+ checks", _readme + _ci)[:2]))
_fd = open(os.path.join(SK, "scripts", "forge_dashboards.py")).read()
_bp = len(re.findall(r"^def bp_", _fd, re.M))
_rows = sum(_readme.count(f"| {e}") for e in "💰🛡🤖📈⚡✅⚖")
check(f"blueprints code ({_bp}) = lignes tableau README ({_rows})", _bp == _rows == 7)
check("references citees par README existent toutes",
      all(os.path.exists(os.path.join(SK, p))
          for p in re.findall(r"\\(((?:references|docs|scripts|tests|demo)/[\\w./-]+)\\)", _readme)),
      str([p for p in re.findall(r"\\(((?:references|docs|scripts|tests|demo)/[\\w./-]+)\\)", _readme)
           if not os.path.exists(os.path.join(SK, p))]))

print("\n" + ("=" * 60))
print(f"RÉSULTAT : {'✅ AUDIT PROPRE' if not FAIL else '❌ ' + str(len(FAIL)) + ' échec(s)'}")
for f in FAIL:
    print("  •", f)
sys.exit(1 if FAIL else 0)
