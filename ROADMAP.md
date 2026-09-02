# Product roadmap

> **Status:** This roadmap communicates product direction, not guaranteed dates. Scope advances only when its acceptance criteria are met.

## Current baseline

Version `v2.0.2` provides:

- Seven discovery-driven dashboard blueprints spanning FinOps, operations, agents and RAG, adoption, self-hosted inference, quality, and governance.
- Multi-dialect discovery for OpenTelemetry GenAI, LiteLLM, vLLM, TGI, and GPU telemetry.
- Native gateway, registry-composed, and recorded cost paths through `--cost-mode`, including generated recording rules for scalable Prometheus queries.
- An opt-in `--pricing-fallback artificial-analysis` path for unresolved prices, with explicit third-party provenance and official sources taking precedence.
- Provisioned SLO, telemetry, budget, inference, and quality alerts.
- Visual audit of rendered panels, with deterministic findings when expected captures or data are missing.
- Exemplars and Tempo links for moving from metrics to existing traces.
- Portable dashboard JSON through `--export-portable`, alongside the compatible classic schema v41 path for Grafana 9 through 13+.
- CI across supported Python and Grafana versions, signed releases, checksums, SBOMs, attestations, protected branches, and protected release tags.

## North star

Turn existing LLM telemetry into Grafana assets that are reliable, explainable, portable, and safe to operate.

## Product principles

- **Provider-neutral first.** Shared telemetry and cost contracts come before provider-specific integrations.
- **Read before write.** Discovery and comparison must make every intended change understandable before deployment.
- **Preserve compatibility.** Existing UIDs, classic schema v41, and supported Grafana versions remain stable unless a documented migration is available.
- **Explicit provenance.** Every price, mapping, and externally sourced value identifies its origin and freshness.
- **Measurable graduation.** Work moves forward only after its stated behavior is covered by repeatable tests and documented operational checks.

## v2.1 - Safer decisions

### Outcome

Operators can understand a proposed deployment and its financial implications before Grafana is changed.

### Scope

- Add a read-only `--diff` mode against dashboards and alerts already present in the target Grafana.
- Generate cache-savings panels when the required cache token and pricing signals are available. These panels are currently documented as manual extensions.
- Generate budget burn-down views from the existing `--daily-budget` input when the required spend signal is available. These views are currently documented as manual extensions.
- Keep existing `--cost-mode` behavior and unpriced-model safeguards visible in every decision view.

### Acceptance criteria

- Diff mode performs no Grafana write request and reports planned creates, updates, and unchanged resources.
- Repeating a diff against an unchanged deployment produces no planned update.
- Cache-savings and budget burn-down panels materialize only when their required signals exist, with an actionable instrumentation gap otherwise.
- Native, registry-based, recorded, and partially priced cost paths remain covered by the offline harness and supported Grafana integration tests.

### Out of scope

- Terraform delivery and native schema v2 output.
- Cost attribution to individual traces or conversations.
- Provider usage API adapters.

## v2.2 - GitOps delivery

### Outcome

Teams can review and apply generated Grafana assets through their existing infrastructure-as-code workflow without introducing a second dashboard model.

### Scope

- Provide Terraform delivery that consumes the existing `--export-portable` JSON output.
- Keep classic schema v41 as the compatible default for Grafana 9 through 13+.
- Offer native schema v2 as an experimental, explicit opt-in for homogeneous Grafana 13+ estates.
- Document review, plan, apply, rollback, and upgrade workflows for generated assets.

### Acceptance criteria

- The same portable JSON input produces a stable Terraform plan when neither configuration nor target state has changed.
- Terraform consumes generated portable JSON rather than defining a parallel dashboard representation.
- Generated artifacts contain no Grafana token, provider credential, or other secret.
- Compatibility tests keep the classic schema v41 path unchanged across the supported Grafana matrix.
- Schema v2 output is isolated behind an experimental option and tested only against supported Grafana 13+ environments.

### Out of scope

- Replacing classic schema v41 as the default.
- Supporting schema v2 in mixed-version or pre-Grafana 13 estates.
- Managing unrelated Grafana infrastructure or provider billing systems.

## v3.0 - Trace-level economics

### Outcome

Operators can investigate a cost change down to the responsible trace or conversation while aggregate metrics remain operationally safe.

### Scope

- Attribute cost to traces or conversations by building on existing exemplars and Tempo links.
- Maintain versioned OpenTelemetry crosswalks for supported GenAI semantic conventions.
- Keep trace and conversation identifiers in trace data rather than high-cardinality metric labels.
- Correlate cost without collecting or storing prompt content by default.
- Consider optional OpenAI and Gemini usage adapters only after contracts for secrets, quotas, storage, provenance, and reconciliation are defined.

### Acceptance criteria

- Detailed attribution reconciles with aggregate cost for the same tested inputs, and any unresolved amount remains explicit.
- Trace and conversation identifiers are not added as Prometheus metric labels.
- Correlation works without prompt or response body storage and documents every field that crosses a system boundary.
- Each OpenTelemetry mapping declares its semantic-convention version and has compatibility fixtures.
- Any provider usage adapter is opt-in, protects credentials, records source and retrieval time, handles quotas, and reports reconciliation gaps.

### Out of scope

- A billing platform or system of record for invoices.
- A general-purpose telemetry collector.
- Default storage of prompts, responses, or conversation bodies.
- Provider pollers without the required operational and security contracts.

## Continuous maintenance

The following work continues across every horizon:

- Refresh official pricing and aliases while preserving source, retrieval date, and fallback provenance.
- Extend governance crosswalks as evidence mappings, without claiming legal compliance or requiring new instrumentation by default.
- Maintain the tested Grafana compatibility matrix and document deprecations before changing defaults.
- Address security findings, dependency and workflow risks, and supply-chain integrity without weakening release controls.
- Keep the README, references, examples, and generated behavior aligned.

## Decision rules

- An item advances to the next horizon only after its acceptance criteria are satisfied by repeatable tests and documented evidence.
- Unmet criteria keep the item in its current horizon, even if related implementation has started.
- Experimental and provider-specific work remains optional until it demonstrates compatibility, security, provenance, and a safe default.
- New work may be reordered as Grafana and OpenTelemetry evolve, but it must preserve the product principles and published scope boundaries.
