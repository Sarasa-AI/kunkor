"""Delayed delivery never presents archived, revoked or unreviewed metadata."""

from contextlib import contextmanager
from uuid import uuid4

import pytest

from app.core.db import get_db_connection
from app.modules.consultation.repository import ConsultationRepository
from app.modules.content.management import (
    BookFields,
    OwnerContentRepository,
    UnitCreate,
    UnitFields,
)
from app.schemas.planning import IntakeSlots
from app.workers import outbox_worker


@pytest.fixture
def delivery_catalog(monkeypatch):
    with get_db_connection(test=True) as conn:
        with conn.transaction(force_rollback=True):
            owner = OwnerContentRepository()
            book = owner.create_book(
                conn,
                BookFields(
                    title="Synthetic Delivery Book", grades=[10], subject_code="mathematics"
                ),
            )
            unit = owner.create_unit(
                conn,
                UnitCreate(
                    book_id=book["id"],
                    kind="chapter",
                    title="Synthetic Reviewed Chapter",
                    estimated_duration_minutes=30,
                    provenance_source="owner_entered",
                    provenance_reference="synthetic-testing",
                    license_id="synthetic-test-license",
                    rights_statement="Synthetic fixtures only",
                    license_active=True,
                ),
            )
            owner.transition(conn, unit["id"], "approve", book=False)
            owner.transition(conn, unit["id"], "publish", book=False)
            chat_id = 4_000_000_000 + uuid4().int % 1_000_000_000
            student = ConsultationRepository.get_or_create_student(conn, chat_id, chat_id)
            plan_id = uuid4()
            intake = IntakeSlots(
                stage_code="upper_secondary",
                grade="G10",
                track="experimental",
                daily_study_capacity_minutes=60,
            )
            ConsultationRepository.save_study_plan(
                conn,
                plan_id,
                student,
                1,
                intake.stage_code,
                "0.5.0",
                "1.0.0",
                {},
                [
                    {
                        "resource_version_id": str(unit["id"]),
                        "duration_minutes": 30,
                        "stage_code": intake.stage_code,
                        "prerequisites": [],
                    }
                ],
                intake_slots=intake.model_dump(),
            )
            event_id = ConsultationRepository.enqueue_outbox_event(
                conn,
                student,
                "STUDY_PLAN_DELIVERY_REQUESTED",
                "study_plan",
                str(plan_id),
                {
                    "student_id": str(student),
                    "plan_id": str(plan_id),
                    "revision_no": 1,
                    "telegram_chat_id": chat_id,
                    "message_text": "CACHED UNVERIFIED OLD TITLE",
                },
            )
            event = conn.execute("SELECT * FROM outbox_events WHERE id=%s", (event_id,)).fetchone()
            sends = []

            def send(chat_id, text):
                sends.append((chat_id, text))
                return 321

            monkeypatch.setattr(outbox_worker, "send_message", send)

            @contextmanager
            def shared_connection(*args, **kwargs):
                yield conn

            monkeypatch.setattr(outbox_worker, "get_db_connection", shared_connection)
            yield conn, owner, book, unit, event, sends


def test_fresh_delayed_plan_renders_current_approved_metadata(delivery_catalog):
    conn, _, _, _, event, sends = delivery_catalog
    assert outbox_worker.publish_to_queue(dict(event), conn=conn) == 321
    assert len(sends) == 1
    assert "Synthetic Reviewed Chapter" in sends[0][1]
    assert "CACHED UNVERIFIED OLD TITLE" not in sends[0][1]


@pytest.mark.parametrize("change", ["archive", "revoke", "draft", "book_archive"])
def test_delayed_stale_content_is_suppressed_and_marked_processed(delivery_catalog, change):
    conn, owner, book, unit, event, sends = delivery_catalog
    if change == "archive":
        owner.transition(conn, unit["id"], "archive", book=False)
    elif change == "book_archive":
        owner.transition(conn, book["id"], "archive", book=True)
    elif change == "revoke":
        owner.edit(conn, unit["id"], UnitFields(license_active=False), book=False)
    else:
        owner.edit(conn, unit["id"], UnitFields(title="Synthetic Unreviewed Edit"), book=False)
    assert outbox_worker.process_pending_outbox_events(limit=1000, test=True) >= 1
    assert not any(chat_id == event["payload"]["telegram_chat_id"] for chat_id, _ in sends)
    record = conn.execute(
        "SELECT processed_at, retry_count FROM outbox_events WHERE id=%s", (event["id"],)
    ).fetchone()
    assert record["processed_at"] is not None
    assert record["retry_count"] == 0


def test_shared_content_lock_blocks_owner_mutation_until_delivery_finishes(delivery_catalog):
    conn, _, _, _, event, _ = delivery_catalog

    def send_with_lock_check(chat_id, text):
        lock = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid() "
            "AND locktype='advisory' AND mode='ShareLock' AND granted) AS held"
        ).fetchone()
        assert lock["held"]
        return 654

    from unittest.mock import patch

    with patch.object(outbox_worker, "send_message", send_with_lock_check):
        assert outbox_worker.publish_to_queue(dict(event), conn=conn) == 654


def test_wrong_student_or_chat_cannot_receive_another_plan(delivery_catalog):
    conn, _, _, _, event, sends = delivery_catalog
    wrong_owner = dict(event)
    wrong_owner["student_id"] = uuid4()
    assert outbox_worker.publish_to_queue(wrong_owner, conn=conn) is None
    wrong_chat = {**dict(event), "payload": {**event["payload"], "telegram_chat_id": 77}}
    assert outbox_worker.publish_to_queue(wrong_chat, conn=conn) is None
    assert sends == []


def test_superseded_plan_delivery_is_terminal_and_unrelated_messages_still_work(delivery_catalog):
    conn, _, _, _, event, sends = delivery_catalog
    ConsultationRepository.supersede_plan(
        conn, event["aggregate_id"], student_id=event["student_id"]
    )
    assert outbox_worker.publish_to_queue(dict(event), conn=conn) is None
    assert sends == []
    assert (
        outbox_worker.publish_to_queue(
            {
                "event_type": "TELEGRAM_MESSAGE_REQUESTED",
                "payload": {"telegram_chat_id": 77, "message_text": "Synthetic welcome"},
            }
        )
        == 321
    )
    assert sends == [(77, "Synthetic welcome")]


def test_republished_content_does_not_reuse_older_cached_plan(delivery_catalog):
    conn, owner, _, unit, event, sends = delivery_catalog
    owner.edit(conn, unit["id"], UnitFields(title="Synthetic Newly Reviewed Title"), book=False)
    owner.transition(conn, unit["id"], "approve", book=False)
    owner.transition(conn, unit["id"], "publish", book=False)
    assert outbox_worker.publish_to_queue(dict(event), conn=conn) is None
    assert sends == []


@pytest.mark.parametrize("archived", [False, True])
def test_generic_educational_guidance_uses_current_catalog_gate(delivery_catalog, archived):
    from psycopg.types.json import Jsonb

    conn, owner, _, unit, event, sends = delivery_catalog
    payload = {**event["payload"], "requires_trusted_catalog": True}
    conn.execute(
        "UPDATE outbox_events SET event_type='TELEGRAM_MESSAGE_REQUESTED', payload=%s WHERE id=%s",
        (Jsonb(payload), event["id"]),
    )
    if archived:
        owner.transition(conn, unit["id"], "archive", book=False)
    assert outbox_worker.process_pending_outbox_events(limit=1000, test=True) >= 1
    related = [text for chat_id, text in sends if chat_id == payload["telegram_chat_id"]]
    if archived:
        assert related == []
    else:
        assert len(related) == 1
        assert "Synthetic Reviewed Chapter" in related[0]
        assert "CACHED UNVERIFIED OLD TITLE" not in related[0]
    state = conn.execute(
        "SELECT processed_at, retry_count FROM outbox_events WHERE id=%s", (event["id"],)
    ).fetchone()
    assert state["processed_at"] is not None
    assert state["retry_count"] == 0
