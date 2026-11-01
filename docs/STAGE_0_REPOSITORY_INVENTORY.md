# Kunkor — Stage 0 Repository Inventory

## 1. Overview & Repository Topology

- **Repository Root:** `/Users/sarasa/Documents/kunkor`
- **Architecture Pattern:** Modular Monolith (ADR-0001)
- **Primary Languages & Runtimes:** Python 3.11+ (FastAPI), TypeScript / Node.js 20+ (Next.js 15), PostgreSQL 16
- **Workspace Structure:**
  - `services/api/`: Backend service (FastAPI, database migrations, worker processes, verification scripts)
  - `apps/web/`: Frontend presentation application (Next.js 15 App Router, Persian RTL)
  - `packages/contracts/`: Shared schemas and contracts root
  - `docs/`: Architecture Decision Records (`docs/adr/`), decisions log (`docs/decisions.md`), execution baselines, task specifications, and acceptance scenario books (`docs/test-scenarios/`)
  - `.github/workflows/`: Continuous integration pipeline (`ci.yml`)

---

## 2. Component Inventory

### 2.1 Backend Application (`services/api`)

- **Entry Point:** `services/api/app/main.py`
  - Instantiates `FastAPI(title="Kunkor Educational Platform API", version="0.1.0")`
  - Enforces whitelisted CORS origin headers via `CORSMiddleware` (SEC-01)
  - Registers system health endpoint `/healthz`
- **Configuration Engine:** `services/api/app/core/config.py`
  - Pydantic-based `Settings(BaseSettings)`
  - Environment attributes: `ENVIRONMENT`, `DATABASE_URL`, `TEST_DATABASE_URL`, `APP_PORT`, `CORS_ALLOWED_ORIGINS`
  - Model validator `validate_environment_and_credentials()` enforcing fail-fast termination in production if `DATABASE_URL` is missing or uses `kunkor_dev_password` (SEC-02)
  - Origin parser parsing comma-separated and JSON list representations, strictly stripping wildcard `*` when credentials are active
- **Database Connection Layer:** `services/api/app/core/db.py`
  - Context manager `get_db_connection(test: bool = False)` wrapping `psycopg.connect()`
  - Explicit row factories (`psycopg.rows.dict_row`)
  - Dual targeting for application vs. test databases
- **Worker Processes:**
  - `services/api/app/workers/outbox_worker.py`: Polling worker consuming `outbox_events` using `FOR UPDATE SKIP LOCKED`. Hardened with `MAX_RETRIES = 5`, per-event transaction isolation, and dead-letter classification (WK-01..04).
  - `services/api/app/workers/placeholder_worker.py`: Service stub for background task execution.
- **Verification Scripts:**
  - `services/api/scripts/migrate.py`: Direct migration runner executing SQL migration files in forward order.
  - `services/api/scripts/migrate_check.py`: Verification harness testing forward, backward rollback, and re-application reversibility. Guarded by `require_test_database()` (DB-04).
  - `services/api/scripts/check_authz_matrix.py`: AST and route dependency inspector enforcing authorization policies (SEC-05).
  - `services/api/scripts/check_imports.py`: Modular boundary enforcement ensuring strict unidirectional module dependencies.
  - `services/api/scripts/seed_dev.py`: Development seed data generator.

### 2.2 Frontend Application (`apps/web`)

- **Framework:** Next.js 15.5.28 with React 19 / TypeScript
- **Styling & Localization:** Tailwind CSS with native right-to-left Persian font stack (`Vazirmatn`) and RTL layout (`apps/web/src/app/layout.tsx`)
- **Landing Smoke Component:** `apps/web/src/app/page.tsx`
  - Queries `/healthz` on FastAPI API service
  - Renders Iranian educational platform branding and operational connectivity status
- **Supply Chain Hardening:** Package lockfile enforced with overrides for `glob` (`^10.5.0`) and `postcss` (`^8.5.32`), achieving zero high/critical CVEs (SEC-03).

---

## 3. Route & Endpoint Inventory

The application currently exposes the following HTTP endpoints (all validated by `check_authz_matrix.py`):

| Method | Path | Summary / Tag | Authz Policy | Whitelist Rationale |
|---|---|---|---|---|
| `GET` | `/healthz` | System liveness probe | Public | Unauthenticated orchestration probe |
| `GET` | `/docs` | OpenAPI Swagger UI | Public | Developer documentation |
| `GET` | `/redoc` | OpenAPI ReDoc UI | Public | Developer documentation |
| `GET` | `/openapi.json` | OpenAPI JSON Schema | Public | API contract distribution |
| `GET` | `/docs/oauth2-redirect` | Swagger OAuth2 redirect | Public | OpenAPI documentation helper |

*Note: No unprotected business or student endpoints exist. All future student-facing routes require explicit `__authz_required__` or authz dependency enforcement per SEC-05.*

---

## 4. Database Schema & Tables Inventory

Database migrations are located in `services/api/migrations/` and managed sequentially. Migration `0001_baseline_schema` establishes:

### Extensions
- `btree_gist`: Multi-column index acceleration and exclusion constraints
- `uuid-ossp`: UUID generation helpers

### Tables & Schema Structure

1. **`audit_events`** (Section 2.3 / WP-13 / ADR-0005)
   - **Columns:**
     - `id`: `UUID PRIMARY KEY DEFAULT gen_random_uuid()`
     - `actor_user_id`: `UUID` (Nullable)
     - `student_id`: `UUID` (Indexed per ADR-0008)
     - `action`: `VARCHAR(100) NOT NULL` (Indexed)
     - `resource_type`: `VARCHAR(100) NOT NULL`
     - `resource_id`: `VARCHAR(100)`
     - `metadata`: `JSONB NOT NULL DEFAULT '{}'`
     - `request_id`: `VARCHAR(100)`
     - `occurred_at`: `TIMESTAMPTZ NOT NULL DEFAULT NOW()`
   - **Trigger Protection:** `trg_audit_events_append_only` calling `prevent_append_only_mutation()`, strictly rejecting all `UPDATE` and `DELETE` queries at database level.
   - **Indexes:** `(student_id, occurred_at)`, `(actor_user_id, occurred_at)`, `(action, occurred_at)`.

2. **`outbox_events`** (Section 2.3 / Transactional Outbox Pattern)
   - **Columns:**
     - `id`: `UUID PRIMARY KEY DEFAULT gen_random_uuid()`
     - `student_id`: `UUID` (Indexed per ADR-0008)
     - `event_type`: `VARCHAR(100) NOT NULL`
     - `aggregate_type`: `VARCHAR(100) NOT NULL`
     - `aggregate_id`: `VARCHAR(100) NOT NULL`
     - `payload`: `JSONB NOT NULL DEFAULT '{}'`
     - `occurred_at`: `TIMESTAMPTZ NOT NULL DEFAULT NOW()`
     - `processed_at`: `TIMESTAMPTZ` (Null until dispatched)
     - `retry_count`: `INT NOT NULL DEFAULT 0`
   - **Indexes:** Partial index `(occurred_at) WHERE processed_at IS NULL`, `(student_id, occurred_at)`.

3. **`idempotency_keys`** (Section 2.3)
   - **Columns:**
     - `id`: `UUID PRIMARY KEY DEFAULT gen_random_uuid()`
     - `student_id`: `UUID`
     - `key`: `VARCHAR(255) NOT NULL`
     - `request_hash`: `VARCHAR(64) NOT NULL`
     - `response_code`: `INT`
     - `response_body`: `JSONB`
     - `created_at`: `TIMESTAMPTZ NOT NULL DEFAULT NOW()`
     - `locked_until`: `TIMESTAMPTZ`
   - **Indexes:** Unique index `(key, COALESCE(student_id, '00000000-0000-0000-0000-000000000000'::uuid))`.

4. **`feature_flags`** (Section 2.3)
   - **Columns:**
     - `id`: `UUID PRIMARY KEY DEFAULT gen_random_uuid()`
     - `name`: `VARCHAR(100) NOT NULL UNIQUE`
     - `description`: `TEXT`
     - `is_enabled`: `BOOLEAN NOT NULL DEFAULT FALSE`
     - `rules`: `JSONB NOT NULL DEFAULT '{}'`
     - `created_at`: `TIMESTAMPTZ NOT NULL DEFAULT NOW()`
     - `updated_at`: `TIMESTAMPTZ NOT NULL DEFAULT NOW()`

5. **`entitlements`** (FR-S1 / Section 2.3 / D-06)
   - **Columns:**
     - `id`: `UUID PRIMARY KEY DEFAULT gen_random_uuid()`
     - `feature_key`: `VARCHAR(100) NOT NULL`
     - `user_id`: `UUID` (Indexed)
     - `student_id`: `UUID` (Indexed per ADR-0008)
     - `is_granted`: `BOOLEAN NOT NULL DEFAULT TRUE`
     - `valid_from`: `TIMESTAMPTZ NOT NULL DEFAULT NOW()`
     - `valid_to`: `TIMESTAMPTZ`
     - `created_at`: `TIMESTAMPTZ NOT NULL DEFAULT NOW()`
   - **Indexes:** `(student_id, feature_key)`, `(user_id, feature_key)`.

---

## 5. Outbox Worker Architecture & Operational Behavior

- **File:** `services/api/app/workers/outbox_worker.py`
- **Execution Model:** Continuous polling worker (`run_worker(poll_interval=2.0, once=False)`).
- **Concurrency & Locking:**
  - Queries pending records using `SELECT ... FROM outbox_events WHERE processed_at IS NULL AND retry_count < 5 ORDER BY occurred_at ASC LIMIT %s FOR UPDATE SKIP LOCKED`.
  - Guarantees zero worker lock contention across parallel replicas.
- **Fault Tolerance & Poison-Pill Handling:**
  - Each individual event dispatch is wrapped in its own database transaction (`with conn.transaction():`).
  - Successful dispatch updates `processed_at = NOW()`.
  - Dispatch exceptions trigger failure logging, increment `retry_count = retry_count + 1`, and preserve other events in the batch.
  - Events reaching `retry_count >= 5` are logged at `CRITICAL` as dead-lettered and excluded from active polling queries.
  - The outer worker polling loop catches general `Exception`, logs details, sleeps for `poll_interval`, and resumes, preventing worker process exit on transient failures.

---

## 6. Test Suite & Test Scenarios Inventory

### 6.1 Automated Test Suite (`services/api/tests/`)

- `test_healthz.py`: API status check (1 test).
- `test_append_only.py`: Verifies immutability trigger preventing UPDATE and DELETE on `audit_events` (3 tests).
- `test_idempotency_and_flags.py`: Verifies unique constraints and flag toggles (2 tests).
- `test_migrations.py`: Verifies round-trip reversibility and destructive database guards (2 tests).
- `test_outbox_worker.py`: Verifies event processing and dead-lettering after 5 retries (2 tests).
- `test_security_remediation.py`: Verifies SEC-01 CORS origins, SEC-02 environment guards, SEC-05 authz inspector, and outbox retry counter (10 tests).
- **Total Automated Unit/Integration Tests in Baseline:** 20 tests.

### 6.2 Acceptance Test Scenario Book (`docs/test-scenarios/`)

Documented per WP-06 / TASK-03 across all 5 educational stages (6 scenarios each: 3 success + 3 failure, totaling 30 scenarios):
1. **Primary Low (`docs/test-scenarios/primary_low.md`):**
   - `SCEN-PL-S01`: Play-based phonics learning path.
   - `SCEN-PL-S02`: Guardian co-viewing session initiation.
   - `SCEN-PL-S03`: Audio-first reading comprehension feedback.
   - `SCEN-PL-F01`: Autonomous registration rejected without guardian consent (D-04).
   - `SCEN-PL-F02`: Daily screen/study capacity overage rejected (>30 mins).
   - `SCEN-PL-F03`: Text-heavy abstract math unit rejected.
2. **Primary High (`docs/test-scenarios/primary_high.md`):**
   - `SCEN-PH-S01`: Structured homework pacing.
   - `SCEN-PH-S02`: Formative self-assessment check-in.
   - `SCEN-PH-S03`: Teacher-assigned remedial fractions module.
   - `SCEN-PH-F01`: Unsupervised profile privacy modification blocked.
   - `SCEN-PH-F02`: Unlicensed supplementary content rejected (D-02).
   - `SCEN-PH-F03`: Excessive study workload rejected (>60 mins).
3. **Lower Secondary (`docs/test-scenarios/lower_secondary.md`):**
   - `SCEN-LS-S01`: Grade 9 academic branch exploration.
   - `SCEN-LS-S02`: Weekly self-directed study schedule generation.
   - `SCEN-LS-S03`: Conceptual science mastery check-in.
   - `SCEN-LS-F01`: Prerequisite cycle in study plan rejected.
   - `SCEN-LS-F02`: High-stakes Konkur test assigned to Grade 7 rejected.
   - `SCEN-LS-F03`: Private student reflection leaked to guardian blocked (D-04).
4. **Upper Secondary (`docs/test-scenarios/upper_secondary.md`):**
   - `SCEN-US-S01`: Experimental track physics & chemistry schedule.
   - `SCEN-US-S02`: Final exam review timetable generation.
   - `SCEN-US-S03`: Missed task dynamic rebalancing.
   - `SCEN-US-F01`: Daily study ceiling breach rejected (>480 mins).
   - `SCEN-US-F02`: Prompt injection attempting curriculum bypass rejected.
   - `SCEN-US-F03`: Cross-track subject assignment rejected without elective flag.
5. **Konkur (`docs/test-scenarios/konkur.md`):**
   - `SCEN-KO-S01`: Comprehensive 12-month Konkur study plan generation.
   - `SCEN-KO-S02`: Mock exam manual score intake & weak topic diagnosis.
   - `SCEN-KO-S03`: High-intensity sprint allocation within physiological limits.
   - `SCEN-KO-F01`: Physiological study limit violation rejected (>600 mins).
   - `SCEN-KO-F02`: Uncalibrated mock exam scoring rejected.
   - `SCEN-KO-F03`: Superseded plan mutation rejected (append-only revision required).

---

## 7. Working Tree Isolation Status

Per project safety protocols and Decision D-11 boundary rules:
- **Preserved in Working Tree (Stage 0.5 Prototypes — NOT COMMITTED):**
  - `services/api/app/ai/provider.py`
  - `services/api/app/engines/validator.py`
  - `services/api/app/schemas/` (`__init__.py`, `planning.py`)
  - `services/api/tests/test_9router_reliability.py`
  - `services/api/tests/test_stage_05_validator.py`
  - `services/api/tests/test_scenarios.py`
  - `services/api/app/ai/__init__.py` (re-exports prototype provider)
  - `services/api/app/engines/__init__.py` (re-exports prototype validator)
- **Stage 0 Committed Baseline:**
  - Hardened config, CORS, outbox worker, authz checker, test isolation, documentation, and TASK-03 scenario book.
