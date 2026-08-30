# Security Policy

**Design constraints** (see README § Security model): stdlib-only, no secret logging, least-privilege token, prompt content never captured by default, idempotent deploys.

**Reporting**: open a private security advisory on GitHub (Security → Advisories → Report a vulnerability). Please do not open public issues for vulnerabilities. Expect an initial response within 72 hours.

**Scope**: the scripts in `scripts/`, the SKILL.md instructions, and the CI workflow. Model prices in the registry are data, not code — wrong prices are bugs, not vulnerabilities.

## Third-party scanning

This skill is scanned with [NVIDIA SkillSpector](https://github.com/NVIDIA/SkillSpector).
Fixes applied following the scan: tool scope declared (`allowed-tools`, including
`Env` since the scripts read `GRAFANA_URL`/`GRAFANA_TOKEN`), explicit
human-confirmation step before writing to a production Grafana, and pinned
container image versions throughout the documentation.

### Scanning the repository vs. scanning the deliverable

Three scan targets give three different scores, and the difference is worth
understanding before you read any of them as a verdict.

- **The extracted skill directory** — what the agent actually loads: **LOW**,
  two findings, both `RP1` false positives explained below. This is the number
  that describes the code you will run.
- **The `.skill` archive** — adds four `SC9` "concealed executable artifact"
  findings, one per Python file. The `.skill` format *is* a zip with a custom
  extension, so any skill shipping scripts triggers this. It is a property of
  the packaging format, not of this code. Extract and scan the directory to see
  through it.
- **The whole repository** — additionally covers CI workflows, the test harness
  and the distribution archive:

| Finding | Where | Why it is expected |
|---|---|---|
| `SC9` Concealed executable artifact | `dist/*.skill` | The archive *is* the advertised deliverable. Its contents are byte-identical to the source in this repo — `tests/audit_harness.py` asserts that on every run, so you can verify rather than trust. |
| `SC2` External script fetching | `.github/workflows/ci.yml` | CI downloads a Prometheus binary to run queries against a real server. Pinned to an explicit version **and** sha256 checksum. |
| `AST4` subprocess calls | `tests/` | The test harness runs the CLI it is testing. |
| `PE3` Credential access | `.gitignore` | The literal string `.env`, in a rule that prevents committing one. |

Two `RP1` findings remain and are **false positives**, documented here rather
than hidden: the rule matches `docker\s+(?:pull|run|create)\s+\S+`, capturing
only the token immediately after `docker run` — `-d` in our examples — and then
looks for a version pin inside that fragment. Every image we reference *is*
pinned to an explicit tag; the flag fires because option flags precede the image
name. Verify by reading `references/instrumentation_guide.md` §5 and
`references/visual_verification.md` §5.
