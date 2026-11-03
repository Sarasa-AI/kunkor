"""Tests for student data retention, adversarial authorization bypass resistance, and erasure."""

import json
import random
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.core.db import get_db_connection
from scripts.student_retention import (
    check_student_activity_age,
    create_retention_authorization,
    execute_student_erasure,
    inventory_student_data,
)


def _seed_test_student(conn, inactive_days: int = 100):
    """Seed a synthetic student with related records and backdated timestamps."""
    student_id = uuid4()
    plan_id = uuid4()
    item_id = uuid4()
    old_date = datetime.now(timezone.utc) - timedelta(days=inactive_days)
    unique_chat_id = random.randint(100000000, 999999999)

    with conn.cursor() as cur:
        # Student
        cur.execute(
            """
            INSERT INTO students
                (id, telegram_chat_id, telegram_user_id, first_name, created_at, updated_at)
            VALUES (%s, %s, %s, 'Synthetic Test Student', %s, %s);
            """,
            (student_id, unique_chat_id, unique_chat_id, old_date, old_date),
        )

        # Intake session
        cur.execute(
            """
            INSERT INTO intake_sessions
                (student_id, current_step, slots, is_completed, created_at, updated_at)
            VALUES (%s, 'completed', '{"stage_code": "konkur"}'::jsonb, TRUE, %s, %s);
            """,
            (student_id, old_date, old_date),
        )

        # Study plan
        cur.execute(
            """
            INSERT INTO study_plans (id, student_id, revision_no, stage_code, status, created_at)
            VALUES (%s, %s, 1, 'konkur', 'active', %s);
            """,
            (plan_id, student_id, old_date),
        )

        # Study plan item
        cur.execute(
            """
            INSERT INTO study_plan_items
                (id, plan_id, student_id, item_order, resource_version_id,
                 stage_code, duration_minutes)
            VALUES (%s, %s, %s, 1, 'res-bio-01', 'konkur', 60);
            """,
            (item_id, plan_id, student_id),
        )

        # Daily progress log (append-only table)
        cur.execute(
            """
            INSERT INTO daily_progress_logs
                (student_id, plan_id, revision_no, completed_units, missed_units,
                 duration_spent_minutes, created_at)
            VALUES (%s, %s, 1, '["res-bio-01"]'::jsonb, '[]'::jsonb, 60, %s);
            """,
            (student_id, plan_id, old_date),
        )

        # Outbox event
        cur.execute(
            """
            INSERT INTO outbox_events
                (student_id, event_type, aggregate_type, aggregate_id, payload, occurred_at)
            VALUES (%s, 'STUDY_PLAN_DELIVERY_REQUESTED', 'study_plan', %s, '{}'::jsonb, %s);
            """,
            (student_id, str(plan_id), old_date),
        )

        # Idempotency key
        cur.execute(
            """
            INSERT INTO idempotency_keys (student_id, key, request_hash, created_at)
            VALUES (%s, %s, 'hash123', %s);
            """,
            (student_id, f"test_key_{student_id}", old_date),
        )

        # Entitlement
        cur.execute(
            """
            INSERT INTO entitlements (student_id, feature_key, is_granted, created_at)
            VALUES (%s, 'ai_consultant', TRUE, %s);
            """,
            (student_id, old_date),
        )

    return student_id, plan_id


def test_retention_inventory():
    with get_db_connection(test=True) as conn:
        student_id, _ = _seed_test_student(conn, inactive_days=100)
        conn.commit()

        counts = inventory_student_data(conn, student_id)
        assert counts["students"] == 1
        assert counts["intake_sessions"] == 1
        assert counts["study_plans"] == 1
        assert counts["study_plan_items"] == 1
        assert counts["daily_progress_logs"] == 1
        assert counts["outbox_events"] == 1
        assert counts["idempotency_keys"] == 1
        assert counts["entitlements"] == 1


def test_retention_age_check_ineligible():
    with get_db_connection(test=True) as conn:
        # Student active 5 days ago, policy requires 30 days
        student_id, _ = _seed_test_student(conn, inactive_days=5)
        conn.commit()

        eligible, reason = check_student_activity_age(conn, student_id, retention_days=30)
        assert eligible is False
        assert "retention policy requires at least 30 days" in reason


def test_retention_age_check_eligible():
    with get_db_connection(test=True) as conn:
        # Student inactive 90 days, policy requires 30 days
        student_id, _ = _seed_test_student(conn, inactive_days=90)
        conn.commit()

        eligible, reason = check_student_activity_age(conn, student_id, retention_days=30)
        assert eligible is True


# ==============================================================================
# ADVERSARIAL SECURITY TESTS
# ==============================================================================


def test_adversarial_guc_manipulation_cannot_bypass_append_only():
    """
    ADVERSARIAL ATTACK TEST:
    An ordinary database user/query attempts to use the old GUC-based mechanism
    to bypass the append-only trigger. The new architecture uses explicit
    authorization table + txid_current() binding instead of GUCs.
    Must be blocked by the trigger's transaction-bound authorization check!
    """
    with get_db_connection(test=True) as conn:
        victim_id, _ = _seed_test_student(conn, inactive_days=100)
        conn.commit()

        with conn.transaction():
            with conn.cursor() as cur:
                # 1. Attacker tries to set GUCs (old mechanism)
                cur.execute(
                    "SELECT set_config('kunkor.retention_target_student_id', %s, true);",
                    (str(victim_id),),
                )
                cur.execute(
                    "SELECT set_config('kunkor.retention_execution_nonce', 'fake_nonce', true);"
                )
                cur.execute(
                    "SELECT set_config('kunkor.authorized_erasure_student_id', %s, true);",
                    (str(victim_id),),
                )

                # 2. Attacker executes direct DELETE -> MUST FAIL WITH 42501
                with pytest.raises(psycopg.Error) as exc_info:
                    cur.execute(
                        "DELETE FROM daily_progress_logs WHERE student_id = %s;",
                        (victim_id,),
                    )
                # Verify append-only error raised with 42501
                assert "append-only" in str(exc_info.value).lower()
                assert exc_info.value.sqlstate == "42501"

        # Verify victim's progress log is 100% intact
        counts = inventory_student_data(conn, victim_id)
        assert counts["daily_progress_logs"] == 1


def test_adversarial_direct_insert_authorization_denied():
    """
    ADVERSARIAL ATTACK TEST:
    Attempt direct unauthorized creation of an authorization record
    without going through administrative verification.
    If an attacker attempts to insert a fake authorization for an active student,
    the privileged function still verifies age cutoff and student existence.
    """
    with get_db_connection(test=True) as conn:
        active_student_id, _ = _seed_test_student(conn, inactive_days=2)
        conn.commit()

        # Insert a forged authorization directly
        fake_token_hash = "f" * 64
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO retention_erasure_authorizations (
                        student_id, authorized_by, authorization_token_hash,
                        inactivity_cutoff_days, expires_at
                    ) VALUES (%s, 'attacker', %s, 0, NOW() + INTERVAL '1 hour');
                    """,
                    (active_student_id, fake_token_hash),
                )
                # Attempt to call execute_student_retention_erasure with 0 days
                # Function must check student's actual activity and REJECT (42501)
                with pytest.raises(psycopg.Error) as exc_info:
                    cur.execute(
                        "SELECT execute_student_retention_erasure(%s, %s, %s);",
                        (active_student_id, 30, fake_token_hash),
                    )
                assert exc_info.value.sqlstate == "42501"


def test_adversarial_unauthorized_function_call_rejected():
    """
    ADVERSARIAL ATTACK TEST:
    An attacker calls execute_student_retention_erasure directly without an
    explicit, valid record in retention_erasure_authorizations.
    Must be rejected with authorization error (42501)!
    """
    with get_db_connection(test=True) as conn:
        victim_id, _ = _seed_test_student(conn, inactive_days=100)
        conn.commit()

        fake_token_hash = "a" * 64

        with conn.transaction():
            with conn.cursor() as cur:
                with pytest.raises(psycopg.Error) as exc_info:
                    cur.execute(
                        "SELECT execute_student_retention_erasure(%s, %s, %s);",
                        (victim_id, 30, fake_token_hash),
                    )
                assert "unauthorized erasure" in str(exc_info.value).lower()
                assert exc_info.value.sqlstate == "42501"

        # Victim's data remains untouched
        counts = inventory_student_data(conn, victim_id)
        assert counts["students"] == 1
        assert counts["daily_progress_logs"] == 1


def test_adversarial_premature_erasure_rejected_by_function():
    """
    ADVERSARIAL ATTACK TEST:
    An authorization is issued, but the student was active 2 days ago.
    The function must enforce the activity age cutoff and reject (22023)!
    """
    with get_db_connection(test=True) as conn:
        active_student_id, _ = _seed_test_student(conn, inactive_days=2)
        conn.commit()

        with conn.transaction():
            _, token_hash = create_retention_authorization(
                conn, active_student_id, "test_admin", retention_days=30
            )
            with pytest.raises(psycopg.Error) as exc_info:
                execute_student_erasure(conn, active_student_id, 30, token_hash)
            assert "too recent" in str(exc_info.value).lower()
            assert exc_info.value.sqlstate == "22023"

        # Records preserved
        counts = inventory_student_data(conn, active_student_id)
        assert counts["students"] == 1


def test_adversarial_direct_delete_on_audit_events_strictly_blocked():
    """
    ADVERSARIAL ATTACK TEST:
    An attacker attempts to DELETE from audit_events.
    audit_events must remain strictly immutable under all conditions!
    """
    with get_db_connection(test=True) as conn:
        student_id, _ = _seed_test_student(conn, inactive_days=100)
        conn.commit()

        with pytest.raises(psycopg.Error) as exc_info:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM audit_events;")
        assert "append-only" in str(exc_info.value).lower()
        assert exc_info.value.sqlstate == "42501"


# ==============================================================================
# AUTHORIZED RETENTION ERASURE & INTEGRITY TESTS
# ==============================================================================


def test_authorized_retention_erasure_execution():
    """
    Verify complete, legitimate erasure flow:
    1. Independent authorization created.
    2. Privileged function executes erasure.
    3. Foreign keys stay enforced.
    4. Target student records wiped.
    5. Anonymous receipt created.
    """
    with get_db_connection(test=True) as conn:
        student_id, _ = _seed_test_student(conn, inactive_days=100)
        conn.commit()

        with conn.transaction():
            auth_id, token_hash = create_retention_authorization(
                conn, student_id, "authorized_operator", retention_days=30
            )
            counts = execute_student_erasure(conn, student_id, 30, token_hash)

        assert counts["students"] == 1
        assert counts["daily_progress_logs"] == 1
        assert counts["study_plans"] == 1

        # Verify all student data is gone
        after_counts = inventory_student_data(conn, student_id)
        assert all(c == 0 for c in after_counts.values())

        # Verify authorization is marked consumed
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT consumed_at FROM retention_erasure_authorizations WHERE id = %s;",
                (auth_id,),
            )
            row = cur.fetchone()
            assert row is not None
            assert row["consumed_at"] is not None

        # Verify non-identifying audit receipt exists
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT action, resource_type, resource_id, metadata, student_id
                FROM audit_events
                WHERE action = 'student.retention_erasure'
                ORDER BY occurred_at DESC LIMIT 1;
                """
            )
            receipt = cur.fetchone()
            assert receipt is not None
            assert receipt["action"] == "student.retention_erasure"
            assert receipt["student_id"] is None
            assert receipt["resource_id"] == "REDACTED"
            meta = receipt["metadata"]
            if isinstance(meta, str):
                meta = json.loads(meta)
            assert meta["retention_policy_days"] == 30
            assert meta["erased_counts"]["students"] == 1
            assert meta["policy_version"] == "5.0_preimage_sha256"


def test_erasure_preserves_unrelated_students():
    """Verify executing authorized erasure on student A leaves student B completely intact."""
    with get_db_connection(test=True) as conn:
        student_a, _ = _seed_test_student(conn, inactive_days=100)
        student_b, _ = _seed_test_student(conn, inactive_days=100)
        conn.commit()

        # Erase student A
        with conn.transaction():
            _, token_hash = create_retention_authorization(
                conn, student_a, "admin", retention_days=30
            )
            execute_student_erasure(conn, student_a, 30, token_hash)

        # Verify student A is gone
        counts_a = inventory_student_data(conn, student_a)
        assert all(c == 0 for c in counts_a.values())

        # Verify student B is completely intact
        counts_b = inventory_student_data(conn, student_b)
        assert counts_b["students"] == 1
        assert counts_b["daily_progress_logs"] == 1
        assert counts_b["study_plans"] == 1
        assert counts_b["intake_sessions"] == 1


def test_erasure_rollback_on_failure():
    """Verify failure during erasure transaction rolls back all changes."""
    with get_db_connection(test=True) as conn:
        student_id, _ = _seed_test_student(conn, inactive_days=100)
        conn.commit()

        try:
            with conn.transaction():
                _, token_hash = create_retention_authorization(
                    conn, student_id, "admin", retention_days=30
                )
                execute_student_erasure(conn, student_id, 30, token_hash)
                # Simulate an unexpected failure right after erasure before commit
                raise RuntimeError("Simulated failure during erasure transaction")
        except RuntimeError:
            pass

        # All records for student must survive intact due to transaction rollback
        counts = inventory_student_data(conn, student_id)
        assert counts["students"] == 1
        assert counts["daily_progress_logs"] == 1
        assert counts["study_plans"] == 1
