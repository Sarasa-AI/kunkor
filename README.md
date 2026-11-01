# kunkor

## PostgreSQL-backed API verification

CI uses Python 3.11 and a disposable PostgreSQL 16 service. GitHub Actions waits
for its `pg_isready` health check before starting job steps. All eight original
tests (including migration rollback/reapply) run via `make test`; `make
migrate-check` also checks migration naming/pairs and the full up/down/up cycle.
Database errors fail the job; no database tests are skipped.

Run the same process locally from the repository root (Docker required):

```bash
set -euo pipefail
python3.11 -m venv .venv
.venv/bin/python -m pip install -r services/api/requirements-dev.txt

# Disposable test-only credentials; never supply a useful application database.
export POSTGRES_USER=kunkor
export POSTGRES_PASSWORD=kunkor_ci_password
export POSTGRES_DB=kunkor_test
export POSTGRES_PORT=5435  # Choose another unused port if needed.
export TEST_DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT}/${POSTGRES_DB}"

docker run --detach --rm --name kunkor-r01-postgres \
  --tmpfs /var/lib/postgresql/data \
  -p "127.0.0.1:${POSTGRES_PORT}:5432" \
  -e POSTGRES_USER -e POSTGRES_PASSWORD -e POSTGRES_DB \
  --health-cmd 'pg_isready -h 127.0.0.1 -U kunkor -d kunkor_test' \
  --health-interval 5s --health-timeout 5s --health-retries 12 \
  postgres:16-alpine
trap 'docker stop kunkor-r01-postgres' EXIT

for attempt in {1..60}; do
  state=$(docker inspect --format '{{.State.Health.Status}}' kunkor-r01-postgres)
  if [ "$state" = healthy ]; then break; fi
  if [ "$state" = unhealthy ]; then exit 1; fi
  sleep 1
done
test "$state" = healthy

make migrate DATABASE_URL="$TEST_DATABASE_URL"
make test
make migrate-check
(cd services/api && ../../.venv/bin/ruff check . && ../../.venv/bin/mypy app)
make import-check authz-matrix
```

The container is removed on exit; rerun with a fresh database for each full
verification. Tests commit data and migration tests drop tables. The name guard
requires a `*_test` database, but cannot establish that its data is disposable.
Never use production credentials. CI credentials are environment variables for
the disposable service, not production secrets.

Local application development still uses `docker compose up -d --wait db`, then
`make migrate` for `kunkor_dev` before starting the application. Compose creates
only the development database. Use the separate disposable container above for
tests, including when an existing Compose volume is present; choose another port
and set `TEST_DATABASE_URL` accordingly. No existing volume needs resetting.
