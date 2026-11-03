"""Compare an already restored synthetic database. Never dumps, restores or mutates data."""

import hashlib
import json
import os

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from scripts.migrate_check import require_test_database


def fingerprint(dsn: str) -> dict[str, tuple[int, str]]:
    require_test_database(dsn)
    if conninfo_to_dict(dsn).get("host") not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Recovery proof requires loopback-only synthetic databases.")
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        tables = [row[0] for row in cur.fetchall()]
        result = {}
        for table in tables:
            cur.execute(
                sql.SQL("SELECT row_to_json(t)::text FROM public.{} t ORDER BY 1").format(
                    sql.Identifier(table)
                )
            )
            rows = [row[0] for row in cur.fetchall()]
            result[table] = (len(rows), hashlib.sha256("\n".join(rows).encode()).hexdigest())
        cur.execute(
            "SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid) "
            "FROM pg_trigger t JOIN pg_class c ON t.tgrelid=c.oid "
            "JOIN pg_namespace n ON c.relnamespace=n.oid "
            "WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY 1,2"
        )
        triggers = json.dumps(cur.fetchall())
        result["_triggers"] = (len(triggers), hashlib.sha256(triggers.encode()).hexdigest())
        cur.execute(
            "SELECT c.relname, x.conname, pg_get_constraintdef(x.oid) "
            "FROM pg_constraint x JOIN pg_class c ON x.conrelid=c.oid "
            "JOIN pg_namespace n ON c.relnamespace=n.oid "
            "WHERE n.nspname='public' ORDER BY 1,2"
        )
        constraints = json.dumps(cur.fetchall())
        result["_constraints"] = (
            len(constraints),
            hashlib.sha256(constraints.encode()).hexdigest(),
        )
        return result


def main() -> None:
    source = os.environ["RECOVERY_SOURCE_DATABASE_URL"]
    target = os.environ["RECOVERY_TARGET_DATABASE_URL"]
    if conninfo_to_dict(source) == conninfo_to_dict(target):
        raise ValueError("Source and restored databases must differ.")
    original, restored = fingerprint(source), fingerprint(target)
    required = {
        "students",
        "intake_sessions",
        "study_plans",
        "study_plan_items",
        "daily_progress_logs",
        "outbox_events",
        "audit_events",
    }
    if not all(original.get(table, (0, ""))[0] > 0 for table in required):
        raise ValueError("Seed complete synthetic consultation/progress/audit data before backup.")
    if original != restored:
        raise ValueError("Restored rows, constraints or append-only triggers differ.")
    print(
        json.dumps(
            {
                "result": "PASS",
                "synthetic_only": True,
                "tables_verified": len(original) - 2,
                "nonempty_required_tables": len(required),
            }
        )
    )


if __name__ == "__main__":
    main()
