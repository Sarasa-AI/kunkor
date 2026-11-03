# Phase 5 — Metadata Whitelist and Offline Evaluation Report

- **Report ID:** `PHASE-05-METADATA-EVAL`
- **Date:** 2026-11-01
- **Status:** `IN_PROGRESS` (Synthetic evaluation complete; human pedagogical review pending)

The previous administrative implementation report is retained unchanged at
[history/PHASE_5_ADMIN_REPORT.md](history/PHASE_5_ADMIN_REPORT.md). Its historical
`COMPLETED` label concerns that earlier administrative scope, not acceptance of this Phase 5 gate.

---

## 1. Evidence Available

`services/api/app/engines/catalog.py` contains 19 local synthetic metadata fixtures.
Every record identifies its provenance as `local_synthetic_fixture`, verification
as `UNVERIFIED`, domain approval as `PENDING`, authorization scope as
`metadata_only_synthetic_evaluation`, `full_content_access=False`, and no
`content_license_id`. Publisher, title, page/test counts, duration, and prerequisite
claims have not been independently verified. No local evidence establishes
bibliographic accuracy or permission to process/display copyrighted content.
The legacy `license_active` field permits synthetic metadata scheduling only;
it is not a `ContentLicense` or a content-rights decision.

The catalog supports metadata-only scheduling under the D-11 distinction. It
contains no full questions or book text. Approval of metadata does not authorize
full-content access. Real resource approval and domain review remain pending.

---

## 2. Reproducible Offline Evaluation Breakdown

The versioned synthetic dataset is `services/api/tests/fixtures/offline_plans.json` (version 2).
Nine test cases explicitly encode expected outcomes across 5 school stages and boundary conditions:

### 2.1 Positive Generation Scenarios (7 Cases)
- **Cases:** `primary_low` (G02), `primary_high` (G05), `lower_secondary` (G09), `upper_secondary` (G10), `konkur_experimental` (G12), `konkur_mathematics` (G12), `konkur_humanities` (G12).
- **Expected Outcome:** `generate_plan`.
- **Actual Outcome:** 7/7 produced valid, non-empty study plans.
- **Verification:** All 7 plans pass authoritative `DeterministicValidator`:
  - Total duration ≤ daily capacity.
  - All assigned units strictly match student grade and academic track.
  - Prerequisite DAG ordering satisfied (zero cycles).
  - Weak-subject coverage: 1.0 (100% of reported weak subjects assigned priority resources).
- **Positive Generation Verdict:** `PASS` (7/7).

### 2.2 Negative Boundary Scenarios (2 Cases)
- **Case `missing_grade`:** Primary High student in Grade `G04`. Catalog contains `G05` only.
  - **Expected Outcome:** `refuse_plan` (Reason: `no_matching_resources_for_grade`).
  - **Actual Outcome:** 0 items generated. No cross-grade resources assigned.
  - **Consultation Behavior:** Returns `status: "resources_unavailable"`, preserves student intake, informs student via Persian message.
  - **Integrity Verified:** Zero invalid plans persisted in database; no unvalidated fallback.
- **Case `insufficient_time`:** Konkur student with 10 minutes daily capacity. Shortest catalog unit is 60 minutes.
  - **Expected Outcome:** `refuse_plan` (Reason: `capacity_below_minimum_resource_duration`).
  - **Actual Outcome:** 0 items generated. Zero capacity limit violations.
  - **Integrity Verified:** Daily capacity constraint strictly respected.
- **Negative Boundary Verdict:** `PASS` (2/2 correctly refused, zero state corruption).

---

## 3. Automated Verification Tests

`services/api/tests/test_plan_evaluation.py` automates these assertions:
1. `test_synthetic_catalog_never_claims_content_authorization`: proves zero content authorization claims.
2. `test_offline_positive_and_negative_evaluations_are_reproducible`: verifies 7/7 positive passes and 2/2 negative refusal handling.

---

## 4. Remaining Gate Decisions

- **Synthetic Offline Evaluation:** `PASS` (9/9 cases match expected outcomes; 100% weak-subject coverage).
- **Resource Metadata Factual Verification:** `PENDING` (requires publisher confirmation).
- **Pedagogical Usefulness & Educational Expert Review:** `PENDING` (requires human domain specialist evaluation).
- **Live 9router Integration:** `UNVERIFIED` (external network calls disabled).
- **Real Pilot:** `BLOCKED` (awaiting owner authorization).

**Overall Exit Gate Decision:** `IN_PROGRESS`. Synthetic mechanics verified; domain and human review pending.
