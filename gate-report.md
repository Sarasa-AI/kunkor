# Kunkor — Stage 0 & R01 Gate Evaluation Report

## 1. Executive Summary
- **Evaluation Date**: 2026-10-29
- **Evaluated Target Commit**: `30212416c9e56d99019c562f421d805111bbc044` (plus uncommitted verified remediations)
- **R01 Gate Status**: **CONDITIONAL / BLOCKED** (Local verification 100% PASS; Remote GitHub CI has 0 workflow runs and local commits cannot be pushed without explicit authorization).
- **Stage 0 Gate Status**: **COMPLETE LOCALLY / BLOCKED ON REMOTE CI** (TASK-00, TASK-01, TASK-02, TASK-03 completed locally; remote CI execution pending).
- **Stage 0.5 Readiness**: Evaluated and defined (`IntakeSlots`, `StudyPlan`, deterministic validator, 15 scenarios, `9router`).

---

## 2. Gate R01 Evaluation (PostgreSQL-Backed CI & Local Verification)

### Acceptance Criteria Checklist
| Criterion | Status | Evidence |
|---|---|---|
| PostgreSQL 16 Isolated Test Database | PASS (Local) | Ran against `postgres:16-alpine` on port 5435; isolated DB `kunkor_test`. |
| Database Migration Round-Trip (Up / Down / Up) | PASS (Local) | Verified via `test_migrations_forward_and_backward`. |
| Destructive Migration Isolation Guard | PASS (Local) | Verified via `test_destructive_checks_reject_application_database`. |
| Python Linting & Typecheck | PASS (Local) | `ruff check .` clean; `mypy app` (11 source files) clean. |
| Web Linting, Typecheck & Production Build | PASS (Local) | `npm run lint` clean; `npm run typecheck` clean; `npm run build` static export clean. |
| Zero High/Critical Dependency Vulnerabilities | PASS (Local) | `npm audit` returns 0 vulnerabilities after Next 15 / overrides upgrade. |
| Remote GitHub Actions CI Execution | **BLOCKED** | Remote repo `Sarasa-AI/kunkor` has 0 workflow runs for evaluated SHA. Git push requires authorization. |

### Conclusion on R01
R01 cannot be marked unconditionally **DONE** per protocol rules because no remote CI run exists for the evaluated commit. It is certified **CONDITIONAL: PASSING LOCALLY, BLOCKED ON REMOTE CI TRIGGER**.

---

## 3. Stage 0 Completion Audit

| Task | Description | Status | Verification Detail |
|---|---|---|---|
| `TASK-00` | Repository, CI & Skeleton | Done (Remediated) | Next 15 RTL frontend, FastAPI backend, healthz endpoint, CORS & config hardened. |
| `TASK-01` | Baseline Documents & Decisions | Done | `docs/decisions.md` (D-01..D-09), ADR-0001..0008, `PROGRESS.md`. |
| `TASK-02` | Database Foundation & Migrations | Done (Remediated) | Baseline schema applied; outbox retry bounded; append-only triggers validated. |
| `TASK-03` | Test Scenario Book | **Done** | `docs/test-scenarios/` (30 scenarios) + `services/api/tests/test_scenarios.py` (30 passed). |

---

## 4. Stage 0.5 Contract Implementation & Readiness

Stage 0.5 contracts and deterministic validation boundary are now implemented and covered by automated tests:

### 1. `IntakeSlots` Contract (`app.schemas.planning.IntakeSlots`)
- Encapsulates student intake parameters required for personalized study guidance:
  ```json
  {
    "stage_code": "konkur",
    "grade": "G12",
    "track": "experimental",
    "daily_study_capacity_minutes": 360,
    "target_exam": "konkur_1406",
    "weak_subjects": ["mathematics", "physics"]
  }
  ```
- Rejects untrusted raw prompt injections (`extra = "forbid"`).
- Enforces physiological limits (max 600m), stage ceilings (primary 30m, high 60m, etc.), and D-04 minor consent.

### 2. `StudyPlan` Contract (`app.schemas.planning.StudyPlan`)
- Schema strictly conforms to ADR-0004, ADR-0005, and ADR-0008:
  - `plan_id` (UUID)
  - `student_id` (UUID, non-nullable per ADR-0008)
  - `revision_no` (int >= 1)
  - `engine_version` (semantic version string)
  - `rule_set_version` (semantic version string)
  - `status` (`draft` | `active` | `superseded`)
  - `items`: Array of scheduled learning units (`StudyPlanItem`).

### 3. Deterministic Validator (`app.engines.validator.DeterministicValidator`)
- Pre-commit invariant checker:
  - Asserts sum of allocated unit minutes $\le$ `daily_study_capacity_minutes` and stage limit.
  - Asserts prerequisite graph acyclicity (DAG cycle detection) and topological order.
  - Verifies that every included resource is in `Published` state with active, non-expired license and matching stage code.
  - Rejects subjects not in track allowlist.
  - LLM proposals failing validator are rejected before reaching database persistence.

### 4. 9router Provider Reliability (`app.ai.provider.NineRouterProvider`)
- ADR-0006 compliance:
  - Pluggable `AiProvider` interface.
  - Bounded 15-second deadline.
  - Circuit breaker / fallback to `DeterministicRuleFallbackPlanner` on timeout, HTTP 500, or budget exhaustion.
  - Zero PII in prompts and secrets redacted from logs.
  - Fully verified via unit tests with mocks.

---

## 5. Gate Summary

| Gate | Status | Evidence | Remaining Blocker | Next Action |
|---|---|---|---|---|
| **R01** | `CONDITIONAL — SPECIFIC GATES REMAIN` | Local checks 100% PASS (63/63 pytest, Ruff, Mypy, Next 15 build, 0 CVEs) | Remote CI has 0 workflow runs | Authorize push to `origin/main` |
| **Stage 0** | `YES — VERIFIED` (Local) | TASK-00, TASK-01, TASK-02, TASK-03 complete & verified | Remote CI pending | Sync with remote CI |
| **TASK-03** | `YES — VERIFIED` | 30 scenarios documented; 30/30 tests pass | None | Complete |
| **Stage 0.5** | `YES — VERIFIED` | Contracts, validator, 9router fallback, 15 tests pass | Stage 1 prerequisites (WP-10 / TASK-04) | Ready for Stage 1 |

---

## 6. Stage 1 Readiness Matrix

| Prerequisite Component | Spec Ref | Current Status | Implemented Evidence | Missing Work | Dependency / Blockers | Entry Criterion Met? |
|---|---|---|---|---|---|---|
| **Identity & Sessions (WP-10)** | `spec.md` §2.1, WP-10 | Ready for Impl | Baseline schema has `audit_events`, `idempotency_keys` | Users table, OTP flow, JWT/session tables, rate limiter | D-09 (Mobile OTP via SMS) | **YES** (Design ready) |
| **Authorization Layer (WP-13)** | ADR-0003, WP-13 | Ready for Impl | `check_authz_matrix.py` enforces security markers | Guardian scopes (`profile.read`, `tasks.read`), RBAC dependencies | Needs WP-10 session model | **YES** (Architecture ready) |
| **Consent & Age Policy (WP-01/10)** | D-04, `spec.md` §1.6 | Implemented in Schema | `IntakeSlots` blocks primary cohorts without `guardian_consent` | DB table `guardian_consents` and revocation endpoint | None (D-04 applied) | **YES** (Contract verified) |
| **Student Temporal Profile (WP-11)** | ADR-0005, ADR-0008, WP-11 | Ready for Impl | ADR-0008 denormalized `student_id` in schemas; `btree_gist` installed in PG 16 | `students` table, `academic_histories` temporal table | Needs WP-10 User ID | **YES** (Schema defined) |
| **Curriculum Catalog (WP-12)** | `spec.md` §2.3, WP-12 | Ready for Impl | `ResourceMeta` model, topological validator in `engines/validator.py` | Catalog tables migration (`courses`, `topics`, `resources`) | None | **YES** (Engine ready) |
| **Deterministic Educational Rules (WP-21)** | ADR-0004, `spec.md` §2.1 | Implemented | `DeterministicValidator` (DAG check, time ceilings, license checks) | Extended golden tests for Stage 1 rulesets | None | **YES** (Verified) |
| **AI Fallback & Bounds (WP-32)** | ADR-0006, D-11 | Implemented | `NineRouterProvider` with 15s deadline, budget guard, zero PII | Integration with real 9router staging gateway | External API key (optional, has fallback) | **YES** (Verified) |

---

## 7. Next Move & Recommendations
1. Push authorization needed for `origin/main` to trigger remote CI workflow and verify R01 remotely.
2. Begin `TASK-04` (WP-10: Identity, User/Student models, and Session management).
