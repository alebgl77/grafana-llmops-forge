# Contributing

## 💰 Registry updates (highest value, 2 minutes)
Prices drift quarterly. Edit `references/model_registry.json`:
1. Add/update the model (id, aliases, vendor, region us|eu|asia, `input_per_mtok`, `output_per_mtok`, optional `cached_input_per_mtok` / `tiered_pricing`).
2. Set `estimate: true` if not from the official page; add the official URL to `_meta.sources` if the vendor is new.
3. Bump `_meta.verified_at`.
CI validates the JSON; the specificity matcher has regression tests, so date-suffixed variants stay safe.

## 🔌 New dialects (gateways/engines)
Add a signature in `discover.py` (`DIALECT_SIGNATURES` + label candidates), extend `Q` in `forge_dashboards.py`, add a topology to `tests/audit_harness.py`. PRs without a harness topology won't be merged.

## Ground rules
- `python3 tests/audit_harness.py` must print `AUDIT PROPRE` (27/27).
- stdlib only in `scripts/` (Playwright stays optional).
- No hardcoded metric names in blueprints — resolve through the capability map.
- Panel descriptions teach interpretation, not paraphrase titles.
