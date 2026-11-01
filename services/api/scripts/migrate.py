#!/usr/bin/env python3
"""
Database Migration Runner for Kunkor Platform.
Manages forward and rollback migrations deterministically.
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import psycopg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrate")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def get_db_url(custom_url: str | None = None) -> str:
    if custom_url:
        return custom_url
    url = os.getenv("DATABASE_URL")
    env = os.getenv("ENVIRONMENT", "development").lower()
    if not url:
        if env == "production":
            raise ValueError("DATABASE_URL environment variable is required in production.")
        return "postgresql://kunkor:kunkor_dev_password@localhost:5435/kunkor_dev"
    if env == "production" and "kunkor_dev_password" in url:
        raise ValueError("Insecure default credentials prohibited in production.")
    return url


def ensure_migrations_table(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
    conn.commit()


def get_applied_versions(conn: psycopg.Connection) -> set[str]:
    ensure_migrations_table(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations ORDER BY version ASC;")
        return {row[0] for row in cur.fetchall()}


def get_migration_files() -> list[tuple[str, Path, Path]]:
    if not MIGRATIONS_DIR.exists():
        return []

    up_files = {p.name.replace(".up.sql", ""): p for p in MIGRATIONS_DIR.glob("*.up.sql")}
    down_files = {p.name.replace(".down.sql", ""): p for p in MIGRATIONS_DIR.glob("*.down.sql")}

    versions = sorted(set(up_files.keys()) | set(down_files.keys()))
    result = []
    for v in versions:
        up = up_files.get(v)
        down = down_files.get(v)
        if not up or not down:
            raise RuntimeError(f"Incomplete migration pair for version {v}: up={up}, down={down}")
        result.append((v, up, down))
    return result


def apply_migrations(db_url: str, steps: int | None = None) -> int:
    files = get_migration_files()
    if not files:
        logger.info("No migration files found in %s", MIGRATIONS_DIR)
        return 0

    with psycopg.connect(db_url) as conn:
        applied = get_applied_versions(conn)
        pending = [m for m in files if m[0] not in applied]

        if not pending:
            logger.info("Database schema is up to date. (0 pending)")
            return 0

        to_apply = pending[:steps] if steps else pending
        for version, up_path, _ in to_apply:
            logger.info("Applying migration: %s ...", version)
            sql = up_path.read_text(encoding="utf-8")
            start = time.perf_counter()
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s);",
                        (version,),
                    )
            elapsed = time.perf_counter() - start
            logger.info("Applied %s successfully in %.3fs", version, elapsed)

    return len(to_apply)


def rollback_migrations(db_url: str, steps: int = 1) -> int:
    files = get_migration_files()
    file_map = {m[0]: m for m in files}

    with psycopg.connect(db_url) as conn:
        applied = sorted(get_applied_versions(conn), reverse=True)
        if not applied:
            logger.info("No migrations to rollback.")
            return 0

        to_rollback = applied[:steps]
        for version in to_rollback:
            if version not in file_map:
                raise RuntimeError(f"Missing down migration file for version: {version}")
            _, _, down_path = file_map[version]
            logger.info("Rolling back migration: %s ...", version)
            sql = down_path.read_text(encoding="utf-8")
            start = time.perf_counter()
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        "DELETE FROM schema_migrations WHERE version = %s;",
                        (version,),
                    )
            elapsed = time.perf_counter() - start
            logger.info("Rolled back %s successfully in %.3fs", version, elapsed)

    return len(to_rollback)


def main() -> int:
    parser = argparse.ArgumentParser(description="Kunkor Database Migration Tool")
    parser.add_argument("--rollback", action="store_true", help="Rollback migrations")
    parser.add_argument("--steps", type=int, default=None, help="Number of migrations to run")
    parser.add_argument("--dsn", type=str, default=None, help="Database connection string")

    args = parser.parse_args()
    db_url = get_db_url(args.dsn)

    try:
        if args.rollback:
            steps = args.steps if args.steps is not None else 1
            rollback_migrations(db_url, steps=steps)
        else:
            apply_migrations(db_url, steps=args.steps)
        return 0
    except Exception as exc:
        logger.error("Migration failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
