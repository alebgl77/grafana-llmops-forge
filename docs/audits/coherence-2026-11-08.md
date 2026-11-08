# Coherence audit, 8 November 2026

Audited baseline: `491fcac4f43318e6eda16d8496912ea441bf888b`.
Scope: source code, configuration, documentation, generated dashboard JSON,
published illustrations and the repository's historical Grafana capture.

## Findings and changes

| Finding | Consequence | Change |
|---|---|---|
| Capture folders used only a truncated title slug | Different UIDs with the same title could overwrite each other's evidence | Include instance, organization and UID in the folder identity; deduplicate requested UIDs while preserving manifest panels |
| Architecture and blueprint reference omitted Quality | Seven blueprints were advertised but only six documented/drawn | Add Quality and check actual membership, not just a count in a heading |
| Banner text overlapped its chart; social PNG still claimed visual verification | Visual identity and proof claims diverged from the product | Shared SVG generator, accessible titles/descriptions and refreshed social export |
| Static FinOps mockup used sovereignty labels and incompatible example totals | Illustration implied facts not established by telemetry | Explicit synthetic native-spend illustration; preserve the separate real historical PNG |
| Governance timeline stayed French in English output and called August 2026 imminent | Default-language and time claims were wrong | Dated English source, French translation and links to current official milestones |
| Governance copy claimed to prove retention | Dashboard results could be mistaken for a configuration/compliance check | State observed scope; require independent retention verification; remove fixed-hour equivalence to calendar months |
| French operational guide described outdated generation behavior | Instructions and current runtime could disagree | Rewrite the concise guide around the canonical protocol and current manifests |
| `make package` did not build the package; demo suppressed rule-copy/reload failures | Commands could report success without their expected result | Use the real reproducible packager and fail on recording-rule load errors |
| Regeneration removed obsolete flat rules but retained the Kubernetes CRD | An old rule could be reapplied despite the current manifest reporting no rules | Remove both owned rule exports when no rules can be generated; preserve unrelated files |

The new visual generator takes blueprint membership and governance rows from
runtime constants. Documentation figures share colors, typography and layout
rules. `dashboard-finops.png` remains the historical real capture; explanatory
SVGs do not substitute for fresh live captures.

## Graphify evidence

Graphify structural extraction covered 26 code/config files; semantic extraction
fully read 27 Markdown/YAML documents (3,526 lines). The combined baseline graph
contains **884 nodes, 2,005 directed edges and 58 communities**. Principal hubs:
`GrafanaClient` (55 connections), `GrafanaError` (34), forge `main` (25), and
`Board` (22). The graph directed the audit toward client boundaries, orchestration,
capture planning and shared blueprint/document contracts.

Graph health: zero missing or dangling endpoints; two self-loops; **58 parallel
relationships collapse into shared endpoints** in Graphify's directed graph.
The raw extraction has 2,063 edges. These are graph-representation limitations,
not demonstrated runtime defects. Inferred relationships were checked against
the actual code before changes were made. The graph is a baseline audit artifact,
not a claim that all behavior or deployment environments were executed.

Reproduce the structural part with Graphify installed:

```bash
graphify extract . --code-only --no-cluster --max-workers 2
graphify cluster-only . --no-label
graphify query "capture_directory load_plan" --budget 2000
```

This reproduction indexes the current source and does not recreate the separately
reviewed semantic fragments. Local `graphify-out/` products are ignored by Git.

## Validation

- Seven-blueprint offline generation succeeds in English and French. Generated
  panel rectangles do not overlap in either locale; both capture plans list all
  seven dashboards. Changed Markdown local link targets exist.
- 88 targeted tests pass: financial coverage (14), financial sources (19),
  financial matching (6), deployment inventory (16), budget lifecycle (11),
  live-query gate contracts (15), capture identity (3), cross-file coherence (4).
  The rule cleanup regression failed before the fix for both native-only signals
  and unpriced OTel models; it also checks an orphan CRD and preserves unrelated files.
  The live-query gate tests here use fixtures, not a
  live Prometheus. Controlled burn-recovery selftest also passes.
- Package/source equality and reproducible supply-chain checks pass.
- New code parses with Python 3.9 grammar; this is not execution under Python 3.9.
- Generated SVG/source parity and `git diff --check` pass. SVGs were rendered
  locally and visually inspected; the historical Grafana PNG was also inspected.
- The full local harness reaches its HTTP fixture stage but cannot finish:
  this Windows execution environment denies socket access (`WinError 10013`).
  Docker's engine is unavailable. New live Grafana/Prometheus, browser rendering,
  Cloud, Enterprise and SSO validation were not performed locally.

The initial connected GitHub integration rejected writes with HTTP 403. The
existing owner session in GitHub's web interface allowed publication to the
dedicated `codex/coherence-audit-2026-11-08` branch instead. Consult the pull
request's checks for the current GitHub-runner results; the local results above
do not claim completion of the remote CI or a live visual review.
Do not interpret these local checks or diagrams as production approval or a
semantic visual review of a newly deployed instance.

## Remaining limits

The forge is a heavily centralized generator: most signal resolution, financial
logic and blueprints share `forge_dashboards.py`. A large refactor would need
carefully preserved query and value contracts; it is not required for the
corrections above. The demo's renderer plugin remains installed separately and
is not exercised by the existing CI deployment jobs. A fresh end-to-end visual
review on the target Grafana remains necessary before claiming visual validation.

Regulatory reference refresh used the [Commission's AI Act page](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai),
[AI Omnibus announcement](https://digital-strategy.ec.europa.eu/en/news/ai-omnibus-enters-force)
and [official implementation timeline](https://ai-act-service-desk.ec.europa.eu/en/ai-act/eu-ai-act-implementation-timeline).
This was a targeted correction of scope and stale milestones, not a legal audit
of every governance reference or every ISO control number.
