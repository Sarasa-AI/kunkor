"""Read-only aggregate outbox check. Exit 1 for dead letters or stale pending work."""

import argparse
import json

from app.core.db import get_db_connection
from app.modules.operations.repository import OperationsRepository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-age-seconds", type=int, required=True)
    args = parser.parse_args()
    if args.max_age_seconds < 1:
        parser.error("--max-age-seconds must be positive")
    with get_db_connection() as conn:
        health = OperationsRepository.outbox_health(conn)
    print(json.dumps(health))
    return int(health["dead_letter"] > 0 or health["oldest_pending_seconds"] > args.max_age_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
