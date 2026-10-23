#!/usr/bin/env python3
"""
Migration Integrity and Reversibility Checker.
Verifies all migrations have up/down pairs and can run cleanly forward and backward.
"""

import logging
import os
import re
import sys
from pathlib import Path

from migrate import apply_migrations, get_migration_files, rollback_migrations

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrate-check")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def check_file_conventions() -> list[str]:
    errors = []
    if not MIGRATIONS_DIR.exists():
        return ["Migrations directory does not exist."]

    files = list(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        return ["No migration files found."]

    pattern = re.compile(r"^\d{4}_[a-z0-9_]+\.(up|down)\.sql$")
    for f in files:
        if not pattern.match(f.name):
            errors.append(f"Invalid migration file name format: {f.name}")

    try:
        pairs = get_migration_files()
        if not pairs:
            errors.append("No valid migration pairs discovered.")
    except Exception as exc:
        errors.append(f"Pairing validation error: {exc}")

    return errors


def test_reversibility(db_url: str) -> None:
    pairs = get_migration_files()
    total = len(pairs)
    logger.info("Testing forward and backward execution of %d migrations on %s ...", total, db_url)

    # 1. Rollback any existing to clean state
    rollback_migrations(db_url, steps=total)

    # 2. Apply all up
    applied = apply_migrations(db_url)
    logger.info("Step 1 (Forward): Applied %d migrations.", applied)

    # 3. Rollback all down
    rolled_back = rollback_migrations(db_url, steps=total)
    logger.info("Step 2 (Backward): Rolled back %d migrations.", rolled_back)

    # 4. Re-apply all up
    re_applied = apply_migrations(db_url)
    logger.info("Step 3 (Re-apply): Successfully applied %d migrations.", re_applied)


def main() -> int:
    errors = check_file_conventions()
    if errors:
        for err in errors:
            logger.error("Convention check failed: %s", err)
        return 1

    test_db_url = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql://kunkor:kunkor_dev_password@localhost:5435/kunkor_test",
    )

    try:
        test_reversibility(test_db_url)
        logger.info("SUCCESS: Migration integrity and reversibility checks passed.")
        return 0
    except Exception as exc:
        logger.error("Reversibility verification failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
