"""Sensitive backend writes and their minimal audit records must succeed together."""

import json
from uuid import uuid4

import pytest

from app.core.db import get_db_connection
from app.modules.consultation.repository import ConsultationRepository
from app.modules.identity.repository import IdentityRepository
from app.modules.operations.repository import OperationsRepository
from app.modules.operations.router import GrantEntitlementRequest, grant_entitlement


def new_student(conn):
    external = uuid4().int % 10**12 + 10**12
    return IdentityRepository.get_or_create_student(conn, external, external), external


def save_plan(conn, student, plan_id, revision):
    return ConsultationRepository.save_study_plan(
        conn, plan_id, student, revision, "upper_secondary", "test-engine", "test-rules", {}, []
    )


def test_identity_creation_is_audited_once_without_external_identity():
    with get_db_connection(test=True) as conn:
        student, external = new_student(conn)
        assert IdentityRepository.get_or_create_student(conn, external, external) == student
        rows = conn.execute(
            "SELECT action,resource_id,metadata FROM audit_events WHERE student_id=%s", (student,)
        ).fetchall()
        assert rows == [
            {"action": "student.identity.created", "resource_id": str(student), "metadata": {}}
        ]
        assert str(external) not in json.dumps(rows)


@pytest.mark.parametrize("implicit", [False, True])
def test_superseding_plan_records_each_transition_once(implicit):
    with get_db_connection(test=True) as conn:
        student, _ = new_student(conn)
        old, new = uuid4(), uuid4()
        save_plan(conn, student, old, 1)
        if implicit:
            save_plan(conn, student, new, 2)
        else:
            ConsultationRepository.supersede_plan(conn, old, student_id=student)
            ConsultationRepository.supersede_plan(conn, old, student_id=student)
        rows = conn.execute(
            "SELECT resource_id,metadata FROM audit_events "
            "WHERE student_id=%s AND action='study_plan.superseded'",
            (student,),
        ).fetchall()
        assert rows == [{"resource_id": str(old), "metadata": {"revision_no": 1}}]


class AuditFailureCursor:
    def __init__(self, cursor, action):
        self.cursor = cursor
        self.action = action

    def __enter__(self):
        self.cursor.__enter__()
        return self

    def __exit__(self, *args):
        return self.cursor.__exit__(*args)

    def execute(self, statement, *args, **kwargs):
        text = str(statement).lower()
        if "insert into audit_events" in text and (self.action is None or self.action in text):
            raise RuntimeError("synthetic audit unavailable")
        return self.cursor.execute(statement, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class AuditFailureConnection:
    def __init__(self, conn, action=None):
        self.conn = conn
        self.action = action

    def cursor(self, *args, **kwargs):
        return AuditFailureCursor(self.conn.cursor(*args, **kwargs), self.action)

    def __getattr__(self, name):
        return getattr(self.conn, name)


@pytest.mark.parametrize("operation", ["identity", "profile", "plan", "progress", "supersede"])
def test_audit_failure_rolls_back_business_write(operation):
    with get_db_connection(test=True) as conn:
        student, external = new_student(conn)
        old = uuid4()
        save_plan(conn, student, old, 1)
        conn.commit()
        before_student = conn.execute("SELECT * FROM students WHERE id=%s", (student,)).fetchone()
        before_plans = conn.execute(
            "SELECT * FROM study_plans WHERE student_id=%s ORDER BY id", (student,)
        ).fetchall()
        before_audit = conn.execute(
            "SELECT * FROM audit_events WHERE student_id=%s ORDER BY id", (student,)
        ).fetchall()
    with pytest.raises(RuntimeError, match="synthetic audit unavailable"):
        with get_db_connection(test=True) as conn:
            # For activation, fail after old-plan supersession and the new insert.
            guarded = AuditFailureConnection(
                conn, "'study_plan.activated'" if operation == "plan" else None
            )
            if operation == "identity":
                IdentityRepository.get_or_create_student(guarded, external + 1, external + 1)
            elif operation == "profile":
                IdentityRepository.update_student_profile(guarded, student, grade="G11")
            elif operation == "plan":
                save_plan(guarded, student, uuid4(), 2)
            elif operation == "progress":
                ConsultationRepository.record_daily_progress(guarded, student, old, 1, [], [], 0)
            else:
                ConsultationRepository.supersede_plan(guarded, old, student_id=student)
    with get_db_connection(test=True) as conn:
        assert (
            conn.execute("SELECT * FROM students WHERE id=%s", (student,)).fetchone()
            == before_student
        )
        assert (
            conn.execute(
                "SELECT * FROM study_plans WHERE student_id=%s ORDER BY id", (student,)
            ).fetchall()
            == before_plans
        )
        assert (
            conn.execute(
                "SELECT * FROM audit_events WHERE student_id=%s ORDER BY id", (student,)
            ).fetchall()
            == before_audit
        )
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM students WHERE telegram_user_id=%s", (external + 1,)
            ).fetchone()["n"]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM daily_progress_logs WHERE student_id=%s", (student,)
            ).fetchone()["n"]
            == 0
        )


@pytest.mark.parametrize("assertion", ["true", "t", 1, "false", 0])
def test_repository_rejects_nonbool_guardian_consent(assertion):
    with get_db_connection(test=True) as conn:
        student, _ = new_student(conn)
        with pytest.raises(ValueError, match="boolean"):
            IdentityRepository.update_student_profile(conn, student, guardian_consent=assertion)
        assert IdentityRepository.get_student_profile(conn, student)["guardian_consent"] is None


@pytest.mark.parametrize("assertion", [True, False])
def test_repository_records_guardian_consent_profile_assertion_and_audit(assertion):
    with get_db_connection(test=True) as conn:
        student, _ = new_student(conn)
        IdentityRepository.update_student_profile(conn, student, guardian_consent=assertion)
        profile = IdentityRepository.get_student_profile(conn, student)
        assert profile["guardian_consent"] is assertion
        event = conn.execute(
            "SELECT metadata FROM audit_events "
            "WHERE student_id=%s AND action='student.profile.update'",
            (student,),
        ).fetchone()
        assert event["metadata"] == {"changes": {"guardian_consent": assertion}}


def test_permission_audit_failure_rolls_back_entitlement(monkeypatch):
    with get_db_connection(test=True) as conn:
        student, _ = new_student(conn)
        conn.commit()

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit unavailable")

    monkeypatch.setattr(OperationsRepository, "record_audit_event", fail)
    key = str(uuid4())
    with pytest.raises(RuntimeError, match="synthetic audit unavailable"):
        grant_entitlement(GrantEntitlementRequest(student_id=student, feature_key=key))
    with get_db_connection(test=True) as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM entitlements WHERE student_id=%s AND feature_key=%s",
                (student, key),
            ).fetchone()["n"]
            == 0
        )
