import argparse
import json
import logging
import time

from app.core.db import get_db_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("outbox-worker")


def publish_to_queue(event: dict) -> None:
    # Stub queue dispatcher: In production/staging dispatches to message broker
    logger.info(
        "Dispatched event [%s] for aggregate %s:%s (student: %s)",
        event["event_type"],
        event["aggregate_type"],
        event["aggregate_id"],
        event.get("student_id"),
    )


def process_pending_outbox_events(limit: int = 50, test: bool = False) -> int:
    with get_db_connection(test=test) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, student_id, event_type, aggregate_type, aggregate_id, payload
                    FROM outbox_events
                    WHERE processed_at IS NULL
                    ORDER BY occurred_at ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED;
                    """,
                    (limit,),
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

                    publish_to_queue(event_data)

                    cur.execute(
                        """
                        UPDATE outbox_events
                        SET processed_at = NOW()
                        WHERE id = %s;
                        """,
                        (row["id"],),
                    )
                    processed_count += 1

                return processed_count


def run_worker(poll_interval: float = 2.0, once: bool = False) -> None:
    logger.info("Outbox worker started (poll_interval=%.1fs, once=%s)", poll_interval, once)
    try:
        while True:
            count = process_pending_outbox_events()
            if count > 0:
                logger.info("Processed %d outbox event(s).", count)
            if once:
                break
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        logger.info("Outbox worker stopping.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kunkor Outbox Event Queue Worker")
    parser.add_argument("--once", action="store_true", help="Run one processing cycle and exit")
    parser.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds")
    args = parser.parse_args()

    run_worker(poll_interval=args.interval, once=args.once)
