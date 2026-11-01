"""Consultation module database repository.

Handles PostgreSQL persistence for students, intake sessions, study plans,
idempotency deduplication, and outbox event enqueueing.
"""

import json
from typing import Any, Optional
from uuid import UUID

import psycopg
from psycopg.rows import dict_row


class ConsultationRepository:
    """PostgreSQL data access layer for consultation and planning workflows."""

    @staticmethod
    def get_or_create_student(
        conn: psycopg.Connection[Any],
        telegram_chat_id: int,
        telegram_user_id: Optional[int] = None,
        telegram_username: Optional[str] = None,
        first_name: Optional[str] = None,
    ) -> UUID:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO students (
                    telegram_chat_id, telegram_user_id, telegram_username, first_name
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (telegram_chat_id) DO UPDATE
                SET updated_at = NOW(),
                    telegram_username = COALESCE(
                        EXCLUDED.telegram_username, students.telegram_username
                    ),
                    first_name = COALESCE(EXCLUDED.first_name, students.first_name)
                RETURNING id;
                """,
                (telegram_chat_id, telegram_user_id, telegram_username, first_name),
            )
            row = cur.fetchone()
            assert row is not None
            return UUID(str(row["id"]))

    @staticmethod
    def get_active_intake_session(
        conn: psycopg.Connection[Any],
        student_id: UUID,
    ) -> Optional[dict[str, Any]]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, student_id, current_step, slots, is_completed, created_at, updated_at
                FROM intake_sessions
                WHERE student_id = %s AND is_completed = FALSE
                ORDER BY created_at DESC
                LIMIT 1;
                """,
                (student_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            session = dict(row)
            if isinstance(session.get("slots"), str):
                session["slots"] = json.loads(session["slots"])
            return session

    @staticmethod
    def create_intake_session(
        conn: psycopg.Connection[Any],
        student_id: UUID,
    ) -> dict[str, Any]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO intake_sessions (student_id, current_step, slots)
                VALUES (%s, 'stage', '{}'::jsonb)
                RETURNING id, student_id, current_step, slots, is_completed, created_at, updated_at;
                """,
                (student_id,),
            )
            row = cur.fetchone()
            assert row is not None
            session = dict(row)
            if isinstance(session.get("slots"), str):
                session["slots"] = json.loads(session["slots"])
            return session

    @staticmethod
    def update_intake_session(
        conn: psycopg.Connection[Any],
        session_id: UUID,
        current_step: str,
        slots: dict[str, Any],
        is_completed: bool = False,
    ) -> None:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE intake_sessions
                SET current_step = %s,
                    slots = %s::jsonb,
                    is_completed = %s,
                    updated_at = NOW()
                WHERE id = %s;
                """,
                (current_step, json.dumps(slots), is_completed, session_id),
            )

    @staticmethod
    def get_latest_plan_revision(
        conn: psycopg.Connection[Any],
        student_id: UUID,
    ) -> int:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT MAX(revision_no) AS max_rev
                FROM study_plans
                WHERE student_id = %s;
                """,
                (student_id,),
            )
            row = cur.fetchone()
            if row and row["max_rev"] is not None:
                return int(row["max_rev"])
            return 0

    @staticmethod
    def save_study_plan(
        conn: psycopg.Connection[Any],
        plan_id: UUID,
        student_id: UUID,
        revision_no: int,
        stage_code: str,
        engine_version: str,
        rule_set_version: str,
        raw_proposal: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> UUID:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO study_plans (
                    id, student_id, revision_no, stage_code, status,
                    engine_version, rule_set_version, raw_proposal
                )
                VALUES (%s, %s, %s, %s, 'active', %s, %s, %s::jsonb)
                RETURNING id;
                """,
                (
                    plan_id,
                    student_id,
                    revision_no,
                    stage_code,
                    engine_version,
                    rule_set_version,
                    json.dumps(raw_proposal),
                ),
            )
            for idx, item in enumerate(items):
                cur.execute(
                    """
                    INSERT INTO study_plan_items (
                        plan_id, student_id, item_order, resource_version_id,
                        stage_code, duration_minutes, prerequisites
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb);
                    """,
                    (
                        plan_id,
                        student_id,
                        idx + 1,
                        item["resource_version_id"],
                        item["stage_code"],
                        item["duration_minutes"],
                        json.dumps(item.get("prerequisites", [])),
                    ),
                )
        return plan_id

    @staticmethod
    def enqueue_outbox_event(
        conn: psycopg.Connection[Any],
        student_id: UUID,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
    ) -> UUID:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO outbox_events (
                    student_id, event_type, aggregate_type, aggregate_id, payload
                )
                VALUES (%s, %s, %s, %s, %s::jsonb)
                RETURNING id;
                """,
                (student_id, event_type, aggregate_type, aggregate_id, json.dumps(payload)),
            )
            row = cur.fetchone()
            assert row is not None
            return UUID(str(row["id"]))

    @staticmethod
    def check_and_record_idempotency_key(
        conn: psycopg.Connection[Any],
        key: str,
        student_id: Optional[UUID],
        request_hash: str,
    ) -> bool:
        """
        Atomically check and record idempotency key.
        Returns True if key is new, False if already seen (duplicate).
        """
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO idempotency_keys (key, student_id, request_hash)
                VALUES (%s, %s, %s)
                ON CONFLICT (
                    key,
                    COALESCE(student_id, '00000000-0000-0000-0000-000000000000'::uuid)
                )
                DO NOTHING
                RETURNING id;
                """,
                (key, student_id, request_hash),
            )
            row = cur.fetchone()
            return row is not None

    @staticmethod
    def get_active_study_plan(
        conn: psycopg.Connection[Any],
        student_id: UUID,
    ) -> Optional[dict[str, Any]]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, student_id, revision_no, stage_code, status,
                       engine_version, rule_set_version, raw_proposal, created_at
                FROM study_plans
                WHERE student_id = %s AND status = 'active'
                ORDER BY revision_no DESC
                LIMIT 1;
                """,
                (student_id,),
            )
            plan_row = cur.fetchone()
            if not plan_row:
                return None
            plan = dict(plan_row)
            cur.execute(
                """
                SELECT id, plan_id, student_id, item_order, resource_version_id,
                       stage_code, duration_minutes, prerequisites
                FROM study_plan_items
                WHERE plan_id = %s
                ORDER BY item_order ASC;
                """,
                (plan["id"],),
            )
            items = [dict(r) for r in cur.fetchall()]
            for it in items:
                if isinstance(it.get("prerequisites"), str):
                    it["prerequisites"] = json.loads(it["prerequisites"])
            plan["items"] = items
            return plan

    @staticmethod
    def record_daily_progress(
        conn: psycopg.Connection[Any],
        student_id: UUID,
        plan_id: UUID,
        revision_no: int,
        completed_units: list[str],
        missed_units: list[str],
        duration_spent_minutes: int,
        student_notes: Optional[str] = None,
    ) -> UUID:
        total_units = len(completed_units) + len(missed_units)
        rate = (len(completed_units) / max(1, total_units)) * 100.0
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO daily_progress_logs (
                    student_id, plan_id, revision_no, completed_units,
                    missed_units, duration_spent_minutes, completion_rate, student_notes
                )
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
                RETURNING id;
                """,
                (
                    student_id,
                    plan_id,
                    revision_no,
                    json.dumps(completed_units),
                    json.dumps(missed_units),
                    duration_spent_minutes,
                    round(rate, 2),
                    student_notes,
                ),
            )
            row = cur.fetchone()
            assert row is not None
            return UUID(str(row["id"]))

    @staticmethod
    def get_completed_unit_ids_for_student(
        conn: psycopg.Connection[Any],
        student_id: UUID,
    ) -> set[str]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT completed_units
                FROM daily_progress_logs
                WHERE student_id = %s;
                """,
                (student_id,),
            )
            all_completed: set[str] = set()
            for row in cur.fetchall():
                units = row["completed_units"]
                if isinstance(units, str):
                    units = json.loads(units)
                if isinstance(units, list):
                    all_completed.update(units)
            return all_completed

    @staticmethod
    def supersede_plan(
        conn: psycopg.Connection[Any],
        plan_id: UUID,
    ) -> None:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE study_plans
                SET status = 'superseded'
                WHERE id = %s;
                """,
                (plan_id,),
            )

    @staticmethod
    def get_student_historical_progress(
        conn: psycopg.Connection[Any],
        student_id: UUID,
    ) -> list[dict[str, Any]]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, student_id, plan_id, revision_no, completed_units,
                       missed_units, duration_spent_minutes, completion_rate,
                       student_notes, created_at
                FROM daily_progress_logs
                WHERE student_id = %s
                ORDER BY created_at ASC;
                """,
                (student_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    @staticmethod
    def get_latest_intake_session(
        conn: psycopg.Connection[Any],
        student_id: UUID,
    ) -> Optional[dict[str, Any]]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, student_id, current_step, slots, is_completed, created_at, updated_at
                FROM intake_sessions
                WHERE student_id = %s
                ORDER BY created_at DESC
                LIMIT 1;
                """,
                (student_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            session = dict(row)
            if isinstance(session.get("slots"), str):
                session["slots"] = json.loads(session["slots"])
            return session
