"""Phase 1 negative contracts. Real isolated PostgreSQL; no provider calls."""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import get_db_connection
from app.main import app
from app.modules.consultation.repository import ConsultationRepository
from app.modules.identity.repository import IdentityRepository

client = TestClient(app)
TOKEN = "phase1-synthetic-token"


def headers(user_id, age=0):
    fields = {"auth_date": str(int(time.time()) - age), "user": json.dumps({"id": user_id})}
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return {"Authorization": "tma " + urlencode(fields)}


@pytest.fixture
def students(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "testing")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "phase1-synthetic-admin")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "phase1-synthetic-webhook")
    # Per-test random IDs avoid destructive cleanup of other suites' fixtures.
    base = uuid4().int % 10**12 + 10**12
    with get_db_connection(test=True) as conn:
        ids = [IdentityRepository.get_or_create_student(conn, base + n, base + n) for n in range(2)]
        conn.commit()
    return ids, base


@pytest.mark.parametrize("age,user", [(301, None), (-61, None), (0, True)])
def test_invalid_signed_credentials(students, age, user):
    _, base = students
    assert (
        client.get(
            "/api/v1/identity/me", headers=headers(base if user is None else user, age)
        ).status_code
        == 401
    )


@pytest.mark.parametrize("authorization", ["tma broken", "tma hash=x&hash=y", "Bearer arbitrary"])
def test_malformed_credentials(students, authorization):
    assert (
        client.get("/api/v1/identity/me", headers={"Authorization": authorization}).status_code
        == 401
    )


def test_identity_injection_cannot_change_other_student(students):
    (a, b), base = students
    auth = {**headers(base), "X-Student-Id": str(b)}
    response = client.patch(
        f"/api/v1/identity/me?student_id={b}",
        headers=auth,
        json={"student_id": str(b), "grade": "G11"},
    )
    assert response.status_code in (200, 422)
    assert client.get("/api/v1/identity/me", headers=headers(base + 1)).json()["grade"] is None
    own = client.get(f"/api/v1/identity/me?student_id={b}", headers=auth)
    assert own.json()["id"] == str(a)


@pytest.mark.parametrize("assertion", [True, False])
def test_guardian_consent_profile_assertion_is_scoped_to_authenticated_student(students, assertion):
    (own, foreign), base = students
    response = client.patch(
        f"/api/v1/identity/me?student_id={foreign}",
        headers={**headers(base), "X-Student-Id": str(foreign)},
        json={"guardian_consent": assertion},
    )
    assert response.status_code == 200
    assert response.json()["id"] == str(own)
    assert response.json()["guardian_consent"] is assertion
    assert client.get(
        "/api/v1/identity/me", headers=headers(base + 1)
    ).json()["guardian_consent"] is None
    assert client.get("/api/v1/admin/audit-logs", headers=headers(base)).status_code == 403


@pytest.mark.parametrize("assertion", ["true", "false", "t", 1, 0])
def test_guardian_consent_http_requires_exact_bool(students, assertion):
    _, base = students
    response = client.patch(
        "/api/v1/identity/me", headers=headers(base), json={"guardian_consent": assertion}
    )
    assert response.status_code == 422
    assert client.get(
        "/api/v1/identity/me", headers=headers(base)
    ).json()["guardian_consent"] is None


def test_mapping_cannot_be_rebound(students):
    _, base = students
    with get_db_connection(test=True) as conn:
        with pytest.raises((ValueError, psycopg.IntegrityError)):
            IdentityRepository.get_or_create_student(conn, base, base + 1)


def test_mapping_retry_is_stable(students):
    (a, _), base = students
    with get_db_connection(test=True) as conn:
        assert IdentityRepository.get_or_create_student(conn, base, base) == a
        assert ConsultationRepository.get_or_create_student(conn, base, base) == a


def test_identity_mutation_rolls_back_on_failure(students):
    (a, _), base = students
    with pytest.raises(psycopg.IntegrityError):
        with get_db_connection(test=True) as conn:
            IdentityRepository.update_student_profile(conn, a, grade="G11")
            conn.execute(
                "INSERT INTO students(telegram_chat_id, telegram_user_id) VALUES(%s,%s)",
                (base + 2, base),
            )
    assert client.get("/api/v1/identity/me", headers=headers(base)).json()["grade"] is None


def test_external_identity_cannot_have_second_student(students):
    _, base = students
    with get_db_connection(test=True) as conn:
        with pytest.raises(psycopg.IntegrityError):
            conn.execute(
                "INSERT INTO students (telegram_chat_id, telegram_user_id) VALUES (%s,%s)",
                (base + 2, base),
            )


def test_foreign_intake_mutation_rejected(students):
    (a, b), _ = students
    with get_db_connection(test=True) as conn:
        session = ConsultationRepository.create_intake_session(conn, b)
        ConsultationRepository.update_intake_session(conn, session["id"], "goal", {}, student_id=a)
        row = conn.execute(
            "SELECT current_step FROM intake_sessions WHERE id=%s", (session["id"],)
        ).fetchone()
        assert row["current_step"] == "stage"


def plan(conn, student):
    return conn.execute(
        "INSERT INTO study_plans(student_id, stage_code) "
        "VALUES (%s,'upper_secondary') RETURNING id",
        (student,),
    ).fetchone()["id"]


def test_foreign_plan_mutation_rejected(students):
    (a, b), _ = students
    with get_db_connection(test=True) as conn:
        foreign = plan(conn, b)
        ConsultationRepository.supersede_plan(conn, foreign, student_id=a)
        assert (
            conn.execute("SELECT status FROM study_plans WHERE id=%s", (foreign,)).fetchone()[
                "status"
            ]
            == "active"
        )


@pytest.mark.parametrize("kind", ["item", "progress", "revision"])
def test_database_enforces_plan_ownership(students, kind):
    (a, b), _ = students
    with get_db_connection(test=True) as conn:
        foreign = plan(conn, b)
        with pytest.raises(psycopg.IntegrityError):
            if kind == "item":
                conn.execute(
                    "INSERT INTO study_plan_items(plan_id, student_id,item_order,"
                    "resource_version_id,stage_code,duration_minutes) "
                    "VALUES(%s,%s,1,'synthetic','upper_secondary',10)",
                    (foreign, a),
                )
            else:
                conn.execute(
                    "INSERT INTO daily_progress_logs(student_id,plan_id,revision_no) "
                    "VALUES(%s,%s,%s)",
                    (b if kind == "revision" else a, foreign, 99 if kind == "revision" else 1),
                )


@pytest.mark.parametrize("path", ["/api/v1/admin/outbox/health", "/api/v1/admin/audit-logs"])
def test_student_token_has_no_admin_authority(students, path):
    _, base = students
    assert client.get(path, headers=headers(base)).status_code == 403


def test_context_and_history_exclude_other_student(students):
    (a, b), base = students
    with get_db_connection(test=True) as conn:
        foreign = plan(conn, b)
        conn.execute(
            "INSERT INTO daily_progress_logs(student_id,plan_id,revision_no,student_notes) "
            "VALUES(%s,%s,1,'foreign-evidence')",
            (b, foreign),
        )
        conn.commit()
    context = client.get(f"/api/v1/identity/context?student_id={b}", headers=headers(base))
    assert context.status_code == 200
    assert context.json()["student"]["id"] == str(a)
    assert context.json()["active_plan"] is None
    assert context.json()["progress_summary"]["total_logs"] == 0
    history = client.get(f"/api/v1/consultation/history?student_id={b}", headers=headers(base))
    assert history.status_code == 200
    assert "foreign-evidence" not in history.text


def test_oversized_webhook_identity_ignored(students):
    huge = 2**63
    response = client.post(
        "/api/v1/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "phase1-synthetic-webhook"},
        json={
            "update_id": 1,
            "message": {
                "chat": {"id": huge, "type": "private"},
                "from": {"id": huge},
                "text": "/start",
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def student_snapshot(conn, student):
    """Capture full persisted rows, including notifications and retry dedup state."""
    snapshot = {}
    for table in (
        "students",
        "study_plans",
        "study_plan_items",
        "daily_progress_logs",
        "outbox_events",
        "idempotency_keys",
    ):
        column = "id" if table == "students" else "student_id"
        snapshot[table] = conn.execute(
            f"SELECT * FROM {table} WHERE {column}=%s ORDER BY 1", (student,)
        ).fetchall()
    return snapshot


def test_progress_and_plan_identity_injection_cannot_touch_foreign_state(students):
    (a, b), base = students
    with get_db_connection(test=True) as conn:
        own_plan, foreign_plan = plan(conn, a), plan(conn, b)
        for owner, plan_id, marker in (
            (a, own_plan, "own-unit"),
            (b, foreign_plan, "foreign-unit"),
        ):
            conn.execute(
                "INSERT INTO study_plan_items(plan_id,student_id,item_order,"
                "resource_version_id,stage_code,duration_minutes) "
                "VALUES(%s,%s,1,%s,'upper_secondary',10)",
                (plan_id, owner, marker),
            )
        event = ConsultationRepository.enqueue_outbox_event(
            conn,
            b,
            "TELEGRAM_MESSAGE_REQUESTED",
            "study_plan",
            str(foreign_plan),
            {"telegram_chat_id": base + 1, "message_text": "foreign-notification"},
        )
        conn.commit()
        before = student_snapshot(conn, b)
    auth = {**headers(base), "X-Student-Id": str(b), "Idempotency-Key": str(uuid4())}
    response = client.post(
        f"/api/v1/consultation/progress?student_id={b}",
        headers=auth,
        json={
            "student_id": str(b),
            "completed_units": ["foreign-unit"],
            "duration_spent_minutes": 10,
        },
    )
    assert response.status_code == 422
    active = client.get(f"/api/v1/consultation/active-plan?student_id={b}", headers=auth)
    assert active.status_code == 200
    # Neither synthetic stored plan has a reviewed catalog resource. Student reads
    # withhold untrusted plans while keeping identity isolation and persisted state.
    assert active.json()["status"] == "awaiting_content"
    assert active.json()["student_id"] == str(a)
    assert active.json()["plan"] is None
    assert "own-unit" not in active.text
    assert "foreign-unit" not in active.text
    assert client.get(f"/api/v1/admin/students/{b}/plans", headers=auth).status_code == 403
    assert client.post(f"/api/v1/admin/outbox/{event}/retry", headers=auth).status_code == 403
    with get_db_connection(test=True) as conn:
        assert student_snapshot(conn, b) == before
        assert ConsultationRepository.get_active_study_plan(conn, a)["id"] == own_plan


@pytest.mark.parametrize(
    "method,path",
    [
        ("PATCH", "/api/v1/identity/me"),
        ("GET", "/api/v1/consultation/me"),
    ],
)
def test_remaining_student_routes_require_credentials(students, method, path):
    assert client.request(method, path, json={}).status_code == 401


@pytest.mark.parametrize("rollback", [False, True])
def test_plan_and_progress_audit_are_atomic_and_minimal(students, rollback):
    (student, _), base = students
    plan_id = uuid4()
    progress_id = None

    def write_and_check(conn):
        nonlocal progress_id
        ConsultationRepository.save_study_plan(
            conn,
            plan_id,
            student,
            1,
            "upper_secondary",
            "synthetic-engine",
            "synthetic-rules",
            {"private_note": "must-not-enter-audit"},
            [],
        )
        progress_id = ConsultationRepository.record_daily_progress(
            conn,
            student,
            plan_id,
            1,
            [],
            [],
            0,
            "must-not-enter-audit",
        )
        rows = conn.execute(
            "SELECT action,resource_type,resource_id,metadata FROM audit_events "
            "WHERE student_id=%s ORDER BY action",
            (student,),
        ).fetchall()
        assert rows == [
            {
                "action": "progress.recorded",
                "resource_type": "daily_progress_log",
                "resource_id": str(progress_id),
                "metadata": {"plan_id": str(plan_id), "revision_no": 1},
            },
            {
                "action": "student.identity.created",
                "resource_type": "student",
                "resource_id": str(student),
                "metadata": {},
            },
            {
                "action": "study_plan.activated",
                "resource_type": "study_plan",
                "resource_id": str(plan_id),
                "metadata": {
                    "revision_no": 1,
                    "engine_version": "synthetic-engine",
                    "rule_set_version": "synthetic-rules",
                },
            },
        ]
        assert "must-not-enter-audit" not in json.dumps(rows)
        if rollback:
            conn.execute(
                "INSERT INTO students(telegram_chat_id,telegram_user_id) VALUES(%s,%s)",
                (base + 2, base),
            )

    if rollback:
        with pytest.raises(psycopg.IntegrityError):
            with get_db_connection(test=True) as conn:
                write_and_check(conn)
    else:
        with get_db_connection(test=True) as conn:
            write_and_check(conn)
            conn.commit()
    with get_db_connection(test=True) as conn:
        assert conn.execute(
            "SELECT count(*) AS n FROM audit_events WHERE student_id=%s",
            (student,),
        ).fetchone()["n"] == (1 if rollback else 3)
        assert conn.execute(
            "SELECT count(*) AS n FROM study_plans WHERE id=%s",
            (plan_id,),
        ).fetchone()["n"] == (0 if rollback else 1)
        assert conn.execute(
            "SELECT count(*) AS n FROM daily_progress_logs WHERE id=%s",
            (progress_id,),
        ).fetchone()["n"] == (0 if rollback else 1)
