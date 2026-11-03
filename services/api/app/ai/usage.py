"""Conservative daily reservations, independently committed before each HTTP attempt.

Reservations count failed/abandoned calls; they are ceilings, never actual bills.
"""

from uuid import UUID

from app.core.config import settings
from app.core.db import get_db_connection


def reserve_daily_attempt(student_id: UUID | None) -> bool:
    cost = settings.NINEROUTER_ATTEMPT_COST_CEILING_USD
    if student_id is None or cost <= 0:
        return False
    limits = (
        (
            "global",
            settings.NINEROUTER_GLOBAL_DAILY_CALLS,
            settings.NINEROUTER_GLOBAL_DAILY_RESERVED_USD,
        ),
        (
            f"student:{student_id}",
            settings.NINEROUTER_STUDENT_DAILY_CALLS,
            settings.NINEROUTER_STUDENT_DAILY_RESERVED_USD,
        ),
    )
    # A separate connection makes reservations survive consultation rollback/restart.
    with get_db_connection() as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '1s'")
        cur.execute("SET LOCAL statement_timeout = '2s'")
        # Global lock serializes both counters across processes, always global first.
        cur.execute("SELECT pg_advisory_xact_lock(110031, 5)")
        cur.execute("SELECT (clock_timestamp() AT TIME ZONE 'UTC')::date AS day")
        day_row = cur.fetchone()
        if day_row is None:
            raise RuntimeError("Usage day unavailable.")
        day = day_row["day"]
        for scope, call_limit, cost_limit in limits:
            cur.execute(
                "INSERT INTO ai_daily_usage (usage_day, scope_key) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                (day, scope),
            )
            cur.execute(
                "SELECT attempts, reserved_usd FROM ai_daily_usage "
                "WHERE usage_day = %s AND scope_key = %s FOR UPDATE",
                (day, scope),
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("Usage reservation row unavailable.")
            if row["attempts"] >= call_limit or row["reserved_usd"] + cost > cost_limit:
                return False
        for scope, _, _ in limits:
            cur.execute(
                "UPDATE ai_daily_usage SET attempts = attempts + 1, "
                "reserved_usd = reserved_usd + %s WHERE usage_day = %s AND scope_key = %s",
                (cost, day, scope),
            )
    return True
