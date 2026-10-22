import logging
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("worker")


def run() -> None:
    logger.info("Kunkor background queue worker initialized (idle loop).")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        logger.info("Worker stopped.")


if __name__ == "__main__":
    run()
