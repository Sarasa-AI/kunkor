import argparse
import json
import logging
import time

from app.core.db import get_db_connection
from app.workers.telegram import DeliveryDisabled, send_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("outbox-worker")


def publish_to_queue(event: dict) -> int | None:
    if event.get("event_type") in {
        "TELEGRAM_MESSAGE_REQUESTED",
        "STUDY_PLAN_DELIVERY_REQUESTED",
        "STUDY_PLAN_REVISION_REQUESTED",
        "STUDY_PLAN_REVISION_DELIVERED",
    }:
        payload = event.get("payload", {})
        return send_message(payload.get("telegram_chat_id"), payload.get("message_text"))
    logger.info(
        "Dispatched event [%s] for aggregate %s", event["event_type"], event["aggregate_id"]
    )
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
                            message_id = publish_to_queue(event_data)
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
                    except Exception as exc:
                        logger.error(
                            "Failed to publish event %s (%s)", row["id"], type(exc).__name__
                        )
                        new_retries = row["retry_count"] + 1
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
                                SET retry_count = retry_count + 1,
                                    next_attempt_at = NOW() + (%s * INTERVAL '1 second'),
                                    last_error = %s
                                WHERE id = %s;
                                """,
                                (min(300, 2**new_retries), type(exc).__name__, row["id"]),
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
            logger.error("Worker error during polling cycle: %s", exc)
            if once:
                raise
            time.sleep(poll_interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kunkor Outbox Event Queue Worker")
    parser.add_argument("--once", action="store_true", help="Run one processing cycle and exit")
    parser.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds")
    args = parser.parse_args()

    run_worker(poll_interval=args.interval, once=args.once)
