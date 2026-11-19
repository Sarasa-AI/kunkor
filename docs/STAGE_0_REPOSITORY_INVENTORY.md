# Stage 0 Repository Inventory

**VERIFIED** checkout `/Users/sarasa/kunkor`, branch `main`, HEAD `84acb5fe1abde4210ac15b3024dd2da6c34ec83b`. Initial `git status --short --branch` showed `## main...origin/main` with a dirty worktree. The inventory covers code on disk. The R01 report records the initial porcelain counts.

## 1. FastAPI routes

- **VERIFIED** `services/api/app/main.py:15` creates the app and mounts consultation, catalog, owner catalog, student identity, and operations routers at lines 24–28. `make authz-matrix` evaluated 47 routes. Five paths are explicitly public in `services/api/app/core/authz.py:9`, including health and generated documentation routes.
- **VERIFIED** `services/api/app/modules/consultation/router.py:86` registers the Telegram webhook. Lines 102, 139, 215, 231, and 374 register plan, progress, history, intake, and identity routes with compatibility aliases.
- **VERIFIED** `services/api/app/modules/content/router.py:177` through the unit routes starting at line 255 serve published catalog reads. `services/api/app/modules/content/admin_router.py:45` through line 122 implements owner-only book and unit management, lifecycle transitions, and audit reads.
- **VERIFIED** `services/api/app/modules/identity/router.py:45` provides profile reads, updates, and context. `services/api/app/modules/operations/router.py:42` through line 148 exposes outbox operations, student/plan/progress inspection, flags, entitlements, and audit logs.

## 2. Persistence and models

- **REFUTED** ORM layer. The runtime uses `psycopg` connections in `services/api/app/core/db.py:26` and parameterized SQL in consultation, content, identity, and operations `repository.py` files. `services/api/app/modules/content/models.py` contains catalog domain data structures. Pydantic request/response and planning models include `services/api/app/schemas/planning.py:44` and `services/api/app/modules/identity/router.py:20`.
- **VERIFIED** SQL persistence for audit/outbox/idempotency/flags/entitlements (`services/api/migrations/0001_baseline_schema.up.sql:17`), students/intake/plans (`services/api/migrations/0002_students_and_consultation.up.sql:4`), progress (`services/api/migrations/0003_daily_progress_and_revisions.up.sql:4`), AI usage (`services/api/migrations/0005_ai_usage.up.sql:3`), and catalog/audit (`services/api/migrations/0008_content_catalog.up.sql:6`, `services/api/migrations/0011_empty_to_grow_catalog.up.sql:119`).

## 3. Migrations

- **REFUTED** Alembic implementation. `rg --files -g '*alembic*'` yielded no project files. `services/api/requirements.txt` declares psycopg. `Makefile:34` and `Makefile:37` use the custom `services/api/scripts/migrate.py` and `services/api/scripts/migrate_check.py` runner for paired SQL.
- **VERIFIED** 11 up/down pairs under `services/api/migrations/`, including existing 0001–0006 and working-tree 0007–0011. The latter cover student profile, versioned catalog, identity isolation, profile constraint round-trip, and catalog operations. R01 exercised all 11 forward/backward/reapply on PostgreSQL 16.15.

## 4. Authentication and authorization

- **VERIFIED** auth dependencies exist in `services/api/app/modules/consultation/auth.py`, `services/api/app/modules/identity/auth.py:16`, and `services/api/app/modules/operations/auth.py`. These cover signed student identities, student context, admin/owner scope, and authenticated catalog access. The Telegram webhook dependency is at `services/api/app/modules/consultation/router.py:38`. The policy shared by startup and CI lives at `services/api/app/core/authz.py:22`.
- **VERIFIED** ADR-3's centralized runtime authorization requirement and ADR-8's denormalized student ownership design are documented in `HEAD:docs/adr/0003-centralized-backend-authz.md:11` and `HEAD:docs/adr/0008-denormalized-student-id.md:11`. Both paths were deleted in the input worktree. The audit report records enforcement separately from the decisions.

## 5. Worker and outbox

- **VERIFIED** `services/api/app/workers/outbox_worker.py` processes PostgreSQL outbox events and runs polling. `services/api/app/workers/telegram.py` supplies the delivery adapter. Despite its filename, the Compose entry point at `docker-compose.yml:60` delegates to the real worker loop via `services/api/app/workers/placeholder_worker.py:8`.

## 6. Tests

- **VERIFIED** `services/api/pyproject.toml:18` points pytest at `services/api/tests/`. `services/api/tests/conftest.py:14` provisions schema through the SQL runner. The 373-item R01 run and 379-item final Stage 0 run covered routing, policy, signed identity, cross-student access, migration/backup, worker/outbox, catalog and consultation integration. Web contract/runtime tests live in `apps/web/tests/`.

## 7. Frontend and clients

- **VERIFIED** Next App Router includes the home page (`apps/web/src/app/page.tsx`), owner content page (`apps/web/src/app/admin/content/page.tsx`), health proxy (`apps/web/src/app/api/healthz/route.ts:3`), and owner API proxy (`apps/web/src/app/api/admin/content/[...path]/route.ts:63`). `npm run build` emitted those four routes plus the framework 404 page. Telegram uses the API webhook and outbound adapter noted above.
- **UNTESTED** live browser and external Telegram/provider delivery. R01 ran Next locally with a synthetic upstream and API tests exercised the outbound adapter with test doubles.
