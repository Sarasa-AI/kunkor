# Local Stage Execution

Stage 0.5 follows the planning contract in `gate-report.md` at `84acb5fe`. Stages 1 through 4 use the current product direction (D-12, D-13 and ADR-0009) and the first four entries in `docs/ROADMAP_10_PHASES_MVP.md`. The local gate excludes the owner-approved release deferrals listed in `HUMAN_ACTION_REQUIRED.md`.

## Stage 0.5 - Planning contract and validator

**VERIFIED.** Baseline `b1712e3` passed 71 focused contract, provider mock, quota and scenario cases. Astra cycle 1 found that the validator skipped trusted prerequisite comparison when duration metadata was unknown. The comparison now runs independently of duration. A regression exercises both an omitted prerequisite and a matching completed prerequisite. The full PostgreSQL suite returned `380 passed, 2 warnings in 16.05s`. Ruff and Mypy passed.

**Astra PASS, cycle 2.** HTTP 200. Astra reviewed the corrected comparison, regression, and unchanged production catalog duration gate.

## Stage 1 - Product contract and architecture

**VERIFIED.** D-12 and ADR-0009 define grades 10-12, the modular monolith, proposal-only agents and domain-owned writes. D-13 makes an empty catalog valid and requires owner approval and active rights for trusted content. The older roadmap's SMS/OTP and age/guardian design is superseded by the current signed Telegram identity contract. The active contract and decisions are recorded with this stage. The identity and catalog runtime acceptance belongs to the next stage.

`pytest -q tests/test_phase1_production_controls.py tests/test_phase1_privacy_authority.py tests/test_phase1_audit_integrity.py tests/test_phase1_migration_safety.py` returned `59 passed in 1.96s` on PostgreSQL 16.15.

**Astra PASS, cycle 1.** HTTP 200. No verified local failure. Live activation and human release checks remain open.

## Stage 2 - Signed identity, profile, and owner catalog

**VERIFIED.** Candidate `a69ccb1` includes signed Telegram identity and tenant-scoped profile/context reads and writes. The local test signer uses synthetic credentials without an external auth call. The composite plan/item and progress ownership constraints reject cross-student linkage. Empty startup, independent publication, active rights, archive isolation, and owner authorization use disposable PostgreSQL and synthetic data only.

`pytest -q` across `test_phase1_identity_isolation.py`, `test_phase2_identity_security.py`, `test_content_catalog.py`, `test_content_owner.py`, `test_content_student_context.py`, `test_empty_catalog_startup.py`, and `test_web_consultation_endpoints.py` returned `99 passed, 2 warnings in 6.33s`. Stage 0's clean candidate also passed the eight web proxy contract tests.

**Astra PASS, cycle 1.** HTTP 200. No verified local defect in signed identity, route policies, or ownership schema. Existing implementation accepted without a code change.

## Stage 3 - Trusted catalog retrieval

**VERIFIED.** Structured PostgreSQL retrieval passed the D-13 gate for incremental publication and trusted use. Missing coverage returns an explicit unavailable state. Unknown counts remain unknown. Revoking rights or archiving source content invalidates stale planning and delivery. No new retrieval capability was needed for this local gate.

`pytest -q tests/test_content_catalog.py tests/test_content_delivery.py tests/test_content_owner.py tests/test_content_student_context.py tests/test_trusted_catalog_agents.py` returned `51 passed, 1 warning in 1.99s`. PostgreSQL state was real and disposable. Delivery used mock transport.

**Astra PASS, cycle 1.** HTTP 200. No verified local blocker. Owner population and per-item rights approvals remain operational.
