# Contributing to Grafana LLMOps Forge

Thanks for considering a contribution. This project has a strong, opinionated
design — reading it first will make your PR land faster.

## The two rules that never bend

1. **Zero third-party dependencies.** Everything runs on the Python 3 standard
   library. No `pip install`, ever. This is a feature, not a limitation: it is
   what lets the toolkit drop into locked-down enterprise/DSI environments where
   approving a new package takes weeks. A PR that adds a dependency will be
   declined on principle — find the stdlib way.
2. **Discovery-first, never assume.** The forge only emits a panel when the
   underlying metric name was actually observed on the instance. No speculative
   panels, no hard-coded metric names. If you add capability, it must key off
   the capability map produced by `discover.py`.

## Getting set up (30 seconds)

```bash
git clone https://github.com/alebgl77/grafana-llmops-forge
cd grafana-llmops-forge

# Offline: render all six dashboards from a simulated capability map
python3 scripts/forge_dashboards.py --selftest

# Full multi-topology invariant suite (litellm-only, vLLM+GPU, degraded, …)
python3 audit_harness.py
```

Both must pass before you open a PR. CI runs them on Linux/macOS/Windows and
Python 3.8 → 3.13.

## Where things live

| Path | What it is |
|---|---|
| `scripts/discover.py` | Probes a Grafana instance → `capability_map.json` |
| `scripts/forge_dashboards.py` | Translates blueprints → dashboards + alerts |
| `scripts/grafana_client.py` | stdlib-only Grafana API client (OSS/Cloud/Enterprise) |
| `scripts/visual_audit.py` | Captures the rendered PNGs for vision review |
| `references/model_registry.json` | The dated pricing registry (~30 models) |
| `references/*.md` | Query library, blueprints, API compat, AI Act, instrumentation |
| `audit_harness.py` | Offline invariant suite across topologies |

## Common contributions

- **Add / update a model price.** Edit `references/model_registry.json`. Keep
  `id`, `vendor`, `region` (`us`/`eu`/`asia`); add `aliases` rather than
  renaming ids; set `estimate: true` if unverified. The audit harness checks
  required fields and valid regions.
- **Add a PromQL/LogQL/TraceQL query.** Put it in `references/query_library.md`
  under the right dialect, using `$__rate_interval` (never a hard-coded window).
- **Extend a blueprint.** Do it in the forge code (the source of truth), never
  by hand-editing a deployed dashboard — the next run would overwrite it.

## PR checklist

- [ ] `--selftest` and `audit_harness.py` pass locally.
- [ ] No new third-party dependency.
- [ ] New metric usage flows from the capability map (no hard-coded names).
- [ ] Regulatory / pricing claims are date-stamped and sourced.
- [ ] Commit messages are clear; PR describes the *why*.

## Good first issues

Look for the [`good first issue`](https://github.com/alebgl77/grafana-llmops-forge/labels/good%20first%20issue)
label. Adding provider pricing, a new query recipe, or a translation of the
docs are all great starting points.

By contributing you agree that your work is licensed under the project's MIT
License.
