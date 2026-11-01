# Kunkor — Security Remediation Record

## 1. Overview
Remediation of confirmed security vulnerabilities identified in Stage 0 baseline. All remediations accompanied by automated regression tests in `services/api/tests/test_security_remediation.py` and validated against clean linters and test suites.

---

## 2. Findings & Concrete Remediations

### SEC-01: Insecure CORS Configuration
- **Vulnerability**: `services/api/app/main.py` configured `CORSMiddleware` with `allow_origins=["*"]` and `allow_credentials=True`. Modern browsers reject credentialed wildcard CORS; misconfigured reflection exposes cross-origin credential theft.
- **Fix**:
  - Added `CORS_ALLOWED_ORIGINS: list[str]` to `Settings` in `services/api/app/core/config.py` defaulting to `["http://localhost:3000", "http://127.0.0.1:3000"]`.
  - Added parsing for JSON arrays and comma-separated origin strings.
  - Hardened validator to strip `*` from origin list whenever `allow_credentials=True` is enabled.
  - Pointed `CORSMiddleware` in `services/api/app/main.py` directly to `settings.CORS_ALLOWED_ORIGINS`.
- **Tests**:
  - `test_sec_01_cors_allowed_origin`: Confirms allowed origin receives CORS response headers.
  - `test_sec_01_cors_disallowed_origin_rejected`: Confirms unwhitelisted origin is not echoed.
  - `test_sec_01_cors_wildcard_never_allowed_with_credentials`: Asserts `*` is filtered out.

---

### SEC-02: Hardcoded Insecure Default Passwords
- **Vulnerability**: `services/api/app/core/config.py` and `scripts/migrate.py` defaulted `DATABASE_URL` to `postgresql://kunkor:kunkor_dev_password@localhost:5435/kunkor_dev` without production environment guards.
- **Fix**:
  - Implemented `validate_environment_and_credentials` model validator in `Settings`:
    - In `ENVIRONMENT=production`: raises `ValueError` if `DATABASE_URL` is empty.
    - In `ENVIRONMENT=production`: raises `ValueError` if `kunkor_dev_password` is present in `DATABASE_URL`.
  - Hardened `scripts/migrate.py` with `validate_production_db_url()` preventing migrations against production using default credentials.
- **Tests**:
  - `test_sec_02_production_missing_database_url_fails`: Verifies startup abort on missing production DB URL.
  - `test_sec_02_production_insecure_default_password_fails`: Verifies startup abort when dev password used in production.
  - `test_sec_02_development_defaults_allowed`: Confirms local development developer workflow remains zero-friction.

---

### SEC-03: Web Dependency Supply Chain CVEs
- **Vulnerability**: `apps/web/package.json` had 5 known CVEs (1 Critical, 4 High) in Next.js 14.2.35, Glob 10.3.10, and PostCSS 8.4.31.
- **Fix**:
  - Upgraded Next.js from `14.2.15` to `^15.5.28`.
  - Added npm dependency overrides:
    ```json
    "overrides": {
      "glob": "^10.5.0",
      "postcss": "^8.5.32"
    }
    ```
  - Rebuilt package lockfile; verified 0 vulnerabilities via `npm audit`.
- **Tests**:
  - `npm run lint`: Clean (0 warnings, 0 errors).
  - `npm run typecheck`: Clean (0 errors).
  - `npm run build`: Production static generation passes.

---

### SEC-05: Authz Matrix Checker False Positives
- **Vulnerability**: `services/api/scripts/check_authz_matrix.py` checked if `len(route.dependant.dependencies) > 0`. A dummy dependency like `Depends(lambda: None)` was falsely counted as 100% compliant authorization.
- **Fix**:
  - Refactored `has_valid_authz()` to require:
    - Explicit route attribute `_authz_enforced = True`, or
    - Dependency callables named with authorization markers (`require_`, `verify_`, `authorize_`, `enforce_`, `permission`, `authz`).
    - Explicitly rejects no-op/dummy lambdas and unannotated dependencies.
- **Tests**:
  - `test_sec_05_authz_checker_rejects_dummy_dependency`: Verifies failure on `Depends(dummy_dep)`.
  - `test_sec_05_authz_checker_accepts_security_marker`: Verifies acceptance on `Depends(require_user)`.

---

### Outbox Worker Hardening
- **Vulnerability**: `services/api/app/workers/outbox_worker.py` aborted entire worker loop on any event processing exception, leaving batch uncommitted or crashing permanently without backoff or dead-letter handling.
- **Fix**:
  - Added `MAX_RETRIES = 5`.
  - Wrapped individual event dispatch in per-event nested transaction savepoints.
  - Incremented `retry_count` and logged error on failed events rather than crashing worker process.
- **Tests**:
  - `test_outbox_worker_increments_retry_on_failure`: Verifies retry counter increments on poison pill.
  - `test_outbox_worker_processes_events`: Verifies regular event processing remains sound.

---

### SEC-06: Prompt Injection Mitigation & Invariant Enforcement
- **Vulnerability**: Untrusted user prompt instructions could attempt to alter curriculum rules, bypass daily study ceilings, or introduce unvetted subjects.
- **Fix**:
  - `app.schemas.planning.IntakeSlots` set to `extra = "forbid"` and `frozen = True`, strictly rejecting extraneous instruction fields.
  - Mandatory physiological ceiling (600m) and stage-specific ceilings enforced before any planning logic executes.
  - Age-based guardian consent (D-04) enforced at model validation.
- **Tests**:
  - `test_intake_slots_forbids_arbitrary_injected_fields`: Verifies rejection of injected attributes.
  - `test_scen_us_f02_prompt_injection_ignored`: Verifies system instructions cannot be overridden.

---

### SEC-07: AI Provider PII Strip & Secret Redaction
- **Vulnerability**: External AI providers receiving student PII (names, phone numbers, raw notes) violate privacy policy and ADR-0006.
- **Fix**:
  - `app.ai.provider.NineRouterProvider` implements whitelist-only context serialization (`_sanitize_context`) excluding all personal identifiers.
  - Error logs redact API tokens and connection headers, logging only exception type names and HTTP status codes.
- **Tests**:
  - `test_9router_reliability.py`: Verifies sanitized payloads, timeout fallback, and budget guards.

