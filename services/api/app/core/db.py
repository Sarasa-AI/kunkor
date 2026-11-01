import logging
import os
import sys
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.core.config import settings

logger = logging.getLogger(__name__)


def get_connection_string(test: bool = False) -> str:
    if test or "pytest" in sys.modules or os.getenv("PYTEST_CURRENT_TEST"):
        return (
            settings.TEST_DATABASE_URL
            or os.getenv("TEST_DATABASE_URL", "")
            or "postgresql://kunkor:kunkor_dev_password@localhost:5435/kunkor_test"
        )
    return settings.DATABASE_URL


@contextmanager
def get_db_connection(
    test: bool = False, autocommit: bool = False
) -> Generator[psycopg.Connection[Any], None, None]:
    conn_str = get_connection_string(test=test)
    conn = psycopg.connect(conn_str, row_factory=dict_row, autocommit=autocommit)
    try:
        yield conn
    finally:
        conn.close()


def check_db_health(test: bool = False) -> bool:
    try:
        with get_db_connection(test=test) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS healthy;")
                row = cur.fetchone()
                return bool(row and row["healthy"] == 1)
    except Exception as exc:
        logger.error("Database health check failed: %s", exc)
        return False
