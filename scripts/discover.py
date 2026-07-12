"""Auto-découverte d'une instance Grafana pour l'observabilité IA/LLM.

Produit une capability map JSON : identité de l'instance, datasources classées,
dialectes de télémétrie LLM détectés AVEC les noms réels des métriques présentes,
labels Loki, présence de Tempo, et liste des écarts d'instrumentation.

Usage :
    python3 discover.py --out capability_map.json [--insecure]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

# Sortie console en UTF-8 : évite un crash cp1252 sous Windows sur les caractères
# non-ASCII des logs (→, ✅, accents). Sans effet là où la console est déjà UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from grafana_client import GrafanaClient, GrafanaError

# Signatures des dialectes de télémétrie IA. Regex volontairement larges :
# la capability map capture ensuite les noms exacts, base du résolveur de la forge.
DIALECT_SIGNATURES = {
    "otel_genai": r"gen_ai_.*",                    # conventions OTel GenAI (+ OpenLIT)
    "litellm":    r"litellm_.*",                   # passerelle LiteLLM (spend USD natif)
    "vllm":       r"vllm:.*",                      # moteur vLLM
    "tgi":        r"tgi_.*",                       # HuggingFace TGI
    "ollama":     r"ollama_.*",                    # Ollama
    "gpu_dcgm":   r"DCGM_FI_DEV_.*",               # NVIDIA DCGM exporter
    "gpu_smi":    r"nvidia_smi_.*|nvidia_gpu_.*",  # exporters nvidia-smi alternatifs
    "langfuse":   r"langfuse_.*",                  # Langfuse self-hosted
}

# Labels de modèle candidats, par dialecte (le premier trouvé gagne).
MODEL_LABEL_CANDIDATES = {
    "otel_genai": ["gen_ai_request_model", "gen_ai_response_model", "gen_ai_model"],
    "litellm":    ["model", "model_group", "litellm_model_name"],
    "vllm":       ["model_name", "model"],
    "tgi":        ["model_id", "model"],
    "ollama":     ["model"],
}
PROVIDER_LABEL_CANDIDATES = {
    "otel_genai": ["gen_ai_provider_name", "gen_ai_system"],
    "litellm":    ["api_provider", "custom_llm_provider", "llm_provider"],
}
TEAM_LABEL_CANDIDATES = ["team", "team_alias", "service_name", "service", "app",
                         "namespace", "job", "hashed_api_key", "end_user"]

LOKI_AI_HINT_LABELS = ["service_name", "gen_ai_system", "ai_system", "app", "job"]


def probe_prometheus(client: GrafanaClient, ds: dict) -> dict:
    """Sonde une datasource prometheus-like : dialectes + noms réels + labels utiles."""
    found = {}
    for dialect, pattern in DIALECT_SIGNATURES.items():
        names = client.prom_metric_names(ds, pattern)
        if names:
            entry = {"metric_names": names[:400]}
            sample = f'{{__name__=~"{pattern}"}}'
            for cand in MODEL_LABEL_CANDIDATES.get(dialect, []):
                vals = client.prom_label_values(ds, cand, match=sample)
                if vals:
                    entry["model_label"] = cand
                    entry["models_seen"] = vals[:60]
                    break
            for cand in PROVIDER_LABEL_CANDIDATES.get(dialect, []):
                vals = client.prom_label_values(ds, cand, match=sample)
                if vals:
                    entry["provider_label"] = cand
                    entry["providers_seen"] = vals[:40]
                    break
            if dialect == "otel_genai":
                for cand in ("gen_ai_token_type", "token_type", "gen_ai_usage_type"):
                    vals = client.prom_label_values(ds, cand, match=sample)
                    if any(v in ("input", "output") for v in vals):
                        entry["token_type_label"] = cand
                        break
            for cand in TEAM_LABEL_CANDIDATES:
                vals = client.prom_label_values(ds, cand, match=sample)
                if vals and len(vals) <= 500:
                    entry.setdefault("group_labels", []).append(
                        {"label": cand, "cardinality": len(vals)})
            found[dialect] = entry
    return found


def build_capability_map(client: GrafanaClient) -> dict:
    cap = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "instance": {
            "url": client.base,
            "version": client.version(),
            "major": client.major_version(),
            "edition": client.edition(),
            "namespace": client.namespace(),
            "apis": {"legacy": True, "resource": client.has_resource_api()},
        },
        "datasources": {"prometheus": [], "loki": [], "tempo": [], "other": []},
        "signals": {},
        "gaps": [],
    }
    try:
        all_ds = client.datasources()
    except GrafanaError as e:
        if e.status == 403:
            cap["gaps"].append("Token sans droit de lister les datasources "
                               "(rôle Viewer insuffisant → passer en Editor/Admin).")
            all_ds = []
        else:
            raise

    proms = client.prometheus_like() if all_ds else []
    for ds in all_ds:
        meta = {"uid": ds.get("uid"), "name": ds.get("name"), "type": ds.get("type"),
                "default": ds.get("isDefault", False)}
        if ds in proms:
            cap["datasources"]["prometheus"].append(meta)
        elif ds.get("type") == "loki":
            cap["datasources"]["loki"].append(meta)
        elif ds.get("type") == "tempo":
            cap["datasources"]["tempo"].append(meta)
        else:
            cap["datasources"]["other"].append(meta)

    for ds in proms:
        signals = probe_prometheus(client, ds)
        if signals:
            cap["signals"][ds["uid"]] = signals

    for meta in cap["datasources"]["loki"]:
        ds = next(d for d in all_ds if d.get("uid") == meta["uid"])
        labels = client.loki_labels(ds)
        meta["labels"] = [l for l in labels if l in LOKI_AI_HINT_LABELS] or labels[:20]

    # ------------------------------------------------------------------ Gaps
    dialects = {d for s in cap["signals"].values() for d in s}
    if not cap["datasources"]["prometheus"]:
        cap["gaps"].append("Aucune datasource Prometheus/Mimir : brancher un backend "
                           "métriques est le prérequis n°1 (voir instrumentation_guide.md).")
    elif not dialects & {"otel_genai", "litellm", "vllm", "tgi", "ollama"}:
        cap["gaps"].append("Prometheus présent mais aucun signal LLM détecté "
                           "(gen_ai_*, litellm_*, vllm:*…) : instrumenter les apps ou "
                           "déployer LiteLLM en passerelle (instrumentation_guide.md).")
    if "otel_genai" in dialects and not cap["datasources"]["tempo"]:
        cap["gaps"].append("Signaux OTel GenAI présents mais pas de Tempo : le tracing "
                           "agents/RAG sera limité aux métriques (pas de vue trace).")
    if not cap["datasources"]["loki"]:
        cap["gaps"].append("Pas de Loki : preuves de journalisation AI Act (Art. 12/26) "
                           "non visualisables dans Grafana.")
    if dialects & {"vllm", "tgi", "ollama"} and not dialects & {"gpu_dcgm", "gpu_smi"}:
        cap["gaps"].append("Inference self-hosted détectée sans métriques GPU : "
                           "déployer dcgm-exporter pour corréler saturation/latence.")
    return cap


def summarize(cap: dict) -> str:
    inst = cap["instance"]
    lines = [f"Grafana {inst['version']} ({inst['edition']}), "
             f"API resource: {'oui' if inst['apis']['resource'] else 'non'}"]
    for kind in ("prometheus", "loki", "tempo"):
        n = len(cap["datasources"][kind])
        if n:
            lines.append(f"  {kind}: {n} datasource(s)")
    for uid, sigs in cap["signals"].items():
        for dial, info in sigs.items():
            extra = ""
            if info.get("models_seen"):
                extra = f" — {len(info['models_seen'])} modèle(s) vus"
            lines.append(f"  [{uid}] dialecte {dial}: "
                         f"{len(info['metric_names'])} métriques{extra}")
    for g in cap["gaps"]:
        lines.append(f"  GAP: {g}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="capability_map.json")
    ap.add_argument("--insecure", action="store_true",
                    help="Ignorer la vérification TLS (labs uniquement)")
    args = ap.parse_args()

    client = GrafanaClient(insecure=args.insecure)
    cap = build_capability_map(client)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(cap, f, indent=2, ensure_ascii=False)
    print(summarize(cap))
    print(f"\nCapability map → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
