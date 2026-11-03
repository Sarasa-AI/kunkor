# Phase 6 — Security Follow-Up Register

**Status:** Active  
**As of:** Commit `9de59a6`  
**Governing Standard:** ADR-0005, D-11 Principle 4 (Defense-in-Depth)

---

## Prioritized Security Items

| # | Priority | Item | Risk & Rationale | Verification / Remediation Needed | Blocks Synthetic Testing? | Blocks Controlled Pilot? | Blocks Production Release? |
|---|----------|------|------------------|-----------------------------------|---------------------------|--------------------------|----------------------------|
| 1 | **P1 (High)** | **Independent External Security Review** | Unknown blind spots in retention privilege boundary, trigger state machine, and transaction binding. Automated tests verify model behavior, not subtle PostgreSQL implementation quirks. | Engage qualified third-party firm for penetration test and formal review of migration 0006 and retention architecture. | ❌ No | ⚠️ Recommended | ✅ **Yes** |
| 2 | **P2 (Medium)** | **Schema-Qualify Table Reference in Trigger** | `prevent_append_only_mutation` references `retention_erasure_authorizations` without explicit `public.` prefix. Safe due to locked `search_path`, but violates strict defense-in-depth. | Update trigger function to use `public.retention_erasure_authorizations`. Re-run migration round-trip test. | ❌ No | ❌ No | ✅ **Yes** |
| 3 | **P2 (Medium)** | **Constant-Time Token Comparison** | Preimage hash comparison uses SQL `=` operator instead of constant-time comparison. While SHA-256 output is fixed 64 chars and timing side-channel risk is low, defense-in-depth recommends constant-time comparison. | Assess feasibility of PostgreSQL constant-time string comparison or implement in procedural code. | ❌ No | ❌ No | ⚠️ Recommended |
| 4 | **P2 (Medium)** | **Concurrent Authorization / Replay Testing** | Two parallel erasure requests for the same student running concurrently could theoretically race on `active_in_transaction_id` before consumption. | Add adversarial test in `test_retention.py`: spawn two concurrent transactions attempting to activate and consume the same authorization record. | ❌ No | ⚠️ Recommended | ✅ **Yes** |
| 5 | **P2 (Medium)** | **Production Role & Effective Privilege Verification** | `kunkor_operator` role created dynamically if exists. In staging/production, the role may not exist or may have excessive grants. Non-superuser execution not proven in production PG. | Write deployment validation script that inspects `pg_roles`, `pg_shdescription`, and effective table privileges for `kunkor` and `kunkor_operator` roles in target environment. | ❌ No | ⚠️ Recommended | ✅ **Yes** |
| 6 | **P3 (Low)** | **Formal Threat Model (STRIDE/LINDDUN)** | Architecture references security principles (D-11) and ADRs, but lacks structured threat model documenting assets, threat actors, attack vectors, and mitigations. | Produce formal threat model document for consultation, planning, and retention subsystems using STRIDE/LINDDUN methodology. | ❌ No | ❌ No | ⚠️ Recommended |

---

## Detailed Item Profiles

### Item 1: Independent External Security Review
- **Priority:** P1 (High)
- **Component:** PostgreSQL retention architecture (`migration 0006`, `scripts/student_retention.py`)
- **Risk:** Agent review cannot substitute for independent security expertise. Undiscovered vulnerabilities in privilege boundaries could lead to unauthorized data erasure or append-only log tampering.
- **Remediation:** Scope third-party engagement: (1) privilege boundary testing, (2) transaction isolation and race conditions, (3) SQL injection vectors via GUC or dynamic SQL, (4) backup/restore integrity.
- **Gate Impact:** Does not block synthetic tests. Recommended before pilot. **Blocks production release.**

### Item 2: Schema-Qualify Table Reference in Trigger
- **Priority:** P2 (Medium)
- **Component:** `services/api/migrations/0006_retention_policy.up.sql::prevent_append_only_mutation`
- **Current Code:**
  ```sql
  SELECT 1 FROM retention_erasure_authorizations ...
  ```
- **Desired Code:**
  ```sql
  SELECT 1 FROM public.retention_erasure_authorizations ...
  ```
- **Risk:** If `search_path` is somehow manipulated prior to trigger execution, an attacker could shadow the table. `SET search_path = pg_catalog, public, pg_temp` mitigates this, but explicit qualification eliminates reliance on search_path precedence.
- **Gate Impact:** Does not block synthetic tests or pilot. **Blocks production release.**

### Item 3: Constant-Time Token Comparison
- **Priority:** P2 (Medium)
- **Component:** `services/api/migrations/0006_retention_policy.up.sql::execute_student_retention_erasure`
- **Current Code:**
  ```sql
  WHERE raw_token_hash = v_computed_hash
  ```
- **Risk:** Standard string comparison may short-circuit on first differing byte. For 64-character SHA-256 hex strings, network jitter typically dwarfs the timing difference, making practical exploitation over network connections extremely difficult. However, local or low-latency attacks might theoretically measure differences.
- **Remediation:** Evaluate PostgreSQL `digest()` / `crypt()` constant-time comparison or accept risk with documented rationale.
- **Gate Impact:** Recommended before production; does not block pilot.

### Item 4: Concurrent Authorization / Replay Testing
- **Priority:** P2 (Medium)
- **Component:** `tests/test_retention.py`
- **Risk:** Tampering trigger state machine handles `NULL → txid` and `txid → NULL`, but behavior under concurrent conflicting transactions (e.g., READ COMMITTED vs REPEATABLE READ) has not been verified via automated test.
- **Remediation:** Add `test_concurrent_erasure_authorization_race` using `threading` or `asyncio` with separate database connections attempting simultaneous activation.
- **Gate Impact:** Recommended before pilot. **Blocks production release.**

### Item 5: Production Role & Effective Privilege Verification
- **Priority:** P2 (Medium)
- **Component:** Deployment scripts / CI/CD pipeline
- **Risk:** Migration uses conditional grant: `IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kunkor_operator')`. If the role is never created, the grants are silently skipped, leaving the function unexecutable by operators. If created with superuser privileges, the boundary is invalidated.
- **Remediation:** Create `scripts/verify_production_roles.py` that asserts:
  1. `kunkor` application role exists and has NO execute permission on `execute_student_retention_erasure`
  2. `kunkor` application role has NO permissions on `retention_erasure_authorizations`
  3. `kunkor_operator` exists, is NOT a superuser, and HAS execute permission
  4. Neither role can bypass append-only triggers
- **Gate Impact:** Recommended before pilot. **Blocks production release.**

### Item 6: Formal Threat Model
- **Priority:** P3 (Low)
- **Component:** Documentation (`docs/THREAT_MODEL.md`)
- **Risk:** Without a structured threat model, future feature additions (e.g., Phase 7 pilot, Phase 8 release) may inadvertently introduce architectural vulnerabilities that violate D-11 principles.
- **Remediation:** Document STRIDE analysis covering:
  - Spoofing (Telegram identity, webhook secrets, operator credentials)
  - Tampering (progress logs, plan history, retention authorizations)
  - Repudiation (audit events, operator actions)
  - Information Disclosure (PII in logs, catalog metadata vs content, student notes)
  - Denial of Service (intake spam, AI provider exhaustion, DB connection exhaustion)
  - Elevation of Privilege (application role to operator, student cross-access)
- **Gate Impact:** Recommended for Phase 8; does not block pilot.

---

## Status Tracking

| Item | Status | Assigned To | Target Date | Resolution |
|------|--------|-------------|-------------|------------|
| 1. External Security Review | Not Started | Product Owner / Security Firm | TBD | |
| 2. Schema-Qualify Trigger Ref | Ready for Dev | Engineering | Next Sprint | |
| 3. Constant-Time Comparison | Evaluated | Engineering | Next Sprint | Documented as low risk; procedural fix if needed |
| 4. Concurrent Replay Test | Ready for Dev | Engineering | Next Sprint | Test case specified |
| 5. Role Verification Script | Ready for Dev | DevOps / Engineering | Next Sprint | Script specification drafted |
| 6. Formal Threat Model | Not Started | Security Lead | Phase 8 | |