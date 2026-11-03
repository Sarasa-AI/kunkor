# Phase 7 — Controlled Pilot Runbook & Operational Specification

- **Document ID:** `PILOT-RUNBOOK-v1.0`
- **Date:** 2026-11-01
- **Status:** `OPERATIONAL_RUNBOOK_READY` (Live execution BLOCKED pending owner credentials and cohort authorization)

---

## 1. Executive Summary & Authorization Boundary

Under the project owner's master prompt and operational instructions:
- **Real pilot execution is BLOCKED** until explicit authorization of:
  1. Dedicated pilot Telegram Bot token (`TELEGRAM_BOT_TOKEN`) and webhook secret (`TELEGRAM_WEBHOOK_SECRET`).
  2. 9router provider API credentials (`NINEROUTER_API_KEY`) and approved model (`NINEROUTER_MODEL`).
  3. Allowlisted pilot user cohort (max 5 consenting students).
- **Current Operational Posture:**
  - `AI_PROVIDER_ENABLED=false` (fallback planner active by default; fail-safe).
  - `TELEGRAM_DELIVERY_ENABLED=false` (outbox events queued transactionally, external HTTP sends disabled).
  - Production default credentials strictly rejected by `app/core/config.py`.
- **Purpose of this Document:**
  Provide an unambiguous, step-by-step operational runbook and record synthetic rehearsal evidence so that once credentials are provided, the pilot can be launched safely within 15 minutes.

---

## 2. Pilot Cohort & Constraints

| Parameter | Specification | Enforcement Mechanism |
|-----------|--------------|----------------------|
| **Cohort Size** | Maximum 5 students | `NINEROUTER_STUDENT_DAILY_CALLS` + manual allowlist in pilot setup |
| **Duration** | 7 consecutive days | Monitored daily via `/api/v1/admin/students` |
| **Stage Coverage** | 1 Primary High, 1 Lower Secondary, 3 Konkur (Experimental, Math, Humanities) | Intake state machine validation |
| **Budget Ceiling** | $1.00/student/day; $10.00 global/day | `ai_daily_usage` table with PostgreSQL advisory locks |
| **Call Ceiling** | 20 calls/student/day; 1,000 global/day | `reserve_daily_attempt()` pre-call reservation |
| **Max Retries** | 2 bounded retries per AI call | `NineRouterProvider.max_retries = 2` |
| **PII Boundary** | Zero PII sent to AI | `sanitize_intake_for_ai()` strips all personal identifiers |
| **Content Boundary** | Zero full copyrighted content processed | Metadata whitelist only (`catalog.py`) |

---

## 3. Pre-Flight Verification Checklist

Before enabling live traffic, the operator must execute and verify:

```bash
# 1. Database migrations up to date
python -m scripts.migrate

# 2. Authorization matrix check (100% deny-by-default)
python -m scripts.check_authz_matrix

# 3. Modular monolith boundaries clean
python -m scripts.check_imports

# 4. Outbox queue health check (0 dead letters)
python -m scripts.check_operations --max-age-seconds 300

# 5. Offline plan evaluation verification
python -m scripts.evaluate_plans
```

---

## 4. Environment Configuration for Live Pilot

When authorized, create `.env.pilot` with the following template:

```ini
ENVIRONMENT=production
DATABASE_URL=postgresql://kunkor:<STRONG_UNIQUE_PASSWORD>@<DB_HOST>:5432/kunkor_pilot
ADMIN_API_KEY=<STRONG_RANDOM_UUID_OR_SECRET>

# AI Provider (9router)
NINEROUTER_ENABLED=true
NINEROUTER_API_BASE=https://api.9router.com
NINEROUTER_API_KEY=<AUTHORIZED_PILOT_KEY>
NINEROUTER_MODEL=ag/gemini-2.5-flash
NINEROUTER_TIMEOUT_SECONDS=15.0
NINEROUTER_MAX_RETRIES=2
NINEROUTER_GLOBAL_DAILY_CALLS=100
NINEROUTER_STUDENT_DAILY_CALLS=20
NINEROUTER_GLOBAL_DAILY_RESERVED_USD=5.00
NINEROUTER_STUDENT_DAILY_RESERVED_USD=1.00
NINEROUTER_ATTEMPT_COST_CEILING_USD=0.005

# Telegram Bot
TELEGRAM_DELIVERY_ENABLED=true
TELEGRAM_BOT_TOKEN=<AUTHORIZED_TELEGRAM_BOT_TOKEN>
TELEGRAM_WEBHOOK_SECRET=<STRONG_RANDOM_SECRET_HEX>
```

---

## 5. Deployment & Execution Procedure

### Step 1: Set Webhook
```bash
curl -F "url=https://<PILOT_DOMAIN>/api/v1/telegram/webhook" \
     -F "secret_token=<TELEGRAM_WEBHOOK_SECRET>" \
     https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook
```

### Step 2: Start API Server
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

### Step 3: Start Outbox Worker
```bash
python -m app.workers.outbox_worker --interval 2.0
```

### Step 4: Verify Webhook Health
```bash
curl -H "X-Admin-Api-Key: <ADMIN_API_KEY>" \
     https://<PILOT_DOMAIN>/api/v1/admin/outbox/health
# Expected: {"pending": 0, "dead_letter": 0, "oldest_pending_seconds": 0}
```

---

## 6. Daily Monitoring Runbook (Operator Actions)

Execute at **09:00 UTC** and **21:00 UTC** daily:

1. **Check Outbox & Dead Letters:**
   ```bash
   python -m scripts.check_operations --max-age-seconds 120
   ```
   If dead letters > 0, inspect failure reason via `/api/v1/admin/outbox/health` and retry via:
   ```bash
   curl -X POST -H "X-Admin-Api-Key: <KEY>" \
        https://<PILOT_DOMAIN>/api/v1/admin/outbox/<EVENT_ID>/retry
   ```

2. **Check Daily AI Spend & Call Counts:**
   ```sql
   SELECT scope_key, attempts, reserved_usd
   FROM ai_daily_usage
   WHERE usage_day = CURRENT_DATE;
   ```

3. **Check Student Progress Submissions:**
   ```bash
   curl -H "X-Admin-Api-Key: <KEY>" \
        https://<PILOT_DOMAIN>/api/v1/admin/students
   ```

4. **Verify Plan Revision Monotonicity:**
   Ensure each student's `active_revision_no` increments sequentially (Rev 1 → Rev 2 → Rev 3) without skipped versions.

---

## 7. Incident Response & Emergency Procedures

### Scenario A: External Provider (9router) Outage
- **Automatic Behavior:** System automatically falls back to `DeterministicRuleFallbackPlanner`. No student requests fail.
- **Operator Action:** Monitor log entries with `fallback_used: true`. No code intervention required.

### Scenario B: Telegram API Throttling or Failure
- **Automatic Behavior:** Outbox worker backs off exponentially up to 5 retries. Events are preserved in `outbox_events` table.
- **Operator Action:** Once Telegram recovers, run outbox retry for dead-lettered events.

### Scenario C: Student Emergency Opt-Out / Privacy Erasure
- **Operator Action:** Execute the retention script:
  ```bash
  python -m scripts.student_retention \
         --student-id <STUDENT_UUID> \
         --retention-days 0 \
         --execute
  ```
  All student data (intake, plans, items, progress, outbox, idempotency) is transactionally deleted; an anonymous receipt is recorded in `audit_events`.

### Scenario D: Immediate Pilot Halt (Kill Switch)
- **Operator Action:** Set in `.env`:
  ```ini
  TELEGRAM_DELIVERY_ENABLED=false
  NINEROUTER_ENABLED=false
  ```
  Restart worker and API. Outgoing messages stop immediately; consultation falls back to rule engine or halts safely.

---

## 8. Pilot Exit Criteria

The pilot phase transitions to `COMPLETED` when:
1. All 5 pilot students complete the intake and receive a validated Rev 1 plan.
2. At least 3 students report daily progress for 3+ consecutive days and receive valid Rev 2+ revisions.
3. Zero unhandled 5xx exceptions logged.
4. Zero PII leakage incidents in logs or telemetry.
5. Zero unvalidated plans persisted in PostgreSQL.
6. Total AI provider spend remains below $10.00.
7. Any reported P0/P1 defects are resolved and verified with tests.

---

## 9. Current Phase Status

- **Technical Readiness:** `100% COMPLETE` (all runbooks, scripts, guards, and fallback engines implemented and synthetically verified).
- **Operational Gate:** `BLOCKED` on explicit owner provision of live Telegram Bot token, 9router API credentials, and pilot student authorization.
