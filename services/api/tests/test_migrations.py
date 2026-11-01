import os

import psycopg
import pytest

from scripts.migrate import apply_migrations, rollback_migrations
from scripts.migrate_check import require_test_database

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://kunkor:kunkor_dev_password@localhost:5435/kunkor_test",
)


def test_destructive_checks_reject_application_database(monkeypatch):
    for dsn in ("postgresql://localhost/kunkor_dev", "dbname=kunkor_prod", "host=localhost"):
        with pytest.raises(ValueError, match="disposable database"):
            require_test_database(dsn)

    # Empty DSN rejected
    with pytest.raises(ValueError, match="explicit test database URL"):
        require_test_database("")

    # Non-local / remote host rejected
    with pytest.raises(ValueError, match="restricted to local/disposable hosts"):
        require_test_database("postgresql://db.prod.internal:5432/kunkor_test")

    # Production environment rejected
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(ValueError, match="prohibited in production"):
        require_test_database(TEST_DB_URL)
    monkeypatch.undo()

    require_test_database(TEST_DB_URL)


def test_migrations_forward_and_backward():
    # 1. Rollback all migrations
    rollback_migrations(TEST_DB_URL, steps=999)

    with psycopg.connect(TEST_DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN (
                    'audit_events', 'outbox_events', 'idempotency_keys',
                    'feature_flags', 'entitlements', 'students', 'study_plans',
                    'daily_progress_logs'
                  );
                """
            )
            tables_after_down = cur.fetchall()
            assert len(tables_after_down) == 0

    # 2. Forward
    applied = apply_migrations(TEST_DB_URL)
    assert applied >= 3

    with psycopg.connect(TEST_DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN (
                    'audit_events', 'outbox_events', 'idempotency_keys',
                    'feature_flags', 'entitlements', 'students', 'study_plans',
                    'daily_progress_logs'
                  )
                ORDER BY table_name;
                """
            )
            tables = [r[0] for r in cur.fetchall()]
            assert "audit_events" in tables
            assert "outbox_events" in tables
            assert "idempotency_keys" in tables
            assert "feature_flags" in tables
            assert "entitlements" in tables
            assert "students" in tables
            assert "study_plans" in tables
            assert "daily_progress_logs" in tables
