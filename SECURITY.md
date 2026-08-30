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

**Scan the extracted skill directory — that is what an agent loads, and it
reports zero findings.** `make scan` builds the package and does exactly that.

Two other targets give different numbers, for reasons worth knowing:

- **The `.skill` archive itself** adds one `SC9` "concealed executable artifact"
  per Python file. The format *is* a zip with a custom extension, so any skill
  shipping scripts triggers it. Extract and scan the directory to see through
  it. The archive is never committed here: CI builds it reproducibly from these
  sources (`tools/package.py`, fixed timestamps → stable sha256), verifies file
  by file that it matches them, and publishes it with its checksum.
- **The whole repository** additionally covers CI workflows, the Makefile and
  the test harness. Ten findings remain there, and each one is a development
  tool doing its job:

| Finding | Where | Why it stays |
|---|---|---|
| `AST4` subprocess call ×7 | `tests/` | The harness runs the CLI it tests. Rewriting the tests to avoid subprocess would make them less faithful, not safer. |
| `SC2` external fetch | `.github/workflows/ci.yml` | A bounded retry loop waiting for the local Grafana container to answer. Replacing it with a fixed `sleep` would remove the finding and make CI flakier. |
| `SSRF2` internal request | `.github/workflows/ci.yml` | The CI assertion that queries `localhost:3000` to prove the dashboards deployed. |
| `PE3` credential access | `.gitignore` | The pattern `*.env`, in a rule whose purpose is to stop anyone committing one. |

We stopped there deliberately. Two earlier attempts to push the repository score
lower made the project worse: a `make` target rewritten to please a rule
introduced two `rm -rf` calls and turned one LOW finding into two HIGH ones.
A scanner is evidence, not a scoreboard.

The `RP1` findings that an earlier revision carried are gone: the container
images in the documentation are now shown as pinned Compose services rather than
`docker run` one-liners, which are both reproducible and unambiguous to a
reader.
