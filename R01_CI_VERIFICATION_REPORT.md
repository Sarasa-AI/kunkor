# R01 — PostgreSQL-backed CI verification

Date: 2026-10-28. Inspected HEAD: `30212416c9e56d99019c562f421d805111bbc044`.

## Initial findings

- `.github/workflows/ci.yml` installed API requirements, ran Ruff/Mypy/pytest,
  import and authorization checks, but provisioned no PostgreSQL service and
  ran no explicit migration initialization or migration integrity command.
- `services/api/requirements-dev.txt` includes runtime dependencies, pytest,
  pytest-asyncio, Ruff and Mypy. `pyproject.toml` collects `tests/`, adds the API
  directory to Python's path, and defines lint/type settings.
- The session-autouse fixture applies existing migrations before every test
  session. All database test modules and application test connections use
  `TEST_DATABASE_URL`, defaulting to
  `postgresql://kunkor:kunkor_dev_password@localhost:5435/kunkor_test`.
  Application migrations instead use `DATABASE_URL`, defaulting to `kunkor_dev`.
- Eight existing tests include destructive rollback/reapply. Missing PostgreSQL
  raises setup errors; there is no database-unavailable skip mechanism.
- The existing SQL runner tracks `schema_migrations`; `make migrate-check`
  verifies naming/pairs and rollback/up/down/up. The baseline has one migration.
- Compose uses `postgres:16-alpine`, port 5435, and creates only `kunkor_dev`.
  Its init SQL installs extensions, not the test database. README had no test
  instructions; TASK-02 records the infrastructure and original test files.
- Existing `.venv` had dependencies below declared lower bounds. Verification
  therefore used a fresh temporary Python 3.11 environment.
- Two pre-existing untracked audit documents were preserved unchanged.

## Files changed and why

- `.github/workflows/ci.yml`: PostgreSQL 16 service, explicit test database and
  credentials, health check, job-level test URL; existing Make targets for
  initialization, full pytest and full migration integrity/reversibility.
- `services/api/scripts/migrate_check.py`: reject destructive targets whose
  database name does not end in `_test`; package import supports reuse by the
  fixture. Remove full connection URL from normal round-trip logging.
- `services/api/tests/conftest.py`: apply the same guard before test migrations.
- `services/api/tests/test_migrations.py`: add one guard regression test for
  development/production/missing database names. The original round-trip test
  body and all eight original tests remain unchanged.
- `README.md`: reproducible disposable database, bounded readiness wait,
  migration/test commands, environment variables, cleanup and local development
  migration order; existing Compose volumes need no changes.
- `R01_CI_VERIFICATION_REPORT.md`: this evidence and limitations.

No product code, baseline SQL, dependency manifests, architecture decisions,
Compose volumes, or roadmap progress statuses were changed.

## PostgreSQL configuration

- Image: `postgres:16-alpine`; locally observed PostgreSQL **16.15**, aarch64.
  Local cached image ID:
  `sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea`.
- Database `kunkor_test`, username `kunkor`, password `kunkor_ci_password`.
  These are disposable test-only values passed through service/job environment
  variables, not production credentials or required repository secrets.
- CI: `127.0.0.1:5435` mapped to service port 5432. Local verification used
  random loopback port **51927**, a memory-backed data directory, no persistent
  volume. A second fresh database, `kunkor_repeat_test`, verified repeatability.
- Health command: `pg_isready -h 127.0.0.1 -U kunkor -d kunkor_test`, interval
  5 seconds, timeout 5 seconds, 12 retries. Local Docker health reached `healthy`
  before migrations/tests. Migrations additionally prove authenticated access.

## Commands executed

Inspection included `git status --short`, `git rev-parse HEAD`, repository file
searches/reads, `docker info`, image inspection and PostgreSQL `SELECT version()`.
The successful local verification used:

```bash
.venv/bin/python -m venv /tmp/kunkor-r01-py311
/tmp/kunkor-r01-py311/bin/python -m pip install --index-url https://pypi.org/simple -r services/api/requirements-dev.txt

docker run --detach --rm --name kunkor-r01-postgres \
  --tmpfs /var/lib/postgresql/data -p 127.0.0.1::5432 \
  -e POSTGRES_DB=kunkor_test -e POSTGRES_USER=kunkor \
  -e POSTGRES_PASSWORD=kunkor_ci_password \
  --health-cmd 'pg_isready -h 127.0.0.1 -U kunkor -d kunkor_test' \
  --health-interval 5s --health-timeout 5s --health-retries 12 postgres:16-alpine
docker inspect kunkor-r01-postgres --format '{{.State.Health.Status}} {{(index (index .NetworkSettings.Ports "5432/tcp") 0).HostPort}}'

export TEST_DATABASE_URL=postgresql://kunkor:kunkor_ci_password@127.0.0.1:51927/kunkor_test
make migrate VENV=/tmp/kunkor-r01-py311 DATABASE_URL="$TEST_DATABASE_URL"
make test VENV=/tmp/kunkor-r01-py311
(cd services/api && /tmp/kunkor-r01-py311/bin/python -m pytest -v tests/test_migrations.py::test_migrations_forward_and_backward)
make migrate-check VENV=/tmp/kunkor-r01-py311
(cd services/api && /tmp/kunkor-r01-py311/bin/ruff check .)
(cd services/api && /tmp/kunkor-r01-py311/bin/mypy app)
make import-check authz-matrix VENV=/tmp/kunkor-r01-py311
/tmp/kunkor-r01-py311/bin/python -m pip check
(cd apps/web && npm run lint)
(cd apps/web && npm run typecheck)

# Negative checks: nonzero exits are expected.
TEST_DATABASE_URL='postgresql://kunkor:unused@127.0.0.1:1/kunkor_test?connect_timeout=2' make test VENV=/tmp/kunkor-r01-py311
TEST_DATABASE_URL='postgresql://localhost:1/kunkor_dev' make migrate-check VENV=/tmp/kunkor-r01-py311
make test VENV=/tmp/kunkor-r01-py311 PYTEST='/tmp/kunkor-r01-py311/bin/python -m pytest /tmp/test_kunkor_r01_failure_probe.py -q'

docker exec kunkor-r01-postgres createdb -U kunkor kunkor_repeat_test
TEST_DATABASE_URL='postgresql://kunkor:kunkor_ci_password@127.0.0.1:51927/kunkor_repeat_test' make migrate test migrate-check VENV=/tmp/kunkor-r01-py311 DATABASE_URL='postgresql://kunkor:kunkor_ci_password@127.0.0.1:51927/kunkor_repeat_test'
docker stop --time 2 kunkor-r01-postgres
docker ps -a --filter name=kunkor-r01-postgres --format '{{.Names}}'
git diff --check
```

The failure probe was a temporary file containing one test:
`def test_failure_probe(): assert False, "R01 intentional failure probe"`.
It was selected through the existing Makefile's `PYTEST` override, without
modifying or disabling repository tests. A temporary subprocess harness
(`/tmp/kunkor_r01_verify.py`) asserted expected exit codes and recorded output
in `/tmp/kunkor-r01-results.log`.

Workflow YAML was parsed locally with PyYAML; assertions verified the service
image/health settings, initialization before pytest before migration checks,
and absence of `continue-on-error` or shell failure suppression in the API job.
This is a structural check, not an executed GitHub Actions run or actionlint.

## Locally executed results

- Clean environment: Python **3.11.7**; dependency installation succeeded from
  official PyPI; `pip check` found no broken requirements.
- Resolved versions: FastAPI 0.162.0, Uvicorn 0.54.0, Pydantic 2.14.1,
  pydantic-settings 2.16.2, httpx 0.28.1, psycopg 3.3.6, pytest 9.2.0,
  pytest-asyncio 1.4.1, Ruff 0.17.3, Mypy 2.4.1.
- Full suite: **9 passed**, 0 skipped, 0 failed, 0.62s. Eight originals plus
  one database-name safety regression. Original migration round-trip also
  selected separately: **1 passed**, 0.07s.
- Migration initialization and naming/pair/full rollback/up/down/up: **PASS**;
  one migration applied at each forward stage and rolled back at backward stage.
- Fresh second database: initialization **PASS**, **9 passed** in 0.27s,
  migration integrity/round-trip **PASS**.
- API Ruff **PASS**; API Mypy **PASS**, 11 source files. Web lint and TypeScript
  **PASS** using existing installed web dependencies.
- Import boundary and authorization matrix checks **PASS**, within their
  existing limited static scope. `git diff --check`: **PASS**.
- Unavailable database: **9 setup errors**, no skips; pytest exit **1**,
  `make test` exit **2**. This intentionally failing run proves fail-closed
  database behavior.
- Application database name: rejected before connection/rollback;
  migration-check exit **1**, Make exit **2**.
- Intentional assertion failure: **1 failed**, pytest exit **1**, Make exit
  **2**, proving test-failure propagation through the exact CI Make target.
- Container cleanup: stopped; `docker ps -a` filter returned no container.

## CI workflow behavior

GitHub Actions provisions the PostgreSQL service before API steps and waits for
its Docker health check. An unhealthy service prevents tests from starting.
Dependencies, lint and types run; `make migrate` receives `DATABASE_URL` set
explicitly to `TEST_DATABASE_URL`, avoiding the development database default.
`make test` collects every existing test, including
`test_migrations_forward_and_backward`. `make migrate-check` separately runs
the complete migration convention/reversibility checker. Import/authz checks
remain in place. No `continue-on-error`, skip-on-connection-error, or `|| true`
is used. A nonzero Make exit fails the shell step/job.

**Remote CI: NOT EXECUTED.** No commit, push, workflow dispatch or remote result
was produced. The local service-health observations and YAML assertions verify
configuration; actual GitHub service startup/job status remain unverified.

## Remaining issues and deviations

- Remote GitHub Actions execution is the remaining acceptance evidence. Local
  verification ran on macOS ARM64; CI runs Ubuntu/Python 3.11. No remote pass
  is claimed.
- Clean install initially hit sandbox networking restrictions, then the
  configured package mirror returned HTTP 402. Official PyPI succeeded without
  changing repository dependency requirements or index configuration. An
  initial temporary Python 3.14 install was not used for reported test results.
- Dependencies and the PostgreSQL major-version image remain unpinned, as in
  the existing project. Dependency locking is outside R01.
- pytest-asyncio emits an unset fixture-loop-scope deprecation warning;
  Starlette emits an httpx TestClient deprecation warning. Tests pass; no
  unrelated dependency or warning suppression changes were made.
- The `_test` suffix guard prevents obvious accidental application targeting;
  it does not prove the database is disposable. README requires isolation and
  fresh databases because tests commit data and drop tables.
- No migration SQL defect was found. The small migration-check import/guard
  changes support safe reuse by pytest and safe destructive verification;
  the DSN log removal avoids printing environment-supplied passwords.
- No next roadmap task was started.

**Status: PARTIAL — implementation and local verification pass; remote CI unverified.**
