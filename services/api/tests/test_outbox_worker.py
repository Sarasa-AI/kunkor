import os

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
