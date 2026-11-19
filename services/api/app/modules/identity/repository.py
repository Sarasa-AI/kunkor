"""Identity module database repository.

Handles PostgreSQL persistence for student profiles, guardian consent, and student context.
"""

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import psycopg
from psycopg.rows import dict_row


class IdentityRepository:
    """PostgreSQL data access layer for student identity and profile."""

    @staticmethod
    def get_or_create_student(
        conn: psycopg.Connection[Any],
        telegram_chat_id: int,
        telegram_user_id: Optional[int] = None,
        telegram_username: Optional[str] = None,
        first_name: Optional[str] = None,
    ) -> UUID:
        """Create a private mapping and audit it in the caller's transaction."""
        if (
            type(telegram_chat_id) is not int
            or type(telegram_user_id) is not int
            or not 0 < telegram_user_id < 2**63
            or telegram_chat_id != telegram_user_id
        ):
            raise ValueError("Invalid private Telegram identity")
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                WITH created AS (INSERT INTO students (
                    telegram_chat_id, telegram_user_id, telegram_username, first_name
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (telegram_chat_id) DO NOTHING
                RETURNING id), audited AS (
                    INSERT INTO audit_events
                        (student_id, action, resource_type, resource_id, metadata)
                    SELECT id, 'student.identity.created', 'student', id::text, '{}'::jsonb
                    FROM created RETURNING id
                ) SELECT id FROM created;
                """,
                (telegram_chat_id, telegram_user_id, telegram_username, first_name),
            )
            row = cur.fetchone()
            if row is not None:
                return UUID(str(row["id"]))
            cur.execute(
                """
                UPDATE students
                SET updated_at = NOW(),
                    telegram_username = COALESCE(%s, telegram_username),
                    first_name = COALESCE(%s, first_name)
                WHERE telegram_chat_id = %s AND telegram_user_id = %s
                RETURNING id;
                """,
                (telegram_username, first_name, telegram_chat_id, telegram_user_id),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError("Telegram identity mapping conflict")
            student_id = UUID(str(row["id"]))
            fields = [
                name
                for name, value in (
                    ("telegram_username", telegram_username),
                    ("first_name", first_name),
                )
                if value is not None
            ]
            if fields:
                IdentityRepository.record_audit_event(
                    conn,
                    student_id,
                    "student.identity_metadata.updated",
                    "student",
                    str(student_id),
                    {"fields": fields},
                )
            return student_id

    @staticmethod
    def get_student_by_id(
        conn: psycopg.Connection[Any],
        student_id: UUID,
    ) -> Optional[dict[str, Any]]:
        """Get student basic profile by ID."""
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, telegram_chat_id, telegram_user_id, telegram_username,
                       first_name, created_at, updated_at
                FROM students
                WHERE id = %s;
                """,
                (student_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)

    @staticmethod
    def get_student_by_telegram_id(
        conn: psycopg.Connection[Any],
        telegram_user_id: int,
        telegram_chat_id: int,
    ) -> Optional[UUID]:
        """Get student ID by Telegram credentials."""
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id FROM students WHERE telegram_user_id = %s AND telegram_chat_id = %s;",
                (telegram_user_id, telegram_chat_id),
            )
            row = cur.fetchone()
            if row:
                return UUID(str(row["id"]))
            return None

    @staticmethod
    def update_student_profile(
        conn: psycopg.Connection[Any],
        student_id: UUID,
        grade: Optional[str] = None,
        track: Optional[str] = None,
        guardian_consent: Optional[bool] = None,
    ) -> None:
        """Update student profile fields. Only provided fields are updated."""
        if guardian_consent is not None and type(guardian_consent) is not bool:
            raise ValueError("guardian_consent must be a boolean.")
        updates = []
        params: list[Any] = []
        if grade is not None:
            updates.append("grade = %s")
            params.append(grade)
        if track is not None:
            updates.append("track = %s")
            params.append(track)
        if guardian_consent is not None:
            updates.append("guardian_consent = %s")
            params.append(guardian_consent)
        if not updates:
            return
        updates.append("updated_at = NOW()")
        params.append(student_id)

        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE students SET {', '.join(updates)} WHERE id = %s;",
                tuple(params),
            )
            if cur.rowcount:
                changes = {
                    name: value
                    for name, value in (
                        ("grade", grade),
                        ("track", track),
                        ("guardian_consent", guardian_consent),
                    )
                    if value is not None
                }
                IdentityRepository.record_audit_event(
                    conn,
                    student_id,
                    "student.profile.update",
                    "student_profile",
                    str(student_id),
                    {"changes": changes},
                )

    @staticmethod
    def get_student_profile(
        conn: psycopg.Connection[Any],
        student_id: UUID,
    ) -> Optional[dict[str, Any]]:
        """Get full student profile including grade, track, and consent."""
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, telegram_chat_id, telegram_user_id, telegram_username,
                       first_name, grade, track, guardian_consent, created_at, updated_at
                FROM students
                WHERE id = %s;
                """,
                (student_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)

    @staticmethod
    def get_student_context(
        conn: psycopg.Connection[Any],
        student_id: UUID,
    ) -> Optional[dict[str, Any]]:
        """Load structured Student Context for Orchestrator consumption.

        Returns a read-model combining profile, latest intake slots, active plan summary,
        and progress history summary.
        """
        with conn.cursor(row_factory=dict_row) as cur:
            # 1. Student profile
            cur.execute(
                """
                SELECT id, telegram_chat_id, telegram_user_id, telegram_username,
                       first_name, grade, track, guardian_consent, created_at
                FROM students
                WHERE id = %s;
                """,
                (student_id,),
            )
            student = cur.fetchone()
            if not student:
                return None
            student = dict(student)

            # 2. Latest intake session
            cur.execute(
                """
                SELECT id, current_step, slots, is_completed, created_at, updated_at
                FROM intake_sessions
                WHERE student_id = %s
                ORDER BY created_at DESC
                LIMIT 1;
                """,
                (student_id,),
            )
            intake = cur.fetchone()
            if intake:
                intake = dict(intake)
                if isinstance(intake.get("slots"), str):
                    intake["slots"] = json.loads(intake["slots"])
            else:
                intake = None

            # 3. Active study plan
            cur.execute(
                """
                SELECT id, student_id, revision_no, stage_code, status,
                       engine_version, rule_set_version, raw_proposal, intake_slots, created_at
                FROM study_plans
                WHERE student_id = %s AND status = 'active'
                ORDER BY revision_no DESC
                LIMIT 1;
                """,
                (student_id,),
            )
            plan = cur.fetchone()
            if plan:
                plan = dict(plan)
                cur.execute(
                    """
                    SELECT id, plan_id, student_id, item_order, resource_version_id,
                           stage_code, duration_minutes, prerequisites
                    FROM study_plan_items
                    WHERE plan_id = %s AND student_id = %s
                    ORDER BY item_order ASC;
                    """,
                    (plan["id"], student_id),
                )
                items = [dict(r) for r in cur.fetchall()]
                for it in items:
                    if isinstance(it.get("prerequisites"), str):
                        it["prerequisites"] = json.loads(it["prerequisites"])
                plan["items"] = items
            else:
                plan = None

            # 4. Progress history summary
            cur.execute(
                """
                SELECT count(*) as total_logs,
                       max(completion_rate) as max_rate,
                       min(completion_rate) as min_rate,
                       avg(completion_rate) as avg_rate,
                       max(created_at) as last_progress_at
                FROM daily_progress_logs
                WHERE student_id = %s;
                """,
                (student_id,),
            )
            progress_summary = cur.fetchone()
            if progress_summary:
                progress_summary = dict(progress_summary)
            else:
                progress_summary = {
                    "total_logs": 0,
                    "max_rate": None,
                    "min_rate": None,
                    "avg_rate": None,
                    "last_progress_at": None,
                }

            return {
                "student": student,
                "intake": intake,
                "active_plan": plan,
                "progress_summary": progress_summary,
                "loaded_at": datetime.now(timezone.utc).isoformat(),
            }

    @staticmethod
    def record_audit_event(
        conn: psycopg.Connection[Any],
        student_id: UUID,
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> UUID:
        """Record audit event for sensitive identity/profile changes."""
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO audit_events (
                    student_id, action, resource_type, resource_id, metadata
                )
                VALUES (%s, %s, %s, %s, %s::jsonb)
                RETURNING id;
                """,
                (student_id, action, resource_type, resource_id, json.dumps(metadata or {})),
            )
            row = cur.fetchone()
            assert row is not None
            return UUID(str(row["id"]))

    @staticmethod
    def list_students(
        conn: psycopg.Connection[Any],
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List students with basic info."""
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, telegram_chat_id, telegram_username, first_name,
                       grade, track, guardian_consent, created_at, updated_at
                FROM students
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s;
                """,
                (limit, offset),
            )
            return [dict(r) for r in cur.fetchall()]
