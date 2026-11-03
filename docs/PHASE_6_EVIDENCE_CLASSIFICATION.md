# Phase 6 — Evidence Classification & Security Limitations

**Status:** `VERIFIED` (Technical & Restore Complete)  
**As of:** Commit `9de59a6` (CI run `41567119569` — all 3 jobs green)

---

## 1. Evidence Classification Matrix

| Evidence Type | Method | Performed By | Scope | Status |
|---------------|--------|--------------|-------|--------|
| **Automated Adversarial Tests** | 11 pytest cases in `tests/test_retention.py` | Agent (automated) | Retention security boundary: GUC injection, unauthorized auth INSERT, unauthorized function call, premature erasure, audit log immutability, cross-student isolation, rollback | ✅ PASS (11/11) |
| **Agent Code Review** | Manual inspection of migration 0006, retention script, triggers, functions, grants | Agent (this session) | Search path, schema qualification, privilege boundary, token commitment, transaction binding, one-time consumption, rollback behavior | ✅ VERIFIED |
| **Independent External Security Review** | — | NOT PERFORMED | Full threat modeling, penetration test, formal verification | ❌ NOT DONE |
| **Backup/Restore Drill** | `tests/test_backup_restore.py::test_backup_and_restore_reproducible_drill` | Agent (automated) | `pg_dump -Fc` source → `pg_restore` target; SHA-256 fingerprint match (13 tables + `_triggers` + `_constraints`); runtime query + trigger enforcement on restored DB | ✅ PASS |
| **Migration Round-Trip** | `tests/test_migrations.py::test_migrations_forward_and_backward` | Agent (automated) | 0001–0006 forward → backward → forward on disposable DB | ✅ PASS |
| **Offline Plan Evaluation** | 9 scenarios in `tests/test_plan_evaluation.py` | Agent (automated) | 7 positive PASS, 2 negative correctly refused | ✅ PASS |
| **Full Regression Suite** | 189 tests | Agent (automated) | All modules, all layers | ✅ PASS (189/189) |

---

## 2. Retention Security — Verified Claims (Agent Review)

### Search Path Safety
- `execute_student_retention_erasure`: `SET search_path = pg_catalog, public, pg_temp`
- `prevent_retention_auth_tampering`: `SET search_path = pg_catalog, public, pg_temp`
- `prevent_append_only_mutation`: `SET search_path = pg_catalog, public, pg_temp`
- **Finding:** `pg_catalog` precedes `public`, preventing unqualified name shadowing. `pg_temp` last.

### Schema Qualification
- All DML inside privileged function uses explicit `retention_erasure_authorizations`, `students`, `daily_progress_logs`, etc.
- Trigger `prevent_append_only_mutation` references `retention_erasure_authorizations` unqualified but resolves via locked `search_path`.
- **Limitation:** Unqualified reference in trigger is safe due to `search_path`, but not explicitly schema-qualified (`public.retention_erasure_authorizations`).

### Token Commitment
- Preimage: 256-bit entropy (`secrets.token_hex(32)`)
- Stored: `SHA-256(preimage)` hex (64 chars)
- Verification: `sha256(p_raw_authorization_token::bytea)` inside `SECURITY DEFINER` function
- **Finding:** Constant-time comparison not used (uses `=` in `WHERE`). Low risk: hash is fixed-length, no timing side-channel on equality.

### Transaction Binding
- Activation: `UPDATE ... SET active_in_transaction_id = txid_current()`
- Validation: Trigger checks `active_in_transaction_id = txid_current() AND consumed_at IS NULL AND expires_at >= NOW()`
- Consumption: `UPDATE ... SET consumed_at = NOW(), active_in_transaction_id = NULL`
- **Finding:** `txid_current()` wraps at 2^31; acceptable for single-transaction binding. Replay prevented by tampering trigger state machine.

### One-Time Consumption
- Tampering trigger enforces state machine:
  - A: `NULL → txid_current()` (activation)
  - B: `txid_current() → NULL` with `consumed_at` set (consumption)
- Consumed records: all fields immutable; any `UPDATE` raises `42501`
- **Finding:** Correctly prevents reuse.

### Privilege Boundary
- `REVOKE ALL ON TABLE retention_erasure_authorizations FROM PUBLIC`
- `REVOKE EXECUTE ON FUNCTION execute_student_retention_erasure(...) FROM PUBLIC`
- `GRANT` to `kunkor_operator` only if role exists (no hardcoded creation)
- `REVOKE` from `kunkor` application role
- **Finding:** Application role cannot INSERT/UPDATE/DELETE authorizations or execute erasure function.

### Rollback Behavior
- `active_in_transaction_id` cleared on commit (consumption step)
- On rollback: `active_in_transaction_id` remains `txid_current()` but transaction ends, so value becomes meaningless; tampering trigger prevents subsequent `UPDATE` to clear it without `consumed_at`
- **Finding:** Authorization cannot be replayed after rollback.

---

## 3. Security Limitations & Unverified Areas

| Limitation | Impact | Required Verification |
|------------|--------|----------------------|
| **No independent external audit** | Unknown blind spots | Engage third-party security firm for penetration test & formal review |
| **Role ownership not verified in production** | `kunkor_operator` may not exist or may have excessive grants | Verify `pg_roles` and effective privileges in staging/prod |
| **No superuser separation test** | Migration creates no superuser, but test DB uses `kunkor` (non-superuser). Production deployment may run migrations as superuser. | Verify migration execution role in CI/CD pipeline |
| **Token timing side-channel** | Hash comparison uses `=` not `hmac.compare_digest` | Low risk (fixed-length hash), but should use constant-time comparison |
| **Unqualified table reference in trigger** | `retention_erasure_authorizations` resolves via `search_path` | Schema-qualify as `public.retention_erasure_authorizations` for defense-in-depth |
| **`txid_current()` wraparound** | 32-bit counter wraps; theoretical collision after 2^31 transactions | Negligible for MVP; document assumption |
| **No concurrent authorization consumption test** | Two parallel erasures for same student not tested | Add test: two transactions racing on same auth record |
| **Operator credential management** | Script requires `OPERATOR_DATABASE_URL`; no rotation/policy documented | Define operator credential lifecycle (rotation, revocation, audit) |
| **No external network security test** | `TELEGRAM_DELIVERY_ENABLED=false`, `NINEROUTER_ENABLED=false` | Enable and test with real credentials in isolated staging |
| **No formal threat model documented** | ADR-0005 references security but no STRIDE/LINDDUN analysis | Create threat model for retention boundary |

---

## 4. Backup/Restore Drill — Verified Claims

| Aspect | Verified | Evidence |
|--------|----------|----------|
| Dump format | `pg_dump -Fc` (custom compressed) | Script uses `-F c -b -v` |
| Restore | `pg_restore` with `-v` | Script restores to fresh DB |
| Fingerprint match | 13 tables + `_triggers` + `_constraints` SHA-256 | `scripts/verify_restore.py::fingerprint()` |
| Runtime queries | Student count, plan count match | Restored DB queried post-restore |
| Trigger enforcement | `UPDATE audit_events` rejected | Restored DB trigger active |
| Docker fallback | Host pg_dump v14 vs server v16 mismatch handled | Script falls back to container pg_dump/pg_restore |

**Limitation:** Drill runs on local Docker container (`kunkor-stage0-test-pg`). Not tested against production-grade PostgreSQL (replication, PITR, standby promotion).

---

## 5. Evidence Classification Summary

```
✅ VERIFIED (Agent automated + code review):
  - 189 unit/integration tests pass
  - 11 retention adversarial tests pass
  - Migration 0001-0006 forward/backward/forward pass
  - Backup/restore drill SHA-256 match + runtime verification
  - Offline plan evaluation 9/9 scenarios match
  - Mypy clean (28 files)
  - Ruff clean
  - Agent review of migration 0006 search_path, grants, triggers, token binding

⚠️ AGENT REVIEW ONLY (Not independent):
  - Retention privilege boundary analysis
  - Search path safety assessment
  - Token commitment and transaction binding logic review
  - Rollback behavior reasoning

❌ NOT VERIFIED:
  - Independent external security audit
  - Production role/privilege verification
  - Concurrent authorization race conditions
  - Operator credential rotation policy
  - Formal threat model (STRIDE/LINDDUN)
  - Production PostgreSQL backup/restore (PITR, replication)
  - Real external integration (Telegram, 9router)
```

---

## 6. Recommended Next Security Steps

1. **Engage third-party security firm** for retention boundary penetration test
2. **Schema-qualify** `retention_erasure_authorizations` in trigger
3. **Use `hmac.compare_digest`** for token hash comparison
4. **Add concurrent authorization test** to `test_retention.py`
5. **Document operator credential lifecycle** (rotation, revocation, audit)
6. **Create formal threat model** for Phase 6 boundary
7. **Test against production-grade PostgreSQL** (RDS/Cloud SQL) with PITR