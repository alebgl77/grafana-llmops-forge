---
name: grafana-llmops-forge
description: Runs end-to-end AI/LLM observability on any Grafana (OSS, Cloud, Enterprise) with a single prerequisite — a reachable Grafana instance. Auto-discovers the instance (version, APIs, datasources), detects which LLM telemetry dialects are actually present (OpenTelemetry GenAI gen_ai.*, LiteLLM, vLLM, TGI, GPU/DCGM, eval scores), then generates and deploys dashboards — FinOps and multi-provider cost by sovereignty (US/EU/Asia), gateway SLOs, agent and RAG tracing, internal adoption, quality evaluations, EU AI Act governance, self-hosted inference — plus burn-rate SLO alerts, cost recording rules, and a visual verification pass on the rendered dashboards. Use this skill whenever the user mentions Grafana, dashboards, AI or LLM monitoring or observability, token costs, AI FinOps, LLMOps, agents or RAG, model adoption, AI Act compliance, or Prometheus/Loki/Tempo applied to AI — even without the word dashboard. Also use it to audit an existing Grafana or an AI stack that emits nothing yet.
---

# Grafana LLMOps Forge

Turns any Grafana instance into an AI/LLM command centre for a platform team: discovery, dashboard generation, alerting, FinOps, EU AI Act governance. Single prerequisite: `GRAFANA_URL` + a service-account token. Everything else is discovered or provisioned.

## Doctrine (what makes this different)

1. **Discovery-first, never assume.** Never generate a panel "just in case". Probe the instance and its datasources, capture the **real metric names**, and only build panels whose queries will return data. OTel exporters disagree on suffixes (`_seconds`, `_token`, `_total`): the capability map is the source of truth, not theory.
2. **Four telemetry dialects, one mental model.** LLM signals arrive in four practical shapes: OTel GenAI conventions (`gen_ai_*` — Development status, v1.4x, opt-in `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`), LiteLLM gateway (`litellm_*`, native USD spend), inference engines (`vllm:*`, `tgi_*`), and GPU (`DCGM_*`). Evaluation signals (`gen_ai_evaluation_*`, RAGAS, guardrails) form a fifth, optional one. Each blueprint is translated into whatever is actually emitted.
3. **Cost is computed, not hoped for.** Prefer recorded cost (`llm:cost_usd_per_second`), then native gateway spend, then on-the-fly composition against the bundled price registry. The registry carries a verification date; if it is older than 30 days and web search is available, refresh the prices of the **detected** models from the official pages BEFORE generating cost panels (protocol in `references/model_registry.json`, key `_meta.refresh_protocol`).
4. **Governance is observable.** The AI Act requires logging (Art. 12), deployer-side retention of at least six months (Art. 26§6), serious-incident reporting (Art. 73) and transparency (Art. 50). The governance dashboard maps articles to measurable signals, with the verified post-Digital-Omnibus timeline. This is not legal advice — say so explicitly to the user.
5. **Total idempotence.** Deterministic UIDs (name hash), upsert with overwrite, a single "AI Observability" folder. Re-running the forge is always safe. `--dry-run` covers everything that writes.
6. **Graceful degradation.** No LLM signal is not a failure: produce an **instrumentation gap report** (what to wire, in which order, with the exact configs from `references/instrumentation_guide.md`), and still deploy the governance dashboard (it works without metrics).
7. **Verified by eye, not just by API.** HTTP 200 proves the JSON was accepted, not that the render is correct. At strategic moments (post-deploy, handing over the governance dashboard, after closing a gap), capture the real rendering (`visual_audit.py`: native Grafana renderer, Playwright fallback), then **inspect the PNGs with vision** using the checklist in `references/visual_verification.md` — scale plausibility ($, latencies), "No data" panels, cross-panel coherence — and loop remediation (max two iterations). Never announce a successful deployment without a visual verdict when capture is possible.

## Standard pipeline

Run these phases in order. Every script is Python 3 stdlib only (no `pip install`).

### Phase 0 — Credentials

```bash
export GRAFANA_URL="https://grafana.example.com"     # no trailing slash
export GRAFANA_TOKEN="glsa_..."                       # service-account token
# Accepted fallback: GRAFANA_USER + GRAFANA_PASSWORD (basic auth)
```

If the user has no token: Administration → Users and access → Service accounts → create an **Editor** account (Admin if alert/datasource provisioning is wanted) → Add service account token. On Grafana Cloud the URL is `https://<stack>.grafana.net`. Never print the token, in answers or generated files.

### Phase 1 — Discovery

```bash
python3 scripts/discover.py --out capability_map.json
# --datasource <uid|name> to target one datasource (prod vs staging)
```

Produces the capability map: version/edition/namespace, API availability (legacy `/api` vs resource `/apis/dashboard.grafana.app`), classified datasources, LLM dialects detected **with real metric names**, exemplar routing, Loki labels, and the gap list. Read the JSON and **summarise the findings to the user before continuing** — this is the moment to catch a wrong datasource or a staging instance.

### Phase 2 — Model registry

Read `references/model_registry.json`. If `_meta.verified_at` is more than 30 days old AND web search is available: refresh the prices of the models actually present in the capability map (not the whole registry) from the URLs in `_meta.sources`, then write `model_registry.local.json` next to the capability map. The generator loads the local file first. Without web access, use the seed as-is — cost dashboards display the registry date in their description.

### Phase 2b — Cost recording rules (strongly recommended)

Every run writes `prometheus_rules_llmops.yml`: prices become series (`llm:price_*_usd_per_token{<model_label>=…}`) and cost becomes an aggregate metric (`llm:cost_usd_per_second`) joined by vector matching. Copy that file into Prometheus `rule_files` and reload: on the next run `discover.py` detects the `recorded` dialect and cost panels drop from a 2N-term sum to an O(1) query — unlimited models, and prices updatable without regenerating dashboards. Without it, on-the-fly composition stays active (40-model ceiling).

### Phase 3 — Blueprint selection

Seven blueprints. Choose from the request plus the capability map (do not re-ask the user for something already expressed):

| Blueprint | ID | Activation condition |
|---|---|---|
| Executive FinOps & cost | `finops` | tokens or spend detected (otel/litellm/recorded) |
| Gateway operations (latency, errors, TTFT) | `gateway` | otel or litellm |
| Agents & RAG (traces, tools, workflows) | `agents` | otel + ideally Tempo; otel alone gives the metrics-only version |
| Internal adoption (teams, apps, model mix) | `adoption` | otel or litellm |
| Self-hosted inference (vLLM/TGI + GPU) | `inference` | vllm/tgi/ollama or DCGM detected |
| Quality & evaluations | `quality` | eval scores detected (RAGAS, LLM judge, guardrails) |
| EU AI Act governance | `governance` | always available (degrades gracefully) |

### Phase 4 — Forge and deploy

```bash
python3 scripts/forge_dashboards.py --capability capability_map.json --blueprints auto --deploy --with-alerts
python3 scripts/forge_dashboards.py --capability capability_map.json --blueprints finops,governance --deploy
python3 scripts/forge_dashboards.py --capability capability_map.json --blueprints auto --dry-run
# Useful options:
#   --slo-target 0.995      burn-rate SLO target (default 0.99)
#   --cost-mode recorded    force recording rules (default: auto-detected)
#   --export-portable       ${DS_*} JSON, publishable on grafana.com/dashboards
#   --datasource <uid|name> pin one datasource
```

The script generates the JSON (classic schema v41 — identical behaviour across OSS/Cloud/Enterprise from v9 to v13, deployed through the legacy API with a K8s-style resource-API fallback), creates the folder, upserts the dashboards, provisions SLO alerts (`--with-alerts`: two-window error burn-rate at 5m/1h and 30m/6h per the SRE method, TTFT p95, daily budget, KV-cache saturation, eval-score drop, and signal loss — that last one with `noDataState: Alerting`, without which it would stay silent precisely when telemetry dies), writes `deploy_manifest.json`, then prints the URLs. Always relay the final URLs to the user.

### Phase 4b — Visual check (vision) — mandatory after any deploy

```bash
python3 scripts/visual_audit.py --dashboards generated_dashboards --out visual_audit
```

Engine auto-selection: native `/render/...` (image-renderer plugin; bundled on Cloud), otherwise Playwright (real headless browser, Bearer header auth, kiosk mode, DOM pre-scan for "No data" and errors). Then **open the PNGs with vision** (`visual_audit/<dash>/full.png` first, suspicious panels next, mapping in `audit_manifest.json`) and apply the checklist and the signature-to-fix table in `references/visual_verification.md`. Verdict per dashboard (✅/⚠/❌), remediate at the source (registry, capability map, code — never the UI), re-forge, re-capture only what was fixed, two iterations maximum. The same script checks non-dashboard settings (datasources, alert rules) through Playwright — see §6 of that reference.

### Phase 5 — Gap report

If requested blueprints are blocked by missing signals: read `references/instrumentation_guide.md` and produce an instrumentation plan ordered by value/effort (typically: 1. LiteLLM in front of providers → immediate spend; 2. OTel GenAI in the apps → agent traces; 3. DCGM if GPUs are on-prem). Give exact configs, not generalities.

### Phase 6 — Report back

Standard output shape: what was **detected** → what was **deployed** (URLs) → what is **missing** and how to close it → dated next steps if governance is active (AI Act deadlines). A platform team reads this in ninety seconds.

## Extending beyond the blueprints

The scripts cover the deterministic core. To extend (extra panels, specific queries, custom variables):
- `references/query_library.md` — PromQL/LogQL/TraceQL library per dialect, ready to paste.
- `references/dashboard_blueprints.md` — panel-by-panel specification, including optional panels not generated by default.
- `references/grafana_api_compat.md` — OSS/Cloud/Enterprise matrix, legacy vs resource APIs, Cloud namespaces (`stacks-<id>`), schema v2 and when to use it.
- To add a panel to an already-deployed dashboard: regenerate through the forge (code is the source of truth), never edit silently in the UI — the next run overwrites.

## Known pitfalls

- **OTel→Prometheus suffixes vary**: `gen_ai.client.token.usage` may surface as `gen_ai_client_token_usage_token_*`, `..._tokens_*`, or without a unit. The resolver matches on prefixes captured in Phase 1; never hardcode a name without checking the capability map.
- **Cardinality**: never group by `gen_ai.conversation.id` or any unique ID in a time series. The forge drops group-by labels above 300 values and bounds grouped panels with `topk`.
- **Tiered pricing**: some models change price beyond a context threshold; the registry carries `tiered_pricing` and the cost panel then notes "low estimate".
- **Grafana Cloud**: the legacy dashboard API works, but provisioned alerts need the right `folderUID` and a sufficient role; on 403, degrade by exporting the rules as JSON and explain manual import.
- **Multi-datasource**: the forge uses one datasource per dialect. If discovery reports several (prod + staging), ask which one and re-run with `--datasource`.
- **Exemplars**: if Tempo exists but the Prometheus datasource does not route exemplars, flag it — that is the missing metric→trace navigation, not a cosmetic detail.
- **Prompt content**: never encourage capturing `gen_ai.input.messages`/`output.messages` by default (sensitive data). If the user wants it: explicit opt-in plus the precautions in `instrumentation_guide.md`.
- **Missing renderer**: a 404 on `/render/...` means the grafana-image-renderer plugin is absent (one-line install in `visual_verification.md` §5); fall back to `--engine playwright`. Behind an SSO proxy where Bearer is rejected: `GRAFANA_COOKIE`.
- **Sensitive captures**: audit PNGs contain costs, team names and models — keep them local, share deliberately, purge after the audit if the environment requires it.
- **Never** store the token in a dashboard, a committed config file, or any printed output.

## Offline self-test

With no instance available (demo, CI, skill development):

```bash
python3 scripts/forge_dashboards.py --selftest
```

Generates a simulated capability map (all dialects), renders the seven blueprints, validates the invariants (unique panel IDs, gridPos inside the 24-column grid, non-empty targets, resolved expressions) and writes the JSON to `./selftest_output/`. Also useful to show the user what the dashboards will look like before touching their instance.

For a full end-to-end run against a real Grafana, `make demo` boots Grafana + Prometheus + a synthetic LLM metrics emitter and runs the whole pipeline.
