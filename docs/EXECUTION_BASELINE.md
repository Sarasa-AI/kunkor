# Kunkor — Execution Baseline & Repository Classification

## 1. Repository State

- **Date:** 2026-10-31
- **Platform:** Darwin (macOS Apple Silicon)
- **Current Branch:** `main`
- **Local HEAD SHA:** `30212416c9e56d99019c562f421d805111bbc044`
- **Remote `origin/main` SHA:** `4285df10cdc3beb8f3c5d36b47e392bfd1548c95`
- **Branch Relationship:** Local `main` is 3 commits ahead of `origin/main`.
- **Ahead Commits:**
  1. `8812c83` — `feat(infra): repository, ci, and skeleton (TASK-00)`
  2. `fdfe7de` — `docs(architecture): baseline decisions and ADRs (TASK-01)`
  3. `3021241` — `feat(db): database migrations, base tables, and append-only triggers (TASK-02)`

## 2. Commit Review (Ahead Commits)

Inspection of commits `8812c83`, `fdfe7de`, `3021241`:
- **Unrelated work:** None found. Commits strictly implement TASK-00 (skeleton, CI), TASK-01 (ADRs, decisions), and TASK-02 (migrations, initial tables, append-only triggers, outbox worker).
- **Stage 0.5 work:** None present in commit history. The packages `services/api/app/ai/__init__.py` and `services/api/app/engines/__init__.py` in those commits are empty baseline marker files (0 bytes).
- **Secrets/PII:** Clean. No hardcoded production credentials, private keys, or student PII detected.

## 3. Working Tree File Classification

### Tracked Modified Files (18)

| File | Current Status | Roadmap Task | Proposed Action | Rationale |
|---|---|---|---|---|
| `.github/workflows/ci.yml` | Modified | R01 | Include in R01 commit | Adds PostgreSQL 16 Alpine service, healthcheck, test DB migration, and `make migrate-check`. |
| `.gitignore` | Modified | R01 / Stage 0 | Include in R01 commit | Ignores `*.tsbuildinfo` generated during TypeScript compilation. |
| `PROGRESS.md` | Modified | Stage 0 | Include in Stage 0 closure commit | Updates TASK-03, R01, and Stage 0 completion statuses. |
| `README.md` | Modified | R01 | Include in R01 commit | Documents local and CI PostgreSQL 16 testing and verification commands. |
| `apps/web/next-env.d.ts` | Modified | R01 / Stage 0 | Include in R01 commit | Generated reference path matching Next.js 15. |
| `apps/web/package.json` | Modified | R01 / SEC-03 | Include in R01 commit | Upgrades Next.js to 15.5.28 and overrides `glob` (`^10.5.0`) and `postcss` (`^8.5.32`) resolving high/critical CVEs. |
| `apps/web/package-lock.json` | Modified | R01 / SEC-03 | Include in R01 commit | Lockfile corresponding to web security remediation. |
| `services/api/app/ai/__init__.py` | Modified | Stage 0.5 | **Exclude / Preserve** | Working tree re-exports `NineRouterProvider` from prototype `provider.py`. Must remain uncommitted for Stage 0.5. |
| `services/api/app/core/config.py` | Modified | Stage 0 (SEC-01, SEC-02) | Include in Stage 0 remediation | Adds `CORS_ALLOWED_ORIGINS` setting and production password rejection validator. |
| `services/api/app/engines/__init__.py` | Modified | Stage 0.5 | **Exclude / Preserve** | Working tree re-exports `DeterministicValidator` from prototype `validator.py`. Must remain uncommitted for Stage 0.5. |
| `services/api/app/main.py` | Modified | Stage 0 (SEC-01) | Include in Stage 0 remediation | Enforces explicit origin whitelist and disallows wildcard CORS with credentials. |
| `services/api/app/workers/outbox_worker.py` | Modified | Stage 0 (WK-01..04) | Include in Stage 0 remediation | Fixes unbounded retry loop, adds `MAX_RETRIES = 5`, per-event transaction isolation, and dead-letter logging. |
| `services/api/scripts/check_authz_matrix.py` | Modified | Stage 0 (SEC-05) / R01 | Include in R01 / Stage 0 | Fixes false positive route authorization inspection. |
| `services/api/scripts/migrate.py` | Modified | Stage 0 (SEC-02) / R01 | Include in R01 commit | Guard against default credentials in production environment. |
| `services/api/scripts/migrate_check.py` | Modified | R01 (B2) / DB-04 | Include in R01 commit | Enforces `require_test_database()` guard preventing destructive checks on non-disposable databases. |
| `services/api/tests/conftest.py` | Modified | R01 (B2) | Include in R01 commit | Calls `require_test_database(TEST_DB_URL)` before session migration fixture. |
| `services/api/tests/test_migrations.py` | Modified | R01 (B2) / DB-04 | Include in R01 commit | Adds `test_destructive_checks_reject_application_database`. |
| `services/api/tests/test_outbox_worker.py` | Modified | Stage 0 (WK-01..04) | Include in Stage 0 remediation | Adds test verifying dead-lettering after maximum retries. |

### Untracked Files (21)

| File | Current Status | Roadmap Task | Proposed Action | Rationale |
|---|---|---|---|---|
| `AUDIT_05_SECURITY_OPERATIONS.md` | Untracked | Stage 0 Reference | Preserve | Prior security and operational audit report. |
| `AUDIT_06_CONSOLIDATED_ROADMAP.md` | Untracked | Stage 0 Reference | Preserve | Prior consolidated roadmap audit report. |
| `R01_CI_VERIFICATION_REPORT.md` | Untracked | R01 Deliverable | Update & Include | R01 verification evidence deliverable. |
| `decision-register.md` | Untracked | Documentation | Preserve | Comprehensive ADR and decision register. |
| `docs/tasks/TASK-03.md` | Untracked | Stage 0 (TASK-03) | Include in Stage 0 | Task record for acceptance scenarios book. |
| `docs/test-scenarios/` (6 files) | Untracked | Stage 0 (TASK-03) | Include in Stage 0 | 30 acceptance scenarios (5 groups x 3 success + 3 failure). |
| `execution-log.md` | Untracked | Audit Log | Preserve / Update | Historical execution log. |
| `gate-report.md` | Untracked | Stage 0 Reference | Preserve / Update | Stage 0 evaluation gate report. |
| `security-fixes.md` | Untracked | Stage 0 Reference | Preserve | Documentation of SEC-01 through SEC-05 fixes. |
| `stage-0-audit.md` | Untracked | Stage 0 Reference | Preserve | Input source for required `STAGE_0_AUDIT_REPORT.md`. |
| `services/api/app/ai/provider.py` | Untracked | Stage 0.5 Prototype | **Preserve / Isolate** | Stage 0.5 9router and fallback provider. Do not stage or commit. |
| `services/api/app/engines/validator.py` | Untracked | Stage 0.5 Prototype | **Preserve / Isolate** | Stage 0.5 deterministic validator engine. Do not stage or commit. |
| `services/api/app/schemas/__init__.py` | Untracked | Stage 0.5 Prototype | **Preserve / Isolate** | Stage 0.5 schemas package. Do not stage or commit. |
| `services/api/app/schemas/planning.py` | Untracked | Stage 0.5 Prototype | **Preserve / Isolate** | Stage 0.5 IntakeSlots and StudyPlan schemas. Do not stage or commit. |
| `services/api/tests/test_9router_reliability.py` | Untracked | Stage 0.5 Prototype | **Preserve / Isolate** | Stage 0.5 reliability tests. Do not stage or commit. |
| `services/api/tests/test_stage_05_validator.py` | Untracked | Stage 0.5 Prototype | **Preserve / Isolate** | Stage 0.5 validator tests. Do not stage or commit. |
| `services/api/tests/test_scenarios.py` | Untracked | Stage 0 (TASK-03) | Include in Stage 0 | Automated tests for 30 acceptance scenarios. |
| `services/api/tests/test_security_remediation.py` | Untracked | Stage 0 Remediation | Include in Stage 0 | Automated tests verifying SEC-01, SEC-02, SEC-05, and outbox fixes. |

## 4. Known Blockers

1. **Remote CI Execution**: Remote repository `Sarasa-AI/kunkor` has 0 GitHub Actions runs. R01 requires pushing verified code to trigger and confirm green CI on GitHub.
2. **Ahead Commits Publication**: Local `main` is 3 commits ahead of `origin/main` (`8812c83`, `fdfe7de`, `3021241`). Pushing R01 to `origin/main` will publish these commits.
3. **Stage 0.5 Contamination Risk**: `services/api/app/ai/__init__.py` and `services/api/app/engines/__init__.py` in the working tree contain imports from untracked Stage 0.5 files. If committed, CI in GitHub Actions would fail with `ModuleNotFoundError`. These two files must NOT be included in R01 or Stage 0 commits.

## 5. Risks and Mitigations

- **Risk: Premature Stage 0.5 exposure.**
  - *Mitigation:* Explicit file staging list. Stage 0.5 files remain untracked and unstaged.
- **Risk: Non-disposable database mutation.**
  - *Mitigation:* `require_test_database()` enforces strict checks: database name must end in `_test`, host must be in allowlist, environment must not be production.
- **Risk: Remote push rejection.**
  - *Mitigation:* Confirm remote tracking SHA before pushing; never force-push.

## 6. Execution Boundaries

- **In Scope:**
  - R01: PostgreSQL CI verification and test isolation.
  - Stage 0: Repository inventory (`docs/STAGE_0_REPOSITORY_INVENTORY.md`), security and technical audit (`docs/STAGE_0_AUDIT_REPORT.md`), TASK-03 scenarios, confirmed security remediation.
- **Out of Scope (Explicitly Isolated):**
  - Stage 0.5 implementations (`provider.py`, `validator.py`, `schemas/`, `test_9router_reliability.py`, `test_stage_05_validator.py`, D-11 inclusion).
  - Stage 1 implementations (Telegram, user onboarding, n8n, vector DB, supervisor).
