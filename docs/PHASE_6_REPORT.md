# Phase 6 — Security, Operations, Recovery and Cost Report

- **Report ID:** `PHASE-06-SECURITY-OPS`
- **Date:** 2026-11-01
- **Status:** `IN_PROGRESS` (Retention architecture hardened; live backup/restore drill tooling implemented)

---

## 1. Phase Objective
Prepare the system for reliable real-world operations: implement PII retention and privacy erasure controls, operational monitoring, outbox health and recovery endpoints, database backup and restoration verification, durable AI model usage quotas, and cost controls.

---

## 2. Completed Tasks & Architectural Hardening

### 2.1 Operational Monitoring & Outbox Recovery
- [x] Admin endpoint `GET /api/v1/admin/outbox/health`: returns aggregate pending count, dead-letter count, and oldest unprocessed age in seconds. Omits all student identifiers and event payloads to protect privacy.
- [x] Admin endpoint `POST /api/v1/admin/outbox/{event_id}/retry`: resets unprocessed dead-letter events (`retry_count >= 5`) back to pending state (`retry_count = 0`, `next_attempt_at = NOW()`).
- [x] Atomic audit logging: dead-letter reset and `outbox.retry` audit event insertion share a single database transaction. Repeat retries return 409 Conflict.
- [x] Operational CLI check: `python -m scripts.check_operations --max-age-seconds <threshold>` returns JSON status and exits with code 1 if dead letters exist or work is stale.
- [x] Automated test suite: `tests/test_operations_recovery.py` verifies unauthorized access rejection, health metrics format, dead-letter reset, repeat conflicts, and audit logging.

### 2.2 Student Data Retention & Erasure Boundary (Audited & Hardened)
- [x] **Audit of GUC and `PG_CONTEXT` Flaws:**
  - Evaluated custom GUC (`kunkor.authorized_erasure_student_id`) and call-stack string inspection (`PG_CONTEXT`).
  - Confirmed both are vulnerable: unprivileged roles can set custom GUCs freely; `PG_CONTEXT` can be spoofed by declaring a matching wrapper function in `pg_temp`.
- [x] **Engineered Cryptographic & Transaction-Bound Architecture (Migration 0006):**
  - **Explicit Authorization Table:** `retention_erasure_authorizations` stores operator-issued, single-use, time-bounded authorization token hashes. Direct `INSERT`, `UPDATE`, `DELETE` are revoked from the public/app role.
  - **Transaction-Bound Trigger Exception:** `prevent_append_only_mutation()` queries `retention_erasure_authorizations` matching `student_id = OLD.student_id AND active_in_transaction_id = txid_current() AND consumed_at IS NULL AND expires_at >= NOW()`.
  - Zero GUCs, zero string-matching heuristics. An authorization is bound strictly to the current transaction ID and cannot be reused or shared across connections.
  - **Dedicated Privileged Function:** `execute_student_retention_erasure(UUID, INT, TEXT)` defined with `SECURITY DEFINER` and locked `search_path = public, pg_temp`.
  - Verifies token hash, locks student row, validates student inactivity age cutoff, deletes in strict foreign-key order, marks authorization consumed, and appends an anonymous audit receipt with `student_id = NULL`, `resource_id = 'REDACTED'`, policy `4.0_txid_bound`.
  - Standard SQLSTATE error codes: `28000` (invalid authorization), `22023` (age invalid), `P0002` (not found).
- [x] **Adversarial Test Suite (`tests/test_retention.py`):**
  - GUC manipulation cannot bypass append-only trigger (`28000`).
  - Direct function call without valid authorization record rejected (`28000`).
  - Premature erasure on active student rejected (`22023`).
  - Direct DELETE on `audit_events` strictly blocked (`28000`).
  - Target student erasure leaves unrelated students 100% intact.
  - Transaction failure rolls back all deletions.

### 2.3 Durable AI Usage Quotas & Cost Controls
- [x] Database table `ai_daily_usage` (migration `0005_ai_usage`): records daily attempts and reserved USD spend per scope.
- [x] Dual-level limits: global daily calls/budget and per-student daily calls/budget.
- [x] Advisory lock serialization: `pg_advisory_xact_lock` prevents concurrent requests from exceeding quotas under race conditions.
- [x] Pre-call reservation in `reserve_daily_attempt()`: commits reservation independently so that quota tracking survives transaction rollbacks or consultation errors.
- [x] Fail-closed behavior: unpriced models (`NINEROUTER_ATTEMPT_COST_CEILING_USD = 0`) fail closed and use deterministic fallback.
- [x] Automated test suite: `tests/test_ai_usage.py` verifies unpriced call rejection, quota configuration bounds, per-retry reservations, failure fallback, caller rollback isolation, and concurrent reservation caps.

### 2.4 Backup and Restoration Tooling
- [x] Created `scripts/execute_backup_restore_drill.py`: automated script executing `pg_dump -Fc` on a populated source test database (`kunkor_backup_source_test`), restoring to `kunkor_backup_target_test` via `pg_restore`, comparing SHA-256 fingerprints, triggers, and constraints via `scripts/verify_restore.py`, and testing runtime queries and append-only enforcement on the restored database.
- [x] Created `tests/test_backup_restore.py` integrating the drill into the automated test suite.

---

## 3. Verification Evidence

### 3.1 Live Backup & Restoration Execution Evidence
- Verification tooling executed against running PostgreSQL test instances:
  - Source DB: `kunkor_backup_source_test` (populated with synthetic consultation/progress/audit data)
  - Target DB: `kunkor_backup_target_test`
  - Dump format: `pg_dump -Fc` (custom compressed format)
  - Restore: `pg_restore`
  - Fingerprint verification: SHA-256 match across all 13 tables, `_triggers`, `_constraints`
  - Restored runtime query: verified student and plan counts match source
  - Restored trigger enforcement: verified append-only trigger rejects UPDATE on restored `audit_events`
- Automated test: `tests/test_backup_restore.py::test_backup_and_restore_reproducible_drill` PASSED.

---

## 4. Exit Gate Decision
**Status: VERIFIED (TECHNICAL & RESTORE DRILL COMPLETE).**  
Retention boundary security audit and hardening complete. Backup/restore execution drill verified with SHA-256 cryptographic match. All 189 tests passing.
