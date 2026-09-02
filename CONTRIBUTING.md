# Contributing

## 💰 Registry updates (highest value, 2 minutes)
Prices drift quarterly. Edit `references/model_registry.json`:
1. Add/update the model (id, aliases, vendor, region us|eu|asia, `input_per_mtok`, `output_per_mtok`, optional `cached_input_per_mtok` / `tiered_pricing`).
2. Set `estimate: true` if not from the official page; add the official URL to `_meta.sources` if the vendor is new.
3. Bump `_meta.verified_at`.
CI validates the JSON; the specificity matcher has regression tests, so date-suffixed variants stay safe.
Do not bump `_meta.verified_at` without checking the official provider pages;
releases fail once the verified data is more than 30 days old.

## 🔌 New dialects (gateways/engines)
Add a signature in `scripts/discover.py` (`DIALECT_SIGNATURES` + label candidates), extend `Q` in `scripts/forge_dashboards.py`, add a topology to `tests/audit_harness.py`. PRs without a harness topology won't be merged.

## Reviewing generated code

Much of this repository was written with an AI assistant, and that changes what
review has to catch. The failure mode is not broken syntax; it is code that
runs, looks plausible and is quietly wrong. Every defect found here so far was
silent: a model billed at another model's price, a regex that parsed everywhere
except against the real engine, an `or` that dropped half the cost, an alert
that stayed quiet exactly when its subject failed. None crashed anything.

So the bar for a change is evidence, not plausibility:

- `python3 tests/audit_harness.py` green, and a new check for whatever class of
  bug the change addresses. A fix without a test that would have caught it is
  half a fix.
- Anything touching queries: `tests/live_query_check.py` against a real
  Prometheus (`make demo` gives you one), plus `tests/value_invariants.py` if
  numbers are involved.
- Secrets never enter the repository, generated or not; `.gitignore` covers the
  variants and the harness greps for token shapes on every run.

## Ground rules
- `python3 tests/audit_harness.py` must print `AUDIT PROPRE`.
- `python3 tests/supply_chain_check.py` must prove that the package and SPDX
  SBOM are reproducible and reject tampering.
- stdlib only in `scripts/` (Playwright stays optional).
- No hardcoded metric names in blueprints; resolve through the capability map.
- Panel descriptions teach interpretation, not paraphrase titles.

Production-impacting changes must also follow
[`docs/PRODUCTION_CHECKLIST.md`](docs/PRODUCTION_CHECKLIST.md), including the
manual Grafana Cloud, Enterprise, and SSO validation where applicable.
