"""Harnais d'audit grafana-llmops-forge : vérifie les chemins hors selftest."""
import json, os, re, subprocess, sys, shutil
import pathlib
import builtins

_builtin_open = builtins.open
def open(file, mode="r", *args, **kwargs):
    """Le dépôt est UTF-8 ; ne pas dépendre de la code page Windows active."""
    if "b" not in mode:
        kwargs.setdefault("encoding", "utf-8")
    return _builtin_open(file, mode, *args, **kwargs)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="backslashreplace")

try:
    import yaml
except ImportError:       # le PRODUIT reste sans dependance ; ce harnais, non.
    sys.exit("Ce harnais requiert pyyaml (il valide les YAML d'infrastructure).\n"
             "  pip install pyyaml\n"
             "Les scripts livres dans scripts/ n'utilisent que la stdlib : "
             "c'est la promesse qui compte, et tests/audit_harness.py la verifie.")

SK = str(pathlib.Path(__file__).resolve().parent.parent)
SC = f"{SK}/scripts"
sys.path.insert(0, SC)
import forge_dashboards
import tempfile
TMP = tempfile.gettempdir()
os.chdir(TMP)
FAIL = []

def check(name, cond, detail=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name
          + (f" : {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(f"{name}: {detail}")

def run_forge(cap, outdir, bps="auto", extra=()):
    outpath = os.path.join(TMP, outdir)
    shutil.rmtree(outpath, ignore_errors=True)   # pas de résidu inter-run
    cpath = os.path.join(TMP, outdir + ".json")
    json.dump(cap, open(cpath, "w"))
    r = subprocess.run([sys.executable, f"{SC}/forge_dashboards.py",
                        "--capability", cpath, "--blueprints", bps,
                        "--out-dir", outpath, "--with-alerts", "--org-id", "1",
                        *extra], capture_output=True, text=True)
    return r, outpath

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
      "agents: required signals" in r.stdout and "inference: required signals" in r.stdout,
      r.stdout[-160:])
sp = [e for t, e in all_exprs(bs["finops"]) if "Spend (selected range)" in t]
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
    def resolve_org(self, requested=None):
        if requested is not None and int(requested) != 3:
            raise discover.GrafanaError(409, "organization mismatch")
        return 3
cap = discover.build_capability_map(FakeClient())
sig = cap["signals"]["p1"]["otel_genai"]
check("dialecte otel détecté + modèle", sig["model_label"] == "gen_ai_request_model")
check("token_type_label sondé", sig.get("token_type_label") == "gen_ai_token_type")
check("gap Tempo signalé", any("Tempo" in g for g in cap["gaps"]))
check("labels Loki filtrés", "service_name" in cap["datasources"]["loki"][0]["labels"])
check("exemplars détectés sur la datasource", cap["datasources"]["prometheus"][0]["exemplars"])
check("gap recording rules signalé", any("Recording rules" in g for g in cap["gaps"]))
try:
    discover.build_capability_map(FakeClient(), ds_filter="inexistante")
    _unknown_ds_failed = False
except discover.GrafanaError as _e:
    _unknown_ds_failed = _e.status == 404 and "--datasource" in str(_e)
check("filtre --datasource inconnu => erreur explicite", _unknown_ds_failed)

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
_registry_snapshot = json.loads(json.dumps(reg))
pricing_sources = __import__("pricing_sources")
pricing_sources.validate_registry(reg)
check("validation registre ne mute pas la source", reg == _registry_snapshot)
_invalid_registry_cases = {}
for _name, _field, _value in (
        ("string", "input_per_mtok", "1.0"),
        ("bool", "input_per_mtok", True),
        ("negative", "input_per_mtok", -1),
        ("nan", "input_per_mtok", float("nan")),
        ("infinity", "input_per_mtok", float("inf")),
        ("huge", "input_per_mtok", 10 ** 400),
        ("over-limit", "input_per_mtok", pricing_sources.MAX_PRICE_PER_MTOK + 1),
        ("date", "pricing_verified_at", "not-a-date"),
        ("http-url", "pricing_source_url", "http://provider.example/pricing")):
    _case = _copy.deepcopy(reg) if "_copy" in globals() else json.loads(json.dumps(reg))
    _case["models"][0][_field] = _value
    _invalid_registry_cases[_name] = _case
_missing_provenance = json.loads(json.dumps(reg))
_missing_provenance["models"][0].pop("pricing_source_kind")
_invalid_registry_cases["missing-provenance"] = _missing_provenance
_collision = json.loads(json.dumps(reg))
_collision["models"][1]["aliases"].append(_collision["models"][0]["id"])
_invalid_registry_cases["normalized-collision"] = _collision
_registry_matrix_ok = True
for _name, _case in _invalid_registry_cases.items():
    try:
        pricing_sources.validate_registry(_case)
        _registry_matrix_ok = False
    except pricing_sources.RegistryValidationError:
        pass
check("registre refuse string/bool/negatif/NaN/inf/provenance/HTTP/collision",
      _registry_matrix_ok)
_tie = {"models": [
    {"id": "foo-model-a", "aliases": [], "input_per_mtok": 1},
    {"id": "foo-model-b", "aliases": [], "input_per_mtok": 2}]}
_tie_match, _tie_unmatched = match_models(["foo-model"], _tie)
check("forge et fallback refusent la meme egalite de meilleur score",
      not _tie_match and _tie_unmatched == ["foo-model"]
      and pricing_sources.resolve_registry_model(
          "foo-model", _tie["models"])[2] == "ambiguous")

# ---------------------------------------------------------------- 7. visual_audit
print("\n[16] Packaging du livrable")
_pkg = os.path.join(TMP, "audit_pkg.skill")
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
_scripts = sorted(f for f in os.listdir(SC) if f.endswith(".py"))
_packaged_scripts = sorted(os.path.basename(n) for n in _names
                           if "/scripts/" in n and n.endswith(".py"))
check("SKILL.md + tous les scripts + les references embarquees",
      _packaged_scripts == _scripts
      and len([n for n in _names if "/references/" in n]) >= 7,
      str({"scripts": _packaged_scripts, "entries": len(_names)}))
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
check(f"description {len(desc)} <= 1024", len(desc) <= 1024)
_fm_ok, _fm = True, {}
try:
    _fm = yaml.safe_load(txt.split("---")[1])
    _fm_ok = isinstance(_fm, dict) and {"name", "description"} <= set(_fm)
except Exception as _e:
    _fm_ok, _fm = False, {"err": str(_e)[:90]}
check("frontmatter SKILL.md parse en YAML (sinon le skill ne charge pas)",
      _fm_ok, str(_fm)[:110])
if _fm_ok:
    check("description YAML-safe (pas de ': ' non quote)",
          ": " not in _fm["description"],
          _fm["description"][max(0, _fm["description"].find(": ") - 30):][:60])
    _d = _fm["description"]
    check("le declencheur couvre les trois referentiels de gouvernance",
          all(k in _d for k in ("AI Act", "42001", "NIST")),
          [k for k in ("AI Act", "42001", "NIST") if k not in _d])
    check("le declencheur mentionne les langues",
          "French" in _d or "English" in _d)
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
sl = [a for a in al.values() if "signal-lost" in a["uid"]]
check("signal-lost alerte sur NoData (bug v1.1)",
      sl and sl[0]["noDataState"] == "Alerting", str([a["noDataState"] for a in sl]))
burn = [a for a in al.values() if "burn-" in a["uid"]]
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
r2, d2 = run_forge(json.load(open(os.path.join(TMP, "audit_v12.json"))), "audit_rec",
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
_hostile = '"}[$__rate_interval])) or vector(999) #\\line\nnext'

def _outside_promql_strings(expr):
    outside, quoted, escaped = [], False, False
    for _char in expr:
        if quoted:
            if escaped:
                escaped = False
            elif _char == "\\":
                escaped = True
            elif _char == '"':
                quoted = False
        elif _char == '"':
            quoted = True
        else:
            outside.append(_char)
    return "".join(outside)

_hostile_helpers = (msel(_hostile), qlbl(_hostile))
check("msel/qlbl confinent guillemet, backslash et controles",
      all(_hostile not in value and "\n" not in value
          and "or vector(999)" not in _outside_promql_strings(value)
          for value in _hostile_helpers), str(_hostile_helpers))
_hostile_cap = _variant(lambda n: n, lambda n: _hostile)
_hostile_signal = _hostile_cap["signals"][_prom]["otel_genai"]
_hostile_signal["metric_names"] = [
    n[:-len(_suffix)] + _hostile + _suffix
    for n in _hostile_signal["metric_names"]
    for _suffix in ("_bucket", "_sum", "_count") if n.endswith(_suffix)]
_hostile_signal["models_seen"] = [_hostile]
_hostile_registry = {"_meta": {"verified_at": "2026-09-01"}, "models": [{
    "id": _hostile, "aliases": [], "vendor": "Acme", "region": "us",
    "input_per_mtok": 1.0, "output_per_mtok": 2.0,
    "pricing_source_kind": "official",
    "pricing_source_url": "https://provider.example/pricing",
    "pricing_verified_at": "2026-09-01"}]}
_hostile_rules_path = os.path.join(TMP, "hostile-promql.yml")
forge_dashboards.emit_recording_rules(
    forge_dashboards.Ctx(_hostile_cap, _hostile_registry), _hostile_rules_path)
_hostile_rules = yaml.safe_load(open(_hostile_rules_path))["groups"][0]["rules"]
_hostile_exprs = [str(rule["expr"]) for rule in _hostile_rules]
check("YAML hostile parse et ne contient aucune injection PromQL",
      _hostile_exprs and all(
          _hostile not in expr
          and "or vector(999)" not in _outside_promql_strings(expr)
          for expr in _hostile_exprs), str(_hostile_exprs[:1]))

def _litellm_security_exprs(spend, remaining, provider):
    cap = _copy.deepcopy(cap_l)
    entry = cap["signals"]["p1"]["litellm"]
    entry["metric_names"] = [spend, remaining]
    entry["provider_label"] = provider
    ctx = forge_dashboards.Ctx(cap, reg)
    q = ctx.q["litellm"]
    gateway = forge_dashboards.bp_gateway(ctx).d
    return [forge_dashboards.cost_rate_expr(q, ctx.matched),
            *(expr for _, expr in all_exprs(gateway))]

_lite_attack = '"}[$__rate_interval])) or vector(999) #\n'
_lite_hostile_exprs = _litellm_security_exprs(
    "litellm_spend" + _lite_attack,
    "litellm_remaining_requests" + _lite_attack,
    "api_provider" + _lite_attack)
check("metriques et label LiteLLM hostiles restent dans leurs litteraux",
      all(_lite_attack not in expr and "\n" not in expr
          and "or vector(999)" not in _outside_promql_strings(expr)
          for expr in _lite_hostile_exprs), str(_lite_hostile_exprs))
_lite_dotted_exprs = _litellm_security_exprs(
    "litellm.spend.metric.total", "litellm.remaining.requests.metric",
    "api.provider")
_lite_dotted = "\n".join(_lite_dotted_exprs)
check("noms pointes LiteLLM utilisent msel et qlbl",
      '{"litellm.spend.metric.total"}' in _lite_dotted
      and 'min by("api.provider")({"litellm.remaining.requests.metric"})'
          in _lite_dotted, _lite_dotted)

# ----------------------------- 14. recording rules : ordre d'évaluation
print("\n[14] Recording rules")
r, d = run_forge(forge_dashboards.selftest_capability(), "audit_rules")
_rp = os.path.join(d, "prometheus_rules_llmops.yml")
check("fichier de règles émis", os.path.exists(_rp))
if os.path.exists(_rp):
    _g = yaml.safe_load(open(_rp))["groups"]
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
        _ok = yaml.safe_load(open(_rp)) is not None
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
_wf = sorted(pathlib.Path(os.path.join(SK, ".github", "workflows")).glob("*.yml"))
check("des workflows sont presents", len(_wf) >= 3, str(len(_wf)))
_txt = {f.name: f.read_text() for f in _wf}
_uses = [(n, u) for n, s in _txt.items()
         for u in re.findall(r"uses:\s*(\S+)", s)]
_unpinned = [(n, u) for n, u in _uses
             if not u.startswith("./") and not re.search(r"@[0-9a-f]{40}$", u)]
check("toute action est epinglee a un SHA de commit (tag mutable = reprise possible)",
      not _unpinned, str(_unpinned[:2]))
_docs = {n: yaml.safe_load(s) for n, s in _txt.items()}
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
         for st in j.get("steps", []) for r in [st.get("run", "")] if r]
_inj = [(n, r[:60]) for n, r in _runs if re.search(r"\$\{\{\s*(github|inputs|steps)\.", r)]
check("aucune interpolation d'expression dans un bloc run (injection de script)",
      not _inj, str(_inj[:1]))
_ci_txt = _txt.get("ci.yml", "")
_release_txt = _txt.get("release.yml", "")
check("release appelle la CI reutilisable avant le job avec droits ecriture",
      "workflow_call:" in _ci_txt
      and "group: ci-${{ github.ref }}" in _ci_txt
      and "uses: ./.github/workflows/ci.yml" in _release_txt
      and _release_txt.index("needs: ci")
          < _release_txt.index("contents: write"))
_blind = re.findall(r"sleep (\d+)", _ci_txt)
check("aucune attente longue en dur dans la CI (attendre l'etat, pas une duree)",
      all(int(s) <= 30 for s in _blind), f"sleep {[s for s in _blind if int(s) > 30]}")
check("les invariants attendent la materialisation des regles",
      "--wait-for-rules" in _ci_txt)
_prod = " ".join(open(os.path.join(SC, f)).read()
                 for f in os.listdir(SC) if f.endswith(".py"))
_third = [m for m in ("yaml", "requests", "httpx", "pydantic", "jinja2", "click")
          if re.search(rf"^\s*(?:import {m}\b|from {m}\b)", _prod, re.M)]
check("le produit livre n'importe que la stdlib", not _third, str(_third))
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
def _scan_files(roots, pattern, suffix=None):
    rx, hits = re.compile(pattern), []
    excluded = {".git", "dist", "__pycache__"}
    for root in roots:
        for base, dirs, files in os.walk(os.path.join(SK, root)):
            dirs[:] = [d for d in dirs if d not in excluded]
            for name in files:
                if suffix and not name.endswith(suffix):
                    continue
                path = os.path.join(base, name)
                try:
                    text = open(path, encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                if rx.search(text):
                    hits.append(os.path.relpath(path, SK))
    return hits

_leak = _scan_files(["."], _SECRET_RX)
check("aucun jeton, cle API, cle privee ou JWT en dur", not _leak, str(_leak[:4]))
_env_reads = "\n".join(
    open(os.path.join(base, name), encoding="utf-8", errors="ignore").read()
    for root in ("scripts", "tools")
    for base, dirs, files in os.walk(os.path.join(SK, root))
    for name in files if name.endswith(".py"))
check("les identifiants ne viennent que de l'environnement",
      "GRAFANA_TOKEN" in _env_reads and "GRAFANA_URL" in _env_reads)
_logged = _scan_files(["scripts", "tools"],
                      r"print\(.*(?:token|TOKEN|password|PASSWORD)", ".py")
check("aucun identifiant imprime sur la sortie", not _logged, str(_logged[:4]))

# ------------------------------------ 20. langue de sortie (audience mondiale)
print("\n[20] Langue des artefacts generes")
r, d = run_forge(forge_dashboards.selftest_capability(), "audit_lang",
                 extra=("--with-alerts",))
_ACCENTS = re.compile(r"[\u00e0-\u00ff]")
_fr = []
for _f in os.listdir(d):
    if _f == "deploy_manifest.json":
        continue
    _blob = open(os.path.join(d, _f), encoding="utf-8").read()
    _fr += [(_f, m[:60]) for m in re.findall(r'"([^"]{4,160})"', _blob)
            if _ACCENTS.search(m)]
check("dashboards, alertes et regles generes en anglais par defaut",
      not _fr, str(_fr[:2]))
check("table de localisation fr disponible",
      os.path.exists(os.path.join(SK, "references", "locale.fr.json")))

# ------------------------------------------ 21. YAML d'infrastructure
print("\n[21] YAML d'infrastructure")
_yamls = [p for p in pathlib.Path(SK).rglob("*.y*ml") if ".git/" not in str(p)]
_bad = []
for _p in _yamls:
    try:
        yaml.safe_load(_p.read_text())
    except Exception as _e:
        _bad.append((_p.name, str(_e)[:60]))
check(f"{len(_yamls)} fichiers YAML parsent", not _bad, str(_bad[:2]))

_dc = yaml.safe_load(open(os.path.join(SK, "demo", "docker-compose.yml")))
check("pas de cle 'version' (obsolete en Compose v2)", "version" not in _dc)
_svc = _dc["services"]
check("toute image est epinglee (jamais :latest)",
      all(":" in s["image"] and not s["image"].endswith(":latest")
          for s in _svc.values()),
      str([s["image"] for s in _svc.values() if s["image"].endswith(":latest")]))
check("chaque service a un healthcheck (up --wait deterministe)",
      all("healthcheck" in s for s in _svc.values()),
      str([n for n, s in _svc.items() if "healthcheck" not in s]))
_ports = [p for s in _svc.values() for p in s.get("ports", [])]
check("aucun port expose hors loopback",
      all(str(p).startswith("127.0.0.1:") for p in _ports), str(_ports))
check("no-new-privileges sur chaque service",
      all("no-new-privileges:true" in s.get("security_opt", []) for s in _svc.values()))
_deps = [(n, k, v) for n, s in _svc.items()
         if isinstance(s.get("depends_on"), dict)
         for k, v in s["depends_on"].items()]
check("les dependances attendent la sante, pas le demarrage",
      _deps and all(v.get("condition") == "service_healthy" for _, _, v in _deps))
check("aucune cle deploy: (ignoree par Compose hors Swarm)",
      not any("deploy" in s for s in _svc.values()))
_named = {v.split(":")[0] for s in _svc.values() for v in s.get("volumes", [])
          if not v.startswith("./")}
check("volumes nommes declares au niveau racine",
      _named <= set(_dc.get("volumes") or {}), str(_named))

_pcfg = yaml.safe_load(open(os.path.join(SK, "demo", "prometheus.yml")))
_ds = yaml.safe_load(open(os.path.join(SK, "demo", "provisioning",
                                      "datasources", "prometheus.yml")))["datasources"][0]
check("timeInterval de la datasource == scrape_interval "
      "(sinon $__rate_interval fausse tous les panneaux)",
      _ds["jsonData"]["timeInterval"] == _pcfg["global"]["scrape_interval"],
      f'{_ds["jsonData"]["timeInterval"]} vs {_pcfg["global"]["scrape_interval"]}')
check("datasource provisionnee non editable", _ds.get("editable") is False)
check("requetes en POST (les expressions de cout sont longues)",
      _ds["jsonData"]["httpMethod"] == "POST")

# les regles generees : deux formats, contenu identique
r, d = run_forge(forge_dashboards.selftest_capability(), "audit_yaml")
_flat = os.path.join(d, "prometheus_rules_llmops.yml")
_crd = os.path.join(d, "prometheusrule_llmops.yaml")
check("format portable ET manifeste PrometheusRule emis",
      os.path.exists(_flat) and os.path.exists(_crd))
if os.path.exists(_crd):
    _c = yaml.safe_load(open(_crd))
    check("CRD conforme au Prometheus Operator",
          _c["apiVersion"] == "monitoring.coreos.com/v1"
          and _c["kind"] == "PrometheusRule" and _c["metadata"].get("labels"))
    check("les deux formats portent exactement les memes regles",
          yaml.safe_load(open(_flat))["groups"] == _c["spec"]["groups"])
    check("en-tete documentant les backends cibles",
          "Thanos" in open(_flat).read() and "Mimir" in open(_flat).read())

# --------------------------------------- 22. gouvernance multi-referentiels
print("\n[22] Referentiels de gouvernance")
_combos = ["eu-ai-act", "iso-42001", "nist-rmf", "iso-42001,nist-rmf",
           "eu-ai-act,iso-42001,nist-rmf"]
_uids, _ok = set(), True
for _c in _combos:
    r, d = run_forge(forge_dashboards.selftest_capability(),
                     "audit_fw_" + _c.replace(",", "_"), extra=("--framework", _c))
    if r.returncode != 0:
        _ok = False
        print("     ", _c, r.stderr[-120:])
        continue
    _g = load_boards(d).get("governance")
    _uids.add(_g["uid"])
    _txt = " ".join(p["options"]["content"] for p in _g["panels"]
                    if p["type"] == "text")
    for _f, _needle in (("eu-ai-act", "Art. 12"), ("iso-42001", "A.6.2.8"),
                        ("nist-rmf", "MANAGE 4.1")):
        _want = _f in _c
        if (_needle in _txt) is not _want:
            _ok = False
            print(f"      {_c}: {_needle} present={_needle in _txt} attendu={_want}")
check("chaque combinaison de --framework genere le bon contenu", _ok)
check("UID stable quel que soit le referentiel (mise a jour, pas duplication)",
      len(_uids) == 1, str(_uids))
r, d = run_forge(forge_dashboards.selftest_capability(), "audit_fw_bad",
                 extra=("--framework", "inexistant"))
check("referentiel inconnu : avertit et retombe sur l'AI Act",
      r.returncode == 0 and "unknown framework" in r.stderr
      and "Art. 12" in " ".join(p["options"]["content"]
                                for p in load_boards(d)["governance"]["panels"]
                                if p["type"] == "text"), r.stderr[-120:])
_ref = open(os.path.join(SK, "references", "ai_governance_frameworks.md")).read()
check("crosswalk documente et honnete sur ses limites",
      "not a legal opinion" in _ref and "Does not prove" in _ref
      and "Annex A numbering varies" in _ref)
_gov = load_boards(d)["governance"]
check("les panneaux mesures restent identiques quel que soit le cadre",
      sum(1 for p in _gov["panels"] if p["type"] != "text") >= 2)

# ------------------------------- 23. coherence visuels / code
print("\n[23] Visuels vs code")
_A = os.path.join(SK, "docs", "assets")
def _svg_text(name):
    return " ".join(re.findall(r">([^<>]{1,240})<",
                               open(os.path.join(_A, name), encoding="utf-8").read()))
_svgs = [f for f in os.listdir(_A) if f.endswith(".svg")]
check(f"{len(_svgs)} visuels vectoriels presents", len(_svgs) >= 4, str(_svgs))
# Les glyphes geometriques de base (fleches, coches) sont dans toutes les
# polices. Le risque est l'emoji couleur, qui exige une police dediee et
# tombe en tofu sans elle ; c'est ce que la revue visuelle avait attrape.
def _emoji(txt):
    return sorted({c for c in txt
                   if ord(c) >= 0x1F000 or 0x1F1E6 <= ord(c) <= 0x1F1FF
                   or ord(c) == 0xFE0F})
_tofu = {f: _emoji(open(os.path.join(_A, f), encoding="utf-8").read()) for f in _svgs}
_tofu = {k: v for k, v in _tofu.items() if v}
check("aucun emoji couleur dans les visuels (tofu selon la police)",
      not _tofu, str(_tofu))

_ban = _svg_text("banner.svg")
check(f"banner annonce {len(forge_dashboards.BLUEPRINTS)} dashboards",
      f"{len(forge_dashboards.BLUEPRINTS)} dashboards" in _ban,
      re.search(r"\d+ dashboards", _ban).group(0) if re.search(r"\d+ dashboards", _ban) else "?")
import discover as _disc
check(f"banner annonce {len(_disc.DIALECT_SIGNATURES)} dialectes",
      f"{len(_disc.DIALECT_SIGNATURES)} dialects" in _ban,
      re.search(r"\d+ dialects", _ban).group(0) if re.search(r"\d+ dialects", _ban) else "?")
check("banner ne promet pas un seul referentiel", "EU AI Act ready" not in _ban)

_arch = _svg_text("architecture.svg")
check(f"schema annonce {len(forge_dashboards.BLUEPRINTS)} blueprints",
      f"{len(forge_dashboards.BLUEPRINTS)} blueprints" in _arch)
_scripts = sorted(f for f in os.listdir(os.path.join(SK, "scripts")) if f.endswith(".py"))
check("schema cite chaque script du pipeline",
      all(s in _arch for s in _scripts),
      str([s for s in _scripts if s not in _arch]))

_cw = _svg_text("governance-crosswalk.svg")
_rows = [r[0] for r in forge_dashboards.CROSSWALK_ROWS]
_miss = [r for r in _rows if r.replace("&", "&amp;") not in _cw and r not in _cw]
check("crosswalk visuel == crosswalk du code",
      len(_miss) <= 1, str(_miss))
check("les trois referentiels nommes dans le visuel",
      all(f in _cw for f in ("EU AI Act", "ISO/IEC 42001", "NIST AI RMF")))
check("le visuel dit ce que le tableau ne prouve PAS",
      "Does not prove" in _cw)

r, d = run_forge(forge_dashboards.selftest_capability(), "audit_visual")
_fin = load_boards(d)["finops"]
_mock = _svg_text("dashboard-finops.svg")
check("le mockup porte le titre reellement genere",
      _fin["title"].replace("&", "&amp;") in _mock or _fin["title"] in _mock,
      _fin["title"])
_shown = [p["title"] for p in _fin["panels"][:4]]
_absent = [p for p in _shown if p not in _mock]
check("les panneaux du mockup existent vraiment", not _absent, str(_absent))
_fr = [w for w in ("Dépense", "Coût", "souveraineté", "requête", "Rythme")
       if w in _mock]
check("mockup en anglais, comme la sortie par defaut", not _fr, str(_fr))

# ------------------------------------ 24. coherence narrative
print("\n[24] Coherence de la documentation utilisateur")
_fr = open(os.path.join(SK, "docs", "README.fr.md")).read()
_hn = open(os.path.join(SK, "docs", "SHOW_HN_DRAFT.md")).read()
_pb = open(os.path.join(SK, "docs", "LAUNCH_PLAYBOOK.md")).read()
for _doc, _name in ((_fr, "README.fr"), (_hn, "Show HN")):
    check(f"{_name} couvre les trois referentiels",
          all(k in _doc for k in ("AI Act", "42001", "NIST")),
          str([k for k in ("AI Act", "42001", "NIST") if k not in _doc]))
    check(f"{_name} mentionne la langue de sortie",
          "locale" in _doc or "English" in _doc or "anglais" in _doc)
check("README.fr mentionne le format Kubernetes",
      "PrometheusRule" in _fr or "Kubernetes" in _fr)
check("README.fr donne le bon compte de modeles",
      str(len(json.load(open(os.path.join(SK, "references",
          "model_registry.json")))["models"])) in _fr)
check("playbook : listes awesome apres la traction, pas avant",
      "60" in _pb)
# liens internes (hors conventions GitHub ../../actions|releases)
_broken = []
for _p in [os.path.join(SK, x) for x in ("README.md", "SKILL.md", "SECURITY.md",
                                         "CONTRIBUTING.md")]:
    _c = open(_p).read()
    for _l in re.findall(r"\]\(([\w./-]+\.(?:md|json|yml|yaml|py|svg|png))\)", _c):
        if _l.startswith("../../"):
            continue
        if not os.path.exists(os.path.normpath(os.path.join(os.path.dirname(_p), _l))):
            _broken.append(f"{os.path.basename(_p)} -> {_l}")
check("aucun lien interne casse", not _broken, str(_broken[:3]))

# ------------------------------- 25. surete operationnelle (mise en prod DSI)
print("\n[25] Surete operationnelle")
_src = (open(os.path.join(SK, "scripts", "forge_dashboards.py")).read()
        + open(os.path.join(SK, "scripts", "grafana_client.py")).read())
_writes = sorted(set(re.findall(r'self\.(?:post|put|delete)\(f?"([^"{]+)', _src)))
_allowed = ("/api/dashboards", "/api/folders", "/api/v1/provisioning/alert-rules",
            "/apis/dashboard.grafana.app")
check("aucune ecriture hors dossier/dashboards/alertes",
      all(any(a in w for a in _allowed) for w in _writes), str(_writes))
check("le client ne peut PAS supprimer (aucune methode delete)",
      "def delete(" not in _src and 'request("DELETE"' not in _src,
      "capacite de suppression presente dans le client")
check("upsert idempotent explicite", '"overwrite": True' in _src)
_rd = open(os.path.join(SK, "README.md")).read()
check("procedure de retour arriere documentee",
      "how to back it out" in _rd and "AI Observability" in _rd)
check("divulgation : rien ne sort du reseau, ce que l'agent voit",
      "leaves your network" in _rd and "an agent sees" in _rd)
_sk = open(os.path.join(SK, "SKILL.md")).read()
check("le skill annonce le retour arriere avant de deployer",
      "Backing it out" in _sk)

# --------------------------- 26. comportement en panne (exploitabilite)
print("\n[26] Comportement en panne")
import socket as _sk, time as _tm
def _free_port():
    s = _sk.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def _fake_session(mode, action):
    port = _free_port()
    # Sous Windows, l'executable d'un venv est un lanceur. Le terminer ne tue
    # pas forcement l'interpreteur enfant; le binaire de base evite cet orphelin.
    python_server = getattr(sys, "_base_executable", sys.executable)
    srv = subprocess.Popen([python_server, os.path.join(SK, "tests", "fake_grafana.py"),
                            mode, str(port)], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    try:
        _up = False
        for _ in range(120):          # jusqu'a 30s : un runner froid est lent
            try:
                _s = _sk.create_connection(("127.0.0.1", port), 0.25)
                _s.close(); _up = True; break
            except OSError:
                _tm.sleep(0.25)
        if not _up:
            # sans ce garde, on interrogeait un port mort et l'echec etait
            # attribue au produit plutot qu'au harnais
            raise RuntimeError(f"fake_grafana n'a pas demarre sur le port {port}")
        env = dict(os.environ, GRAFANA_URL=f"http://127.0.0.1:{port}", GRAFANA_TOKEN="x")
        return action(env)
    finally:
        srv.terminate(); srv.wait(timeout=5)

def _fake_out(mode):
    return os.path.join(tempfile.gettempdir(), f"fkout_{mode}")

def _against_fake(mode, args, discover_args=()):
    cap = os.path.join(tempfile.gettempdir(), f"fk_{mode}.json")
    out = _fake_out(mode)
    shutil.rmtree(out, ignore_errors=True)
    def action(env):
        discovery = subprocess.run(
            [sys.executable, os.path.join(SC, "discover.py"), "--out", cap,
             *discover_args], env=env, capture_output=True, text=True, timeout=60)
        if discovery.returncode:
            return discovery
        return subprocess.run(
            [sys.executable, os.path.join(SC, "forge_dashboards.py"),
             "--capability", cap, "--out-dir", out, *args],
            env=env, capture_output=True, text=True, timeout=90)
    return _fake_session(mode, action)

r = _against_fake("nofolder", ["--deploy"])
check("403 sur la creation du dossier : message actionnable, pas de traceback",
      r.returncode == 3 and "[fail]" in r.stderr and "Traceback" not in r.stderr,
      r.stderr[-140:])
check("403 dossier : dit que rien n'a ete ecrit et ou sont les JSON",
      "Nothing was written" in r.stderr and "on disk" in r.stderr)
r = _against_fake("dashfail", ["--deploy"])
check("403 sur un dashboard : etat partiel decrit, pas de traceback",
      r.returncode == 4 and "[partial]" in r.stderr and "Traceback" not in r.stderr,
      r.stderr[-140:])
check("403 dashboard : dit que relancer est sur",
      "Re-running" in r.stderr and "safe" in r.stderr)
r = _against_fake("ds403", ["--deploy"])
check("403 datasource reste une erreur et donne un exit non nul",
      r.returncode != 0 and "discovery aborted" in r.stderr, r.stderr[-180:])
for _mode, _code in (("ds429", "429"), ("ds500", "500")):
    r = _against_fake(_mode, ["--deploy"])
    check(f"{_code} datasource ne devient jamais une liste vide",
          r.returncode != 0 and _code in r.stderr, r.stderr[-180:])
r = _against_fake("dsempty", ["--deploy"])
check("200 avec liste datasource vide reste un etat valide",
      r.returncode == 0, r.stderr[-180:])
r = _against_fake("proxy500", ["--deploy"])
check("500 du proxy datasource est fail-closed",
      r.returncode != 0 and "500" in r.stderr, r.stderr[-180:])
r = _against_fake("noorg", ["--deploy"])
check("absence d'organisation resolue est une erreur claire",
      r.returncode != 0 and "organization" in r.stderr.lower(), r.stderr[-180:])
r = _against_fake("noorg", ["--deploy", "--org-id", "9"],
                  discover_args=("--org-id", "9"))
check("override org non confirmable est refuse",
      r.returncode != 0 and "403" in r.stderr, r.stderr[-180:])
r = _against_fake("orgmismatch", ["--deploy", "--org-id", "9"],
                  discover_args=("--org-id", "9"))
check("override org ignore par Grafana est refuse",
      r.returncode != 0 and "confirmed organization 7" in r.stderr,
      r.stderr[-220:])
r = _against_fake("orgscope", ["--deploy", "--org-id", "9"],
                  discover_args=("--org-id", "9"))
check("override org scope toutes les requetes et est confirme",
      r.returncode == 0
      and json.load(open(os.path.join(_fake_out("orgscope"),
                                     "deploy_manifest.json")))["org_id"] == 9,
      r.stderr[-180:])
r = _against_fake("ok", ["--deploy", "--with-alerts"])
check("instance saine : deploiement complet", r.returncode == 0, r.stderr[-140:])
_ok_manifest = json.load(open(os.path.join(_fake_out("ok"), "deploy_manifest.json")))
check("org API propagee au manifeste", _ok_manifest["org_id"] == 7)
r = _against_fake("alertfail", ["--deploy", "--with-alerts"])
_alert_manifest = json.load(open(os.path.join(_fake_out("alertfail"),
                                              "deploy_manifest.json")))
check("alerte refusee => nonzero et manifeste non-success",
      r.returncode != 0 and _alert_manifest["deployment_status"] in ("partial", "failed")
      and _alert_manifest["resources"]["alerts"]["failed"] > 0,
      r.stderr[-180:])
r = _against_fake("alertfail", ["--deploy", "--with-alerts", "--best-effort"])
_alert_best = json.load(open(os.path.join(_fake_out("alertfail"),
                                          "deploy_manifest.json")))
check("--best-effort autorise exit 0 sans maquiller le manifeste",
      r.returncode == 0 and _alert_best["deployment_status"] != "success")

from grafana_client import (GrafanaClient, GrafanaError, alert_logical_identity,
                            normalized_http_origin)
import http.server
import threading
import urllib.error

class _HTTPProbeHandler(http.server.BaseHTTPRequestHandler):
    def _handle(self):
        self.server.seen.append((self.command, self.path, dict(self.headers)))
        count = sum(method == self.command and path == self.path
                    for method, path, _ in self.server.seen)
        status, headers, body = 200, {"Content-Type": "application/json"}, b'{"ok":true}'
        if self.server.source and self.path in ("/cross", "/bytes-cross"):
            status, headers, body = 302, {"Location": self.server.cross_target}, b""
        elif self.server.source and self.path == "/relative":
            status, headers, body = 302, {"Location": "/ok"}, b""
        elif self.server.source and self.path == "/retry-get" and count == 1:
            status, body = 500, b"temporary"
        elif self.server.source and self.path == "/post-500":
            status, body = 500, b"failed"
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)
    do_GET = _handle
    do_POST = _handle
    def log_message(self, *args): pass

_target_server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HTTPProbeHandler)
_target_server.source, _target_server.seen = False, []
_source_server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HTTPProbeHandler)
_source_server.source, _source_server.seen = True, []
_source_server.cross_target = (
    f"http://127.0.0.1:{_target_server.server_address[1]}/collect")
_servers = (_source_server, _target_server)
_threads = [threading.Thread(target=server.serve_forever, daemon=True)
            for server in _servers]
for _thread in _threads: _thread.start()
try:
    check("origines normalisent hostname et ports HTTP effectifs",
          normalized_http_origin("http://GRAFANA.EXAMPLE")
          == normalized_http_origin("http://grafana.example:80")
          and normalized_http_origin("https://GRAFANA.EXAMPLE")
          == normalized_http_origin("https://grafana.example:443"))
    class _HostClassificationClient(GrafanaClient):
        def get(self, path, **kwargs):
            if path == "/api/frontend/settings" and self._is_grafana_cloud_host():
                return {"namespace": "stacks-42"}
            raise GrafanaError(404, "simulated")

    for _url, _cloud in (
            ("https://grafana.net", True),
            ("https://foo.grafana.net", True),
            ("https://FOO.GRAFANA.NET.", True),
            ("https://grafana.net.evil.example", False),
            ("https://notgrafana.net", False),
            ("https://evil.example/path/.grafana.net", False)):
        _host_client = _HostClassificationClient(_url, token="test")
        check(f"classification Cloud limitee au hostname: {_url}",
              _host_client.edition() == ("cloud" if _cloud else "oss")
              and _host_client.namespace()
                  == ("stacks-42" if _cloud else "default"))

    _source_url = f"http://127.0.0.1:{_source_server.server_address[1]}"
    _bearer_http = GrafanaClient(_source_url, token="bearer-secret", retries=2)
    _bearer_http._scoped_org_id = 7
    try:
        _bearer_http.get("/cross")
        _bearer_blocked = False
    except GrafanaError as _e:
        _bearer_blocked = (_e.status == 502 and str(_e) == "HTTP 502: redirect blocked"
                           and "bearer-secret" not in str(_e))
    check("redirect Bearer cross-origin bloque avant seconde requete",
          _bearer_blocked and not _target_server.seen)
    check("redirect relatif same-origin conserve auth et org",
          _bearer_http.get("/relative") == {"ok": True}
          and all(item[2].get("Authorization") == "Bearer bearer-secret"
                  and item[2].get("X-Grafana-Org-Id") == "7"
                  for item in _source_server.seen if item[1] in ("/relative", "/ok")))

    _basic_http = GrafanaClient(_source_url, token="bootstrap", retries=2)
    _basic_http.token, _basic_http.user, _basic_http.password = "", "alice", "secret"
    _basic_http._scoped_org_id = 9
    try:
        _basic_http.get_bytes("/bytes-cross")
        _basic_blocked = False
    except GrafanaError as _e:
        _basic_blocked = _e.status == 502 and "secret" not in str(_e)
    check("redirect Basic get_bytes cross-origin sans fuite auth/org",
          _basic_blocked and not _target_server.seen
          and any(headers.get("Authorization") == "Basic YWxpY2U6c2VjcmV0"
                  and headers.get("X-Grafana-Org-Id") == "9"
                  for _, path, headers in _source_server.seen
                  if path == "/bytes-cross"))

    import grafana_client as _grafana_client
    _real_sleep = _grafana_client.time.sleep
    _grafana_client.time.sleep = lambda *_: None
    try:
        try:
            _bearer_http.post("/post-500", {"x": 1})
        except GrafanaError:
            pass
        _get_retry_ok = _bearer_http.get("/retry-get") == {"ok": True}
    finally:
        _grafana_client.time.sleep = _real_sleep
    check("POST 5xx non rejoue, GET idempotent conserve retry borne",
          sum(method == "POST" and path == "/post-500"
              for method, path, _ in _source_server.seen) == 1
          and sum(method == "GET" and path == "/retry-get"
                  for method, path, _ in _source_server.seen) == 2
          and _get_retry_ok)

    class _NetworkFailure:
        def __init__(self): self.attempts = 0
        def open(self, *args, **kwargs):
            self.attempts += 1
            raise urllib.error.URLError("untrusted transport detail")
    _network = _NetworkFailure()
    _bearer_http._opener = _network
    try:
        _bearer_http.post("/network", {"x": 1})
        _network_blocked = False
    except SystemExit as _e:
        _network_blocked = str(_e) == "Instance Grafana injoignable"
    check("POST erreur reseau non rejoue et erreur assainie",
          _network.attempts == 1 and _network_blocked)
finally:
    for _server in _servers:
        _server.shutdown()
        _server.server_close()
    for _thread in _threads: _thread.join(timeout=2)

_sample_rule = {"uid": "llmops-alr-sample", "title": "Sample", "folderUID": "f1",
                "orgID": 7, "ruleGroup": "llmops-slo",
                "labels": {"origin": "llmops-forge",
                           "llmops_rule_identity": alert_logical_identity("sample")}}
class _AlertClient:
    def __init__(self, existing): self.existing, self.writes = existing, []
    def get(self, path): return self.existing
    def put(self, path, payload): self.writes.append(("PUT", path)); return {"ok": True}
    def post(self, path, payload): self.writes.append(("POST", path)); return {"ok": True}
    upsert_alert_rule = GrafanaClient.upsert_alert_rule

for _field, _value in (("folderUID", "other"), ("orgID", 99), ("uid", "foreign")):
    _existing = dict(_sample_rule)
    _existing["labels"] = dict(_sample_rule["labels"])
    _existing[_field] = _value
    _ac = _AlertClient(_existing)
    try:
        _ac.upsert_alert_rule(dict(_sample_rule))
        _collision_refused = False
    except GrafanaError as _e:
        _collision_refused = (_e.status == 409 and "uid-scope" in str(_e).lower()
                              and not _ac.writes)
    check(f"collision alerte {_field} refusee avant ecriture", _collision_refused,
          str(_ac.writes))
_compatible = _AlertClient(dict(_sample_rule))
_compatible.upsert_alert_rule(dict(_sample_rule))
check("alerte compatible conserve l'upsert idempotent",
      _compatible.writes == [("PUT", "/api/v1/provisioning/alert-rules/llmops-alr-sample")],
      str(_compatible.writes))
_other_identity = dict(_sample_rule)
_other_identity["labels"] = dict(_sample_rule["labels"],
    llmops_rule_identity=alert_logical_identity("different-logical-rule"))
_ac = _AlertClient(_other_identity)
try:
    _ac.upsert_alert_rule(dict(_sample_rule))
    _logical_collision_refused = False
except GrafanaError as _e:
    _logical_collision_refused = (_e.status == 409 and "uid-scope" in str(_e).lower()
                                  and not _ac.writes)
check("meme UID/org/dossier mais identite logique differente refusee avant PUT",
      _logical_collision_refused, str(_ac.writes))
_legacy_rule = dict(_sample_rule)
_legacy_rule["labels"] = {"origin": "llmops-forge"}
_ac = _AlertClient(_legacy_rule)
try:
    _ac.upsert_alert_rule(dict(_sample_rule))
    _legacy_refused = False
except GrafanaError as _e:
    _legacy_refused = (_e.status == 409 and "uid-scope" in str(_e).lower()
                       and not _ac.writes)
check("ancienne regle forge sans identite logique est fail-closed",
      _legacy_refused, str(_ac.writes))
check("identite logique utilise uid_name complet avant troncature",
      alert_logical_identity("x" * 200 + "a")
      != alert_logical_identity("x" * 200 + "b"))
for _mode in ("alertcollision-folder", "alertcollision-org", "alertcollision-identity"):
    r = _against_fake(_mode, ["--deploy", "--with-alerts"])
    check(f"{_mode} produit un 409 actionnable",
          r.returncode != 0 and "uid-scope" in (r.stdout + r.stderr).lower(),
          (r.stdout + r.stderr)[-220:])

_legacy_uid = forge_dashboards.det_uid("ai-executive-finops")
check("UID legacy strictement inchange sans scope",
      _legacy_uid == "llmops-ai-executive-finops-b6b56614a5", _legacy_uid)
check("deux scopes produisent des UIDs distincts et deterministes",
      forge_dashboards.det_uid("ai-executive-finops", scope="prod")
      != forge_dashboards.det_uid("ai-executive-finops", scope="staging")
      and forge_dashboards.det_uid("ai-executive-finops", scope="prod")
      == forge_dashboards.det_uid("ai-executive-finops", scope="prod"))
r = _against_fake("collision", ["--deploy"])
check("collision dashboard dans un autre dossier refusee",
      r.returncode != 0 and "uid-scope" in (r.stderr + r.stdout).lower(),
      (r.stderr + r.stdout)[-220:])
r = _against_fake("collision", ["--deploy", "--uid-scope", "prod"])
check("scope explicite evite la collision inter-dossier", r.returncode == 0,
      r.stderr[-180:])

sys.path.insert(0, SC)
import visual_audit
from types import SimpleNamespace
_url_args = SimpleNamespace(resolved_org_id=37, time_from="now-1h", time_to="now")
_url_client = SimpleNamespace(base="https://grafana.example")
check("Playwright recoit l'org resolue, jamais 1 en dur",
      "orgId=37" in visual_audit.playwright_dashboard_url(
          _url_client, {"uid": "x"}, _url_args))

def _visual_action(extra, mode="ok", engine="renderer", uid="missing"):
    out = os.path.join(tempfile.gettempdir(), f"visual_{mode}_{engine}")
    shutil.rmtree(out, ignore_errors=True)
    def action(env):
        return subprocess.run(
            [sys.executable, os.path.join(SC, "visual_audit.py"), "--uids", uid,
             "--engine", engine, "--out", out, *extra], env=env,
            capture_output=True, text=True, timeout=60)
    result = _fake_session(mode, action)
    return result, json.load(open(os.path.join(out, "audit_manifest.json")))

r, _visual_ok = _visual_action([], mode="renderok")
check("renderer sain produit une capture et un manifeste success",
      r.returncode == 0 and _visual_ok["audit_status"] == "success"
      and _visual_ok["dashboards"][0]["files"], r.stderr[-180:])
for _status in (403, 429, 500):
    r, _visual_bad = _visual_action([], mode=f"render{_status}", engine="auto")
    check(f"renderer {_status} ne bascule jamais vers Playwright",
          r.returncode != 0 and _visual_bad["audit_status"] == "failed"
          and _visual_bad["errors"][0].get("status") == _status
          and _visual_bad["engine"] == "auto", r.stderr[-220:])
r, _visual_404 = _visual_action([], mode="render404", engine="auto")
check("renderer 404 explicite autorise seulement le fallback Playwright",
      r.returncode != 0 and _visual_404["engine"] == "playwright",
      (r.stdout + r.stderr)[-220:])
r, _visual_hard_allowed = _visual_action(["--allow-empty"], mode="render403",
                                          engine="auto")
check("--allow-empty ne masque pas une erreur renderer",
      r.returncode != 0 and _visual_hard_allowed["audit_status"] == "failed")

class _PWResponse:
    def __init__(self, status, url): self.status, self.url = status, url
class _PWPage:
    def __init__(self, status, final="https://grafana.example/d/x/slug"):
        self.status, self.final, self.url = status, final, "about:blank"
    def goto(self, *args, **kwargs):
        self.url = self.final
        return _PWResponse(self.status, self.final)
for _status in (401, 403, 429, 500):
    try:
        visual_audit._checked_goto(_PWPage(_status), "https://grafana.example/d/x")
        _pw_failed = False
    except GrafanaError as _e:
        _pw_failed = _e.status == _status
    check(f"Playwright HTTP {_status} est fail-closed", _pw_failed)
visual_audit._checked_goto(_PWPage(200), "https://grafana.example/d/x/original")
check("Playwright accepte le slug final du dashboard attendu", True)
for _name, _final in (("login", "https://grafana.example/login"),
                      ("autre dashboard", "https://grafana.example/d/y/slug"),
                      ("origine externe", "https://sso.example/d/x/slug")):
    try:
        visual_audit._checked_goto(
            _PWPage(200, _final), "https://grafana.example/d/x/original")
        _redirect_failed = False
    except GrafanaError:
        _redirect_failed = True
    check(f"Playwright refuse redirection {_name}", _redirect_failed)

class _HeaderClient:
    _headers = GrafanaClient._headers
    def __init__(self, token, user, password, org):
        self.token, self.user, self.password = token, user, password
        self._scoped_org_id = org
        self.base = "https://grafana.example/grafana"
_basic_client = _HeaderClient("", "alice", "secret", 9)
_basic_headers = visual_audit._scoped_request_headers(
    _basic_client, "https://grafana.example/grafana/d/x/slug", {})
check("requete dashboard same-origin recoit Basic et org",
      _basic_headers.get("Authorization") == "Basic YWxpY2U6c2VjcmV0"
      and _basic_headers.get("X-Grafana-Org-Id") == "9", str(_basic_headers.keys()))
check("credentials HTTP Basic sont limites a l'origine Grafana",
      visual_audit._basic_http_credentials(_basic_client).get("origin")
      == "https://grafana.example")
_bearer_client = _HeaderClient("token-value", "", "", 11)
_bearer_headers = visual_audit._scoped_request_headers(
    _bearer_client, "https://grafana.example/grafana/d/x/slug", {})
check("requete dashboard same-origin recoit Bearer et org",
      _bearer_headers.get("Authorization") == "Bearer token-value"
      and _bearer_headers.get("X-Grafana-Org-Id") == "11",
      str(_bearer_headers.keys()))
for _name, _client, _incoming in (
        ("Basic", _basic_client, {"Authorization": "Basic secret",
                                  "X-Grafana-Org-Id": "9"}),
        ("Bearer", _bearer_client, {"authorization": "Bearer token-value",
                                    "x-grafana-org-id": "11"}),
        ("cookie", _basic_client, {"Cookie": "grafana_session=secret"})):
    _external_headers = visual_audit._scoped_request_headers(
        _client, "https://cdn.example/asset.js", _incoming)
    check(f"sous-ressource cross-origin ne recoit jamais {_name}",
          not ({k.casefold() for k in _external_headers}
               & {"authorization", "cookie", "x-grafana-org-id"}),
          str(_external_headers.keys()))
_old_cookie = os.environ.get("GRAFANA_COOKIE")
os.environ["GRAFANA_COOKIE"] = "grafana_session=session-value"
try:
    _cookies = visual_audit._playwright_cookies(_basic_client)
    check("cookie Playwright porte domaine path secure de l'origine",
          len(_cookies) == 1 and _cookies[0]["domain"] == "grafana.example"
          and _cookies[0]["path"] == "/grafana" and _cookies[0]["secure"] is True,
          str(_cookies))
    _same_cookie = visual_audit._scoped_request_headers(
        _basic_client, "https://grafana.example/grafana/d/x/slug",
        {"Cookie": "grafana_session=session-value"})
    check("cookie same-origin est conserve par l'interception",
          _same_cookie.get("Cookie") == "grafana_session=session-value")
finally:
    if _old_cookie is None:
        os.environ.pop("GRAFANA_COOKIE", None)
    else:
        os.environ["GRAFANA_COOKIE"] = _old_cookie
class _Renderer404Basic(_HeaderClient):
    def get_bytes(self, *args, **kwargs):
        raise GrafanaError(404, "renderer absent")
_fallback_client = _Renderer404Basic("", "alice", "secret", 9)
check("fallback renderer 404 conserve Basic et scope org pour Playwright",
      not visual_audit.renderer_available(_fallback_client, "x")
      and visual_audit._scoped_request_headers(
          _fallback_client, "https://grafana.example/grafana/d/x/slug", {}
      ).get("Authorization", "").startswith("Basic ")
      and visual_audit._scoped_request_headers(
          _fallback_client, "https://grafana.example/grafana/d/x/slug", {}
      ).get("X-Grafana-Org-Id") == "9")
_findings = {}
visual_audit._scan_dom(
    "Unauthorized\nDatasource not found\nNo data\nWelcome to Grafana\nSign in to Grafana",
    _findings)
check("marqueurs DOM critiques et login distingues de No data",
      {"Unauthorized", "Datasource not found", "Welcome to Grafana",
       "Sign in to Grafana"}.issubset(
          set(_findings) & visual_audit.CRITICAL_DOM_MARKERS)
      and "No data" not in visual_audit.CRITICAL_DOM_MARKERS, str(_findings))

# -------------------------------- 24. fallback de prix Artificial Analysis
print("\n[24] Fallback de prix Artificial Analysis")
import http.client
import urllib.error
import urllib.request
import pricing_sources
from datetime import datetime, timezone

_aa_secret = "aa-test-secret-that-must-not-leak"
_aa_now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

def _aa_page(data, page=1, total=1):
    return {"tier": "free", "pagination": {
        "page": page, "page_size": 200, "total_pages": total,
        "has_more": page < total}, "data": data}

def _aa_model(name="acme-model", slug="acme-model", inp=1.25, out=4.5):
    return {"id": "00000000-0000-0000-0000-000000000001", "name": name,
            "slug": slug, "aliases": [],
            "model_creator": {"name": "Acme AI"},
            "pricing": {"price_1m_input_tokens": inp,
                        "price_1m_output_tokens": out,
                        "price_1m_cache_hit_tokens": 0.25}}

class _AAResponse:
    def __init__(self, value=None, raw=None, status=200, headers=None):
        self.body = raw if raw is not None else json.dumps(value).encode()
        self.status = status
        self.headers = headers or {}
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def getcode(self): return self.status
    def read(self, size): return self.body[:size]

class _AAOpener:
    def __init__(self, pages): self.pages, self.requests = list(pages), []
    def open(self, request, timeout):
        self.requests.append((request, timeout))
        item = self.pages.pop(0)
        if isinstance(item, BaseException): raise item
        if isinstance(item, _AAResponse): return item
        return _AAResponse(item)

_aa_base = {"_meta": {"verified_at": "2026-09-01"}, "models": []}
with tempfile.TemporaryDirectory(prefix="aa-pricing-") as _aa_tmp:
    _aa_cache = os.path.join(_aa_tmp, pricing_sources.CACHE_FILENAME)
    _aa_open = _AAOpener([_aa_page([_aa_model()])])
    _aa_result = pricing_sources.apply_artificial_analysis_fallback(
        _aa_base, ["acme-model"], _aa_cache, _aa_secret,
        opener=_aa_open, now=_aa_now)
    _aa_entry = _aa_result["registry"]["models"][0]
    _aa_cache_doc = json.load(open(_aa_cache))
    _aa_request = _aa_open.requests[0][0]
    check("succes: prix tiers marque, estime et attribue",
          _aa_result["priced"] == ["acme-model"]
          and _aa_entry["pricing_source_kind"] == "artificial_analysis"
          and _aa_entry["estimate"] is True
          and _aa_entry["attribution"] == "Artificial Analysis"
          and _aa_entry["pricing_basis"] == "median_multi_provider")
    check("cache AA est un overlay minimal, jamais un registre fusionne",
          "models" not in _aa_cache_doc
          and _aa_cache_doc["schema"] == pricing_sources.CACHE_SCHEMA
          and len(_aa_cache_doc["entries"]) == 1
          and "original" not in _aa_cache_doc["entries"][0])
    _strict_base = {"_meta": {"verified_at": "2026-09-01"}, "models": [{
        "id": "existing-model", "aliases": [], "vendor": "Acme", "region": "us",
        "input_per_mtok": None, "output_per_mtok": None,
        "cached_input_per_mtok": None, "pricing_source_kind": "unavailable",
        "pricing_source_url": "https://provider.example/pricing",
        "availability_checked_at": "2026-09-01"}]}
    _strict_snapshot = _copy.deepcopy(_strict_base)
    _invalid_price_results = []
    for _label, _value in (
            ("extreme", pricing_sources.MAX_PRICE_PER_MTOK + 1),
            ("bool", True), ("nan", float("nan")), ("inf", float("inf"))):
        _invalid_item = _aa_model("new-model", "new-model")
        _invalid_item["pricing"]["price_1m_input_tokens"] = _value
        _invalid_price_results.append(
            pricing_sources.apply_artificial_analysis_fallback(
                _strict_base, ["new-model"],
                os.path.join(_aa_tmp, f"invalid-price-{_label}.json"), _aa_secret,
                opener=_AAOpener([_aa_page([_invalid_item])]), now=_aa_now))
    check("prix tiers extreme/bool/NaN/inf refuses avant les regles",
          pricing_sources._registry_number(pricing_sources.MAX_PRICE_PER_MTOK)
          and not pricing_sources._registry_number(
              pricing_sources.MAX_PRICE_PER_MTOK + 1)
          and all(not result["priced"] and result["registry"] == _strict_snapshot
                  for result in _invalid_price_results)
          and _strict_base == _strict_snapshot)

    _bad_vendor = _aa_model("new-model", "new-model")
    _bad_vendor["model_creator"] = {"name": 7}
    _bad_vendor_path = os.path.join(_aa_tmp, "invalid-vendor.json")
    _bad_vendor_result = pricing_sources.apply_artificial_analysis_fallback(
        _strict_base, ["new-model"], _bad_vendor_path, _aa_secret,
        opener=_AAOpener([_aa_page([_bad_vendor])]), now=_aa_now)
    _bad_schema = _aa_model("existing-model", "existing-model")
    _bad_schema["aliases"] = ["new-model"]
    _bad_schema_path = os.path.join(_aa_tmp, "invalid-schema.json")
    _bad_schema_result = pricing_sources.apply_artificial_analysis_fallback(
        _strict_base, ["new-model"], _bad_schema_path, _aa_secret,
        opener=_AAOpener([_aa_page([_bad_schema])]), now=_aa_now)
    check("fusion tierce invalide revient au registre officiel avec warning sain",
          _bad_vendor_result["registry"] == _strict_snapshot
          and _bad_schema_result["registry"] == _strict_snapshot
          and not _bad_vendor_result["priced"] and not _bad_schema_result["priced"]
          and _bad_vendor_result["warnings"] == ["pricing overlay rejected"]
          and _bad_schema_result["warnings"] == ["pricing overlay rejected"]
          and not os.path.exists(_bad_vendor_path)
          and not os.path.exists(_bad_schema_path)
          and _strict_base == _strict_snapshot)
    check("cle uniquement dans x-api-key, jamais URL/cache",
          dict(_aa_request.header_items()).get("X-api-key") == _aa_secret
          and _aa_secret not in _aa_request.full_url
          and _aa_secret not in open(_aa_cache).read())
    _aa_bomb = _AAOpener([])
    _aa_cached = pricing_sources.apply_artificial_analysis_fallback(
        _aa_base, ["acme-model"], _aa_cache, None,
        opener=_aa_bomb, now=_aa_now)
    check("cache frais 24h reutilise sans requete ni cle",
          _aa_cached["cache_used"] and _aa_cached["priced"] == ["acme-model"]
          and not _aa_bomb.requests)

    _expired_doc = json.loads(json.dumps(_aa_cache_doc))
    _expired_doc["entries"][0]["pricing_verified_at"] = "2026-08-30T00:00:00Z"
    _expired_path = os.path.join(_aa_tmp, "expired.json")
    json.dump(_expired_doc, open(_expired_path, "w"))
    _expired = pricing_sources.apply_artificial_analysis_fallback(
        _aa_base, ["acme-model"], _expired_path, None, now=_aa_now)
    check("cache expire ignore et base reste non tarifaire",
          not _expired["priced"] and not _expired["registry"]["models"])

    _updated_official = {"_meta": {"verified_at": "2026-09-02"}, "models": [{
        "id": "acme-model", "aliases": [], "input_per_mtok": 7.0,
        "output_per_mtok": 8.0, "pricing_source_kind": "official"}]}
    _updated = pricing_sources.apply_artificial_analysis_fallback(
        _updated_official, ["acme-model"], _aa_cache, None, now=_aa_now)
    check("cache tiers ne masque jamais seed officiel mis a jour",
          _updated["registry"]["models"][0]["input_per_mtok"] == 7.0
          and not _updated["cache_used"])

    _cap_off = json.loads(json.dumps(forge_dashboards.selftest_capability()))
    _cap_off["signals"]["prom-selftest"]["otel_genai"]["models_seen"] = ["acme-model"]
    _cap_off_path = os.path.join(_aa_tmp, "capability.json")
    _base_path = os.path.join(_aa_tmp, "official-base.json")
    json.dump(_cap_off, open(_cap_off_path, "w"))
    json.dump(_aa_result["registry"], open(_base_path, "w"))
    _off_out = os.path.join(_aa_tmp, "fallback-off")
    _off_run = subprocess.run([
        sys.executable, os.path.join(SC, "forge_dashboards.py"),
        "--capability", _cap_off_path, "--registry", _base_path,
        "--blueprints", "finops", "--out-dir", _off_out, "--org-id", "1"],
        capture_output=True, text=True)
    _off_board = json.load(open(os.path.join(_off_out, "finops.json")))
    check("fallback desactive ne charge jamais overlay AA",
          _off_run.returncode == 0
          and "Artificial Analysis median" not in json.dumps(_off_board)
          and "Models without a price" in _off_run.stdout)

    _aa_no_key_open = _AAOpener([])
    _aa_no_key = pricing_sources.apply_artificial_analysis_fallback(
        _aa_base, ["new-model"], os.path.join(_aa_tmp, "absent.json"), None,
        opener=_aa_no_key_open, now=_aa_now)
    check("cle absente: zero requete et modele non tarife",
          not _aa_no_key_open.requests and not _aa_no_key["priced"]
          and _aa_no_key["warnings"])

    _bad_keys_ok = True
    for _bad_key in ("bad\r\nheader", "bad\x01key",
                     "x" * (pricing_sources.MAX_API_KEY_LENGTH + 1), "clé"):
        _bad_open = _AAOpener([])
        _bad_result = pricing_sources.apply_artificial_analysis_fallback(
            _aa_base, ["bad-key-model"], os.path.join(_aa_tmp, "bad-key.json"),
            _bad_key, opener=_bad_open, now=_aa_now)
        _bad_keys_ok = (_bad_keys_ok and not _bad_open.requests
                        and _bad_result["warnings"] == ["invalid API key"]
                        and _bad_key not in "".join(_bad_result["warnings"]))
    check("cles CRLF/controle/non-ASCII/trop longues refusees avant Request",
          _bad_keys_ok)

    class _AAValueErrorOpener:
        def open(self, request, timeout):
            raise ValueError(_aa_secret)
    _value_error = pricing_sources.apply_artificial_analysis_fallback(
        _aa_base, ["value-error-model"], os.path.join(_aa_tmp, "value.json"),
        _aa_secret, opener=_AAValueErrorOpener(), now=_aa_now)
    check("ValueError devient erreur constante sans fuite",
          _value_error["warnings"] == ["request rejected"]
          and _aa_secret not in "".join(_value_error["warnings"]))

    _bad_status_snapshot = json.loads(json.dumps(_aa_base))
    _bad_status = pricing_sources.apply_artificial_analysis_fallback(
        _aa_base, ["bad-status-model"],
        os.path.join(_aa_tmp, "bad-status.json"), _aa_secret,
        opener=_AAOpener([http.client.BadStatusLine(_aa_secret)]),
        now=_aa_now)
    check("BadStatusLine avant reponse devient erreur constante et conserve la base",
          _bad_status["warnings"] == ["HTTP protocol failure"]
          and _aa_secret not in "".join(_bad_status["warnings"])
          and _bad_status["registry"] == _bad_status_snapshot
          and _aa_base == _bad_status_snapshot
          and not _bad_status["priced"])

    class _AAIncompleteResponse(_AAResponse):
        def read(self, size):
            raise http.client.IncompleteRead(_aa_secret.encode(), size)
    _incomplete = pricing_sources.apply_artificial_analysis_fallback(
        _aa_base, ["incomplete-model"],
        os.path.join(_aa_tmp, "incomplete.json"), _aa_secret,
        opener=_AAOpener([_AAIncompleteResponse(value={})]), now=_aa_now)
    check("IncompleteRead devient erreur constante et conserve la base",
          _incomplete["warnings"] == ["response read failed"]
          and _aa_secret not in "".join(_incomplete["warnings"])
          and _incomplete["registry"] == _aa_base
          and not _incomplete["priced"])

    _real_json_loads = pricing_sources.json.loads
    try:
        def _raise_recursion(*args, **kwargs):
            raise RecursionError(_aa_secret)
        pricing_sources.json.loads = _raise_recursion
        _recursive = pricing_sources.apply_artificial_analysis_fallback(
            _aa_base, ["recursive-model"],
            os.path.join(_aa_tmp, "recursive.json"), _aa_secret,
            opener=_AAOpener([_AAResponse(value={})]), now=_aa_now)
    finally:
        pricing_sources.json.loads = _real_json_loads
    check("RecursionError JSON devient erreur constante et conserve la base",
          _recursive["warnings"] == ["invalid JSON response"]
          and _aa_secret not in "".join(_recursive["warnings"])
          and _recursive["registry"] == _aa_base
          and not _recursive["priced"])

    _huge_number = 10 ** 400
    _huge_result = pricing_sources.apply_artificial_analysis_fallback(
        _aa_base, ["huge-model"], os.path.join(_aa_tmp, "huge.json"),
        _aa_secret, opener=_AAOpener([_aa_page([
            _aa_model("huge-model", "huge-model", _huge_number, 2.0)])]),
        now=_aa_now)
    check("entier JSON enorme refusé sans exception et conserve la base",
          _huge_result["statuses"] == {"huge-model": "null"}
          and _huge_result["registry"] == _aa_base
          and not _huge_result["priced"])

    _aa_http_ok = True
    for _status in (401, 403, 429, 500, 503):
        _err = urllib.error.HTTPError(pricing_sources.AA_URL, _status,
                                     "simulated", {}, None)
        _result = pricing_sources.apply_artificial_analysis_fallback(
            _aa_base, ["error-model"], os.path.join(_aa_tmp, f"e{_status}.json"),
            _aa_secret, opener=_AAOpener([_err]), now=_aa_now)
        _aa_http_ok = _aa_http_ok and not _result["priced"] and _result["warnings"]
    check("401/403/429/5xx degradent sans prix invente", _aa_http_ok)

    _aa_pages = _AAOpener([_aa_page([], 1, 2),
                           _aa_page([_aa_model()], 2, 2)])
    _catalog = pricing_sources.fetch_artificial_analysis(
        _aa_secret, opener=_aa_pages)
    check("pagination bornee suit page=2",
          len(_catalog) == 1 and len(_aa_pages.requests) == 2
          and _aa_pages.requests[1][0].full_url.endswith("?page=2"))

    _ambiguous = [_aa_model("same", "one"), _aa_model("Same", "two")]
    _null = _aa_model("null-model", "null-model", None, 2.0)
    check("match strict ambigu ou prix null refuse",
          pricing_sources.strict_catalog_match("same", _ambiguous)[1] == "ambiguous"
          and pricing_sources.strict_catalog_match("same-extra", _ambiguous)[1] == "absent"
          and pricing_sources.strict_catalog_match("null-model", [_null])[1] == "null")

    _tamper_cases = {
        "nan": ("input_per_mtok", float("nan")),
        "negative": ("output_per_mtok", -1),
        "string": ("input_per_mtok", "1.25"),
        "provenance": ("attribution", "Mallory"),
        "url": ("pricing_source_url", "https://evil.example/prices"),
        "estimate": ("estimate", 1),
        "timestamp": ("pricing_verified_at", "not-an-iso-date"),
        "non-utc": ("pricing_verified_at", "2026-09-01T13:00:00+01:00"),
    }
    _tamper_ok = True
    for _label, (_field, _value) in _tamper_cases.items():
        _tampered = json.loads(json.dumps(_aa_cache_doc))
        _tampered["entries"][0][_field] = _value
        _tampered_path = os.path.join(_aa_tmp, f"tampered-{_label}.json")
        json.dump(_tampered, open(_tampered_path, "w"))
        _tampered_result = pricing_sources.apply_artificial_analysis_fallback(
            _aa_base, ["acme-model"], _tampered_path, None, now=_aa_now)
        _tamper_ok = (_tamper_ok and not _tampered_result["priced"]
                      and not _tampered_result["registry"]["models"])
    check("cache falsifie NaN/negatif/chaine/provenance/URL/estimate/date ignore",
          _tamper_ok)
    try:
        pricing_sources.fetch_artificial_analysis(
            _aa_secret, opener=_AAOpener([_AAResponse(raw=b"not-json")]))
        _invalid_json = False
    except pricing_sources.PricingSourceError:
        _invalid_json = True
    check("JSON invalide refuse sans exception brute", _invalid_json)

    _official = {"_meta": {}, "models": [{"id": "acme-model", "aliases": [],
        "input_per_mtok": 9.0, "output_per_mtok": 10.0,
        "pricing_source_kind": "official"}]}
    _official_open = _AAOpener([])
    _official_result = pricing_sources.apply_artificial_analysis_fallback(
        _official, ["acme-model"], os.path.join(_aa_tmp, "official.json"),
        _aa_secret, opener=_official_open, now=_aa_now)
    check("prix officiel complet prioritaire et zero requete",
          _official_result["registry"]["models"][0]["input_per_mtok"] == 9.0
          and not _official_open.requests)
    _partial = {"_meta": {"verified_at": "2026-09-01"}, "models": [{
        "id": "acme-model", "aliases": [], "vendor": "Acme", "region": "us",
        "input_per_mtok": 9.0, "output_per_mtok": None,
        "pricing_source_kind": "official",
        "pricing_source_url": "https://provider.example/pricing",
        "pricing_verified_at": "2026-09-01"}]}
    _partial_snapshot = _copy.deepcopy(_partial)
    _partial_result = pricing_sources.apply_artificial_analysis_fallback(
        _partial, ["acme-model"], os.path.join(_aa_tmp, "partial.json"),
        _aa_secret, opener=_AAOpener([_aa_page([_aa_model()])]), now=_aa_now)
    _partial_entry = _partial_result["registry"]["models"][0]
    check("champ officiel partiel conserve, seul le null recoit le fallback",
          _partial_entry["input_per_mtok"] == 9.0
          and _partial_entry["output_per_mtok"] == 4.5
          and _partial == _partial_snapshot
          and _partial_entry["pricing_field_sources"]["input_per_mtok"][
              "pricing_source_kind"] == "official")
    _partial_ctx = forge_dashboards.Ctx(_cap_off, _partial_result["registry"])
    _partial_rules_path = os.path.join(_aa_tmp, "partial-rules.yml")
    forge_dashboards.emit_recording_rules(_partial_ctx, _partial_rules_path)
    _partial_rules = yaml.safe_load(open(_partial_rules_path))["groups"][0]["rules"]
    _partial_prices = {rule["record"]: rule for rule in _partial_rules
                       if rule["record"] in (forge_dashboards.PRICE_IN,
                                             forge_dashboards.PRICE_OUT)}
    _input_labels = _partial_prices[forge_dashboards.PRICE_IN]["labels"]
    _output_labels = _partial_prices[forge_dashboards.PRICE_OUT]["labels"]
    check("recording rules conservent la provenance propre a chaque champ",
          _input_labels["pricing_source_kind"] == "official"
          and _input_labels["price_estimate"] == "false"
          and "pricing_attribution" not in _input_labels
          and _input_labels["pricing_source_url"]
              == "https://provider.example/pricing"
          and _output_labels["pricing_source_kind"] == "artificial_analysis"
          and _output_labels["price_estimate"] == "true"
          and _output_labels["pricing_source_url"] == pricing_sources.AA_URL
          and _output_labels["pricing_attribution"]
              == pricing_sources.AA_ATTRIBUTION)
    _aa_rules_path = os.path.join(_aa_tmp, "aa-rules.yml")
    forge_dashboards.emit_recording_rules(
        forge_dashboards.Ctx(_cap_off, _aa_result["registry"]), _aa_rules_path)
    _aa_rules = yaml.safe_load(open(_aa_rules_path))["groups"][0]["rules"]
    _aa_price_labels = [rule["labels"] for rule in _aa_rules
                        if rule["record"] in (forge_dashboards.PRICE_IN,
                                              forge_dashboards.PRICE_OUT)]
    check("attribution AA presente sur les series input et output AA",
          len(_aa_price_labels) == 2
          and all(labels["pricing_attribution"]
                  == pricing_sources.AA_ATTRIBUTION
                  for labels in _aa_price_labels))

    _legacy_partial = {"_meta": {"verified_at": "2026-09-01"}, "models": [{
        "id": "legacy-partial", "aliases": [], "vendor": "Legacy", "region": "unknown",
        "input_per_mtok": 9.0, "output_per_mtok": None,
        "cached_input_per_mtok": 0.75}]}
    _legacy_api = _aa_model("legacy-partial", "legacy-partial", 1.0, 4.5)
    _legacy_result = pricing_sources.apply_artificial_analysis_fallback(
        _legacy_partial, ["legacy-partial"],
        os.path.join(_aa_tmp, "legacy-partial.json"), _aa_secret,
        opener=_AAOpener([_aa_page([_legacy_api])]), now=_aa_now)
    _legacy_entry = _legacy_result["registry"]["models"][0]
    check("registre legacy partiel conserve tout non-null et source locale explicite",
          _legacy_entry["input_per_mtok"] == 9.0
          and _legacy_entry["output_per_mtok"] == 4.5
          and _legacy_entry["cached_input_per_mtok"] == 0.75
          and _legacy_entry["pricing_field_sources"]["input_per_mtok"][
              "pricing_source_kind"] == "local_registry_legacy"
          and _legacy_entry["pricing_field_sources"]["cached_input_per_mtok"][
              "pricing_source_kind"] == "local_registry_legacy"
          and _legacy_entry["pricing_field_sources"]["output_per_mtok"][
              "pricing_source_kind"] == "artificial_analysis")

    _converging_registry = {"_meta": {"verified_at": "2026-09-01"}, "models": [{
        "id": "shared-model", "aliases": ["alias-one", "alias-two"],
        "vendor": "Acme", "region": "unknown",
        "input_per_mtok": None, "output_per_mtok": None,
        "pricing_source_kind": "unavailable",
        "pricing_source_url": "https://provider.example/pricing",
        "availability_checked_at": "2026-09-01"}]}

    _matrix_base = {"_meta": {"verified_at": "2026-09-01"}, "models": [{
        "id": "matrix-shared",
        "aliases": ["matrix-a", "matrix-b", "matrix-c"],
        "vendor": "Acme", "region": "unknown",
        "input_per_mtok": None, "output_per_mtok": None,
        "pricing_source_kind": "unavailable",
        "pricing_source_url": "https://provider.example/pricing",
        "availability_checked_at": "2026-09-01"}]}
    _matrix_snapshot = _copy.deepcopy(_matrix_base)

    def _matrix_model(alias, identity, price):
        item = _aa_model(alias, alias, price, price * 2)
        item["id"] = identity
        return item

    def _matrix_seed(path, alias, identity, price):
        return pricing_sources.apply_artificial_analysis_fallback(
            _matrix_base, [alias], path, _aa_secret,
            opener=_AAOpener([_aa_page([
                _matrix_model(alias, identity, price)])]), now=_aa_now)

    def _matrix_rejected(result, aliases, path, unchanged_cache=None):
        cache_ok = (open(path, "rb").read() == unchanged_cache
                    if unchanged_cache is not None
                    else json.load(open(path))["entries"] == [])
        return (result["registry"] == _matrix_snapshot
                and _matrix_base == _matrix_snapshot
                and not result["priced"]
                and result["statuses"] == {
                    alias: "ambiguous" for alias in aliases}
                and cache_ok)

    _matrix_cache_a = os.path.join(_aa_tmp, "matrix-cache-a.json")
    _matrix_seed_a = _matrix_seed(
        _matrix_cache_a, "matrix-a", "identity-a", 1.0)
    _matrix_cache_only = pricing_sources.apply_artificial_analysis_fallback(
        _matrix_base, ["matrix-a"], _matrix_cache_a, None, now=_aa_now)
    check("resolveur: cache A seul ecrit une fois la destination D",
          _matrix_seed_a["priced"] == ["matrix-a"]
          and _matrix_cache_only["priced"] == ["matrix-a"]
          and _matrix_cache_only["cache_used"]
          and _matrix_cache_only["registry"]["models"][0][
              "input_per_mtok"] == 1.0
          and _matrix_base == _matrix_snapshot
          and len(json.load(open(_matrix_cache_a))["entries"]) == 1)

    _matrix_cache_ab = os.path.join(_aa_tmp, "matrix-cache-ab.json")
    _matrix_seed(_matrix_cache_ab, "matrix-a", "identity-a", 1.0)
    _matrix_seed(_matrix_cache_ab, "matrix-b", "identity-b", 2.0)
    _matrix_ab_before = open(_matrix_cache_ab, "rb").read()
    _matrix_cache_conflict = pricing_sources.apply_artificial_analysis_fallback(
        _matrix_base, ["matrix-a", "matrix-b"], _matrix_cache_ab, None,
        now=_aa_now)
    check("resolveur: caches A et B distincts vers D sont tous refuses",
          _matrix_rejected(
              _matrix_cache_conflict, ["matrix-a", "matrix-b"],
              _matrix_cache_ab, unchanged_cache=_matrix_ab_before))

    _matrix_api_bc = os.path.join(_aa_tmp, "matrix-api-bc.json")
    _matrix_api_conflict = pricing_sources.apply_artificial_analysis_fallback(
        _matrix_base, ["matrix-b", "matrix-c"], _matrix_api_bc, _aa_secret,
        opener=_AAOpener([_aa_page([
            _matrix_model("matrix-b", "identity-b", 2.0),
            _matrix_model("matrix-c", "identity-c", 3.0)])]), now=_aa_now)
    check("resolveur: API B et C distincts vers D sont tous refuses",
          _matrix_rejected(
              _matrix_api_conflict, ["matrix-b", "matrix-c"],
              _matrix_api_bc))

    _matrix_cache_api_b = os.path.join(_aa_tmp, "matrix-cache-api-b.json")
    _matrix_seed(_matrix_cache_api_b, "matrix-a", "identity-a", 1.0)
    _matrix_cache_api_b_result = pricing_sources.apply_artificial_analysis_fallback(
        _matrix_base, ["matrix-a", "matrix-b"], _matrix_cache_api_b,
        _aa_secret, opener=_AAOpener([_aa_page([
            _matrix_model("matrix-b", "identity-b", 2.0)])]), now=_aa_now)
    check("resolveur: cache A et API B distincts vers D sont tous refuses",
          _matrix_rejected(
              _matrix_cache_api_b_result, ["matrix-a", "matrix-b"],
              _matrix_cache_api_b))

    _matrix_cache_api_bc = os.path.join(_aa_tmp, "matrix-cache-api-bc.json")
    _matrix_seed(_matrix_cache_api_bc, "matrix-a", "identity-a", 1.0)
    _matrix_cache_api_bc_result = pricing_sources.apply_artificial_analysis_fallback(
        _matrix_base, ["matrix-a", "matrix-b", "matrix-c"],
        _matrix_cache_api_bc, _aa_secret,
        opener=_AAOpener([_aa_page([
            _matrix_model("matrix-b", "identity-b", 2.0),
            _matrix_model("matrix-c", "identity-c", 3.0)])]), now=_aa_now)
    check("resolveur: cache A plus API B et C vers D rejette tout le groupe",
          _matrix_rejected(
              _matrix_cache_api_bc_result,
              ["matrix-a", "matrix-b", "matrix-c"],
              _matrix_cache_api_bc))

    _matrix_cache_ab_api_c = os.path.join(
        _aa_tmp, "matrix-cache-ab-api-c.json")
    _matrix_seed(_matrix_cache_ab_api_c, "matrix-a", "identity-a", 1.0)
    _matrix_seed(_matrix_cache_ab_api_c, "matrix-b", "identity-b", 2.0)
    _matrix_cache_ab_api_c_result = (
        pricing_sources.apply_artificial_analysis_fallback(
            _matrix_base, ["matrix-a", "matrix-b", "matrix-c"],
            _matrix_cache_ab_api_c, _aa_secret,
            opener=_AAOpener([_aa_page([
                _matrix_model("matrix-c", "identity-c", 3.0)])]),
            now=_aa_now))
    check("resolveur: caches A et B plus API C vers D rejettent tout le groupe",
          _matrix_rejected(
              _matrix_cache_ab_api_c_result,
              ["matrix-a", "matrix-b", "matrix-c"],
              _matrix_cache_ab_api_c))

    _matrix_api_blocked = os.path.join(
        _aa_tmp, "matrix-api-ambiguity-blocks-cache.json")
    _matrix_seed(_matrix_api_blocked, "matrix-a", "identity-a", 1.0)
    _matrix_api_blocked_result = (
        pricing_sources.apply_artificial_analysis_fallback(
            _matrix_base, ["matrix-a", "matrix-b"], _matrix_api_blocked,
            _aa_secret, opener=_AAOpener([_aa_page([
                _matrix_model("matrix-b", "identity-b", 2.0),
                _matrix_model("matrix-b", "identity-c", 3.0)])]),
            now=_aa_now))
    check("resolveur: ambiguite API sans plan bloque le cache vers D",
          _matrix_rejected(
              _matrix_api_blocked_result, ["matrix-a", "matrix-b"],
              _matrix_api_blocked))

    _matrix_cache_blocked = os.path.join(
        _aa_tmp, "matrix-cache-ambiguity-blocks-api.json")
    _matrix_seed(_matrix_cache_blocked, "matrix-a", "identity-a", 1.0)
    _matrix_cache_blocked_doc = json.load(open(_matrix_cache_blocked))
    _matrix_duplicate_overlay = _copy.deepcopy(
        _matrix_cache_blocked_doc["entries"][0])
    _matrix_duplicate_overlay["aa_model_id"] = "identity-b"
    _matrix_cache_blocked_doc["entries"].append(_matrix_duplicate_overlay)
    json.dump(_matrix_cache_blocked_doc, open(_matrix_cache_blocked, "w"))
    _matrix_cache_blocked_result = (
        pricing_sources.apply_artificial_analysis_fallback(
            _matrix_base, ["matrix-a"], _matrix_cache_blocked, _aa_secret,
            opener=_AAOpener([_aa_page([
                _matrix_model("matrix-a", "identity-c", 3.0)])]),
            now=_aa_now))
    check("resolveur: ambiguite cache sans plan bloque l API vers D",
          _matrix_rejected(
              _matrix_cache_blocked_result, ["matrix-a"],
              _matrix_cache_blocked))

    _aa_one = _aa_model("alias-one", "alias-one")
    _aa_one["id"] = "aa-one"
    _aa_two = _aa_model("alias-two", "alias-two")
    _aa_two["id"] = "aa-two"
    _converging = pricing_sources.apply_artificial_analysis_fallback(
        _converging_registry, ["alias-one", "alias-two"],
        os.path.join(_aa_tmp, "converging.json"), _aa_secret,
        opener=_AAOpener([_aa_page([_aa_one, _aa_two])]), now=_aa_now)
    check("deux objets AA distincts convergeant vers une entree sont refuses",
          not _converging["priced"]
          and _converging["registry"]["models"][0]["input_per_mtok"] is None
          and set(_converging["statuses"].values()) == {"ambiguous"})

    _cross_cache = os.path.join(_aa_tmp, "cross-source-convergence.json")
    _cross_seed = pricing_sources.apply_artificial_analysis_fallback(
        _converging_registry, ["alias-one"], _cross_cache, _aa_secret,
        opener=_AAOpener([_aa_page([_aa_one])]), now=_aa_now)
    _cross_result = pricing_sources.apply_artificial_analysis_fallback(
        _converging_registry, ["alias-one", "alias-two"], _cross_cache,
        _aa_secret, opener=_AAOpener([_aa_page([_aa_two])]), now=_aa_now)
    check("convergence croisee cache A et API B refusee avant toute mutation",
          _cross_seed["priced"] == ["alias-one"]
          and not _cross_result["priced"]
          and _cross_result["registry"]["models"][0]["input_per_mtok"] is None
          and set(_cross_result["statuses"].values()) == {"ambiguous"})

    _supersession_cache = os.path.join(_aa_tmp, "api-supersession.json")
    _same_old = _aa_model("alias-one", "alias-one", 1.25, 4.5)
    _same_old["id"] = "aa-shared"
    _supersession_seed = pricing_sources.apply_artificial_analysis_fallback(
        _converging_registry, ["alias-one"], _supersession_cache, _aa_secret,
        opener=_AAOpener([_aa_page([_same_old])]), now=_aa_now)
    _same_new = _aa_model("alias-two", "alias-two", 2.5, 9.0)
    _same_new["id"] = "aa-shared"
    _new_now = datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc)
    _supersession = pricing_sources.apply_artificial_analysis_fallback(
        _converging_registry, ["alias-one", "alias-two"],
        _supersession_cache, _aa_secret,
        opener=_AAOpener([_aa_page([_same_new])]), now=_new_now)
    _supersession_doc = json.load(open(_supersession_cache))
    _supersession_restart = pricing_sources.apply_artificial_analysis_fallback(
        _converging_registry, ["alias-two", "alias-one"],
        _supersession_cache, None, opener=_AAOpener([]), now=_new_now)
    check("plan API supplante cache de meme identite et reste stable au redemarrage",
          _supersession_seed["priced"] == ["alias-one"]
          and _supersession["registry"]["models"][0]["input_per_mtok"] == 2.5
          and _supersession["registry"]["models"][0]["output_per_mtok"] == 9.0
          and _supersession["statuses"]["alias-one"] == "superseded"
          and _supersession["priced"] == ["alias-two"]
          and len(_supersession_doc["entries"]) == 1
          and _supersession_doc["entries"][0]["seen"] == "alias-two"
          and _supersession_doc["entries"][0]["input_per_mtok"] == 2.5
          and _supersession_restart["registry"]["models"][0][
              "input_per_mtok"] == 2.5
          and _supersession_restart["registry"]["models"][0][
              "output_per_mtok"] == 9.0
          and _supersession_restart["priced"] == ["alias-two"])

    _tie_registry = {"_meta": {}, "models": [
        {"id": "foo-model-a", "aliases": [], "input_per_mtok": None,
         "output_per_mtok": None},
        {"id": "foo-model-b", "aliases": [], "input_per_mtok": None,
         "output_per_mtok": None}]}
    _tie_result = pricing_sources.apply_artificial_analysis_fallback(
        _tie_registry, ["foo-model"], os.path.join(_aa_tmp, "tie.json"),
        _aa_secret, opener=_AAOpener([_aa_page([_aa_model("foo-model", "foo-model")])]),
        now=_aa_now)
    check("egalite de score registre refusee avant mutation",
          not _tie_result["priced"]
          and all(model["input_per_mtok"] is None
                  for model in _tie_result["registry"]["models"]))

    _atomic_path = os.path.join(_aa_tmp, "atomic.json")
    open(_atomic_path, "w").write("old")
    _real_replace = pricing_sources.os.replace
    try:
        pricing_sources.os.replace = lambda *_: (_ for _ in ()).throw(OSError("stop"))
        try:
            pricing_sources._atomic_write_json(_atomic_path, {"new": True})
        except OSError:
            pass
    finally:
        pricing_sources.os.replace = _real_replace
    check("echec de remplacement conserve ancien cache et nettoie temporaire",
          open(_atomic_path).read() == "old"
          and not [n for n in os.listdir(_aa_tmp)
                   if n.startswith(".artificial-analysis-pricing.")])

    _cap_aa = json.loads(json.dumps(forge_dashboards.selftest_capability()))
    _cap_aa["signals"]["prom-selftest"]["otel_genai"]["models_seen"] = ["acme-model"]
    _ctx_aa = forge_dashboards.Ctx(_cap_aa, _aa_result["registry"])
    _board_aa = forge_dashboards.bp_finops(_ctx_aa).d
    _board_text = json.dumps(_board_aa, ensure_ascii=False)
    check("dashboard signale mediane multi-provider et attribution",
          "median multi-provider" in _board_text
          and "Attribution: Artificial Analysis" in _board_text)

try:
    pricing_sources.SameOriginRedirectHandler().redirect_request(
        urllib.request.Request(pricing_sources.AA_URL), None, 302, "redirect", {},
        "https://evil.example/collect")
    _redirect_blocked = False
except pricing_sources.PricingSourceError:
    _redirect_blocked = True
check("redirect hors origine bloque", _redirect_blocked)

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
# Le controle ci-dessus ne voit que le tableau ; la prose, elle, avait derive
# ("The six blueprints" au-dessus de sept lignes). On lit donc aussi les phrases.
# CHANGELOG.md est exclu a dessein : ses "6 blueprints" datent de la v1.0.0 et
# sont exacts pour cette version. Un journal enregistre le passe, il ne derive pas.
_words = {"six": 6, "seven": 7, "sept": 7, "eight": 8, "huit": 8}
_claims = []
for _doc in ("README.md", "SKILL.md", "docs/SKILL.fr.md", "docs/README.fr.md"):
    _t = open(os.path.join(SK, _doc), encoding="utf-8").read()
    for _m in re.finditer(r"(\d+|six|seven|sept|eight|huit)\s+blueprints", _t, re.I):
        _tok = _m.group(1).lower()
        _n = _words.get(_tok, int(_tok) if _tok.isdigit() else None)
        if _n is not None and _n != _bp:
            _claims.append(f"{_doc}: {_m.group(0)}")
check(f"aucune prose n'annonce un nombre de blueprints != {_bp}",
      not _claims, str(_claims[:3]))
# Le projet refuse les attentes devinees (cf. les deux commentaires de ci.yml) :
# la CI ne doit pas en reintroduire une par commodite.
_naps = re.findall(r"run:\s*sleep\s+\d+", _ci)
check("aucune attente devinee (run: sleep N) dans la CI", not _naps, str(_naps))
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
