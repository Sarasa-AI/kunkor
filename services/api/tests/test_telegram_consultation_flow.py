"""Phase 3 End-to-End Integration Tests: Complete Telegram Consultation Flow.

Tests:
1. Multi-step conversational intake state machine via Telegram webhook.
2. Telegram identity creation and linking.
3. Proposer-Validator study plan generation and deterministic persistence.
4. Outbox delivery event enqueueing and worker processing.
5. Idempotent update deduplication (zero duplicate plans or deliveries).
6. Webhook security and authentication.
"""

import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import get_connection_string
from app.main import app
from app.workers.outbox_worker import process_pending_outbox_events

client = TestClient(app)


def test_telegram_webhook_secret_verification(monkeypatch):
    """Verify endpoint rejects requests with invalid secret token when configured."""
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "super_secret_token_123")

    # Unauthorized request without header
    res = client.post("/api/v1/telegram/webhook", json={"update_id": 99999})
    assert res.status_code == 403

    # Unauthorized request with wrong header
    res = client.post(
        "/api/v1/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong_token"},
        json={"update_id": 99999},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_complete_end_to_end_telegram_consultation_and_delivery():
    """
    Simulate full student consultation journey from /start to validated study plan.
    """
    chat_id = int(str(uuid.uuid4().int)[:9])  # Unique Telegram chat ID
    tg_user_id = chat_id + 1000

    # Step 1: /start greeting
    update_1 = {
        "update_id": chat_id * 10 + 1,
        "message": {
            "message_id": 101,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": tg_user_id, "first_name": "سارا", "username": "sara_pilot"},
            "text": "/start",
        },
    }
    res_1 = client.post("/api/v1/telegram/webhook", json=update_1)
    assert res_1.status_code == 200
    data_1 = res_1.json()
    assert data_1["status"] == "intake_in_progress"
    assert data_1["step"] == "stage"
    assert "به کنکور خوش آمدید" in data_1["response_text"]

    # Step 2: Student specifies stage and grade ("دوازدهم کنکور")
    update_2 = {
        "update_id": chat_id * 10 + 2,
        "message": {
            "message_id": 102,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": tg_user_id, "first_name": "سارا"},
            "text": "دوازدهم تجربی کنکور",
        },
    }
    res_2 = client.post("/api/v1/telegram/webhook", json=update_2)
    assert res_2.status_code == 200
    data_2 = res_2.json()
    assert data_2["status"] == "intake_in_progress"
    assert data_2["step"] == "track"
    assert "رشته تحصیلی شما چیست" in data_2["response_text"]

    # Step 3: Student specifies academic track ("تجربی")
    update_3 = {
        "update_id": chat_id * 10 + 3,
        "message": {
            "message_id": 103,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": tg_user_id, "first_name": "سارا"},
            "text": "تجربی",
        },
    }
    res_3 = client.post("/api/v1/telegram/webhook", json=update_3)
    assert res_3.status_code == 200
    data_3 = res_3.json()
    assert data_3["status"] == "intake_in_progress"
    assert data_3["step"] == "capacity"
    assert "ساعت یا دقیقه برای مطالعه" in data_3["response_text"]

    # Step 4: Student specifies daily study capacity ("۴ ساعت")
    update_4 = {
        "update_id": chat_id * 10 + 4,
        "message": {
            "message_id": 104,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": tg_user_id, "first_name": "سارا"},
            "text": "۴ ساعت",
        },
    }
    res_4 = client.post("/api/v1/telegram/webhook", json=update_4)
    assert res_4.status_code == 200
    data_4 = res_4.json()
    assert data_4["status"] == "intake_in_progress"
    assert data_4["step"] == "weak_subjects"
    assert "احساس ضعف" in data_4["response_text"]

    # Step 5: Student specifies weak subjects ("زیست و شیمی") -> triggers proposal & validation
    update_5 = {
        "update_id": chat_id * 10 + 5,
        "message": {
            "message_id": 105,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": tg_user_id, "first_name": "سارا"},
            "text": "زیست و شیمی",
        },
    }
    res_5 = client.post("/api/v1/telegram/webhook", json=update_5)
    assert res_5.status_code == 200
    data_5 = res_5.json()
    assert data_5["status"] == "plan_generated"
    assert data_5["step"] == "completed"
    assert data_5["revision_no"] == 1
    assert "برنامه مطالعه شخصی‌سازی شده شما با موفقیت آماده" in data_5["response_text"]

    student_id = data_5["student_id"]
    plan_id = data_5["plan_id"]

    # Database Verification: Assert PostgreSQL Persistence
    test_dsn = get_connection_string(test=True)
    with psycopg.connect(test_dsn) as conn:
        with conn.cursor() as cur:
            # 1. Student identity
            cur.execute(
                "SELECT id, telegram_chat_id, first_name FROM students WHERE id = %s;",
                (student_id,),
            )
            student_row = cur.fetchone()
            assert student_row is not None
            assert student_row[1] == chat_id
            assert student_row[2] == "سارا"

            # 2. Study plan
            cur.execute(
                """
                SELECT id, student_id, revision_no, stage_code, status
                FROM study_plans WHERE id = %s;
                """,
                (plan_id,),
            )
            plan_row = cur.fetchone()
            assert plan_row is not None
            assert str(plan_row[1]) == student_id
            assert plan_row[2] == 1
            assert plan_row[3] == "konkur"
            assert plan_row[4] == "active"

            # 3. Study plan items with denormalized student_id
            cur.execute(
                """
                SELECT count(*), sum(duration_minutes)
                FROM study_plan_items
                WHERE plan_id = %s AND student_id = %s;
                """,
                (plan_id, student_id),
            )
            item_stats = cur.fetchone()
            assert item_stats is not None
            item_count, total_minutes = item_stats
            assert item_count >= 1
            assert total_minutes <= 240  # Respects the 4-hour (240m) capacity!

            # 4. Outbox delivery event
            cur.execute(
                """
                SELECT id, event_type, aggregate_type, aggregate_id, processed_at
                FROM outbox_events WHERE aggregate_id = %s;
                """,
                (plan_id,),
            )
            outbox_row = cur.fetchone()
            assert outbox_row is not None
            assert outbox_row[1] == "STUDY_PLAN_DELIVERY_REQUESTED"
            assert outbox_row[2] == "study_plan"
            assert outbox_row[4] is None  # Not processed yet

    # 5. Outbox Worker Dispatching
    processed = process_pending_outbox_events(test=True)
    assert processed >= 1

    # Verify event is marked processed
    with psycopg.connect(test_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT processed_at FROM outbox_events WHERE aggregate_id = %s;",
                (plan_id,),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] is not None  # Processed timestamp stamped!


def test_telegram_update_deduplication_is_idempotent():
    """Verify duplicate update_id returns duplicate status without re-running consultation."""
    chat_id = int(str(uuid.uuid4().int)[:9])
    dup_update = {
        "update_id": chat_id * 10 + 99,
        "message": {
            "message_id": 999,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": chat_id, "first_name": "کاربر تکراری"},
            "text": "/start",
        },
    }

    # First delivery: processed
    res_1 = client.post("/api/v1/telegram/webhook", json=dup_update)
    assert res_1.status_code == 200
    assert res_1.json()["status"] == "intake_in_progress"

    # Second delivery with identical update_id: cleanly ignored
    res_2 = client.post("/api/v1/telegram/webhook", json=dup_update)
    assert res_2.status_code == 200
    assert res_2.json()["status"] == "duplicate"
