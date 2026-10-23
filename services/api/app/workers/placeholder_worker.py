import logging

from app.workers.outbox_worker import run_worker

logger = logging.getLogger("worker")


def run() -> None:
    logger.info("Kunkor background worker delegating to outbox worker loop.")
    run_worker(poll_interval=5.0)


if __name__ == "__main__":
    run()
