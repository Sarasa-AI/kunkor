# Kunkor — Decision Register

## 1. Architectural Decisions (ADR Register)

| ADR ID | Title | Status | Scope & Alignment |
|---|---|---|---|
| ADR-0001 | Modular Monolith | Accepted | Single repository, isolated modules in `services/api/app/modules`, no microservices. |
| ADR-0002 | Technology Stack Selection | Accepted | FastAPI (Python 3.11), Next.js 15 (TypeScript, RTL), PostgreSQL 16. |
| ADR-0003 | Centralized Backend Authorization | Accepted | Deny-by-default, explicit backend enforcement (`require_authz`), student ID scoping. |
| ADR-0004 | Isolated Educational Logic | Accepted | Pure deterministic rules engine in `services/api/app/engines`, never inside LLM prompts. |
| ADR-0005 | Temporal and Append-Only Records | Accepted | Immutable audit events and task executions (`supersedes_id` for changes). |
| ADR-0006 | Pluggable AI Abstraction | Accepted | AI behind abstract interface, optional P1 dependency, fallback operation without LLM. |
| ADR-0007 | Structured Retrieval First | Accepted | Relational SQL catalog before vector search; deterministic curriculum retrieval. |
| ADR-0008 | Denormalized Student ID | Accepted | Mandatory `student_id` column across student data tables for strict data isolation. |

---

## 2. Open Product Decisions Log (`docs/decisions.md`)

| Decision ID | Topic | Working Default | Status | Impact / Notes |
|---|---|---|---|---|
| D-01 | MVP Curriculum Scope | Grade 12 Experimental Sciences (تجربی) | `proposed` | Focuses seed data and rules on one cohort first. |
| D-02 | Resource License & Verification | 2 approvals (license + educational) | `proposed` | Mandatory before `ResourceVersion` publishing. |
| D-03 | Exam Integrations | Manual entry only in MVP | `proposed` | Defer OCR and external school API integrations. |
| D-04 | Age Policy & Guardian Consent | Guardian consent required for ages < 15 | `proposed` | Privacy-first conservative default. |
| D-05 | Hosting & Cloud Region | Self-hosted Docker Compose | `default-applied` | Local and staging portability. |
| D-06 | Monetization & Quotas | Free tier only for MVP | `proposed` | No billing integration in Phase 0/1. |
| D-07 | Rule Engine vs AI Planning | Rule engine strictly authoritative | `proposed` | AI proposes, deterministic engine validates/discards. |
| D-08 | Gamification & Rewards | Basic streaks only | `proposed` | Avoid dark patterns and extractive mechanics. |
| D-09 | Authentication Mechanism | Mobile OTP via SmsProvider | `proposed` | Standard verification for Iranian phone numbers. |
| D-10 | AI Consultant Direct Contract | Bounded structured consultant | `proposed` | Reconciles owner consultant scenario with ADR-0004/0006. |

---

## 3. Security & Operational Remediation Decisions

| ID | Title | Approved Decision | Enforcement Point |
|---|---|---|---|
| SEC-DEC-01 | Explicit CORS Origin Whitelist | Strip wildcard `*` whenever credentials enabled; rely on `CORS_ALLOWED_ORIGINS`. | `Settings`, `main.py` |
| SEC-DEC-02 | Production Fail-Fast on Default Passwords | Reject `kunkor_dev_password` and empty DSNs in `ENVIRONMENT=production`. | `Settings`, `migrate.py` |
| SEC-DEC-03 | Continuous Dependency Remediation | Overwrite vulnerable transitive packages (`glob`, `postcss`) and track Next.js security releases. | `package.json` overrides |
| SEC-DEC-05 | Strict Authorization Dependency Checking | Deny dependencies without security/authz marker functions or route attributes. | `check_authz_matrix.py` |
| SEC-DEC-06 | Bounded Outbox Retries | Dead-letter retry limit (`MAX_RETRIES = 5`) with per-event transaction boundaries. | `outbox_worker.py` |

---

## 4. Stage 0.5 Contract Decisions

1. **IntakeSlots Contract**:
   - Structured JSON schema specifying student educational grade (`G01`–`G12`, `POSTK`), track (`math`, `experimental`, `humanities`), target exam, daily study capacity (minutes), and weak subject priorities.
2. **StudyPlan Contract**:
   - Versioned schema (`plan_id`, `student_id`, `revision_no`, `engine_version`, `rule_set_version`, `status`, `items`).
   - Pure state transitions: `draft` -> `active` -> `superseded`.
3. **Deterministic Validator Contract**:
   - Pure validation function (`validate_study_plan(plan, student_profile, curriculum_catalog)`).
   - Validates time budgets, prerequisite ordering, and daily limits without LLM input.
4. **15 Scenario Specification Contract**:
   - 3 success + 3 failure scenarios across 5 groups: `primary_low`, `primary_high`, `lower_secondary`, `upper_secondary`, `konkur`.
5. **9router AI Provider Contract**:
   - Implements abstract `AiProvider` interface via `9router` unified proxy.
   - Strictly bounded timeouts (15s), budget tracking, structured output parsing (`response_format={"type": "json_object"}`), and graceful fallback to rule-based planner.
