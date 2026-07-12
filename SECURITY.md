# Security Policy

Grafana LLMOps Forge is built for environments where security posture is the
whole point (locked-down DSI, regulated data). Two design choices carry most of
the weight:

- **Zero third-party dependencies** — nothing to audit beyond the Python stdlib
  and this repository. No transitive supply chain.
- **The service-account token is never logged, never persisted, never written
  into a dashboard or config.** It lives only in an environment variable for the
  duration of a run.

## Handling secrets safely

- Provide credentials via `GRAFANA_TOKEN` (service account, recommended) or
  `GRAFANA_USER` / `GRAFANA_PASSWORD`. Never paste them into a file that could
  be committed — `.env` and `*.local` are git-ignored by default.
- Grant the **minimum role**: `Editor` is enough for folders + dashboards; only
  use `Admin` if you want the forge to provision alert rules.
- **Never enable prompt-content capture by default.** `gen_ai.input.messages` /
  `gen_ai.output.messages` are sensitive (GDPR); they are off by default and
  should stay off unless you have an explicit, short-retention reason.
- Audit PNGs from `visual_audit.py` can contain real costs, team names and
  model usage. Store them locally, share deliberately, purge after audit if your
  environment requires it. They are git-ignored by default.

## Reporting a vulnerability

Please report suspected vulnerabilities **privately** — do not open a public
issue for anything exploitable.

- Preferred: open a [GitHub security advisory](https://github.com/alebgl77/grafana-llmops-forge/security/advisories/new)
  (private).
- Or email the maintainer at the address on the GitHub profile.

Please include reproduction steps and impact. We aim to acknowledge within a few
business days and to coordinate a fix and disclosure timeline with you.

## Supported versions

This is early-stage software. Security fixes target the latest tagged release
and `main`.
