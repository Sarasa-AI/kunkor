"""Operations repository for Admin, Feature Flags, Entitlements, and Audit Events."""

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import psycopg
from psycopg.rows import dict_row


class OperationsRepository:
    """PostgreSQL data access layer for admin operations and entitlements."""

    @staticmethod
    def get_students(
        conn: psycopg.Connection[Any],
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT s.id, s.telegram_chat_id, s.telegram_username, s.first_name,
                       s.created_at, s.updated_at,
                       p.revision_no as active_revision_no,
                       p.stage_code as active_stage_code
                FROM students s
                LEFT JOIN study_plans p ON s.id = p.student_id AND p.status = 'active'
                ORDER BY s.created_at DESC
                LIMIT %s OFFSET %s;
                """,
                (limit, offset),
            )
            return [dict(r) for r in cur.fetchall()]

    @staticmethod
    def get_student_plans(
        conn: psycopg.Connection[Any],
        student_id: UUID,
    ) -> list[dict[str, Any]]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, student_id, revision_no, stage_code, status,
                       engine_version, rule_set_version, raw_proposal, created_at
                FROM study_plans
                WHERE student_id = %s
                ORDER BY revision_no DESC;
                """,
                (student_id,),
            )
            plans = [dict(r) for r in cur.fetchall()]
            for p in plans:
                cur.execute(
                    """
                    SELECT id, item_order, resource_version_id, stage_code,
                           duration_minutes, prerequisites
                    FROM study_plan_items
                    WHERE plan_id = %s
                    ORDER BY item_order ASC;
                    """,
                    (p["id"],),
                )
                p["items"] = [dict(r) for r in cur.fetchall()]
            return plans

    @staticmethod
    def get_student_progress_logs(
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
                ORDER BY created_at DESC;
                """,
                (student_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    @staticmethod
    def get_feature_flags(conn: psycopg.Connection[Any]) -> list[dict[str, Any]]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, name, description, is_enabled, rules, created_at, updated_at
                FROM feature_flags
                ORDER BY name ASC;
                """
            )
            return [dict(r) for r in cur.fetchall()]

    @staticmethod
    def set_feature_flag(
        conn: psycopg.Connection[Any],
        name: str,
        is_enabled: bool,
        description: Optional[str] = None,
        rules: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO feature_flags (name, is_enabled, description, rules, updated_at)
                VALUES (%s, %s, %s, %s::jsonb, NOW())
                ON CONFLICT (name) DO UPDATE
                SET is_enabled = EXCLUDED.is_enabled,
                    description = COALESCE(EXCLUDED.description, feature_flags.description),
                    rules = COALESCE(EXCLUDED.rules, feature_flags.rules),
                    updated_at = NOW()
                RETURNING id, name, description, is_enabled, rules, created_at, updated_at;
                """,
                (name, is_enabled, description, json.dumps(rules or {})),
            )
            row = cur.fetchone()
            assert row is not None
            return dict(row)

    @staticmethod
    def is_feature_enabled(conn: psycopg.Connection[Any], name: str) -> bool:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT is_enabled FROM feature_flags WHERE name = %s;",
                (name,),
            )
            row = cur.fetchone()
            return bool(row["is_enabled"]) if row else False

    @staticmethod
    def get_student_entitlements(
        conn: psycopg.Connection[Any],
        student_id: UUID,
    ) -> list[dict[str, Any]]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, feature_key, student_id, is_granted, valid_from, valid_to, created_at
                FROM entitlements
                WHERE student_id = %s
                ORDER BY created_at DESC;
                """,
                (student_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    @staticmethod
    def grant_or_revoke_entitlement(
        conn: psycopg.Connection[Any],
        student_id: UUID,
        feature_key: str,
        is_granted: bool = True,
        valid_to: Optional[datetime] = None,
    ) -> dict[str, Any]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO entitlements (student_id, feature_key, is_granted, valid_to)
                VALUES (%s, %s, %s, %s)
                RETURNING id, feature_key, student_id, is_granted, valid_from, valid_to, created_at;
                """,
                (student_id, feature_key, is_granted, valid_to),
            )
            row = cur.fetchone()
            assert row is not None
            return dict(row)

    @staticmethod
    def check_entitlement(
        conn: psycopg.Connection[Any],
        student_id: UUID,
        feature_key: str,
    ) -> bool:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT is_granted, valid_to
                FROM entitlements
                WHERE student_id = %s AND feature_key = %s
                ORDER BY created_at DESC
                LIMIT 1;
                """,
                (student_id, feature_key),
            )
            row = cur.fetchone()
            if not row:
                return False
            if not row["is_granted"]:
                return False
            valid_to = row["valid_to"]
            if valid_to and valid_to < datetime.now(timezone.utc):
                return False
            return True

    @staticmethod
    def record_audit_event(
        conn: psycopg.Connection[Any],
        action: str,
        resource_type: str,
        actor_user_id: Optional[UUID] = None,
        student_id: Optional[UUID] = None,
        resource_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> UUID:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO audit_events (
                    actor_user_id, student_id, action, resource_type,
                    resource_id, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                RETURNING id;
                """,
                (
                    actor_user_id,
                    student_id,
                    action,
                    resource_type,
                    resource_id,
                    json.dumps(metadata or {}),
                ),
            )
            row = cur.fetchone()
            assert row is not None
            return UUID(str(row["id"]))

    @staticmethod
    def get_audit_events(
        conn: psycopg.Connection[Any],
        limit: int = 50,
        offset: int = 0,
        student_id: Optional[UUID] = None,
        action: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT id, actor_user_id, student_id, action, resource_type, "
            "resource_id, metadata, occurred_at "
            "FROM audit_events WHERE 1=1"
        )
        params: list[Any] = []
        if student_id:
            query += " AND student_id = %s"
            params.append(student_id)
        if action:
            query += " AND action = %s"
            params.append(action)
        query += " ORDER BY occurred_at DESC LIMIT %s OFFSET %s;"
        params.extend([limit, offset])

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, tuple(params))
            return [dict(r) for r in cur.fetchall()]
