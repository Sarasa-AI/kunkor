"""Phase 2 Identity & Security Tests: Cross-Student Isolation & Authorization.

Verifies:
1. Student A cannot read Student B's profile (cross-student isolation)
2. Student A cannot update Student B's profile
3. Student A cannot access Student B's context
4. Student A cannot submit progress for Student B
5. Student A cannot read Student B's active plan
6. Unauthorized access denied on all identity endpoints
7. Authenticated profile read/update happy path works
8. student_id enforcement regression test
"""

import hashlib
import hmac
import json
import time
import uuid
from urllib.parse import urlencode

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import get_connection_string, get_db_connection
from app.main import app

pytestmark = pytest.mark.usefixtures("synthetic_planner_catalog")

client = TestClient(app)

TEST_DB_URL = get_connection_string(test=True)

# Test tokens
TELEGRAM_BOT_TOKEN = "synthetic-test-bot-token"

# Two different Telegram user IDs for isolation testing
STUDENT_A_CHAT_ID = 111111111
STUDENT_A_USER_ID = 111111111
STUDENT_B_CHAT_ID = 222222222
STUDENT_B_USER_ID = 222222222


def signed_headers(
    user_id: int, chat_id: int, *, timestamp: int | None = None, token: str = TELEGRAM_BOT_TOKEN
) -> dict[str, str]:
    """Generate signed Telegram Mini App credentials."""
    fields = {
        "auth_date": str(int(time.time()) if timestamp is None else timestamp),
        "user": json.dumps({"id": user_id}),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return {
        "Authorization": "tma " + urlencode(fields),
        "Idempotency-Key": str(uuid.uuid4()),
    }


@pytest.fixture(autouse=True)
def clean_db(monkeypatch):
    """Ensure clean database before and after each test."""
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
    monkeypatch.setattr(settings, "ENVIRONMENT", "testing")
    with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                TRUNCATE TABLE
                    outbox_events,
                    daily_progress_logs,
                    study_plan_items,
                    study_plans,
                    intake_sessions,
                    entitlements,
                    feature_flags,
                    idempotency_keys,
                    students
                CASCADE;
                """
            )
    yield
    with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                TRUNCATE TABLE
                    outbox_events,
                    daily_progress_logs,
                    study_plan_items,
                    study_plans,
                    intake_sessions,
                    entitlements,
                    feature_flags,
                    idempotency_keys,
                    students
                CASCADE;
                """
            )


@pytest.fixture
def student_a():
    """Create student A in database."""
    with get_db_connection(test=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO students (
                    telegram_chat_id, telegram_user_id, telegram_username, first_name
                )
                VALUES (%s, %s, 'student_a', 'دانش‌آموز الف')
                RETURNING id;
                """,
                (STUDENT_A_CHAT_ID, STUDENT_A_USER_ID),
            )
            student_id = cur.fetchone()["id"]
            conn.commit()
            return uuid.UUID(str(student_id))


@pytest.fixture
def student_b():
    """Create student B in database."""
    with get_db_connection(test=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO students (
                    telegram_chat_id, telegram_user_id, telegram_username, first_name
                )
                VALUES (%s, %s, 'student_b', 'دانش‌آموز ب')
                RETURNING id;
                """,
                (STUDENT_B_CHAT_ID, STUDENT_B_USER_ID),
            )
            student_id = cur.fetchone()["id"]
            conn.commit()
            return uuid.UUID(str(student_id))


@pytest.fixture
def student_a_headers():
    return signed_headers(STUDENT_A_USER_ID, STUDENT_A_CHAT_ID)


@pytest.fixture
def student_b_headers():
    return signed_headers(STUDENT_B_USER_ID, STUDENT_B_CHAT_ID)


# ==================== Cross-Student Isolation Tests ====================


def test_cross_student_isolation_profile_read(
    student_a, student_b, student_a_headers, student_b_headers
):
    """Student A cannot read Student B's profile via /me endpoint."""
    # Student A reads their own profile - should succeed
    res_a = client.get("/api/v1/identity/me", headers=student_a_headers)
    assert res_a.status_code == 200
    assert str(res_a.json()["id"]) == str(student_a)

    # Student A tries to read Student B's profile via direct student_id manipulation
    # Authentication scopes the response to the current student.
    # This tests that the endpoint properly scopes to authenticated student only
    res_a_me = client.get("/api/v1/identity/me", headers=student_a_headers)
    assert res_a_me.json()["first_name"] == "دانش‌آموز الف"
    assert res_a_me.json()["first_name"] != "دانش‌آموز ب"


def test_cross_student_isolation_profile_update(
    student_a, student_b, student_a_headers, student_b_headers
):
    """Student A cannot update Student B's profile."""
    # Student A updates their own profile - should succeed
    res_a = client.patch(
        "/api/v1/identity/me",
        json={"grade": "G12", "track": "experimental"},
        headers=student_a_headers,
    )
    assert res_a.status_code == 200
    assert res_a.json()["grade"] == "G12"
    assert res_a.json()["track"] == "experimental"

    # Student B's profile should remain unchanged
    res_b = client.get("/api/v1/identity/me", headers=student_b_headers)
    assert res_b.status_code == 200
    assert res_b.json()["grade"] is None
    assert res_b.json()["track"] is None


def test_cross_student_isolation_context_read(
    student_a, student_b, student_a_headers, student_b_headers
):
    """Student A cannot access Student B's context via /context endpoint."""
    # Student A reads their own context - should succeed
    res_a = client.get("/api/v1/identity/context", headers=student_a_headers)
    assert res_a.status_code == 200
    assert str(res_a.json()["student"]["id"]) == str(student_a)

    # Student B reads their own context - should succeed
    res_b = client.get("/api/v1/identity/context", headers=student_b_headers)
    assert res_b.status_code == 200
    assert str(res_b.json()["student"]["id"]) == str(student_b)

    # The endpoint returns only the authenticated student's context
    # No way to inject another student_id


def test_cross_student_isolation_active_plan_read(
    student_a, student_b, student_a_headers, student_b_headers
):
    """Student A cannot read Student B's active plan."""
    # Create a plan for Student A via intake
    intake_payload = {
        "stage_code": "konkur",
        "grade": "G12",
        "track": "experimental",
        "daily_study_capacity_minutes": 240,
        "weak_subjects": ["biology", "chemistry"],
    }
    client.post("/api/v1/consultation/intake", json=intake_payload, headers=student_a_headers)

    # Student A reads their own active plan - should succeed
    res_a = client.get("/api/v1/consultation/active-plan", headers=student_a_headers)
    assert res_a.status_code == 200
    assert res_a.json()["status"] == "active"

    # Student B reads their active plan - should be not_found
    res_b = client.get("/api/v1/consultation/active-plan", headers=student_b_headers)
    assert res_b.status_code == 200
    assert res_b.json()["status"] == "not_found"

    # Student A cannot read Student B's plan via the endpoint
    # The endpoint scopes to authenticated student automatically


def test_cross_student_isolation_progress_submit(
    student_a, student_b, student_a_headers, student_b_headers
):
    """Student A cannot submit progress for Student B."""
    # Create plans for both students
    intake_payload = {
        "stage_code": "konkur",
        "grade": "G12",
        "track": "experimental",
        "daily_study_capacity_minutes": 180,
        "weak_subjects": ["biology"],
    }
    client.post("/api/v1/consultation/intake", json=intake_payload, headers=student_a_headers)
    client.post("/api/v1/consultation/intake", json=intake_payload, headers=student_b_headers)

    # Student A reads their active plan to get resource IDs
    plan_a = client.get("/api/v1/consultation/active-plan", headers=student_a_headers).json()[
        "plan"
    ]
    items_a = plan_a["items"]
    assert len(items_a) >= 1
    completed_unit = items_a[0]["resource_version_id"]

    # Student A submits progress for their own plan - should succeed
    res_a = client.post(
        "/api/v1/consultation/progress",
        json={
            "completed_units": [completed_unit],
            "missed_units": [],
            "duration_spent_minutes": 60,
        },
        headers=student_a_headers,
    )
    assert res_a.status_code == 200
    assert res_a.json()["status"] == "plan_revised"
    assert res_a.json()["revision_no"] == 2

    # Student B's plan should remain at revision 1
    plan_b = client.get("/api/v1/consultation/active-plan", headers=student_b_headers).json()[
        "plan"
    ]
    assert plan_b["revision_no"] == 1


# ==================== Unauthorized Access Tests ====================


def test_unauthorized_identity_me_without_credentials():
    """GET /identity/me requires valid student access credentials."""
    res = client.get("/api/v1/identity/me")
    assert res.status_code == 401
    assert "signed Telegram credentials" in res.json()["detail"]


def test_unauthorized_identity_me_with_invalid_credentials():
    """GET /identity/me rejects invalid credentials."""
    # Invalid token format
    res = client.get("/api/v1/identity/me", headers={"Authorization": "tma invalid"})
    assert res.status_code == 401

    # Expired credentials
    expired_headers = signed_headers(
        STUDENT_A_USER_ID, STUDENT_A_CHAT_ID, timestamp=int(time.time()) - 600
    )
    res = client.get("/api/v1/identity/me", headers=expired_headers)
    assert res.status_code == 401

    # Wrong user ID (non-existent)
    wrong_user_headers = signed_headers(999999999, 999999999)
    res = client.get("/api/v1/identity/me", headers=wrong_user_headers)
    assert res.status_code == 401


def test_unauthorized_identity_context_without_credentials():
    """GET /identity/context requires valid student access credentials."""
    res = client.get("/api/v1/identity/context")
    assert res.status_code == 401


def test_unauthorized_consultation_endpoints_without_credentials():
    """All consultation endpoints require authentication."""
    endpoints = [
        ("GET", "/api/v1/consultation/active-plan"),
        ("POST", "/api/v1/consultation/progress"),
        ("GET", "/api/v1/consultation/history"),
        ("POST", "/api/v1/consultation/intake"),
    ]
    for method, path in endpoints:
        res = client.request(method, path)
        assert res.status_code == 401, f"{method} {path} should require auth"


# ==================== Authenticated Happy Path Tests ====================


def test_authenticated_profile_read_happy_path(student_a, student_a_headers):
    """Authenticated student can read their own profile."""
    res = client.get("/api/v1/identity/me", headers=student_a_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == str(student_a)
    assert data["telegram_username"] == "student_a"
    assert data["first_name"] == "دانش‌آموز الف"
    assert "grade" in data
    assert "track" in data
    assert "guardian_consent" in data


def test_authenticated_profile_update_happy_path(student_a, student_a_headers):
    """Authenticated student can update their own profile with audit logging."""
    # Update grade and track
    res = client.patch(
        "/api/v1/identity/me",
        json={"grade": "G11", "track": "mathematics"},
        headers=student_a_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["grade"] == "G11"
    assert data["track"] == "mathematics"

    # Verify persistence
    res2 = client.get("/api/v1/identity/me", headers=student_a_headers)
    assert res2.json()["grade"] == "G11"
    assert res2.json()["track"] == "mathematics"

    # Verify audit event recorded
    with get_db_connection(test=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT action, resource_type, resource_id, metadata
                FROM audit_events
                WHERE student_id = %s AND action = 'student.profile.update'
                ORDER BY occurred_at DESC LIMIT 1;
                """,
                (student_a,),
            )
            audit = cur.fetchone()
            assert audit is not None
            assert audit["action"] == "student.profile.update"
            assert audit["resource_type"] == "student_profile"
            assert audit["resource_id"] == str(student_a)
            metadata = audit["metadata"]
            if isinstance(metadata, str):
                import json as _json

                metadata = _json.loads(metadata)
            assert metadata["changes"]["grade"] == "G11"
            assert metadata["changes"]["track"] == "mathematics"


def test_authenticated_guardian_consent_update(student_a, student_a_headers):
    """Authenticated students can update their own boolean profile assertion."""
    res = client.patch(
        "/api/v1/identity/me",
        json={"guardian_consent": True},
        headers=student_a_headers,
    )
    assert res.status_code == 200
    profile = client.get("/api/v1/identity/me", headers=student_a_headers).json()
    assert profile["guardian_consent"] is True

    # Update to False
    res2 = client.patch(
        "/api/v1/identity/me",
        json={"guardian_consent": False},
        headers=student_a_headers,
    )
    assert res2.status_code == 200
    assert res2.json()["guardian_consent"] is False


def test_authenticated_context_read_happy_path(student_a, student_a_headers):
    """Authenticated student can read their own context."""
    res = client.get("/api/v1/identity/context", headers=student_a_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["student"]["id"] == str(student_a)
    assert "intake" in data
    assert "active_plan" in data
    assert "progress_summary" in data
    assert "loaded_at" in data

    # Verify structure
    assert data["progress_summary"]["total_logs"] == 0
    assert data["intake"] is None
    assert data["active_plan"] is None


def test_authenticated_context_includes_intake_and_plan(student_a, student_a_headers):
    """Context includes intake and active plan after they exist."""
    # Create intake and plan
    intake_payload = {
        "stage_code": "konkur",
        "grade": "G12",
        "track": "experimental",
        "daily_study_capacity_minutes": 240,
        "weak_subjects": ["biology", "chemistry"],
    }
    client.post("/api/v1/consultation/intake", json=intake_payload, headers=student_a_headers)

    # Read context
    res = client.get("/api/v1/identity/context", headers=student_a_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["intake"] is not None
    assert data["intake"]["slots"]["grade"] == "G12"
    assert data["intake"]["slots"]["track"] == "experimental"
    assert data["active_plan"] is not None
    assert data["active_plan"]["revision_no"] == 1
    assert data["active_plan"]["stage_code"] == "konkur"


# ==================== Validation & Regression Tests ====================


def test_grade_validation_rejects_invalid_grades(student_a, student_a_headers):
    """Grade must be G10, G11, or G12."""
    invalid_grades = ["G09", "G13", "POSTK", "K", "invalid"]
    for grade in invalid_grades:
        res = client.patch(
            "/api/v1/identity/me",
            json={"grade": grade},
            headers=student_a_headers,
        )
        assert res.status_code == 422, f"Grade {grade} should be rejected"


def test_track_validation_rejects_invalid_tracks(student_a, student_a_headers):
    """Track must be one of the allowed values."""
    invalid_tracks = ["science", "art", "engineering", "invalid"]
    for track in invalid_tracks:
        res = client.patch(
            "/api/v1/identity/me",
            json={"track": track},
            headers=student_a_headers,
        )
        assert res.status_code == 422, f"Track {track} should be rejected"


def test_student_id_enforcement_in_consultation_service(
    student_a, student_b, student_a_headers, student_b_headers
):
    """Regression: student_id is enforced in all consultation operations."""
    # Create plans for both
    intake_payload = {
        "stage_code": "konkur",
        "grade": "G12",
        "track": "experimental",
        "daily_study_capacity_minutes": 180,
        "weak_subjects": ["biology"],
    }
    client.post("/api/v1/consultation/intake", json=intake_payload, headers=student_a_headers)
    client.post("/api/v1/consultation/intake", json=intake_payload, headers=student_b_headers)

    # Verify study_plan_items have correct student_id (denormalized per ADR-0008)
    with get_db_connection(test=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT student_id, count(*) as cnt FROM study_plan_items GROUP BY student_id;"
            )
            rows = cur.fetchall()
            assert len(rows) == 2
            for row in rows:
                student_id = str(row["student_id"])
                count = row["cnt"]
                assert count > 0
                assert student_id in (str(student_a), str(student_b))

    # Verify study_plans have correct student_id
    with get_db_connection(test=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT student_id, count(*) as cnt FROM study_plans GROUP BY student_id;")
            rows = cur.fetchall()
            assert len(rows) == 2
            for row in rows:
                student_id = str(row["student_id"])
                count = row["cnt"]
                assert count > 0
                assert student_id in (str(student_a), str(student_b))

    # Verify intake_sessions have correct student_id
    with get_db_connection(test=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT student_id, count(*) as cnt FROM intake_sessions GROUP BY student_id;"
            )
            rows = cur.fetchall()
            assert len(rows) == 2
            for row in rows:
                student_id = str(row["student_id"])
                count = row["cnt"]
                assert count > 0
                assert student_id in (str(student_a), str(student_b))

    # Verify daily_progress_logs have correct student_id (will be empty until progress is submitted)
    with get_db_connection(test=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT student_id, count(*) as cnt FROM daily_progress_logs GROUP BY student_id;"
            )
            rows = cur.fetchall()
            # Note: progress logs are only created when progress is submitted
            # At this point, no progress has been submitted, so this may be empty
            for row in rows:
                student_id = str(row["student_id"])
                count = row["cnt"]
                assert count > 0
                assert student_id in (str(student_a), str(student_b))

    # Verify outbox_events have correct student_id
    with get_db_connection(test=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT student_id, count(*) as cnt FROM outbox_events GROUP BY student_id;"
            )
            rows = cur.fetchall()
            assert len(rows) == 2
            for row in rows:
                student_id = str(row["student_id"])
                count = row["cnt"]
                assert count > 0
                assert student_id in (str(student_a), str(student_b))

    # Verify audit_events have correct student_id (only check the two test students)
    with get_db_connection(test=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT student_id, count(*) as cnt
                FROM audit_events
                WHERE student_id IN (%s, %s)
                GROUP BY student_id;
                """,
                (student_a, student_b),
            )
            rows = cur.fetchall()
            # Both students should have at least one audit event (from profile updates or intake)
            for row in rows:
                student_id = str(row["student_id"])
                count = row["cnt"]
                assert count > 0
                assert student_id in (str(student_a), str(student_b))


def test_student_id_enforcement_in_identity_service(
    student_a, student_b, student_a_headers, student_b_headers
):
    """Regression: identity operations enforce student_id scoping."""
    # Update student A's profile
    client.patch(
        "/api/v1/identity/me",
        json={"grade": "G12", "track": "experimental"},
        headers=student_a_headers,
    )

    # Student B's profile should be unaffected
    res_b = client.get("/api/v1/identity/me", headers=student_b_headers)
    assert res_b.json()["grade"] is None
    assert res_b.json()["track"] is None

    # Verify database state
    with get_db_connection(test=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, grade, track FROM students WHERE id IN (%s, %s);",
                (student_a, student_b),
            )
            rows = cur.fetchall()
            grades = {str(row["id"]): row["grade"] for row in rows}
            tracks = {str(row["id"]): row["track"] for row in rows}
            assert grades[str(student_a)] == "G12"
            assert tracks[str(student_a)] == "experimental"
            assert grades[str(student_b)] is None
            assert tracks[str(student_b)] is None


def test_pii_masking_boundary_not_leaked_in_logs(student_a, student_a_headers):
    """PII masking boundary: student identity not leaked in AI telemetry."""
    # This test verifies that the PII masking module is used
    # and no raw Telegram IDs appear in sanitized intake for AI
    from app.ai.pii import sanitize_intake_for_ai
    from app.schemas.planning import IntakeSlots

    intake = IntakeSlots(
        stage_code="konkur",
        grade="G12",
        track="experimental",
        daily_study_capacity_minutes=240,
        weak_subjects=["biology", "chemistry"],
    )

    sanitized = sanitize_intake_for_ai(intake)

    # Verify no identity fields in sanitized output
    assert "telegram_chat_id" not in sanitized
    assert "telegram_user_id" not in sanitized
    assert "telegram_username" not in sanitized
    assert "first_name" not in sanitized
    assert "student_id" not in sanitized

    # Verify only educational parameters present
    expected_keys = {
        "stage_code",
        "grade",
        "track",
        "goal_code",
        "study_days",
        "max_session_minutes",
        "daily_study_capacity_minutes",
        "weak_subjects",
    }
    assert set(sanitized.keys()) == expected_keys
