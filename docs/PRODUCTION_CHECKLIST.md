# Production readiness checklist

This checklist separates repository controls that are enforced by code from
GitHub and Grafana controls that an administrator must enable manually.

## Release gate

- [ ] `main` is green for `audit (3.9)`, `audit (3.13)`, `live-queries`,
  `Windows portability (Python 3.13)`, and all five `E2E Grafana …` jobs.
- [ ] `references/model_registry.json` was checked against its official
  provider sources no more than 30 days ago. Never advance `verified_at`
  without performing that check. The release workflow rejects older or future
  dates.
- [ ] The release is launched from an existing `v*` tag. It builds the `.skill`
  twice, verifies its source contents, creates and verifies a deterministic
  SPDX 2.3 SBOM, writes `SHA256SUMS`, then creates a draft release.
- [ ] Both GitHub attestations (build provenance and SBOM) succeed before the
  draft is published. A failed run deliberately leaves its draft and assets in
  place. Diagnose it, remove the draft manually, and rerun; the workflow never
  overwrites an existing release or asset.
- [ ] A consumer can run `gh attestation verify` on the downloaded `.skill`
  and `sha256sum --check SHA256SUMS` in the download directory.

Artifact attestations for private repositories require a compatible GitHub
Enterprise Cloud plan. They are not supported by GitHub Enterprise Server; in
that environment this release workflow is expected to stop before publication.

## GitHub repository settings (manual)

Apply these controls in the repository settings; workflow files cannot enable
them:

- [ ] Enable immutable releases. Keep the release workflow's no-overwrite
  checks even after enabling the server-side control.
- [ ] Create a branch ruleset targeting `main`: require pull requests, at least
  one approval, dismissal of stale approvals, Code Owner review using the
  existing `.github/CODEOWNERS`, resolution of review threads, and all CI
  checks named in the release gate above. Block force pushes and branch
  deletion, and grant bypass only to a small emergency group.
- [ ] Create a tag ruleset for `v*` that blocks updates and deletion and limits
  tag creation to release maintainers.
- [ ] Under Actions settings, keep the default `GITHUB_TOKEN` read-only and
  disable approval/bypass by untrusted fork workflows. The release job grants
  only the four writes it needs: contents, OIDC identity token, attestations,
  and artifact metadata.
- [ ] Enable Dependabot alerts and Dependabot security updates. The committed
  Dependabot configuration already proposes weekly updates for pinned GitHub
  Actions and demo container images.
- [ ] Enable CodeQL default setup for every detected language and require its
  check in the `main` ruleset.
- [ ] Enable secret scanning, validity checks where available, and push
  protection. Review and revoke any bypass promptly.
- [ ] Review the repository Security Advisories access list and test the private
  reporting route documented in `SECURITY.md`.

## Grafana compatibility policy

CI exercises these immutable images:

| Grafana | Policy | Meaning |
|---|---|---|
| 9.5.21 | Legacy compatibility only | Regression signal; no security or support commitment from this project |
| 10.4.19 | Legacy compatibility only | Regression signal; no security or support commitment from this project |
| 11.6.16 | Legacy compatibility only | Regression signal; no security or support commitment from this project |
| 12.4.9 | Supported | Tested release line |
| 13.2.0 | Supported | Tested release line |

Passing a legacy CI job proves API compatibility with that exact image, not
that its Grafana release line still receives upstream security fixes. Production
deployments should use a supported, fully patched Grafana release. The demo
stack pins every image by tag and multi-architecture digest; CI supplies the
complete Grafana reference through `GRAFANA_IMAGE`.

## Grafana Cloud, Enterprise, and SSO validation (manual)

Container E2E cannot reproduce hosted API gateways, Enterprise RBAC, SSO, or
tenant policy. Before each production rollout, use a non-production
organization and complete this sequence:

- [ ] Use HTTPS with certificate verification. Store the service-account token
  in the deployment secret manager; do not use `--insecure` or a personal
  administrator password.
- [ ] Give the deployment identity only the target folder, datasource-read,
  dashboard-write, and alerting permissions it needs. Verify that an SSO viewer
  can read dashboards but cannot edit them or reveal datasource credentials.
- [ ] Run discovery with the intended organization and datasource. Treat any
  datasource 403/5xx as a failed gate; do not tolerate errors in the production
  validation run.
- [ ] Generate with explicit `--org-id`, `--folder`, and a stable tenant-specific
  `--uid-scope`. Review `--dry-run` output before using `--deploy`.
- [ ] Deploy to the staging folder, confirm every dashboard has live data, and
  verify alert rules evaluate and reach the approved contact point. Test both a
  firing condition and recovery notification.
- [ ] Validate SSO group-to-role mapping, folder isolation, datasource access,
  audit logging, retention, and API rate limits separately in Grafana Cloud or
  Enterprise.
- [ ] Export or otherwise back up the current dashboards and alert rules, record
  their UIDs, and rehearse rollback before promoting the same inputs to
  production.
- [ ] After deployment, inspect the generated manifest and Grafana audit log;
  any partial or failed resource makes the rollout unsuccessful.

## Ongoing operations

- [ ] Investigate the weekly registry-freshness issue when the 30-day threshold
  is crossed; update prices only from the official URLs in the registry.
- [ ] Triage Dependabot, CodeQL, secret-scanning, and failed compatibility jobs
  on a defined rotation.
- [ ] Revalidate Cloud/Enterprise/SSO behavior after a Grafana upgrade or any
  RBAC, datasource, organization, or identity-provider change.
