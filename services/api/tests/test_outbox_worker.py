import os
from uuid import uuid4

import psycopg
import pytest

from app.workers.outbox_worker import process_pending_outbox_events

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://kunkor:kunkor_dev_password@localhost:5435/kunkor_test",
)


@pytest.fixture(autouse=True)
def isolate_synthetic_outbox():
    with psycopg.connect(TEST_DB_URL) as conn:
        conn.execute("DELETE FROM outbox_events")
    yield


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


def test_telegram_transport_requires_explicit_enable(monkeypatch):

    from app.core.config import settings
    from app.workers.telegram import DeliveryDisabled, send_message

    monkeypatch.setattr(settings, "TELEGRAM_DELIVERY_ENABLED", False)
    with pytest.raises(DeliveryDisabled):
        send_message(123, "synthetic")


def test_telegram_transport_checks_api_acceptance(monkeypatch):
    import httpx

    from app.core.config import settings
    from app.workers import telegram

    monkeypatch.setattr(settings, "TELEGRAM_DELIVERY_ENABLED", True)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "synthetic-token")
    calls = []

    def accepted(url, **kwargs):
        calls.append(kwargs["json"])
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 77}})

    monkeypatch.setattr(telegram.httpx, "post", accepted)

    # Response status checking requires an associated request, just like real httpx.
    def response(url, **kwargs):
        result = accepted(url, **kwargs)
        result.request = httpx.Request("POST", url)
        return result

    monkeypatch.setattr(telegram.httpx, "post", response)
    assert telegram.send_message(123, "synthetic") == 77
    assert calls == [{"chat_id": 123, "text": "synthetic"}]

    monkeypatch.setattr(
        telegram.httpx,
        "post",
        lambda url, **kwargs: httpx.Response(
            200, json={"ok": False}, request=httpx.Request("POST", url)
        ),
    )
    with pytest.raises(RuntimeError, match="acceptance unconfirmed"):
        telegram.send_message(123, "synthetic")


def test_disabled_delivery_stays_pending(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "TELEGRAM_DELIVERY_ENABLED", False)
    with psycopg.connect(TEST_DB_URL) as conn:
        row = conn.execute(
            "INSERT INTO outbox_events (event_type, aggregate_type, aggregate_id, payload) "
            "VALUES ('TELEGRAM_MESSAGE_REQUESTED', 'test', 'disabled', "
            '\'{"telegram_chat_id":123,"message_text":"synthetic"}\') RETURNING id'
        ).fetchone()
        event_id = row[0]
    process_pending_outbox_events(limit=1000, test=True)
    with psycopg.connect(TEST_DB_URL) as conn:
        row = conn.execute(
            "SELECT processed_at, retry_count FROM outbox_events WHERE id = %s", (event_id,)
        ).fetchone()
        assert row == (None, 0)


def test_failed_delivery_backoff_then_accepted(monkeypatch):
    from app.workers import outbox_worker

    with psycopg.connect(TEST_DB_URL) as conn:
        event_id = conn.execute(
            "INSERT INTO outbox_events (event_type, aggregate_type, aggregate_id, payload) "
            "VALUES ('TELEGRAM_MESSAGE_REQUESTED', 'test', 'retry', "
            '\'{"telegram_chat_id":123,"message_text":"synthetic"}\') RETURNING id'
        ).fetchone()[0]

    def fail(chat_id, text):
        raise RuntimeError("synthetic timeout")

    monkeypatch.setattr(outbox_worker, "send_message", fail)
    process_pending_outbox_events(limit=1000, test=True)
    with psycopg.connect(TEST_DB_URL) as conn:
        row = conn.execute(
            "SELECT processed_at, retry_count, next_attempt_at > NOW(), last_error "
            "FROM outbox_events WHERE id = %s",
            (event_id,),
        ).fetchone()
        assert row == (None, 1, True, "RuntimeError")
        conn.execute("UPDATE outbox_events SET next_attempt_at = NOW() WHERE id = %s", (event_id,))
    monkeypatch.setattr(outbox_worker, "send_message", lambda chat_id, text: 88)
    process_pending_outbox_events(limit=1000, test=True)
    with psycopg.connect(TEST_DB_URL) as conn:
        row = conn.execute(
            "SELECT processed_at IS NOT NULL, telegram_message_id, last_error "
            "FROM outbox_events WHERE id = %s",
            (event_id,),
        ).fetchone()
        assert row == (True, 88, None)


def test_telegram_httpx_logs_redact_bot_token(monkeypatch, caplog):
    import logging

    import httpx

    from app.core.config import settings
    from app.workers import telegram

    monkeypatch.setattr(settings, "TELEGRAM_DELIVERY_ENABLED", True)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "synthetic-secret-token")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"ok": True, "result": {"message_id": 99}})
    )
    with httpx.Client(transport=transport) as client:
        monkeypatch.setattr(telegram.httpx, "post", client.post)
        with caplog.at_level(logging.INFO, logger="httpx"):
            assert telegram.send_message(123, "synthetic") == 99
    assert "HTTP Request" in caplog.text
    assert "[REDACTED]" in caplog.text
    assert "synthetic-secret-token" not in caplog.text


@pytest.mark.parametrize("http_status,retries", [(400, 5), (403, 5), (429, 1), (500, 1)])
def test_telegram_rejection_classification(monkeypatch, caplog, http_status, retries):
    import httpx

    from app.core.config import settings
    from app.workers import telegram

    monkeypatch.setattr(settings, "TELEGRAM_DELIVERY_ENABLED", True)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "synthetic-token")
    marker = "synthetic-private-rejection-body"

    def reject(url, **kwargs):
        return httpx.Response(http_status, text=marker, request=httpx.Request("POST", url))

    monkeypatch.setattr(telegram.httpx, "post", reject)
    with psycopg.connect(TEST_DB_URL) as conn:
        event_id = conn.execute(
            "INSERT INTO outbox_events (event_type, aggregate_type, aggregate_id, payload) "
            "VALUES ('TELEGRAM_MESSAGE_REQUESTED', 'test', 'reject', %s::jsonb) RETURNING id",
            ('{"telegram_chat_id":123,"message_text":"synthetic"}',),
        ).fetchone()[0]

    assert process_pending_outbox_events(test=True) == 0
    with psycopg.connect(TEST_DB_URL) as conn:
        row = conn.execute(
            "SELECT processed_at, retry_count, next_attempt_at > NOW(), last_error "
            "FROM outbox_events WHERE id = %s",
            (event_id,),
        ).fetchone()
    classification = "PermanentDeliveryError" if retries == 5 else "RuntimeError"
    assert row == (None, retries, True, classification)
    assert marker not in caplog.text


def test_locked_event_is_skipped_and_recovered_after_rollback(monkeypatch, caplog):
    monkeypatch.setenv("PGOPTIONS", "-c lock_timeout=1000")
    marker = "synthetic-private-aggregate"
    with psycopg.connect(TEST_DB_URL) as conn:
        first, second = conn.execute(
            "INSERT INTO outbox_events (event_type, aggregate_type, aggregate_id, payload) "
            "VALUES ('test.event', 'test', %s, '{}'), ('test.event', 'test', 'other', '{}') "
            "RETURNING id",
            (marker,),
        ).fetchall()

    with psycopg.connect(TEST_DB_URL) as interrupted_worker:
        interrupted_worker.execute("SELECT id FROM outbox_events WHERE id = %s FOR UPDATE", first)
        with caplog.at_level("INFO", logger="outbox-worker"):
            assert process_pending_outbox_events(test=True) == 1
        assert interrupted_worker.execute(
            "SELECT processed_at IS NOT NULL FROM outbox_events WHERE id = %s", second
        ).fetchone() == (True,)
        interrupted_worker.rollback()
    with caplog.at_level("INFO", logger="outbox-worker"):
        assert process_pending_outbox_events(test=True) == 1
        assert process_pending_outbox_events(test=True) == 0
    assert marker not in caplog.text


def test_worker_defers_student_lock_conflict_without_consuming_retry():
    chat_id = uuid4().int % (2**62) + 1
    with psycopg.connect(TEST_DB_URL) as conn:
        student_id = conn.execute(
            "INSERT INTO students (telegram_chat_id, telegram_user_id) VALUES (%s, %s) "
            "RETURNING id",
            (chat_id, chat_id),
        ).fetchone()[0]
        event_id = conn.execute(
            "INSERT INTO outbox_events (event_type, aggregate_type, aggregate_id, payload, "
            "student_id, retry_count) "
            "VALUES ('STUDY_PLAN_DELIVERY_REQUESTED', 'study_plan', %s, '{}', %s, 4) RETURNING id",
            (str(uuid4()), student_id),
        ).fetchone()[0]

    with psycopg.connect(TEST_DB_URL) as erasure:
        erasure.execute("SELECT id FROM students WHERE id = %s FOR UPDATE", (student_id,))
        assert process_pending_outbox_events(test=True) == 0
        assert erasure.execute(
            "SELECT retry_count, processed_at, next_attempt_at > NOW() "
            "FROM outbox_events WHERE id = %s",
            (event_id,),
        ).fetchone() == (4, None, True)
        erasure.execute("DELETE FROM outbox_events WHERE student_id = %s", (student_id,))
        erasure.rollback()
        erasure.execute(
            "UPDATE outbox_events SET next_attempt_at = NOW() WHERE id = %s", (event_id,)
        )

    assert process_pending_outbox_events(test=True) == 1
    with psycopg.connect(TEST_DB_URL) as conn:
        assert conn.execute(
            "SELECT retry_count, processed_at IS NOT NULL FROM outbox_events WHERE id = %s",
            (event_id,),
        ).fetchone() == (4, True)
        conn.execute("DELETE FROM outbox_events WHERE id = %s", (event_id,))
        conn.execute("DELETE FROM students WHERE id = %s", (student_id,))
