"""Phase 4 Integration Tests: Daily Progress and Plan Revision.

Verifies:
1. Multi-day progress reporting via Telegram webhook (/progress and Persian text).
2. Immutable daily progress logging in PostgreSQL (append-only trigger protection).
3. Revision loop: Plan Rev 1 -> Superseded, Plan Rev 2 -> Active (revision_no increment).
4. Prerequisite unlocking: completed units unlock downstream dependent units.
5. Missed unit prioritization in revised plans.
6. Outbox revision event delivery.
7. Historical progress query auditability.
"""

import uuid
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.db import get_connection_string
from app.main import app
from app.modules.consultation.repository import ConsultationRepository
from app.modules.consultation.service import ConsultationService
from app.workers.outbox_worker import process_pending_outbox_events

client = TestClient(app)


@pytest.fixture(autouse=True)
def synthetic_telegram(monkeypatch):
    from app.core.config import settings
    from app.workers import outbox_worker

    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "synthetic-webhook-secret")
    monkeypatch.setattr(settings, "NINEROUTER_ENABLED", False)
    monkeypatch.setattr(outbox_worker, "send_message", lambda chat_id, text: 12345)
    client.headers["X-Telegram-Bot-Api-Secret-Token"] = "synthetic-webhook-secret"
    yield
    client.headers.pop("X-Telegram-Bot-Api-Secret-Token", None)


def _complete_intake_for_student(chat_id: int) -> dict[str, Any]:
    """Helper to run a test student through the 5-step intake and produce Rev 1 plan."""
    tg_user_id = chat_id

    # 1. /start
    res1 = client.post(
        "/api/v1/telegram/webhook",
        json={
            "update_id": chat_id * 10 + 1,
            "message": {
                "message_id": 1,
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": tg_user_id, "first_name": "آرش"},
                "text": "/start",
            },
        },
    )
    assert res1.status_code == 200

    # 2. Stage
    res2 = client.post(
        "/api/v1/telegram/webhook",
        json={
            "update_id": chat_id * 10 + 2,
            "message": {
                "message_id": 2,
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": tg_user_id, "first_name": "آرش"},
                "text": "دوازدهم تجربی کنکور",
            },
        },
    )
    assert res2.status_code == 200

    # 3. Track
    res3 = client.post(
        "/api/v1/telegram/webhook",
        json={
            "update_id": chat_id * 10 + 3,
            "message": {
                "message_id": 3,
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": tg_user_id, "first_name": "آرش"},
                "text": "تجربی",
            },
        },
    )
    assert res3.status_code == 200

    # 4. Capacity
    res4 = client.post(
        "/api/v1/telegram/webhook",
        json={
            "update_id": chat_id * 10 + 4,
            "message": {
                "message_id": 4,
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": tg_user_id, "first_name": "آرش"},
                "text": "۴ ساعت",
            },
        },
    )
    assert res4.status_code == 200

    # 5. Weak subjects -> Rev 1 generated
    res5 = client.post(
        "/api/v1/telegram/webhook",
        json={
            "update_id": chat_id * 10 + 5,
            "message": {
                "message_id": 5,
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": tg_user_id, "first_name": "آرش"},
                "text": "زیست و شیمی",
            },
        },
    )
    assert res5.status_code == 200
    data = res5.json()
    assert data["step"] == "goal"
    for offset, text, next_step in [
        (101, "آزمون", "days"),
        (102, "شنبه،دوشنبه", "session"),
        (103, "25 دقیقه", "completed"),
    ]:
        response = client.post(
            "/api/v1/telegram/webhook",
            json={
                "update_id": chat_id * 10 + offset,
                "message": {
                    "chat": {"id": chat_id, "type": "private"},
                    "from": {"id": chat_id},
                    "text": text,
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["step"] == next_step
    assert data["status"] == "plan_generated"
    assert data["revision_no"] == 1
    return data


@pytest.mark.asyncio
async def test_multi_day_progress_reporting_and_revision_flow():
    """
    Test Day 1 intake -> Day 1 progress check-in -> Day 2 Plan Rev 2 generation.
    """
    chat_id = int(str(uuid.uuid4().int)[:9])
    tg_user_id = chat_id

    # Day 1: Student finishes intake and gets Plan Rev 1
    plan_rev1_data = _complete_intake_for_student(chat_id)
    student_id = plan_rev1_data["student_id"]
    rev1_plan_id = plan_rev1_data["plan_id"]

    test_dsn = get_connection_string(test=True)

    # Verify Rev 1 in DB
    with psycopg.connect(test_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, revision_no, status FROM study_plans WHERE id = %s;",
                (rev1_plan_id,),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[1] == 1
            assert row[2] == "active"

    # Step: Student sends bare /progress -> receives format guide with current active items
    res_prompt = client.post(
        "/api/v1/telegram/webhook",
        json={
            "update_id": chat_id * 10 + 6,
            "message": {
                "message_id": 6,
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": tg_user_id, "first_name": "آرش"},
                "text": "/progress",
            },
        },
    )
    assert res_prompt.status_code == 200
    prompt_data = res_prompt.json()
    assert prompt_data["status"] == "progress_prompt"
    assert "گزارش مطالعه خود را در قالب زیر ارسال کنید" in prompt_data["response_text"]

    # Day 1 Evening: Student reports progress
    # Completed konkur_bio_g12_ch1, missed konkur_chem_g12_ch1
    progress_update = {
        "update_id": chat_id * 10 + 7,
        "message": {
            "message_id": 7,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": tg_user_id, "first_name": "آرش"},
            "text": (
                "/progress completed=konkur_bio_g12_ch1 "
                "missed=konkur_chem_g12_ch1 duration=90 notes=good progress"
            ),
        },
    }
    res_prog = client.post("/api/v1/telegram/webhook", json=progress_update)
    assert res_prog.status_code == 200
    prog_data = res_prog.json()
    assert prog_data["status"] == "plan_revised"
    assert prog_data["revision_no"] == 2
    assert prog_data["completion_rate"] == 50.0
    assert "گزارش پیشرفت شما ثبت شد" in prog_data["response_text"]
    assert "ویرایش 2" in prog_data["response_text"]

    rev2_plan_id = prog_data["plan_id"]
    progress_id = prog_data["progress_id"]

    # Verify PostgreSQL Database State
    with psycopg.connect(test_dsn) as conn:
        with conn.cursor() as cur:
            # 1. Daily progress log persisted correctly
            cur.execute(
                """
                SELECT id, student_id, plan_id, revision_no, completed_units,
                       missed_units, duration_spent_minutes, completion_rate, student_notes
                FROM daily_progress_logs
                WHERE id = %s;
                """,
                (progress_id,),
            )
            prog_row = cur.fetchone()
            assert prog_row is not None
            assert str(prog_row[1]) == student_id
            assert str(prog_row[2]) == rev1_plan_id
            assert prog_row[3] == 1  # Logged against Rev 1
            assert "konkur_bio_g12_ch1" in prog_row[4]
            assert "konkur_chem_g12_ch1" in prog_row[5]
            assert prog_row[6] == 90
            assert float(prog_row[7]) == 50.0
            assert prog_row[8] == "good progress"

            # 2. Rev 1 is now superseded
            cur.execute(
                "SELECT status FROM study_plans WHERE id = %s;",
                (rev1_plan_id,),
            )
            assert cur.fetchone()[0] == "superseded"

            # 3. Rev 2 is active
            cur.execute(
                "SELECT status, revision_no FROM study_plans WHERE id = %s;",
                (rev2_plan_id,),
            )
            rev2_row = cur.fetchone()
            assert rev2_row[0] == "active"
            assert rev2_row[1] == 2

            # 4. Missed unit was prioritized in Rev 2
            cur.execute(
                """
                SELECT resource_version_id, item_order
                FROM study_plan_items
                WHERE plan_id = %s
                ORDER BY item_order ASC;
                """,
                (rev2_plan_id,),
            )
            items = cur.fetchall()
            item_ids = [it[0] for it in items]
            assert "konkur_chem_g12_ch1" in item_ids
            # Missed unit should be near top (first item)
            assert item_ids[0] == "konkur_chem_g12_ch1"

            # 5. Outbox events: Rev 1 delivery + Rev 2 revision delivery
            cur.execute(
                """
                SELECT event_type, processed_at, aggregate_id
                FROM outbox_events
                WHERE student_id = %s AND aggregate_type = 'study_plan'
                ORDER BY occurred_at ASC;
                """,
                (student_id,),
            )
            outbox_rows = cur.fetchall()
            assert len(outbox_rows) == 2
            assert outbox_rows[0][0] == "STUDY_PLAN_DELIVERY_REQUESTED"
            assert outbox_rows[1][0] == "STUDY_PLAN_REVISION_REQUESTED"
            assert outbox_rows[1][2] == rev2_plan_id

    # Verify Outbox Worker processes revision event without errors
    processed_count = process_pending_outbox_events(test=True)
    assert processed_count >= 2

    # Confirm outbox events have processed_at populated
    with psycopg.connect(test_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT processed_at FROM outbox_events WHERE student_id = %s;",
                (student_id,),
            )
            for row in cur.fetchall():
                assert row[0] is not None


@pytest.mark.asyncio
async def test_append_only_protection_on_daily_progress_logs():
    """
    Verify ADR-0005: daily_progress_logs table rejects UPDATE and DELETE mutations via trigger.
    """
    chat_id = int(str(uuid.uuid4().int)[:9])
    plan_data = _complete_intake_for_student(chat_id)
    student_id = plan_data["student_id"]
    plan_id = plan_data["plan_id"]

    test_dsn = get_connection_string(test=True)
    with psycopg.connect(test_dsn) as conn:
        # 1. Insert progress log via repository
        log_id = ConsultationRepository.record_daily_progress(
            conn=conn,
            student_id=uuid.UUID(student_id),
            plan_id=uuid.UUID(plan_id),
            revision_no=1,
            completed_units=["konkur_bio_g12_ch1"],
            missed_units=[],
            duration_spent_minutes=60,
            student_notes="immutable log",
        )
        conn.commit()

        # 2. Attempt UPDATE -> must raise psycopg.Error
        with conn.cursor() as cur:
            with pytest.raises(psycopg.Error) as exc_info:
                cur.execute(
                    "UPDATE daily_progress_logs SET student_notes = 'tampered' WHERE id = %s;",
                    (log_id,),
                )
            assert "append-only" in str(exc_info.value)
        conn.rollback()

        # 3. Attempt DELETE -> must raise psycopg.Error
        with conn.cursor() as cur:
            with pytest.raises(psycopg.Error) as exc_info:
                cur.execute(
                    "DELETE FROM daily_progress_logs WHERE id = %s;",
                    (log_id,),
                )
            assert "append-only" in str(exc_info.value)
        conn.rollback()


@pytest.mark.asyncio
async def test_persian_progress_report_parsing_and_revision():
    """
    Verify Persian text reporting:
    /progress تکمیل: bio | نرسیدم: chem | زمان: 120 دقیقه | یادداشت: عالی بود
    """
    chat_id = int(str(uuid.uuid4().int)[:9])
    tg_user_id = chat_id

    plan_rev1_data = _complete_intake_for_student(chat_id)
    student_id = plan_rev1_data["student_id"]

    persian_progress_update = {
        "update_id": chat_id * 10 + 8,
        "message": {
            "message_id": 8,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": tg_user_id, "first_name": "آرش"},
            "text": (
                "/progress تکمیل: konkur_bio_g12_ch1 | "
                "نرسیدم: konkur_chem_g12_ch1 | زمان: 120 دقیقه | یادداشت: عالی بود"
            ),
        },
    }
    res = client.post("/api/v1/telegram/webhook", json=persian_progress_update)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "plan_revised"
    assert data["revision_no"] == 2
    assert data["completion_rate"] == 50.0

    # Historical query verification
    test_dsn = get_connection_string(test=True)
    with psycopg.connect(test_dsn) as conn:
        history = ConsultationRepository.get_student_historical_progress(
            conn, uuid.UUID(student_id)
        )
        assert len(history) == 1
        assert history[0]["revision_no"] == 1
        assert history[0]["duration_spent_minutes"] == 120
        assert history[0]["student_notes"] == "عالی بود"


@pytest.mark.asyncio
async def test_progress_without_active_plan_rejected():
    """
    Verify that reporting progress without having an active plan returns guidance to /start.
    """
    chat_id = int(str(uuid.uuid4().int)[:9])
    tg_user_id = chat_id

    res = client.post(
        "/api/v1/telegram/webhook",
        json={
            "update_id": chat_id * 10 + 9,
            "message": {
                "message_id": 9,
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": tg_user_id, "first_name": "ناشناس"},
                "text": "/progress completed=konkur_bio_g12_ch1",
            },
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "no_active_plan"
    assert "ابتدا با ارسال /start" in data["response_text"]


@pytest.mark.asyncio
async def test_direct_service_method_and_prerequisite_unlocking():
    """
    Verify calling handle_progress_and_revision directly, and check that completed
    prerequisite (konkur_bio_g12_ch1) unlocks downstream unit (konkur_bio_g12_ch2).
    """
    chat_id = int(str(uuid.uuid4().int)[:9])
    plan_data = _complete_intake_for_student(chat_id)
    student_id = uuid.UUID(plan_data["student_id"])

    service = ConsultationService()
    test_dsn = get_connection_string(test=True)

    with psycopg.connect(test_dsn) as conn:
        # Day 1: Student completes chapter 1
        result_rev2 = await service.handle_progress_and_revision(
            conn=conn,
            student_id=student_id,
            completed_units=["konkur_bio_g12_ch1"],
            missed_units=[],
            duration_spent_minutes=60,
            student_notes="Finished ch1, ready for ch2",
        )
        assert result_rev2["status"] == "plan_revised"
        assert result_rev2["revision_no"] == 2
        assert result_rev2["completion_rate"] == 100.0

        # Verify completed unit list in repository
        completed_units = ConsultationRepository.get_completed_unit_ids_for_student(
            conn, student_id
        )
        assert "konkur_bio_g12_ch1" in completed_units

        # Day 2: Student completes chapter 2 (which had chapter 1 as prerequisite)
        result_rev3 = await service.handle_progress_and_revision(
            conn=conn,
            student_id=student_id,
            completed_units=["konkur_bio_g12_ch2"],
            missed_units=[],
            duration_spent_minutes=60,
            student_notes="Finished ch2 successfully",
        )
        assert result_rev3["status"] == "plan_revised"
        assert result_rev3["revision_no"] == 3

        # Verify history has 2 entries in chronological order
        history = ConsultationRepository.get_student_historical_progress(conn, student_id)
        assert len(history) == 2
        assert history[0]["revision_no"] == 1
        assert history[1]["revision_no"] == 2
        assert history[0]["completed_units"] == ["konkur_bio_g12_ch1"]
        assert history[1]["completed_units"] == ["konkur_bio_g12_ch2"]


@pytest.mark.asyncio
async def test_progress_rejects_unknown_duplicate_and_overlapping_units_before_history():
    from fastapi import HTTPException

    chat_id = int(str(uuid.uuid4().int)[:9])
    generated = _complete_intake_for_student(chat_id)
    student_id = uuid.UUID(generated["student_id"])
    service = ConsultationService()
    with psycopg.connect(get_connection_string(test=True)) as conn:
        plan = service.repo.get_active_study_plan(conn, student_id)
        unit = plan["items"][0]["resource_version_id"]
        for completed, missed in [(["unknown-resource"], []), ([unit, unit], []), ([unit], [unit])]:
            with pytest.raises(HTTPException) as exc:
                await service.handle_progress_and_revision(conn, student_id, completed, missed, 30)
            assert exc.value.status_code == 422
        assert service.repo.get_student_historical_progress(conn, student_id) == []
        assert service.repo.get_active_study_plan(conn, student_id)["id"] == plan["id"]


def test_restart_keeps_one_active_intake_and_durable_prompts():
    chat_id = int(str(uuid.uuid4().int)[:9])
    for offset in (1, 2):
        result = client.post(
            "/api/v1/telegram/webhook",
            json={
                "update_id": chat_id * 10 + offset,
                "message": {
                    "chat": {"id": chat_id, "type": "private"},
                    "from": {"id": chat_id},
                    "text": "/start",
                },
            },
        )
        assert result.status_code == 200
    student_id = result.json()["student_id"]
    with psycopg.connect(get_connection_string(test=True)) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM intake_sessions WHERE student_id = %s AND NOT is_completed",
                (student_id,),
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM outbox_events WHERE student_id = %s "
                "AND event_type = 'TELEGRAM_MESSAGE_REQUESTED'",
                (student_id,),
            ).fetchone()[0]
            == 2
        )


def test_telegram_rejects_group_or_mismatched_sender():
    chat_id = int(str(uuid.uuid4().int)[:9])
    for chat_type, sender in [("group", chat_id), ("private", chat_id + 1)]:
        result = client.post(
            "/api/v1/telegram/webhook",
            json={
                "update_id": chat_id,
                "message": {
                    "chat": {"id": chat_id, "type": chat_type},
                    "from": {"id": sender},
                    "text": "/start",
                },
            },
        )
        assert result.json()["reason"] == "private_identity_required"
    with psycopg.connect(get_connection_string(test=True)) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM students WHERE telegram_chat_id = %s", (chat_id,)
            ).fetchone()[0]
            == 0
        )


def test_invalid_intake_clarifies_twice_then_cancels():
    chat_id = int(str(uuid.uuid4().int)[:9])
    statuses = []
    for offset, text in enumerate(["/start", "invalid", "invalid", "invalid"], 1):
        result = client.post(
            "/api/v1/telegram/webhook",
            json={
                "update_id": chat_id * 10 + offset,
                "message": {
                    "chat": {"id": chat_id, "type": "private"},
                    "from": {"id": chat_id},
                    "text": text,
                },
            },
        )
        statuses.append(result.json()["status"])
    assert statuses == [
        "intake_in_progress",
        "clarification_required",
        "clarification_required",
        "intake_cancelled",
    ]


@pytest.mark.asyncio
async def test_invalid_proposals_repair_at_most_twice_then_validate_fallback():
    from app.schemas.planning import IntakeSlots

    class InvalidProvider:
        calls = 0

        async def propose_study_plan(self, *args, **kwargs):
            self.calls += 1
            return {"items": []}

    provider = InvalidProvider()
    service = ConsultationService(ai_provider=provider)
    intake = IntakeSlots(
        stage_code="konkur",
        grade="G12",
        track="experimental",
        daily_study_capacity_minutes=180,
        weak_subjects=["biology"],
    )
    from app.engines.catalog import get_resources_for_stage

    plan, proposal = await service.validate_or_repair(
        {"items": []}, intake, get_resources_for_stage("konkur"), uuid.uuid4(), 1
    )
    assert provider.calls == 2
    assert plan.items
    assert proposal["source"] == "deterministic_fallback_planner"


@pytest.mark.asyncio
async def test_completed_curriculum_stops_without_repeating_completed_units():
    chat_id = int(str(uuid.uuid4().int)[:9])
    generated = _complete_intake_for_student(chat_id)
    student_id = uuid.UUID(generated["student_id"])
    service = ConsultationService()
    seen = set()
    with psycopg.connect(get_connection_string(test=True)) as conn:
        for _ in range(10):
            plan = service.repo.get_active_study_plan(conn, student_id)
            units = [item["resource_version_id"] for item in plan["items"]]
            assert not seen.intersection(units)
            seen.update(units)
            result = await service.handle_progress_and_revision(
                conn, student_id, units, [], 180, telegram_chat_id=chat_id
            )
            if result["status"] == "curriculum_completed":
                break
        else:
            pytest.fail("Curriculum failed to finish within catalog bound")
        assert service.repo.get_active_study_plan(conn, student_id) is None
        assert len(service.repo.get_student_historical_progress(conn, student_id)) >= 1


def test_structured_constraints_validate_and_split_without_inventing_study_days():
    from pydantic import ValidationError

    from app.schemas.planning import IntakeSlots, split_study_sessions

    base = dict(
        stage_code="konkur", grade="G12", track="experimental", daily_study_capacity_minutes=120
    )
    for invalid in [
        dict(study_days=[]),
        dict(study_days=[0, 0]),
        dict(study_days=[7]),
        dict(study_days=[True]),
        dict(study_days=[1.0]),
        dict(study_days=["1"]),
        dict(max_session_minutes=0),
        dict(max_session_minutes=121),
        dict(goal_code="student name"),
    ]:
        with pytest.raises(ValidationError):
            IntakeSlots(**base, **invalid)
    intake = IntakeSlots(**base, study_days=[0, 5], max_session_minutes=25, goal_code="review")
    items = [{"resource_version_id": "synthetic-unit", "duration_minutes": 60}]
    sessions = split_study_sessions(items, intake.max_session_minutes)
    assert [s["duration_minutes"] for s in sessions] == [25, 25, 10]
    assert intake.study_days == [0, 5]
    assert sum(s["duration_minutes"] for s in sessions) == 60


@pytest.mark.parametrize(
    "answers",
    [
        ["/start", "هفتم", "90 دقیقه", "ریاضی", "مدرسه", "شنبه", "20 دقیقه"],
        ["/start", "دوازدهم", "تجربی", "15 دقیقه", "زیست", "آزمون", "شنبه", "10 دقیقه"],
    ],
)
def test_unsupported_grade_or_small_capacity_preserves_intake_without_plan(answers):
    chat_id = int(str(uuid.uuid4().int)[:9])
    for offset, text in enumerate(answers, 1):
        response = client.post(
            "/api/v1/telegram/webhook",
            json={
                "update_id": chat_id * 100 + offset,
                "message": {
                    "chat": {"id": chat_id, "type": "private"},
                    "from": {"id": chat_id},
                    "text": text,
                },
            },
        )
        assert response.status_code == 200
    result = response.json()
    assert result["status"] == "resources_unavailable"
    with psycopg.connect(get_connection_string(test=True)) as conn:
        student_id = uuid.UUID(result["student_id"])
        assert ConsultationRepository.get_active_study_plan(conn, student_id) is None
        session = ConsultationRepository.get_latest_intake_session(conn, student_id)
        assert session["slots"]["goal_code"] in ("school", "exam")
        assert session["slots"]["max_session_minutes"] in (10, 20)
        assert (
            conn.execute(
                "SELECT count(*) FROM outbox_events WHERE student_id = %s "
                "AND aggregate_type = 'study_plan'",
                (student_id,),
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    "update",
    [
        {"update_id": 1, "message": []},
        {"update_id": True, "message": {}},
        {"update_id": 1, "message": {"chat": [], "from": {}, "text": "x"}},
        {"update_id": 1, "message": {"chat": {}, "from": {}, "text": []}},
    ],
)
def test_malformed_telegram_updates_are_ignored(update):
    response = client.post("/api/v1/telegram/webhook", json=update)
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
