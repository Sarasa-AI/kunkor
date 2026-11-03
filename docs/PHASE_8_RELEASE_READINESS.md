# Phase 8 — MVP Release Readiness & Acceptance Audit

- **Document ID:** `RELEASE-READINESS-MVP-v1.0`
- **Date:** 2026-11-01
- **Status:** `IN_PROGRESS` (Release Candidate drafted; production release blocked until prerequisite gates are satisfied)

---

## 1. Executive Summary

This report provides an objective, evidence-based assessment of the Kunkor educational consultation platform against the release readiness criteria for MVP.

The core implementation—FastAPI backend, PostgreSQL database schemas, 7-step Telegram consultation state machine, deterministic plan validator with DAG cycle checking, daily progress logging with append-only triggers, dynamic plan revision loop, AI usage quotas, outbox worker, and student privacy retention controls—is **fully implemented and synthetically coherent**.

However, **a release candidate cannot be declared "Production-Ready" merely from the existence of code and documentation.** This report explicitly documents which verification gates have passed synthetically, and which operational and external gates remain unexecuted or pending authorization.

---

## 2. Multi-Gate Release Audit Ledger

| Gate Area | Subsystem | Verification Status | Evidence / Remaining Blocker |
|---|---|---|---|
| **Core Architecture** | D-11 Principles 1–5 | ✅ PASS | Proposer-Validator, PII masking, metadata whitelist, modular monolith, no n8n/multi-agent. |
| **Data Integrity** | ADR-0005 Immutability | ✅ PASS | Triggers `trg_audit_events_append_only` and `trg_daily_progress_logs_append_only` enforced; target-locked erasure in migration 0006. |
| **Data Integrity** | ADR-0008 Identity | ✅ PASS | Non-nullable `student_id` present on all study plans, items, and outbox events. |
| **Security & Authz** | Deny-by-default (SEC-05) | ✅ PASS | 100% of non-public routes require explicit `require_admin_auth` or signed TMA `require_student_access`. |
| **AI Safety & Cost** | Quotas & Advisory Locks | ✅ PASS | `ai_daily_usage` table with advisory lock serialization; pre-call reservations commit independently; fail-closed on unpriced calls. |
| **AI Reliability** | 9router Client | ⚠️ SYNTHETIC ONLY | Bounded timeouts, retries, 429 backoff, and rule fallback verified via mocks. Live network integration UNVERIFIED. |
| **Telegram Transport** | Webhook & Outbox | ⚠️ SYNTHETIC ONLY | Deduplication, identity linking, and outbox enqueueing pass ASGI tests. Live sendMessage UNVERIFIED. |
| **Pedagogical Quality**| Offline Plan Evaluation | ⚠️ SYNTHETIC ONLY | 7/9 available cases pass validator with 100% weak-subject coverage. Educational usefulness UNVERIFIED by human experts. |
| **Disaster Recovery** | Backup & Restore Proof | ❌ UNEXECUTED | Fingerprint verification script `verify_restore.py` exists, but live `pg_dump`/`pg_restore` execution drill between loopback databases has not been run. |
| **Pilot Operations** | Controlled Real Pilot | ❌ BLOCKED | Phase 7 runbook complete (`PHASE_7_PILOT_RUNBOOK.md`); live execution blocked pending explicit owner credential and cohort authorization. |

---

## 3. Production Deployment Architecture (Reference)

```
[ Telegram Student ]
        │
        ▼ (HTTPS / Webhook)
┌───────────────────────────────────────────────┐
│              FastAPI Gateway                  │
│  - Secret token verification                   │
│  - Request rate limiting                       │
│  - Telegram initData HMAC-SHA256 verification │
└───────┬───────────────────────────────┬───────┘
        │                               │
        ▼                               ▼
┌──────────────────┐            ┌──────────────────┐
│   Consultation   │            │    Operations    │
│  State Machine   │            │   Admin API &    │
│  (Intake/Revise) │            │   Entitlements   │
└───────┬──────────┘            └───────┬──────────┘
        │                               │
        ▼                               │
┌───────────────────────────────┐       │
│    Deterministic Validator    │       │
│  - Time limits & DAG check    │       │
│  - Licensing & Track matching │       │
└───────┬───────────────────────┘       │
        │                               │
        ▼ (Transactional Write)         │
┌───────────────────────────────────────┴───────┐
│                 PostgreSQL                    │
│  - students, study_plans, study_plan_items    │
│  - daily_progress_logs (append-only)          │
│  - audit_events (append-only)                 │
│  - idempotency_keys                           │
│  - outbox_events                              │
│  - ai_daily_usage (advisory lock counters)    │
└───────┬───────────────────────────────────────┘
        │
        ▼ (Poll: SKIP LOCKED)
┌───────────────────────────────────────────────┐
│             Outbox Worker                     │
│  - Bounded retries (max 5) with backoff       │
│  - Telegram delivery (when enabled)           │
│  - Dead-letter logging & admin retry          │
└───────────────────────────────────────────────┘
```

---

## 4. Mandatory Pre-Release Action Items (Exit Criteria)

To advance this Release Candidate to `COMPLETED`:

1. **Commit and CI Verification (Phase 1):**
   - Stage and commit current working tree changes.
   - Run remote CI on GitHub Actions and record successful green run.

2. **Database Backup & Restoration Execution Drill (Phase 6):**
   - Seed test database with full synthetic records.
   - Run `pg_dump` to create a backup file.
   - Restore into a clean target test database via `pg_restore`.
   - Run `python -m scripts.verify_restore` and confirm exit code 0 and matching SHA-256 fingerprints.

3. **Owner Authorization for Phase 7 (Pilot):**
   - Receive explicit owner authorization with dedicated bot token, 9router credentials, and pilot cohort (≤5 students).
   - Execute Phase 7 pilot under the documented runbook.

---

## 5. Current Gate Verdict

**Status: IN_PROGRESS.**  
The technical implementation is complete and synthetically verified. Final release sign-off is held pending the live database restore verification drill and owner-authorized pilot execution.
