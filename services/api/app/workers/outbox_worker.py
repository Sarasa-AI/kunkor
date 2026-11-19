import argparse
import json
import logging
import time
from typing import Any
from uuid import UUID

import psycopg

from app.core.db import get_db_connection
from app.engines.catalog import catalog_from_resources, get_resources_for_stage
from app.engines.validator import DeterministicValidationError, DeterministicValidator
from app.modules.consultation.repository import ConsultationRepository
from app.modules.consultation.service import ConsultationService, trusted_plan_view
from app.modules.content.service import ContentService
from app.schemas.planning import IntakeSlots, StudyPlan, StudyPlanItem
from app.workers.telegram import DeliveryDisabled, PermanentDeliveryError, send_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("outbox-worker")


EDUCATIONAL_DELIVERY_EVENTS = {
    "STUDY_PLAN_DELIVERY_REQUESTED",
    "STUDY_PLAN_REVISION_REQUESTED",
    "STUDY_PLAN_REVISION_DELIVERED",
}


def _deliver_current_plan(event: dict, conn: psycopg.Connection[Any]) -> int | None:
    """Suppress stale deliveries and render current approved metadata under locks."""
    payload = event.get("payload", {})
    if not isinstance(payload, dict):
        return None
    try:
        student_id = UUID(str(event.get("student_id")))
        plan_id = UUID(str(payload.get("plan_id", event.get("aggregate_id"))))
    except (ValueError, TypeError):
        return None
    # A payload cannot change the event's owner or target an unrelated chat.
    student = conn.execute(
        "SELECT telegram_chat_id FROM students WHERE id = %s FOR SHARE NOWAIT", (student_id,)
    ).fetchone()
    if not student or payload.get("telegram_chat_id") != student["telegram_chat_id"]:
        return None
    plan_row = conn.execute(
        "SELECT * FROM study_plans WHERE id = %s AND student_id = %s FOR SHARE",
        (plan_id, student_id),
    ).fetchone()
    if not plan_row or plan_row["status"] != "active":
        return None
    if payload.get("revision_no") not in (None, plan_row["revision_no"]):
        return None
    items = conn.execute(
        "SELECT * FROM study_plan_items WHERE plan_id = %s AND student_id = %s ORDER BY item_order",
        (plan_id, student_id),
    ).fetchall()
    if not items:
        return None
    resource_ids = [item["resource_version_id"] for item in items]
    try:
        # Legacy identifiers absent from the owner catalog cannot be trusted.
        for resource_id in resource_ids:
            UUID(resource_id)
        ContentService().lock_agent_resources(conn, resource_ids)
        if trusted_plan_view(conn, {**plan_row, "items": items}) is None:
            return None
        intake = IntakeSlots.model_validate(plan_row["intake_slots"])
        resources = get_resources_for_stage(
            plan_row["stage_code"], conn, grade=intake.grade, track=intake.track
        )
        plan = StudyPlan(
            plan_id=plan_id,
            student_id=student_id,
            revision_no=plan_row["revision_no"],
            engine_version=plan_row["engine_version"],
            rule_set_version=plan_row["rule_set_version"],
            status="active",
            created_at=plan_row["created_at"],
            items=[
                StudyPlanItem(
                    item_id=str(item["id"]),
                    resource_version_id=item["resource_version_id"],
                    stage_code=item["stage_code"],
                    duration_minutes=item["duration_minutes"],
                    prerequisites=item["prerequisites"],
                )
                for item in items
            ],
        )
        DeterministicValidator.validate_study_plan(
            plan,
            intake,
            catalog_from_resources(resources),
            completed_unit_ids=ConsultationRepository.get_completed_unit_ids_for_student(
                conn, student_id
            ),
        )
    except (ValueError, TypeError, DeterministicValidationError):
        return None
    # Cached text may contain a title from an older content revision. Render only
    # the latest approved titles; unknown or changed scheduling metadata fails above.
    text = ConsultationService()._format_study_plan_message(plan, intake, resources)
    return send_message(student["telegram_chat_id"], text)


def publish_to_queue(event: dict, conn: psycopg.Connection[Any] | None = None) -> int | None:
    payload = event.get("payload", {})
    educational = event.get("event_type") in EDUCATIONAL_DELIVERY_EVENTS or (
        event.get("event_type") == "TELEGRAM_MESSAGE_REQUESTED"
        and isinstance(payload, dict)
        and payload.get("requires_trusted_catalog") is True
    )
    if educational:
        if conn is not None:
            # Release read-side locks after delivery instead of holding them for the batch.
            with conn.transaction(force_rollback=True):
                conn.execute("SET LOCAL lock_timeout = '1s'")
                return _deliver_current_plan(event, conn)
        with get_db_connection() as delivery_conn:
            with delivery_conn.transaction():
                return _deliver_current_plan(event, delivery_conn)
    if event.get("event_type") == "TELEGRAM_MESSAGE_REQUESTED":
        if not isinstance(payload, dict):
            raise PermanentDeliveryError("Invalid outbox payload")
        return send_message(payload.get("telegram_chat_id"), payload.get("message_text"))
    return None


MAX_RETRIES = 5


def process_pending_outbox_events(limit: int = 50, test: bool = False) -> int:
    with get_db_connection(test=test) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, student_id, event_type, aggregate_type, aggregate_id,
                           payload, retry_count
                    FROM outbox_events
                    WHERE processed_at IS NULL AND retry_count < %s AND next_attempt_at <= NOW()
                    ORDER BY occurred_at ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED;
                    """,
                    (MAX_RETRIES, limit),
                )
                rows = cur.fetchall()
                if not rows:
                    return 0

                processed_count = 0
                for row in rows:
                    event_data = dict(row)
                    if isinstance(event_data.get("payload"), str):
                        try:
                            event_data["payload"] = json.loads(event_data["payload"])
                        except Exception:
                            pass

                    try:
                        with conn.transaction():
                            # Keep ownership and delivery checks in the row-locking transaction.
                            message_id = publish_to_queue(event_data, conn)
                            cur.execute(
                                """
                                UPDATE outbox_events
                                SET processed_at = NOW(), telegram_message_id = %s,
                                    last_error = NULL
                                WHERE id = %s;
                                """,
                                (message_id, row["id"]),
                            )
                            processed_count += 1
                    except DeliveryDisabled:
                        continue
                    except psycopg.errors.LockNotAvailable:
                        cur.execute(
                            "UPDATE outbox_events "
                            "SET next_attempt_at = NOW() + INTERVAL '2 seconds' WHERE id = %s",
                            (row["id"],),
                        )
                    except Exception as exc:
                        logger.error(
                            "Failed to publish event %s (%s)", row["id"], type(exc).__name__
                        )
                        new_retries = (
                            MAX_RETRIES
                            if isinstance(exc, PermanentDeliveryError)
                            else row["retry_count"] + 1
                        )
                        if new_retries >= MAX_RETRIES:
                            logger.critical(
                                "Event %s reached max retries (%d); dead-lettered.",
                                row["id"],
                                MAX_RETRIES,
                            )
                        with conn.transaction():
                            cur.execute(
                                """
                                UPDATE outbox_events
                                SET retry_count = %s,
                                    next_attempt_at = NOW() + (%s * INTERVAL '1 second'),
                                    last_error = %s
                                WHERE id = %s;
                                """,
                                (new_retries, min(300, 2**new_retries),
                                 type(exc).__name__, row["id"]),
                            )

                return processed_count


def run_worker(poll_interval: float = 2.0, once: bool = False) -> None:
    logger.info("Outbox worker started (poll_interval=%.1fs, once=%s)", poll_interval, once)
    while True:
        try:
            count = process_pending_outbox_events()
            if count > 0:
                logger.info("Processed %d outbox event(s).", count)
            if once:
                break
            time.sleep(poll_interval)
        except KeyboardInterrupt:
            logger.info("Outbox worker stopping.")
            break
        except Exception as exc:
            logger.error("Worker error during polling cycle: %s", type(exc).__name__)
            if once:
                raise
            time.sleep(poll_interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kunkor Outbox Event Queue Worker")
    parser.add_argument("--once", action="store_true", help="Run one processing cycle and exit")
    parser.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds")
    args = parser.parse_args()

    run_worker(poll_interval=args.interval, once=args.once)
