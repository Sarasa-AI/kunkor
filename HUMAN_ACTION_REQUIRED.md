# Human Action Required

The owner approved local Stage 0 verification on 2026-11-19 and explicitly deferred the following release checks. Each remains open. Astra evaluates local stages on verified code, security, schema, and test failures. These deferrals alone do not block a local stage.

- **R01 remote GitHub Actions** — PENDING. Owner selects and pushes the local commits, then records the workflow run URL and result.
- **Gitleaks Git history scan** — UNTESTED. Run with redacted output on the release candidate and reachable history.
- **Trivy dependency and image scan** — UNTESTED. Run against the release candidate and built images, then triage findings.
- **Node 20 CI parity** — UNTESTED. Re-run the frontend CI steps using the workflow's Node 20 runtime. Local evidence used Node 22.

## Live integrations and decisions

These affect activation of the corresponding live capability. Local verification uses signed synthetic identities, mock provider/transport responses, and disposable databases.

- Configure Telegram bot token and webhook secret through the deployment secret store before live verification. Validate the intended bot and webhook without real student data in staging.
- Configure the application model provider credential, approved model and price ceiling, daily budgets, and permitted runtime endpoint before enabling model calls. The supervisor credential is separate. Store no credential values here.
- Confirm curriculum and track metadata where required by the content record. The owner must approve source provenance and active usage rights per item before trusted use. An empty catalog is valid under D-13.
- Record production hosting and deployment decisions, and authorize any pilot separately.
