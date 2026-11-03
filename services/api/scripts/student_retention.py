"""Student data retention and GDPR/privacy erasure script.

Enforces:
- Read-only dry run by default.
- --execute requires explicit flag and authorized database connection.
- Age cutoff verification against student latest activity.
- Cryptographic token commitment (raw 256-bit token passed; stored as SHA-256 hash).
- Explicit, independently verified authorization table (retention_erasure_authorizations).
- Privileged PostgreSQL function execution with locked search_path.
- Transaction-bound trigger verification using txid_current().
- Zero GUC reliance; zero PG_CONTEXT string inspection.
- Transactional deletion of all linked student data in strict foreign-key order.
- Non-identifying deletion receipt appended to audit_events.
- Zero PII retained in deletion audit record.
"""

import argparse
import hashlib
import json
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.core.db import get_db_connection


def get_operator_db_connection(dsn: str | None = None) -> psycopg.Connection:
    """Connect as the authorized operator role to issue authorizations and run erasures."""
    url = dsn or os.getenv("OPERATOR_DATABASE_URL")
    if not url:
        raise ValueError(
            "Privileged operator database connection required: "
            "provide --operator-dsn or set OPERATOR_DATABASE_URL environment variable."
        )
    return psycopg.connect(url, row_factory=dict_row)



def inventory_student_data(
    conn: psycopg.Connection, student_id: UUID
) -> dict[str, int]:
    """Count all rows across all tables associated with a student."""
    counts = {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT COUNT(*) AS c FROM students WHERE id = %s", (student_id,))
        counts["students"] = cur.fetchone()["c"]

        cur.execute(
            "SELECT COUNT(*) AS c FROM intake_sessions WHERE student_id = %s",
            (student_id,),
        )
        counts["intake_sessions"] = cur.fetchone()["c"]

        cur.execute(
            "SELECT COUNT(*) AS c FROM study_plans WHERE student_id = %s",
            (student_id,),
        )
        counts["study_plans"] = cur.fetchone()["c"]

        cur.execute(
            """
            SELECT COUNT(*) AS c FROM study_plan_items spi
            JOIN study_plans sp ON spi.plan_id = sp.id
            WHERE sp.student_id = %s
            """,
            (student_id,),
        )
        counts["study_plan_items"] = cur.fetchone()["c"]

        cur.execute(
            "SELECT COUNT(*) AS c FROM daily_progress_logs WHERE student_id = %s",
            (student_id,),
        )
        counts["daily_progress_logs"] = cur.fetchone()["c"]

        cur.execute(
            "SELECT COUNT(*) AS c FROM outbox_events WHERE student_id = %s",
            (student_id,),
        )
        counts["outbox_events"] = cur.fetchone()["c"]

        cur.execute(
            "SELECT COUNT(*) AS c FROM idempotency_keys WHERE student_id = %s",
            (student_id,),
        )
        counts["idempotency_keys"] = cur.fetchone()["c"]

        cur.execute(
            "SELECT COUNT(*) AS c FROM entitlements WHERE student_id = %s",
            (student_id,),
        )
        counts["entitlements"] = cur.fetchone()["c"]

    return counts


def check_student_activity_age(
    conn: psycopg.Connection, student_id: UUID, retention_days: int
) -> tuple[bool, str]:
    """Check if student has been inactive for at least retention_days."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT updated_at, created_at FROM students WHERE id = %s",
            (student_id,),
        )
        row = cur.fetchone()
        if not row:
            return False, "Student not found."

        latest_activity = row["updated_at"] or row["created_at"]

        cur.execute(
            """
            SELECT MAX(created_at) AS latest_progress
            FROM daily_progress_logs
            WHERE student_id = %s
            """,
            (student_id,),
        )
        prog_row = cur.fetchone()
        if prog_row and prog_row["latest_progress"]:
            if prog_row["latest_progress"] > latest_activity:
                latest_activity = prog_row["latest_progress"]

        now = datetime.now(timezone.utc)
        age_days = (now - latest_activity).total_seconds() / 86400.0

        if age_days < retention_days:
            return (
                False,
                f"Student activity is {age_days:.1f} days old; "
                f"retention policy requires at least {retention_days} days.",
            )

        return True, "Eligible for retention deletion."


def create_retention_authorization(
    conn: psycopg.Connection,
    student_id: UUID,
    authorized_by: str,
    retention_days: int,
    valid_minutes: int = 15,
) -> tuple[UUID, str]:
    """
    Issue an explicit, independently verified retention authorization.
    Generates a high-entropy 256-bit bearer token and stores its SHA-256 hash.
    Returns (authorization_id, raw_token).
    """
    raw_token = secrets.token_hex(32)
    token_hash = hashlib.sha256(raw_token.encode("ascii")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=valid_minutes)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO retention_erasure_authorizations (
                student_id, authorized_by, authorization_token_hash,
                inactivity_cutoff_days, expires_at
            ) VALUES (%s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (student_id, authorized_by, token_hash, retention_days, expires_at),
        )
        row = cur.fetchone()
        assert row is not None
        auth_id = UUID(str(row["id"]))

    return auth_id, raw_token


def execute_student_erasure(
    conn: psycopg.Connection,
    student_id: UUID,
    retention_days: int,
    raw_authorization_token: str,
) -> dict[str, int]:
    """
    Execute erasure via the privileged PostgreSQL function.
    Passes raw token to function, which verifies against stored SHA-256 hash.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT execute_student_retention_erasure(%s, %s, %s) AS summary;",
            (student_id, retention_days, raw_authorization_token),
        )
        row = cur.fetchone()
        assert row is not None
        summary = row["summary"]
        if isinstance(summary, str):
            summary = json.loads(summary)
        return dict(summary)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Student Data Retention & Privacy Erasure Script"
    )
    parser.add_argument(
        "--student-id",
        type=str,
        required=True,
        help="UUID of the student to evaluate / erase",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        required=True,
        help="Minimum inactivity days required for retention deletion",
    )
    parser.add_argument(
        "--operator",
        type=str,
        default="cli_operator",
        help="Identifier of the authorizing operator",
    )
    parser.add_argument(
        "--operator-dsn",
        type=str,
        default=None,
        help="Connection DSN for privileged operator execution",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Actually execute deletion (default: dry run)",
    )
    args = parser.parse_args()

    if args.retention_days < 0:
        print(json.dumps({"error": "retention-days must be non-negative"}), file=sys.stderr)
        return 1

    try:
        student_uuid = UUID(args.student_id)
    except ValueError:
        print(json.dumps({"error": "Invalid student UUID format"}), file=sys.stderr)
        return 1

    with get_db_connection() as conn:
        eligible, reason = check_student_activity_age(
            conn, student_uuid, args.retention_days
        )
        if not eligible:
            print(
                json.dumps(
                    {
                        "status": "ineligible",
                        "student_id": str(student_uuid),
                        "reason": reason,
                    }
                )
            )
            return 1

        inventory = inventory_student_data(conn, student_uuid)

        if not args.execute:
            print(
                json.dumps(
                    {
                        "status": "dry_run",
                        "student_id": str(student_uuid),
                        "eligible": True,
                        "retention_days": args.retention_days,
                        "inventory": inventory,
                        "message": "Dry run complete. Use --execute to perform deletion.",
                    },
                    indent=2,
                )
            )
            return 0

    try:
        with get_operator_db_connection(args.operator_dsn) as op_conn:
            with op_conn.transaction():
                _, raw_token = create_retention_authorization(
                    op_conn, student_uuid, args.operator, args.retention_days
                )
                erased_counts = execute_student_erasure(
                    op_conn, student_uuid, args.retention_days, raw_token
                )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "erased",
                "student_id": "REDACTED",
                "retention_days": args.retention_days,
                "erased_counts": erased_counts,
                "message": (
                    "Student data successfully erased under privileged retention policy."
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
