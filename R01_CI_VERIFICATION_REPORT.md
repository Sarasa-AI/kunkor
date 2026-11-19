# R01 CI Verification

- **VERIFIED** checkout `/Users/sarasa/kunkor`, branch `main`, HEAD `84acb5fe1abde4210ac15b3024dd2da6c34ec83b`. `git rev-list --left-right --count HEAD...origin/main` returned `0 0` against the local tracking ref.
- **VERIFIED** initial `git status --short --branch` began `## main...origin/main`. `git status --porcelain=v1 --untracked-files=all` counted 39 unstaged modifications, 48 unstaged deletions, 477 untracked files, zero staged changes. All local checks evaluated working-tree source, including untracked inputs.
- **PENDING** remote GitHub Actions on the audited changes. `.github/workflows/ci.yml:3` runs on push or pull request to `main`. This report records local results only.

## Local results

| Status | Command | Output or observation |
| --- | --- | --- |
| VERIFIED | `docker exec <audit-container> psql -U kunkor -d kunkor_stage0_test -Atc 'SHOW server_version'` | `16.15`. Fresh container from cached `postgres:16-alpine`, random port bound to loopback. |
| VERIFIED | `make migrate` | All 11 SQL migrations applied. Last output included `Applied 0011_empty_to_grow_catalog successfully`. |
| VERIFIED | `make test VENV="$PWD/services/api/.venv" PYTEST="$PWD/services/api/.venv/bin/python -m pytest"` | `373 passed, 2 warnings in 16.75s`, including the backup/restore integration test. |
| VERIFIED | `make migrate-check VENV="$PWD/services/api/.venv"` | `Step 1 (Forward): Applied 11 migrations.` `Step 2 (Backward): Rolled back 11 migrations.` `Step 3 (Re-apply): Successfully applied 11 migrations.` |
| VERIFIED | `cd services/api && .venv/bin/python -m ruff check .` | `All checks passed!` |
| VERIFIED | `cd services/api && .venv/bin/python -m mypy app` | `Success: no issues found in 43 source files`. |
| VERIFIED | `cd services/api && .venv/bin/python -m pip --disable-pip-version-check check` | `No broken requirements found.` |
| VERIFIED | `make import-check authz-matrix VENV="$PWD/services/api/.venv"` | `Modular boundary check passed (0 violations).` `Evaluated 47 routes.` `100% of routes meet authorization criteria.` |
| VERIFIED | `npm ci --offline --no-audit --no-fund` | Isolated web copy with repository lockfile, `added 337 packages in 2s`. |
| VERIFIED | `npm run lint` / `npm run typecheck` | `No ESLint warnings or errors`; TypeScript exited 0. |
| VERIFIED | `npm run test:healthz` / `npm run test:content` | 12 and 8 passed, respectively. |
| VERIFIED | `npm run build` / `npm run test:healthz:runtime` | `Compiled successfully`; production Next process with synthetic upstream, `1 passed`. |
| VERIFIED | `npm run test:contexts` | 2 passed with Docker available. These tests are additional to the workflow. |
| VERIFIED | Extract the secret-scan shell block from `.github/workflows/ci.yml:110`, then run via `bash -e -c` on a temporary Git index with a synthetic fixture. | Original script returned 0 with only the first marker present. Patched script returned `clean: exit=0`, `first: exit=1`, `second: exit=1`. |

API ran on Python 3.11.14. Web ran on Node 22.23.5/npm 10.9.9 with Next 15.5.28. The CI workflow specifies Node 20. The web checks ran in a temporary copy to keep generated files outside the checkout. The existing workspace dependency tree lacked its native SWC binary. An offline lockfile install in the temporary copy restored it.

The database commands used explicit `DATABASE_URL` and `TEST_DATABASE_URL` pointing to the same disposable database, exported test CORS origins, and disabled real provider and Telegram delivery. `DOCKER_PG_CONTAINER` pointed at that container for version-matched `pg_dump`/`pg_restore`. Before the CORS override, dotenv changed the test app's origin allowlist and two assertions failed (`tests/test_security_remediation.py:70`, `tests/test_web_consultation_endpoints.py:378`, paths relative to `services/api`). The CI-style origins restored both checks without changing application CORS behavior. Relocated venv launchers had stale shebangs, so Python modules were invoked via the working interpreter.

The workflow patch makes either blocked pattern fail the job and omits matching text from logs. It is a scoped CI check. Full history-scanner coverage is tracked under SEC-04. `git diff --check -- .github/workflows/ci.yml` passed. The full-tree check showed four pre-existing Markdown trailing-space warnings at `docs/PHASE_1_REPORT.md:9`, `docs/PHASE_1_REPORT.md:10`, `docs/PHASE_2_REPORT.md:5`, and `docs/PHASE_3_REPORT.md:5`.

## Stage 0 rerun

**VERIFIED** after the targeted fixes, the same `make test migrate-check` commands returned `378 passed, 2 warnings in 16.74s` and `SUCCESS: Migration integrity and reversibility checks passed.` Ruff passed. Mypy returned `Success: no issues found in 44 source files`. Import and authorization matrix checks passed, with 47 routes evaluated. The isolated web lint, typecheck, 12 health tests, 8 content tests, build and 1 production runtime test passed again. Remote GitHub Actions remains **PENDING**.

**VERIFIED** after supervisor remediation, the same API commands returned `379 passed, 2 warnings in 17.72s` and `SUCCESS: Migration integrity and reversibility checks passed.` Ruff, Mypy, dependency consistency, import boundaries and the 47-route authorization matrix passed. The web inputs are unchanged from the verified build.

**VERIFIED** on 2026-11-19, `git checkout-index -a` materialized the scoped commit candidate in a clean directory. The PostgreSQL 16.15 run returned `379 passed, 2 warnings in 16.00s`, all 11 migration round-trips passed, and the import and 47-route policy checks passed. Ruff and Mypy passed. Locked web installation and all workflow web commands passed on Node 22, plus both Docker-context tests. The candidate includes inherited runtime dependencies and excludes unrelated documentation deletions, local configuration, and evidence archives.
