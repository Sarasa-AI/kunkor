import os

import psycopg

from app.workers.outbox_worker import process_pending_outbox_events

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://kunkor:kunkor_dev_password@localhost:5435/kunkor_test",
)


def test_outbox_worker_processes_events():
    with psycopg.connect(TEST_DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO outbox_events (event_type, aggregate_type, aggregate_id, payload)
                VALUES (%s, %s, %s, %s)
                RETURNING id;
                """,
                ("user.registered", "user", "u-12345", '{"role": "student"}'),
            )
            event_id = cur.fetchone()[0]
        conn.commit()

    # Process events in test database
    processed = process_pending_outbox_events(limit=10, test=True)
    assert processed >= 1

    # Verify event is marked as processed
    with psycopg.connect(TEST_DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT processed_at FROM outbox_events WHERE id = %s;", (event_id,))
            row = cur.fetchone()
            assert row is not None
            assert row[0] is not None


def test_outbox_worker_dead_letters_after_max_retries():
    with psycopg.connect(TEST_DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO outbox_events (
                    event_type, aggregate_type, aggregate_id, payload, retry_count
                )
                VALUES (%s, %s, %s, %s, 5)
                RETURNING id;
                """,
                ("poison.pill", "test", "p-999", '{"invalid": true}'),
            )
            poison_id = cur.fetchone()[0]
        conn.commit()

    # Process events; event with retry_count >= MAX_RETRIES must not be processed
    process_pending_outbox_events(limit=10, test=True)

    with psycopg.connect(TEST_DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT processed_at, retry_count FROM outbox_events WHERE id = %s;",
                (poison_id,),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] is None
            assert row[1] == 5
