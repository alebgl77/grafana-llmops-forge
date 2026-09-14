# Product roadmap

**Make every AI change a decision you can defend.**

For platform and AI engineering leaders in European enterprises running self-hosted Grafana,
Forge's proposed direction is to turn existing telemetry into reproducible operational decisions.
Forge execution and decision-artifact storage stay in customer infrastructure. The customer
chooses and controls external integrations; there is no mandatory Forge Cloud.

[Version française](docs/ROADMAP.fr.md) · [Current capabilities](README.md)

## Release, branch validation and proposed work

**Status: 2026-09-14.** The released baseline is **v2.0.2**, published on 2026-09-02.
The five foundational corrections and budget-alert lifecycle fix in
[PR #5](https://github.com/alebgl77/grafana-llmops-forge/pull/5) are **validated on its branch
and awaiting integration into main**. They are implemented in the PR, **not yet in main or a release**.
The remaining H0 contracts, H1–H3, the journey and the decision dossier remain proposed future work.

Today, Forge is a local Python standard-library CLI and an agent skill. Discovery drives seven
Grafana dashboards, alerts, pricing and recording rules, portable exports and visual capture.
It uses the customer's Prometheus/Mimir, Loki, Tempo and Grafana, alongside external evaluators.
The direction preserves that model: no persistent Forge server, collector, trace store or
evaluation engine.

The existing domains provide the starting signals: FinOps and self-hosted infrastructure for
cost and resources; Ops and agents/RAG for latency, retries and failures; quality for external
evaluation signals. Adoption can help delimit real usage and cohorts where identifiers exist;
governance supplies declared or observed facts and unknowns. Joining these into a valid
comparison is future work, not a capability claimed for today's seven dashboards.

## A future journey: should we move this assistant?

**Illustrative future demonstration, not an available workflow.** A team considers replacing
the hosted API model behind an internal RAG assistant with an EU-hosted inference stack.
The candidate looks cheaper per token. That alone does not establish a lower cost per useful
outcome, acceptable quality, or where every dependency processes data.

1. A runtime change breaks the meaning or coverage of a token signal. Forge would identify the
   telemetry contract gap and specify the missing measurement before presenting a comparison.
2. After that gap is repaired, the team runs a bounded baseline/candidate comparison. Forge
   would assemble existing telemetry and external evaluation results for a defined workload,
   with model, prompt and retrieval versions, quality criteria and latency limits recorded.
3. The review would distinguish reported API usage costs, price-based estimates, allocated
   infrastructure costs, scenario assumptions and declared deployment facts. Retries or failures might
   erase a token-price advantage; incomplete cost allocation might leave the answer unknown.
4. The result would be **comparable and favorable**, **comparable and unfavorable**, or
   **indeterminate**, with reasons. An indeterminate result names the smallest next action:
   recover an evaluator version, measure a missing population, or validate a cost allocation.
5. A reviewer could inspect the configuration diff, rollout checks and rollback prerequisites
   in existing tools, then retain a portable record of the decision and its evidence.

“Do not deploy” and “insufficient evidence” are useful outcomes. An observed difference is not
automatically caused by the model change. This journey promises neither counterfactual
predictions nor automatic traffic routing or rollback.

## Three product bets

**1. Measurements that remain interpretable when the stack changes.**
Units, scope, freshness, coverage and provenance must travel with each signal. Versioned
OpenTelemetry crosswalks and runtime contracts should expose unsupported or changed semantics.
An explicit unknown is more useful than a precise number built on an invalid assumption.

**2. Cost per successful task that can actually be compared.**
Success needs a versioned definition, external quality evidence and explicit latency criteria.
Comparisons need identifiable workload cohorts and model, prompt and retrieval versions.
Reported API usage cost, price-based estimates, allocated self-hosted infrastructure cost and
scenario estimates must remain distinct. Native telemetry cost is not an invoice; H2 reconciliation
checks scope, lag and residuals. Cost scope must account for retries and failures; denominator
rules must explain which tasks are eligible and successful. There is no universal weighted score.

**3. A reviewable dossier for an AI change.**
The product bet is the validity of the comparison and the reasons for a decision across tools.
A portable record makes that reasoning reviewable; JSON packaging alone is not differentiation.
Declared and observed dependencies, evaluation evidence and GitOps rollout references should
meet in that record without replacing the systems that produced them.

## The proposed decision record

**Proposed interface, not an implemented CLI or schema.** The dossier would be versioned,
portable JSON with a human-readable summary and links to Grafana and existing evidence.
A reviewer should be able to answer “what justified this decision?” after the live view changes.

| Part of the record | What a reviewer needs |
| --- | --- |
| Scope and identity | Workload/cohort, baseline and candidate, model/prompt/retrieval versions, time windows and sample sizes. |
| Measurement evidence | Signal sources, units, freshness, coverage and known gaps; frozen aggregate inputs or immutable retained evidence references. |
| Reproduction | Decision-rule and calculation versions/digests, tied to the retained input versions. |
| Economics | Cost class, included retries/failures, allocation rules, pricing version and reconciliation residuals. |
| Quality and latency | Versioned success definition, criteria, evaluator provenance/version, external run references, uncertainty and minimum evidence thresholds. |
| Dependencies | Provider origin separate from deployment location; each fact classified as declared, observed or unknown. |
| Comparison and checks | Baseline/candidate differences, comparability result, check outcomes with reasons, and next measurement for each indeterminate conclusion. |
| Review and promotion | Configuration diff, approver reference in existing tools, rollout evidence and rollback prerequisites. |

Aggregate metrics are the default; trace drill-down is optional. Raw prompts and secrets are
excluded by default. Reference access, evidence retention and sensitive-data export controls
are part of the contract, so a link is not mistaken for durable, accessible evidence.
A signed artifact can prove integrity and signer identity; it cannot prove factual truth,
deployment residency or regulatory compliance.

## Sequence: earn each next horizon

These are dependencies and decision gates, not calendar commitments. The former v2.1, v2.2
and v3 labels are tentative packaging choices to revisit after the gates pass.

| Horizon | User question | Demonstrable output | Dependency |
| --- | --- | --- | --- |
| **H0 · Trusted foundations** | Can we interpret these numbers and see what would change? | Signal contracts, explicit gaps and a read-only asset diff. | Integrate validated PR #5; establish measurement scope. |
| **H1 · Compare a change** | Can we accept this model or prompt change at our required quality and latency? | A bounded comparison with cost per successful task and a reasoned outcome. | H0 contracts hold for the pilot workload. |
| **H2 · Ship with evidence** | Can someone review and reproduce the promotion decision? | A portable promotion dossier and checks consumed by existing CI. | H1 demonstrates repeat decision value. |
| **H3 · Rehearse the next migration** | What should we test before changing provider or hosting? | An executed rehearsal record or a clearly labeled sensitivity scenario. | Earlier pilots justify broader scope and accounting inputs exist. |

### H0 · Trusted foundations

**Output:** reliable foundations for the seven domains, plus read-only preview/diff of proposed
Grafana assets, showing created, updated and unchanged resources without writing to Grafana.

PR #5 is the first prerequisite: sampled recorded-cost integration with coverage; financial
numerator and denominator bound to the same source and an instant budget value; no silent
model truncation and explicit pricing coverage; mean/minimum labels for score gauges distinct
from histogram quantiles; provider origin separated from declared deployment location and
local inventory. These corrections narrow errors; they do not establish backend completeness.

PR #5 also omits new budget rules when financial coverage is insufficient. During deployment
with `--with-alerts`, an existing Forge budget alert is paused after its ownership and scope
are verified. Its pause is preserved if coverage recovers.

Remaining contracts must cover units, counter/histogram/gauge semantics, freshness, missing
and unsupported signals, unpriced models and provenance. In particular, complete absence of
inline counters can still look like zero; it must not become evidence of no spend.

**Pass only if:** known fixtures and pilot captures distinguish real zero from missing, stale
or unsupported data; financial scope and coverage are inspectable; changed OTel/runtime
semantics are detected or rejected. Repeated read-only diffs must be stable and demonstrably
perform no writes. Any concealed gap or unexplained financial disagreement holds H1 back.

### H1 · Compare a change

**Output:** a narrow baseline/candidate comparison with one of three explicit conclusions:
comparable and favorable, comparable and unfavorable, or indeterminate. Each conclusion has
reasons; each indeterminate conclusion has a smallest next measurement or action.

Start with reported native API usage cost on one RAG/assistant workload and import existing
evaluation evidence. Add a self-hosted runtime only after that workflow proves useful;
estimated costs and allocated infrastructure costs require separately validated provenance.
Use comparable cohorts and explicit cost/denominator scope, including retries and failures.
Show cache economics and budget burn only where the required usage and prices are observable.

**Pass only if:** the pilot can reproduce the comparison from its inputs and reject mismatched
cohorts, windows, success definitions or cost coverage. Sample sizes, uncertainty and evaluator
provenance must satisfy declared minimum evidence thresholds; a quality average alone cannot
pass. Missing signals, undersampling or unstable evaluation must yield insufficient evidence.
A favorable observed difference must not be presented as proof of a causal model effect.

### H2 · Ship with evidence

**Output:** the portable promotion dossier and checks consumed by existing CI, with review,
plan and apply boundaries for portable JSON, Terraform and native provisioning workflows.
Plan performs no writes. Customer tools retain approval, deployment and rollback; Forge adds
evidence and checks, with least privilege and no new background control loop.

Keep classic dashboard JSON as the compatibility path. A future schema-v2 option is opt-in
for suitable Grafana estates, gated by import, upgrade and rollback compatibility evidence.
Trace/conversation attribution can use existing exemplars and Tempo references without
putting trace or conversation IDs in metric labels.

Provider usage adapters are optional and follow explicit permission, quota, storage,
retention and reconciliation contracts. Both trace attribution and provider reconciliation
must expose completeness, lag and unallocated residuals rather than imply exhaustive totals.

**Pass only if:** another reviewer replays the decision using retained, versioned inputs and
rules. Changed or missing evidence yields indeterminate rather than reusing the prior verdict.
Redaction and access controls hold; plan makes no writes; and approval remains in
the customer's CI. A controlled fixture must exercise rollback prerequisites through existing
tools. Incomplete attribution must remain visible, and unsupported schema combinations fail
explicitly. No deployment-controller capability is required to pass.

### H3 · Rehearse the next migration — exploration

**Output:** dependency inventory, observed endpoints where available, and a bounded provider
or hosting migration exercise. Distinguish an **executed rehearsal**, with its test mechanism
and evidence, from a **sensitivity scenario**, whose input ranges and assumptions are visible.
Capacity, total-cost sensitivity and quality benchmark evidence could inform the next test.

**Pass only if:** the pilot can trace each conclusion to an executed test or an explicit
assumption, reproduce scenario calculations, and identify inputs that could change the
decision. Unknown dependencies and deployment locations stay unknown. Stop expansion if the
earlier workflow has not earned repeated use or accounting inputs cannot support the analysis.

This horizon is not a causal forecast, a legal residency attestation or an automated router.

## Validate the direction with a staged pilot

The first proposed pilot asks: **“Can we accept this model or prompt change at our required
quality and latency, and what does a successful task cost?”**
Begin with one API-based RAG/assistant workload; consider one self-hosted runtime next.
This is a staged validation proposal, not a commitment to deliver both simultaneously.

Record a baseline before setting improvement targets:

- Time from an eligible change to a reviewable decision, including evidence collection.
- Proportion of eligible changes with reproducible evidence; define eligibility up front.
- Signal coverage, reconciliation gaps and unresolved unknowns.
- Cost per successful task at fixed quality and latency criteria, with cost provenance.
- Whether the team returns to the workflow for a second real change.

**Go/no-go:** the pilot reproduces a decision from the exported record, correctly refuses a
comparison with missing or mismatched evidence, and uses it for a second real change.
Choose acceptance thresholds with the pilot after measuring the baseline; claim no percentage
improvement in advance. Defer or stop a bet if an existing native tool already meets the need,
mandatory new storage would dominate the work, or the evidence cannot support the decision.

## Where this fits

Official product descriptions checked on **2026-09-08**; this is context, not an exhaustive
feature comparison.

| Existing capability | Implication for Forge's proposed focus |
| --- | --- |
| [Grafana Cloud Agent Observability](https://grafana.com/docs/grafana-cloud/observe-and-act/agent-observability/) covers OTel traces, cost, latency, online evaluations/guards and offline experiments. | Reuse evidence and Grafana; do not rebuild an agent-observability backend. |
| [Grafana Assistant](https://grafana.com/products/cloud/ai-assistant/) supports self-managed OSS/Enterprise through a connection to Grafana Cloud. | A generic assistant is not the product bet. |
| [Grafana's open-source MCP server](https://grafana.com/docs/grafana/latest/developer-resources/mcp/) supports self-managed Grafana and Cloud. | Generic MCP access or dashboard CRUD is not differentiation. |
| [Langfuse](https://langfuse.com/resources/engineering/clarifications) offers traces, prompts, datasets, evaluations and experiments, including self-hosting and CI workflows. | Import evaluation evidence; do not claim generic CI gates as unique. |
| [Phoenix](https://arize.com/phoenix/) offers tracing, evaluations and experiments. | Work with existing evaluators and trace systems. |

**Hypothesis to validate:** reproducible operational decisions across tools on the customer's
existing self-hosted stack are useful enough to adopt repeatedly. Comparison validity,
explicit refusal and actionable evidence gaps must earn that place; it is not an exclusivity
claim or a reason to replace Grafana, an evaluation engine or a trace backend.

## Maintenance and open assumptions

Pricing freshness/provenance, OTel and runtime crosswalks, governance terminology, compatibility,
security, supply-chain integrity and aligned documentation remain prerequisites at every horizon.
Visual captures support review; they do not establish the truth or completeness of telemetry.

Pilot access, a stable success definition, evaluation quality, accounting inputs and permission
to use/export the necessary evidence remain open assumptions. Staffing and delivery dates are
not established. Release scope and version numbers follow validated gates, not this document.
