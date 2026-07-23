# Security Policy

**Design constraints** (see README § Security model): stdlib-only, no secret logging, least-privilege token, prompt content never captured by default, idempotent deploys.

**Reporting**: open a private security advisory on GitHub (Security → Advisories → Report a vulnerability). Please do not open public issues for vulnerabilities. Expect an initial response within 72 hours.

**Scope**: the scripts in `scripts/`, the SKILL.md instructions, and the CI workflow. Model prices in the registry are data, not code — wrong prices are bugs, not vulnerabilities.
