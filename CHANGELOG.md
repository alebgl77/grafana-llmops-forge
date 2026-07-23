# Changelog

## [1.1.0] — 2026-07-23
### Added
- Visual verification layer: `visual_audit.py` (native renderer + Playwright fallback, DOM pre-scan), vision checklist & remediation protocol (`references/visual_verification.md`), `deploy_manifest.json`.
- Offline audit harness: 27 checks across 4 instance topologies (`tests/audit_harness.py`).
### Fixed
- **Billing-accuracy bug**: model matcher now scores by specificity — `gpt-5.4-mini` can no longer be priced as `gpt-5.4` (was ×5.5 overcost). Regression-tested.
### Hardened
- Per-dashboard capture isolation; tolerance for hand-made capability maps.

## [1.0.0] — 2026-07-12
- Initial release: discovery-first pipeline, 6 blueprints, 4 dialects, 30-model registry (verified 2026-07-12), 5 SLO alerts, EU AI Act mapping (post-Digital-Omnibus timeline).
