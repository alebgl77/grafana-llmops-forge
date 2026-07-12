# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Cross-platform CI (Linux/macOS/Windows · Python 3.8 → 3.13) running the
  offline self-test and the multi-topology audit harness.

## [0.1.0] — 2026-07-12

First public release.

### Added
- **Auto-discovery** (`discover.py`): probes a Grafana instance and produces a
  capability map — version/edition, datasources, and the LLM telemetry dialects
  actually present, with the **real metric names** (OpenTelemetry GenAI
  `gen_ai.*`, LiteLLM, vLLM/TGI/Ollama, NVIDIA DCGM).
- **Six dashboard blueprints** (`forge_dashboards.py`): FinOps & cost, Gateway
  Operations, Agents & RAG, internal Adoption, self-hosted Inference, and EU AI
  Act Governance. Classic schema v41 via the legacy API — compatible with
  Grafana 9 → 13+, OSS/Cloud/Enterprise.
- **Cost computed, not hoped**: an embedded, date-stamped pricing registry of
  ~30 models (input/output/cache, US/EU/Asia sovereignty) composed into PromQL,
  with a 30-day refresh protocol.
- **SLO alerting** (`--with-alerts`): error burn-rate, TTFT p95, daily budget,
  KV-cache saturation, and signal-absence rules.
- **Graceful degradation**: zero LLM signal produces an instrumentation-gap
  report plus a working governance dashboard, not a failure.
- **Idempotence**: deterministic UIDs, upsert with overwrite, and a `--dry-run`
  mode for everything that writes.
- **Vision-verified rendering** (`visual_audit.py`): native Grafana renderer or
  Playwright fallback captures the real render for inspection.
- **Offline self-test** (`--selftest`) and a portable multi-topology audit
  harness (`audit_harness.py`).
- Reference library: query recipes, blueprint specs, Grafana API compatibility
  matrix, instrumentation guide, and an EU AI Act × observability mapping
  (verified July 2026, post-Digital Omnibus).
- Packaged as a Claude Code / Agent **Skill** (`SKILL.md`).

[Unreleased]: https://github.com/alebgl77/grafana-llmops-forge/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/alebgl77/grafana-llmops-forge/releases/tag/v0.1.0
