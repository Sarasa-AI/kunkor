# KUNKOR — SECURITY, TESTING AND OPERATIONAL READINESS AUDIT
Document ID: `AUDIT-05-SEC-OPS`  
Scope: Current repository commit baseline (TASK-00, TASK-01, TASK-02).  
Status: FAILED G0/G1 READINESS. NOT PRODUCTION READY.

---

## 1. Security Findings

| Finding ID | Severity | Component | Summary | Status |
|---|---|---|---|---|
| `SEC-01` | Critical | `services/api/app/main.py:12-18` | Wildcard CORS origin (`allow_origins=["*"]`) combined with `allow_credentials=True`. Browsers reject credentialed wildcard CORS; misconfiguration allows arbitrary cross-origin session hijacking when configured with origins or credentials reflection. | Confirmed |
| `SEC-02` | High | `services/api/app/core/config.py`, `docker-compose.yml`, `scripts/migrate.py` | Hardcoded default secrets and database credentials (`kunkor_dev_password`) in source repository. Fallback strings used directly if environment variables unset. | Confirmed |
| `SEC-03` | High | `apps/web/package.json` | 5 Known CVEs in Web dependencies (1 Critical, 4 High): Next.js DoS, Cache Poisoning, SSRF vulnerabilities, Glob CLI command injection (`GHSA-5j98-mcp5-4vw2`), PostCSS path traversal / XSS. | Confirmed |
| `SEC-04` | Medium | `services/api/requirements.txt` | Unpinned dependencies (`>=` versions instead of exact pin/lockfile hash). Vulnerable to supply chain tampering and non-deterministic builds. | Confirmed |
| `SEC-05` | Medium | `services/api/scripts/check_authz_matrix.py` | Naive route endpoint inspection: routes using sub-routers or FastAPI dependencies bypassing attribute check falsely report 100% authorization compliance. | Confirmed |
| `SEC-06` | Medium | `.github/workflows/ci.yml:74-75` | Ineffective secret scanning in CI: literal string grep matching only two static tokens (`PRIVATE KEY`, `kunkor_prod_secret`). Fails to catch API keys, database URLs, or real tokens. | Confirmed |
| `SEC-07` | Low | `services/api/Dockerfile`, `apps/web/Dockerfile` | Containers run as default `root` user. Lacks `USER` directive isolation in runtime containers. | Confirmed |
| `SEC-08` | Low | `services/api/migrations/0001_baseline_schema.up.sql:12` | Trigger `prevent_append_only_mutation()` raises SQL error code `'23505'` (unique_violation) instead of `'42501'` (insufficient_privilege) or `'22000'` (data exception). | Confirmed |

### Verification Details for Key Findings

#### `SEC-01`: Insecure CORS Policy
- **Evidence:** `services/api/app/main.py`:
  ```python
  app.add_middleware(
      CORSMiddleware,
      allow_origins=["*"],
      allow_credentials=True,
      allow_methods=["*"],
      allow_headers=["*"],
  )
  ```
- **Impact:** Any malicious domain can execute authenticated cross-origin requests if credentials reflection is used, or causes complete CORS handshake failures on strict browsers.
- **Remediation:** Restrict `allow_origins` to explicit domain list via environment variable (e.g. `settings.CORS_ALLOWED_ORIGINS`). Set `allow_credentials=False` for public routes.

#### `SEC-02`: Hardcoded Database Password Defaults
- **Evidence:** `services/api/app/core/config.py`:
  ```python
  DATABASE_URL: str = os.getenv(
      "DATABASE_URL",
      "postgresql://kunkor:kunkor_dev_password@localhost:5435/kunkor_dev",
  )
  ```
- **Impact:** Predictable credentials expose unauthorized database access in local, dev, and improperly configured staging environments.
- **Remediation:** Remove defaults for production; require explicit `DATABASE_URL` injection; fail fast on startup if missing in non-dev environment.

---

## 2. Educational & AI-Specific Risk Assessment

| Risk Vector | Current Architecture Status | Evaluated Safeguard / Flaw | Risk Level |
|---|---|---|---|
| Cross-Student Data Leakage | Schema ready (`student_id` denormalized), Application layer missing | Module logic (TASK-04 to TASK-07) unbuilt. No RLS active in Postgres yet. Current API lacks student authorization checks. | High |
| Unsupported Educational Claims | Rules engine not yet implemented | Pure deterministic rule-based evaluation specified in ADR-4 / Spec 2.6 not yet written. | Medium |
| Infeasible Study Schedules | Planning module not implemented | Planning engine (TASK-13/14) not implemented. | Medium |
| Uncontrolled Model Tool Access | Spec mandates isolated LLM abstraction (ADR-6) | AI code not present (planned P1/TASK-25). No LLM execution pathways currently exist in codebase. | Low |
| Prompt Injection | Spec mandates structured output only | AI integration pending. Architecture relies on retrieval-first without open generative agents. | Low (Current) / High (Future) |
| Model Call Data Leakage | ADR-6 pluggable AI abstraction | No external API calls currently implemented. | Low (Current) |
| Unbounded Model Retries | Outbox worker present, AI worker missing | `outbox_events.retry_count` column exists. Backoff and dead-letter queues not implemented in worker. | Medium |
| Excessive Parallel Execution | Queue is polling-based stub | Outbox worker uses synchronous sequential single-thread loop (`limit=50`). No rate limit on outbound jobs. | Medium |
| Duplicate Telegram Updates | Not in MVP | Out of scope for current iteration. | N/A |
| Silent Plan Generation Failures | Planning engine unbuilt | Transactional guarantees exist via DB, but domain error handling is pending. | Medium |

---

## 3. Test Infrastructure & Execution Results

### Test Suite Execution Summary

| Test Category | Target / Command | Result | Details / Root Cause |
|---|---|---|---|
| Linter (Python) | `services/api && ruff check .` | **Passed** | Clean. 0 errors. |
| Linter (Web) | `apps/web && npm run lint` | **Passed** | Clean. 0 errors. |
| Typecheck (Python) | `services/api && mypy app` | **Passed** | 11 source files checked. 0 errors. |
| Typecheck (Web) | `apps/web && npm run typecheck` | **Passed** | `tsc --noEmit` clean. 0 errors. |
| Import Boundary Check | `make import-check` | **Passed** | AST analysis passed with 0 modular violations. |
| Authz Matrix Verification | `make authz-matrix` | **Passed (Surface)** | Evaluated 5 routes. 100% compliance reported. |
| DB Migration Integrity | `make migrate-check` | **Failed** | Blocked: PostgreSQL daemon not running on port 5435 (`Connection refused`). |
| Pytest Test Suite | `services/api && pytest` | **Failed** | 8 tests collected; 8 setup errors due to missing test database connection. |
| Secret Scanning | `ci.yml` grep step | **Passed (Weak)** | Naive pattern matching passed, but misses real risks. |
| Frontend Unit/E2E | None | **Not Applicable** | No tests configured or written in `apps/web`. |

---

## 4. Infrastructure & Deployment Readiness

- **Docker & Compose:** Configuration present in `docker-compose.yml` defining `db`, `api`, `web`, and `queue`. Database uses custom port `5435:5432`.
- **Database Initialization:** `init-db.sql` enables `btree_gist` and `uuid-ossp`. Schema applied via custom script `scripts/migrate.py`.
- **Connection Management:** No connection pooling library (e.g. `psycopg_pool`) configured in `app/core/db.py`; connections opened and closed per request/operation.
- **Clean Environment Launch:** Fails out of the box if Docker daemon is not active. Local test runs require live Postgres running on port 5435.

---

## 5. Reliability & Operational Assessment

- **Database Transactions:** Handled explicitly in migrations and outbox workers (`with conn.transaction()`).
- **Append-Only Protection:** Verified via trigger function `prevent_append_only_mutation()` on `audit_events`.
- **Outbox Worker Failure Modes:** In `app/workers/outbox_worker.py`, unhandled payload processing exceptions during event publishing do not increment `retry_count` or route to a dead-letter queue, creating an infinite processing loop for poison pill events.
- **Connection Leakage:** Connection functions rely on context managers; unhandled connection failures during initialization raise raw driver errors without structured fallback.

---

## 6. Dependency & Configuration Risks

### Frontend (`apps/web`)
- 5 high/critical vulnerabilities identified by `npm audit`:
  - `glob`: Command injection via CLI arguments (`GHSA-5j98-mcp5-4vw2`).
  - `next`: Denial of Service and Server-Side Request Forgery vulnerabilities in Next.js 14.2.15.
  - `postcss`: Arbitrary file disclosure via `sourceMappingURL`.

### Backend (`services/api`)
- Direct dependencies unpinned in `requirements.txt` (`>=` constraint only).
- Missing cryptographic digest verification / `pip-tools` compile lockfile (`requirements.lock`).

---

## 7. Prioritized Remediation Backlog

| Rank | Issue ID | Component | Required Action | Target Gate |
|---|---|---|---|---|
| 1 | `SEC-01` | API | Fix CORS configuration in `app/main.py`. Disallow wildcard with credentials. | Immediate / G0 |
| 2 | `SEC-03` | Web | Upgrade `next`, `eslint-config-next`, and lockfile dependencies. | Immediate / G0 |
| 3 | `OPS-01` | Workers | Add dead-letter queue and retry count increments in `outbox_worker.py`. | G1 |
| 4 | `SEC-02` | API / Config | Remove hardcoded passwords; enforce strict environment variable injection. | G1 |
| 5 | `SEC-04` | API | Generate locked dependencies (`pip-tools` / poetry / hash-locked requirements). | G1 |
| 6 | `SEC-06` | CI | Integrate Trufflehog or Gitleaks for automated secret scanning in CI. | G1 |
| 7 | `SEC-07` | Infra | Configure non-root user execution in both Dockerfiles. | G1 |
| 8 | `SEC-08` | Migrations | Correct SQL error code in `prevent_append_only_mutation` trigger. | G1 |

---

## 8. Release-Blocking Issues

1. **Permissive CORS Policy:** Must be restricted before any public API gateway exposure.
2. **Critical Dependency Vulnerabilities:** Next.js and Glob CVEs must be patched before production traffic.
3. **Database Integration Pipeline Failure:** Automated tests and migration checks cannot run without containerized database services in CI.
4. **Poison-Pill Worker Loop:** Outbox worker lacks retry bounding and failure isolation.

---

## 9. Minimum Production-Readiness Checklist

- [ ] CORS allowed origins constrained to whitelisted production domains.
- [ ] Database credentials, API tokens, and secrets supplied exclusively through runtime environment or secrets manager.
- [ ] All npm dependencies patched; `npm audit` returns 0 vulnerabilities.
- [ ] Python requirements locked with explicit hash pinning.
- [ ] Database connection pooling implemented (`psycopg_pool`).
- [ ] Containerized integration tests and forward/backward migration checks automated and green in CI pipeline.
- [ ] Non-root execution configured in Docker containers.
- [ ] Outbox processor equipped with exponential backoff and dead-letter queue.
