<div align="center">

<a href="README.md">English</a> · <a href="README.fr.md">Français</a>

<img src="assets/hero.png" alt="Grafana LLMOps Forge — turn any Grafana into an AI/LLM observability command center" width="100%">

# Grafana LLMOps Forge

### Turn **any Grafana** into an AI/LLM observability command center — LLMOps, FinOps &amp; EU AI Act governance, auto-discovered and auto-forged.

[![License: MIT](https://img.shields.io/badge/License-MIT-3BA55D.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-4C9AFF?logo=python&logoColor=white)](#requirements)
[![Dependencies: zero](https://img.shields.io/badge/dependencies-zero%20(stdlib%20only)-8B7BFF)](#requirements)
[![Grafana](https://img.shields.io/badge/Grafana-OSS%20%C2%B7%20Cloud%20%C2%B7%20Enterprise-F46800?logo=grafana&logoColor=white)](#compatibility)
[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-D97757?logo=anthropic&logoColor=white)](#use-it-as-a-claude-code-skill)
[![CI](https://github.com/alebgl77/grafana-llmops-forge/actions/workflows/ci.yml/badge.svg)](https://github.com/alebgl77/grafana-llmops-forge/actions/workflows/ci.yml)

**Prerequisite: a Grafana URL + a service-account token. Everything else is discovered or provisioned.**

`No data leaves your infrastructure` · `no pip install (stdlib only)` · `idempotent & --dry-run` · `the token is never logged`

</div>

---

## What is Grafana LLMOps Forge?

**Grafana LLMOps Forge is a discovery-first, zero-dependency Python toolkit (and a Claude Code / Agent Skill) that turns a Grafana instance you already run into an AI/LLM observability command center.** You give it one URL and a token; it discovers the LLM telemetry actually present, forges cost, gateway, agent, adoption, inference and EU AI Act governance dashboards from your *real* metric names, provisions SLO alerts, and then vision-verifies the rendered result. It is a **complement** to Langfuse, Phoenix, OpenLIT or plain OpenTelemetry — not a replacement.

- 🔭 **Auto-discovers 4 telemetry dialects** — OpenTelemetry GenAI (`gen_ai.*`), LiteLLM spend, self-hosted inference (vLLM / TGI / Ollama), and NVIDIA DCGM GPU — capturing the metric names that really exist, so it only builds panels that will return data.
- 🧱 **Forges 6 dashboard blueprints** — FinOps & cost, gateway operations, agents & RAG tracing, adoption, self-hosted inference, and EU AI Act governance — plus SLO alert rules.
- 💶 **Computes cost, doesn't guess it** — an embedded, date-stamped registry of ~30 models (input/output/cache, US/EU/Asia sovereignty) composed into PromQL inside your own Grafana.
- 👁️ **Vision-verifies the render** — screenshots the real dashboards and inspects them for implausible scales, "No data" panels, and cross-panel inconsistency before declaring success.

<div align="center">
<img src="assets/pipeline.png" alt="Discover → Price → Forge → Deploy → Verify pipeline" width="100%">
</div>

---

## Quick start

### Try it in 60 seconds — offline, no Grafana, no signup

```bash
git clone https://github.com/alebgl77/grafana-llmops-forge
cd grafana-llmops-forge

# Renders all six dashboards as JSON from a simulated capability map
python3 scripts/forge_dashboards.py --selftest
```

You'll get the six dashboard JSONs in `./selftest_output/` — a good way to inspect the panels and PromQL before pointing it at anything real.

### Point it at a real Grafana

```bash
export GRAFANA_URL="https://grafana.example.com"     # no trailing slash
export GRAFANA_TOKEN="glsa_..."                       # service-account token (Editor role)

# 1) Discover what telemetry your instance actually has
python3 scripts/discover.py --out capability_map.json

# 2) Forge & deploy everything that's activatable, with SLO alerts
python3 scripts/forge_dashboards.py --capability capability_map.json \
        --blueprints auto --deploy --with-alerts

# 3) Capture the real render for vision review
python3 scripts/visual_audit.py --dashboards generated_dashboards --out visual_audit
```

> No service-account token yet? In Grafana: **Administration → Users and access → Service accounts** → create one with the **Editor** role (Admin if you also want alert provisioning) → **Add service account token**. On Grafana Cloud the URL is `https://<stack>.grafana.net`.

Prefer to preview before writing anything? Add `--dry-run` to step 2 — everything that writes supports it.

---

## The 6 dashboards it forges

| Blueprint | The question it answers | Activates when |
|---|---|---|
| 💶 **Executive FinOps & Cost** | *What is AI costing us, where, and is it drifting?* | tokens or spend detected (OTel / LiteLLM) |
| 🚦 **Gateway Operations** | *Is the LLM service meeting its SLOs right now?* | OTel or LiteLLM |
| 🕸️ **Agents & RAG** | *What do our agents do, where do they fail, what do they cost?* | OTel (+ Tempo ideally) |
| 📈 **Adoption** | *Who actually adopted what?* | OTel or LiteLLM |
| 🖥️ **Self-hosted Inference** | *Are our GPUs holding up, and at what cost vs API?* | vLLM / TGI / Ollama or DCGM |
| ⚖️ **EU AI Act Governance** | *What do we show an auditor or the risk committee?* | always (works degraded) |

<div align="center">
<img src="assets/dashboard-finops.png" alt="Executive FinOps & Cost dashboard — spend by sovereignty, top models, cost per request" width="100%">
<br><em>Executive FinOps & Cost — illustrative render from <code>--selftest</code> synthetic data.</em>
</div>

---

## How it works

<div align="center">
<img src="assets/architecture.png" alt="Architecture: 4 auto-detected telemetry dialects feed a stdlib-only discovery-first engine that forges 6 dashboards on your Grafana" width="100%">
</div>

The forge emits the **classic dashboard schema (v41) via the legacy API** — the one combination that works identically from Grafana 9 to 13+, across OSS, Cloud and Enterprise, with no feature flags. Every run is idempotent: deterministic UIDs, upsert with overwrite, a single `AI Observability` folder. Re-running is always safe.

### Discovery-first — never assume, always probe

Exporters disagree on suffixes: `gen_ai.client.token.usage` can surface as `gen_ai_client_token_usage_token_*`, `..._tokens_*`, or with no unit at all. So the forge never hard-codes a metric name. `discover.py` probes your datasources, captures the **names that really exist**, and the generator resolves each blueprint against that capability map — building only panels backed by a real signal. **Zero signal for a domain → an instrumentation-gap report, not a broken dashboard.**

### Cost is computed, not hoped

When a gateway exposes native spend (LiteLLM, USD), the forge uses it. Otherwise it **composes PromQL** by joining your token counters to the embedded model registry — input/output/cache pricing per model, tagged by region (🇺🇸 US / 🇪🇺 EU / 🌏 Asia). The registry is date-stamped; every cost panel shows its `verified_at` date so you never trust stale pricing by accident.

### Vision-verified rendering

An HTTP 200 proves the JSON was accepted, not that the render is right. After deploying, `visual_audit.py` captures the real dashboards (native Grafana renderer, or a Playwright browser fallback) and the PNGs are inspected **by vision** — scale plausibility ($ , latencies), "No data" panels, cross-panel coherence — then a bounded remediation loop fixes issues at the source and re-forges. Most tools validate the data path; this one validates what a human would actually see.

---

## Why Grafana LLMOps Forge vs. the alternatives?

It sits on a different layer from the trace/eval backends. **They are where telemetry is stored; this is what turns whatever you already emit into cost, ops and governance dashboards — on the Grafana you already run.** Already using LiteLLM, OpenLIT, Phoenix or plain OTel `gen_ai`? Perfect — Forge auto-detects your dialect and builds on top of it.

| | **Grafana LLMOps Forge** | Langfuse | Grafana Cloud AI Obs (OpenLIT) | Datadog LLM Obs |
|---|---|---|---|---|
| Runs on the Grafana you already own | ✅ OSS / Ent / Cloud | it *is* the store you route into | Cloud-first | ❌ SaaS |
| Instrumentation required | **none — consumes what exists** | SDK/OTel into Langfuse | OpenLIT SDK | Datadog SDK |
| Discovery of your *real* metric names | ✅ | ❌ fixed schema | ❌ static pre-builts | ❌ |
| Telemetry dialects | **4** (OTel · LiteLLM · vLLM/TGI/Ollama · DCGM) | OTel/SDK | mainly OpenLIT/OTel | its own |
| Multi-region FinOps (US/EU/Asia) | ✅ | ❌ | ❌ | partial |
| EU AI Act article→signal dashboard | ✅ | ❌ (retention only) | ❌ | ❌ |
| Vision-verified render | ✅ | ❌ | ❌ | ❌ |
| Dependencies | **Python stdlib only** | Postgres + ClickHouse | Grafana Cloud service | SaaS agent |
| License | **MIT / OSS** | MIT core + paid cloud | paid | paid |

*Capabilities as of 2026-07; every project evolves — corrections welcome via PR.*

---

## EU AI Act governance — as observability *evidence*

The governance dashboard maps specific EU AI Act articles to **measurable Grafana signals**, so you have something concrete to show an auditor or a risk committee.

| Article | Requirement | Measurable signal |
|---|---|---|
| **Art. 12** | Automatic logging of high-risk systems | log volume per system, continuity (no gaps) |
| **Art. 26§6** | Deployer keeps logs ≥ 6 months | Loki `retention_period ≥ 4392h` + log age |
| **Art. 50** | "You're talking to an AI" disclosure | disclosure counter (if instrumented) |
| **Art. 73** | Serious-incident reporting (short deadlines) | firing alerts + timestamps |

<div align="center">
<img src="assets/dashboard-governance.png" alt="EU AI Act governance dashboard — regulatory timeline, sovereignty traffic, logging evidence, model inventory, incident watch" width="100%">
<br><em>EU AI Act Governance — regulatory timeline, model inventory (region/weights/GPAI), and incident watch.</em>
</div>

> [!IMPORTANT]
> This is a **compliance-observability aid, not legal advice, and not a compliance certification.** Regulatory references are date-stamped (verified 2026-07-12, post-Digital Omnibus) and some underlying standards are still draft — re-verify anything material.

---

## Requirements

- **Python 3.8+** — standard library only. There is nothing to `pip install`.
- **A Grafana instance** (OSS, Cloud, or Enterprise) reachable over HTTP, with a Prometheus-compatible datasource for metric-based dashboards. Loki (logs) and Tempo (traces) unlock the governance and agent-tracing panels.
- Optional, for `visual_audit.py`'s browser engine: `pip install playwright && playwright install chromium` (the native Grafana renderer needs nothing local; it's included on Grafana Cloud).

### Compatibility

Classic schema v41 via the legacy API → Grafana **9 → 13+**, OSS / Cloud / Enterprise. See [`references/grafana_api_compat.md`](references/grafana_api_compat.md) for the full matrix (legacy vs. resource API, Cloud namespaces, schema v2).

---

## Use it as a Claude Code Skill

This repository *is* a [Claude Code / Agent Skill](SKILL.md). Drop it into your skills directory and Claude will drive the whole pipeline — discovery, generation, deployment, and vision-based verification — whenever you mention Grafana, LLM/AI monitoring, token cost, FinOps, LLMOps, agents/RAG, AI Act compliance, or Prometheus/Loki/Tempo applied to AI.

```bash
# example: alongside your other Claude Code skills
git clone https://github.com/alebgl77/grafana-llmops-forge ~/.claude/skills/grafana-llmops-forge
```

---

## Extending it

The scripts cover the deterministic core; the reference library is where you go deeper:

- [`references/query_library.md`](references/query_library.md) — ready-to-paste PromQL / LogQL / TraceQL by dialect.
- [`references/dashboard_blueprints.md`](references/dashboard_blueprints.md) — panel-by-panel spec of the 6 blueprints, including optional panels.
- [`references/instrumentation_guide.md`](references/instrumentation_guide.md) — close the gaps: LiteLLM, OTel GenAI, vLLM, DCGM, Loki retention, with exact configs.
- [`references/model_registry.json`](references/model_registry.json) — the dated pricing registry (add your self-hosted prices in `model_registry.local.json`).

To add a panel, extend the forge (the source of truth) and re-run — never hand-edit a deployed dashboard, or the next run overwrites it.

---

## Roadmap

- [ ] Native schema-v2 (dynamic dashboards / tabs) output for Grafana 13+ as-code teams
- [ ] More dialects (Langfuse self-hosted metrics, additional gateways)
- [ ] Per-feature / per-app cost attribution panel pack
- [ ] Scheduled PDF export of the governance board to the risk committee (Enterprise/Cloud)
- [ ] Community pricing-registry contributions workflow

Have a request? [Open an issue](https://github.com/alebgl77/grafana-llmops-forge/issues) or a [discussion](https://github.com/alebgl77/grafana-llmops-forge/discussions).

---

## FAQ

**Does it require `pip install`?**
No. Pure Python 3 standard library — zero dependencies, no supply chain, fully auditable. It drops into locked-down enterprise/DSI environments where new packages are hard to approve.

**Which Grafana editions does it support?**
OSS, Cloud, and Enterprise. It runs entirely against the Grafana you already operate — no new backend, and no trace or cost data ever leaves your perimeter.

**What telemetry does it auto-detect?**
Four dialects: OpenTelemetry GenAI (`gen_ai.*`), LiteLLM (`litellm_*` spend), self-hosted inference (vLLM / TGI / Ollama), and NVIDIA DCGM GPU. Discovery reads the metric names actually present and only emits panels that will return data.

**Is this a replacement for Langfuse, Phoenix, or Datadog?**
No — it's a complement. Those are trace/eval backends you route data into; Forge is the discovery-first generation and governance layer that visualizes and governs whatever they (or plain OTel) already emit, on your existing Grafana.

**Does it make me EU AI Act compliant?**
No, and it is not legal advice. The governance dashboard maps AI Act articles (e.g. 12, 26, 50, 73) to measurable Grafana signals so you have observability *evidence* to show an auditor. References are date-stamped and some underlying standards are still draft.

**How accurate is the cost math?**
It uses an embedded, date-stamped registry of ~30 models (input/output/cache, US/EU/Asia) composed into PromQL. Every cost panel shows the registry's verification date, and the registry follows a 30-day refresh protocol.

**How do I try it without a live Grafana?**
Run `python3 scripts/forge_dashboards.py --selftest` — it generates all six dashboards as JSON from a simulated capability map in seconds, no signup and no instance required.

---

## Contributing & security

Contributions are welcome — start with [`CONTRIBUTING.md`](CONTRIBUTING.md) and look for [`good first issue`](https://github.com/alebgl77/grafana-llmops-forge/labels/good%20first%20issue). The two rules that never bend: **zero third-party dependencies** and **discovery-first** (no hard-coded metric names). Please report vulnerabilities privately per [`SECURITY.md`](SECURITY.md).

## License

[MIT](LICENSE) © 2026 Alexandre Beguel.

<div align="center">
<br>
<strong>If this saved you a week of dashboard-wrangling, a ⭐ helps other teams find it.</strong>
<br><br>
<sub>LLMOps observability · AI FinOps · Grafana LLM dashboards · EU AI Act monitoring · <code>gen_ai</code> OpenTelemetry · self-hosted inference & GPU (DCGM) monitoring</sub>
</div>
