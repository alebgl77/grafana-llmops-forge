<div align="center">

<img src="docs/assets/banner.svg" alt="grafana-llmops-forge" width="100%"/>

# grafana-llmops-forge

**Point it at any Grafana. Get a complete AI/LLM observability suite — discovered, generated, deployed, and *visually verified*.**

[![CI](https://img.shields.io/badge/CI-27%2F27%20checks-3fb950?logo=githubactions&logoColor=white)](.github/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.8%2B%20·%20stdlib%20only-3776AB?logo=python&logoColor=white)](#-security-model)
[![Zero deps](https://img.shields.io/badge/dependencies-0-3fb950)](#-security-model)
[![Grafana](https://img.shields.io/badge/Grafana-9%20→%2013%2B%20·%20OSS%20·%20Cloud%20·%20Enterprise-F46800?logo=grafana&logoColor=white)](references/grafana_api_compat.md)
[![Agent Skill](https://img.shields.io/badge/format-Agent%20Skill%20(open%20standard)-d2a8ff)](https://agentskills.io)
[![EU AI Act](https://img.shields.io/badge/EU%20AI%20Act-observability%20mapped-2ea043)](references/eu_ai_act_observability.md)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

**English** · [Français](docs/README.fr.md)

</div>

---

Your teams ship LLM features. Your CFO asks what they cost. Your board asks about the **EU AI Act**. Your SREs get paged about latency on a system nobody instrumented. And your Grafana — the tool you already trust — shows none of it.

`grafana-llmops-forge` fixes that with **one prerequisite: a reachable Grafana** (URL + service-account token). Everything else is discovered, not assumed.

```bash
export GRAFANA_URL=https://grafana.your-company.com GRAFANA_TOKEN=glsa_...

python3 scripts/discover.py --out capability_map.json          # ① what do you actually have?
python3 scripts/forge_dashboards.py \
        --capability capability_map.json \
        --blueprints auto --deploy --with-alerts               # ② forge + deploy + SLO alerts
python3 scripts/visual_audit.py --dashboards generated_dashboards  # ③ prove it renders right
```

<div align="center"><img src="docs/assets/dashboard-finops.svg" alt="Generated FinOps dashboard" width="100%"/>
<sub><i>The FinOps blueprint — costs composed from a 30-model price registry, split by provider sovereignty (EU / US / Asia).</i></sub></div>

## Why this is different

Most "LLM dashboards" are static JSON that assume your metric names. This is a **forge**:

1. **Discovery-first, never assume.** `discover.py` probes your datasources and captures the *actual* metric names present (OTel exporters disagree on suffixes — `_seconds`, `_token`, `_total`). Panels are only generated for queries that will return data. Missing signals become an **instrumentation gap report** with exact configs, not empty panels.
2. **Four telemetry dialects, one mental model.** OpenTelemetry GenAI (`gen_ai_*`), LiteLLM gateway (`litellm_*`, native USD spend), inference engines (`vllm:*`, `tgi_*`), GPU (`DCGM_*`). Each blueprint is translated into whatever you actually emit.
3. **Cost is computed, not hoped for.** Native gateway spend when available; otherwise PromQL composed by joining your token counters with a bundled **30-model price registry** (US/EU/Asia, input/output/cached, tiered pricing) — refreshable from official pricing pages when stale.
4. **Governance is observable.** The EU AI Act dashboard maps articles (12, 26§6, 50, 73) to live signals: logging evidence, retention posture, incident watch, an auto-built model inventory with sovereignty and GPAI flags, and the post-Digital-Omnibus timeline.
5. **Verified by eye, not just by API.** HTTP 200 proves the JSON was accepted — not that the render is right. After deploy, `visual_audit.py` captures every panel (native Grafana renderer, Playwright fallback) and an AI vision pass checks scale plausibility, "No data" panels, p50>p95 impossibilities, cross-panel coherence — then loops remediation (max 2 iterations, then an honest report).

<div align="center"><img src="docs/assets/architecture.svg" alt="Pipeline" width="100%"/></div>

## The six blueprints

| Dashboard | Answers | Key panels |
|---|---|---|
| 💰 **Executive FinOps** | *What does AI cost, where, is it drifting?* | spend/day, cost/request, **sovereignty split 🇪🇺🇺🇸🌏**, per-team spend, top models, unpriced-models watchlist |
| 🛡 **Gateway Operations** | *Are we meeting SLOs right now?* | availability, p50/p95/p99, **TTFT**, errors by type, provider rate-limit headroom, `$model` variable |
| 🤖 **Agents & RAG** | *What do our agents do, where do they fail?* | invoke/tool rates, per-tool errors, tokens per agent, embeddings latency, **TraceQL panel** (Tempo) |
| 📈 **Adoption** | *Who actually adopted what?* | active teams, **new adopters (7d)**, model mix over time, top token consumers — shadow AI shows up here |
| ⚡ **Inference (self-hosted)** | *Do our GPUs hold, at what cost vs API?* | vLLM TTFT/TPOT, queue, **KV-cache saturation**, preemptions, GPU util/VRAM, API-price benchmark table |
| ⚖ **EU AI Act Governance** | *What do we show an auditor?* | regulatory timeline (July 2026, post-Omnibus), logging evidence (Art. 12/26§6), **auto model inventory** (region/license/GPAI), incident watch (Art. 73) |

Plus **5 provisioned SLO alerts**: error ratio >5%, telemetry signal lost, daily budget breach (`--daily-budget`), TTFT p95 >3s, vLLM KV-cache >92%.

## Quick start

<details>
<summary><b>As an Agent Skill (Claude, or any agentskills.io-compatible agent)</b></summary>

Drop the folder into your skills directory (or install the packaged `.skill` from [Releases](../../releases)), then just talk:

> *"Audit my Grafana at https://grafana.internal and deploy whatever makes sense — then prove it visually."*

The skill handles discovery → registry refresh → blueprint selection → deploy → vision-verified loop, and reports gaps with exact instrumentation configs.
</details>

<details>
<summary><b>As a standalone CLI (no AI required)</b></summary>

Pure Python 3.8+ stdlib. No pip install. The three commands at the top of this README are the whole workflow. `--dry-run` writes JSON without touching your instance; `--selftest` renders all six blueprints offline from a simulated capability map.
</details>

<details>
<summary><b>No LLM telemetry yet?</b></summary>

Run discovery anyway. You'll get a prioritized gap report, and [`references/instrumentation_guide.md`](references/instrumentation_guide.md) contains copy-paste configs ordered by value/effort: **LiteLLM gateway (~30 min → native USD spend)** → OTel GenAI SDK setup → vLLM/TGI scrape → dcgm-exporter → Loki retention for AI-Act evidence.
</details>

## 🔒 Security model

Skills execute code — [a 2026 Snyk audit found 36% of published skills had at least one flaw](https://github.com/obviousworks/Claude-AI-skills-collection-2026#security). This repo is designed to be auditable in one sitting:

- **Zero dependencies.** Python stdlib only (`urllib`, `json`, `hashlib`). ~2,000 lines total. Playwright is *optional*, only for the visual-audit fallback.
- **Least privilege.** Works with an Editor service-account token. Alert provisioning degrades gracefully on 403 (exports JSON for manual import).
- **No secret leakage.** The token is never logged, never embedded in dashboards, never placed in URLs.
- **No prompt-content capture.** `gen_ai.input/output.messages` stay off by default; the docs treat enabling them as a GDPR decision, not a flag.
- **Idempotent & reversible.** Deterministic UIDs, one folder, `overwrite` semantics — delete the folder, it's gone.
- **Offline-testable.** `--selftest` + `tests/audit_harness.py` (27 checks, 4 instance topologies) run with zero network. That's the CI.

## Repo layout

```
SKILL.md                      # agent playbook (7-phase pipeline, doctrine, pitfalls)
scripts/
  grafana_client.py           # universal client: OSS/Cloud/Enterprise, legacy + K8s-style APIs
  discover.py                 # capability map: real metric names, dialects, gaps
  forge_dashboards.py         # 6 blueprints × detected dialect, cost engine, alerts
  visual_audit.py             # render/Playwright capture + DOM pre-scan for vision review
references/
  model_registry.json         # 30+ models: $/1M in·out·cached, context, sovereignty, GPAI
  query_library.md            # PromQL/LogQL/TraceQL per dialect, anti-patterns
  dashboard_blueprints.md     # panel-by-panel specs + optional extensions
  instrumentation_guide.md    # exact configs to close each gap
  eu_ai_act_observability.md  # article → signal → panel mapping, deployer checklist
  visual_verification.md      # vision checklist, failure signatures → fixes
  grafana_api_compat.md       # 3 API generations, editions matrix, schema v2 notes
tests/audit_harness.py        # 27 offline checks across 4 instance topologies
```

## FAQ

**Does it overwrite my existing dashboards?** No — everything lives in its own folder with `llmops-forge`-tagged, deterministically-UID'd dashboards. Re-running updates in place.

**Grafana Cloud?** Yes. Cloud is auto-detected; the image renderer is built in, so visual audit works out of the box.

**My models aren't in the registry.** They appear in an "unpriced models" panel instead of being billed wrong. Add a price or alias to `model_registry.json`, re-forge. (The matcher scores by specificity — `gpt-5.4-mini` will never be billed at `gpt-5.4` rates; there's a test for that.)

**Is the AI Act dashboard legal advice?** No, and it says so on the dashboard. It's the *evidence layer* your counsel will ask you for.

## Roadmap

- [ ] Native schema-v2 output (tabs/conditional layouts) for Grafana 13+ as-code shops
- [ ] Cache-savings & budget burn-down panels (specs in `dashboard_blueprints.md`)
- [ ] OpenAI/Gemini usage-API pollers for orgs with zero telemetry
- [ ] Terraform/Grafana-as-code export mode

## Contributing

Model prices drift quarterly — **registry PRs are the most valuable contribution** and take 2 minutes ([guide](CONTRIBUTING.md)). Dialect additions (new gateway/engine signatures) are second. `python3 tests/audit_harness.py` must stay green.

<div align="center">
<sub>Built with the <a href="https://agentskills.io">Agent Skills</a> open standard · works in Claude Code, Claude.ai, Cowork, and as a plain CLI.<br/>
If this saved your platform team a sprint, a ⭐ helps the next DSI find it.</sub>
</div>
