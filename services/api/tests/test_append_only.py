import os

import psycopg
import pytest

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://kunkor:kunkor_dev_password@localhost:5435/kunkor_test",
)


def test_append_only_audit_events_allows_insert():
    with psycopg.connect(TEST_DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_events (action, resource_type, metadata)
                VALUES (%s, %s, %s)
                RETURNING id;
                """,
                ("auth.login", "user", '{"ip": "127.0.0.1"}'),
            )
            row = cur.fetchone()
            assert row is not None
            event_id = row[0]
            assert event_id is not None
        conn.commit()


def test_append_only_audit_events_rejects_update():
    with psycopg.connect(TEST_DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_events (action, resource_type)
                VALUES (%s, %s)
                RETURNING id;
                """,
                ("test.action", "resource"),
            )
            event_id = cur.fetchone()[0]
        conn.commit()

        # Attempting UPDATE must fail due to trigger
        with conn.cursor() as cur:
            with pytest.raises(psycopg.Error) as exc_info:
                cur.execute(
                    """
                    UPDATE audit_events
                    SET action = %s
                    WHERE id = %s;
                    """,
                    ("tampered.action", event_id),
                )
            assert "append-only" in str(exc_info.value)
        conn.rollback()


def test_append_only_audit_events_rejects_delete():
    with psycopg.connect(TEST_DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_events (action, resource_type)
                VALUES (%s, %s)
                RETURNING id;
                """,
                ("test.action_delete", "resource"),
            )
            event_id = cur.fetchone()[0]
        conn.commit()

        # Attempting DELETE must fail due to trigger
        with conn.cursor() as cur:
            with pytest.raises(psycopg.Error) as exc_info:
                cur.execute(
                    """
                    DELETE FROM audit_events
                    WHERE id = %s;
                    """,
                    (event_id,),
                )
            assert "append-only" in str(exc_info.value)
        conn.rollback()
