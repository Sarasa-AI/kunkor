"""Integration tests for student-facing web consultation endpoints (Phase 6).

Covers:
- Signed Telegram identity; public student identifiers rejected.
- GET /api/v1/consultation/active-plan (and /active-plan).
- POST /api/v1/consultation/progress (and /progress) with Rev N+1 generation.
- GET /api/v1/consultation/history (and /history).
- POST /api/v1/consultation/intake web initiation.
- GET /api/v1/consultation/me profile retrieval.
- Entitlement gating enforcement on web endpoints.
"""

import hashlib
import hmac
import json
import os
import time
import uuid
from urllib.parse import urlencode

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import get_db_connection
from app.main import app

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://kunkor:kunkor_dev_password@localhost:5435/kunkor_test",
)


@pytest.fixture(autouse=True)
def clean_db(monkeypatch):
    """Ensure clean database before and after each test."""
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "synthetic-test-bot-token")
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
def test_student():
    """Create a persistent test student in the database."""
    with get_db_connection(test=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO students (
                    telegram_chat_id, telegram_user_id, telegram_username, first_name
                )
                VALUES (888123456, 888123456, 'web_student', 'سارا')
                RETURNING id;
                """
            )
            student_id = cur.fetchone()["id"]
            conn.commit()
            return uuid.UUID(str(student_id))


def signed_headers(user_id=888123456, *, timestamp=None, token="synthetic-test-bot-token"):
    fields = {
        "auth_date": str(int(time.time()) if timestamp is None else timestamp),
        "user": json.dumps({"id": user_id}),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return {"Authorization": "tma " + urlencode(fields), "Idempotency-Key": str(uuid.uuid4())}


def test_auth_rejection_without_credentials():
    """Endpoints require valid student access credentials."""
    client = TestClient(app)
    res = client.get("/api/v1/consultation/active-plan")
    assert res.status_code == 401
    assert "signed Telegram credentials" in res.json()["detail"]


def test_auth_rejection_with_invalid_credentials():
    """Endpoints reject invalid UUID or non-existent Telegram chat id."""
    client = TestClient(app)
    # Non-existent UUID
    fake_uuid = str(uuid.uuid4())
    res = client.get("/api/v1/consultation/active-plan", headers={"X-Student-Id": fake_uuid})
    assert res.status_code == 401

    # Non-existent telegram chat ID
    res = client.get("/api/v1/consultation/active-plan", headers={"X-Student-Id": "999999999"})
    assert res.status_code == 401


def test_auth_rejects_public_identifiers_and_accepts_signed_identity(test_student):
    client = TestClient(app)
    for headers in (
        {"X-Student-Id": str(test_student)},
        {"X-Student-Id": "888123456"},
        {"Authorization": f"Bearer {test_student}"},
    ):
        assert client.get("/api/v1/consultation/me", headers=headers).status_code == 401
    response = client.get("/api/v1/consultation/me", headers=signed_headers())
    assert response.status_code == 200
    assert response.json()["id"] == str(test_student)


@pytest.mark.parametrize(
    "overrides",
    [
        {"token": "attacker-token"},
        {"timestamp": int(time.time()) - 600},
        {"timestamp": int(time.time()) + 600},
        {"user_id": 999999999},
        {"user_id": True},
        {"user_id": -1},
    ],
)
def test_signed_identity_rejects_forgery_expiry_and_other_users(test_student, overrides):
    response = TestClient(app).get("/api/v1/consultation/me", headers=signed_headers(**overrides))
    assert response.status_code == 401


def test_signed_identity_rejects_duplicate_and_malformed_fields(test_student):
    client = TestClient(app)
    headers = signed_headers()
    headers["Authorization"] += "&auth_date=1"
    assert client.get("/api/v1/consultation/me", headers=headers).status_code == 401
    for credential in ("tma nonsense", "tma user=%FF", "tma " + "x" * 8193):
        assert (
            client.get("/api/v1/consultation/me", headers={"Authorization": credential}).status_code
            == 401
        )


def test_web_intake_and_active_plan_lifecycle(test_student):
    """Student creates a plan via web intake and reads it back via active-plan endpoint."""
    client = TestClient(app)
    headers = signed_headers()

    # 1. Initially no active plan
    res_initial = client.get("/api/v1/consultation/active-plan", headers=headers)
    assert res_initial.status_code == 200
    assert res_initial.json()["status"] == "not_found"
    assert res_initial.json()["plan"] is None

    # 2. Initialize intake via POST /api/v1/consultation/intake
    intake_payload = {
        "stage_code": "konkur",
        "grade": "G12",
        "track": "experimental",
        "daily_study_capacity_minutes": 240,
        "weak_subjects": ["biology", "chemistry"],
    }
    res_intake = client.post("/api/v1/consultation/intake", json=intake_payload, headers=headers)
    assert res_intake.status_code == 200
    data = res_intake.json()
    assert data["status"] == "plan_generated"
    assert data["revision_no"] == 1
    assert data["student_id"] == str(test_student)

    # 3. Read active plan back
    res_plan = client.get("/api/v1/consultation/active-plan", headers=headers)
    assert res_plan.status_code == 200
    plan_data = res_plan.json()
    assert plan_data["status"] == "active"
    assert plan_data["plan"]["revision_no"] == 1
    items = plan_data["plan"]["items"]
    assert len(items) > 0
    assert plan_data["total_duration_minutes"] <= 240

    # Also verify route alias /active-plan works identically
    res_alias = client.get("/active-plan", headers=headers)
    assert res_alias.status_code == 200
    assert res_alias.json()["plan"]["id"] == plan_data["plan"]["id"]


def test_web_daily_progress_revision_loop(test_student):
    """
    Student submits daily progress via web, resulting in Rev 2 generation
    with missed unit carryover.
    """
    client = TestClient(app)
    headers = signed_headers()

    # 1. Initialize initial plan
    client.post(
        "/api/v1/consultation/intake",
        json={
            "stage_code": "konkur",
            "grade": "G12",
            "track": "experimental",
            "daily_study_capacity_minutes": 180,
            "weak_subjects": ["biology"],
        },
        headers=headers,
    )
    plan_1 = client.get("/api/v1/consultation/active-plan", headers=headers).json()["plan"]
    items_1 = plan_1["items"]
    assert len(items_1) >= 2

    completed_unit = items_1[0]["resource_version_id"]
    missed_unit = items_1[1]["resource_version_id"]

    # 2. Submit daily progress report
    progress_payload = {
        "completed_units": [completed_unit],
        "missed_units": [missed_unit],
        "duration_spent_minutes": 60,
        "student_notes": "خوب پیش رفت اما وقت برای تست شیمی کم آوردم",
    }
    res_prog = client.post("/api/v1/consultation/progress", json=progress_payload, headers=headers)
    assert res_prog.status_code == 200
    prog_data = res_prog.json()
    assert prog_data["status"] == "plan_revised"
    assert prog_data["revision_no"] == 2
    assert prog_data["completion_rate"] == 50.0

    # 3. Read active plan back (now Rev 2)
    res_rev2 = client.get("/api/v1/consultation/active-plan", headers=headers)
    assert res_rev2.status_code == 200
    plan_2 = res_rev2.json()["plan"]
    assert plan_2["revision_no"] == 2
    rev2_unit_ids = [it["resource_version_id"] for it in plan_2["items"]]
    # Pedagogical carryover: missed unit should be present in Rev 2
    assert missed_unit in rev2_unit_ids

    # 4. Check progress history
    res_hist = client.get("/api/v1/consultation/history", headers=headers)
    assert res_hist.status_code == 200
    hist_data = res_hist.json()
    assert hist_data["total_logs"] == 1
    log = hist_data["logs"][0]
    assert log["revision_no"] == 1
    assert log["completed_units"] == [completed_unit]
    assert log["missed_units"] == [missed_unit]
    assert log["student_notes"] == "خوب پیش رفت اما وقت برای تست شیمی کم آوردم"


def test_web_progress_validation_errors(test_student):
    """Submitting empty progress units returns validation error."""
    client = TestClient(app)
    headers = signed_headers()

    # Without plan: returns 400 Bad Request
    res_no_plan = client.post(
        "/api/v1/consultation/progress",
        json={"completed_units": ["math_01"], "missed_units": [], "duration_spent_minutes": 60},
        headers=headers,
    )
    assert res_no_plan.status_code == 400

    # Create plan
    client.post(
        "/api/v1/consultation/intake",
        json={"stage_code": "konkur", "grade": "G12", "track": "experimental"},
        headers=headers,
    )

    # Empty units: returns 422
    res_empty = client.post(
        "/api/v1/consultation/progress",
        json={"completed_units": [], "missed_units": [], "duration_spent_minutes": 60},
        headers=headers,
    )
    assert res_empty.status_code == 422


def test_web_entitlement_gating(test_student):
    """When subscription enforcement is enabled, unentitled student is blocked with 403."""
    client = TestClient(app)
    headers = signed_headers()

    # Enable feature flag via DB
    with get_db_connection(test=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO feature_flags (name, is_enabled)
                VALUES ('enforce_subscription_entitlements', TRUE)
                ON CONFLICT (name) DO UPDATE SET is_enabled = TRUE;
                """
            )
            conn.commit()

    # Blocked without entitlement
    res_blocked = client.post(
        "/api/v1/consultation/intake",
        json={"stage_code": "konkur", "grade": "G12", "track": "experimental"},
        headers=headers,
    )
    assert res_blocked.status_code == 403
    assert "نیازمند اشتراک فعال است" in res_blocked.json()["detail"]

    # Grant entitlement
    with get_db_connection(test=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO entitlements (student_id, feature_key, is_granted)
                VALUES (%s, 'ai_consultant', TRUE);
                """,
                (test_student,),
            )
            conn.commit()

    # Now allowed
    res_allowed = client.post(
        "/api/v1/consultation/intake",
        json={"stage_code": "konkur", "grade": "G12", "track": "experimental"},
        headers=headers,
    )
    assert res_allowed.status_code == 200
    assert res_allowed.json()["status"] == "plan_generated"


def test_signed_identity_handles_untrusted_json_and_hash(test_student):
    client = TestClient(app)
    for user_json in ("[]", "{bad json", "[" * 1100 + "0" + "]" * 1100):
        fields = {"auth_date": str(int(time.time())), "user": user_json}
        check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
        secret = hmac.new(b"WebAppData", settings.TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256)
        fields["hash"] = hmac.new(secret.digest(), check.encode(), hashlib.sha256).hexdigest()
        headers = {"Authorization": "tma " + urlencode(fields)}
        assert client.get("/api/v1/consultation/me", headers=headers).status_code == 401
    assert (
        client.get(
            "/api/v1/consultation/me", headers={"Authorization": "tma hash=%FF&user=1"}
        ).status_code
        == 401
    )


def test_web_write_preflight_allows_auth_and_idempotency():
    response = TestClient(app).options(
        "/api/v1/consultation/intake",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
        },
    )
    assert response.status_code == 200
    assert "idempotency-key" in response.headers["access-control-allow-headers"].lower()


def test_web_intake_replay_conflict_and_structured_constraints(test_student):
    client = TestClient(app)
    headers = signed_headers()
    body = {"goal_code": "review", "study_days": [0, 5], "max_session_minutes": 25}
    first = client.post("/intake", json=body, headers=headers)
    assert first.status_code == 200
    replay = client.post("/intake", json=body, headers=headers)
    assert replay.status_code == 200
    # Compare semantically equal responses (normalize datetime format)
    first_json = first.json()
    replay_json = replay.json()
    # Normalize created_at format for comparison
    def normalize_created_at(obj):
        if isinstance(obj, dict):
            result = {}
            for k, v in obj.items():
                if k == "created_at" and isinstance(v, str):
                    result[k] = v.replace("+00:00", "Z")
                else:
                    result[k] = normalize_created_at(v)
            return result
        elif isinstance(obj, list):
            return [normalize_created_at(v) for v in obj]
        return obj

    assert normalize_created_at(replay_json) == normalize_created_at(first_json)
    changed = client.post("/intake", json={**body, "goal_code": "exam"}, headers=headers)
    assert changed.status_code == 409
    plan = client.get("/active-plan", headers=headers).json()
    assert plan["plan"]["goal_code"] == "review"
    assert plan["plan"]["study_days"] == [0, 5]
    assert plan["plan"]["max_session_minutes"] == 25
    assert all(session["duration_minutes"] <= 25 for session in plan["plan"]["sessions"])
    assert (
        sum(session["duration_minutes"] for session in plan["plan"]["sessions"])
        == plan["total_duration_minutes"]
    )
    with get_db_connection(test=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM study_plans WHERE student_id=%s", (test_student,))
        assert cur.fetchone()["n"] == 1
        cur.execute("SELECT count(*) AS n FROM outbox_events WHERE student_id=%s", (test_student,))
        assert cur.fetchone()["n"] == 1


def test_concurrent_web_intake_replay_creates_one_plan(test_student):
    from concurrent.futures import ThreadPoolExecutor

    headers = signed_headers()

    def request_once(_):
        with TestClient(app) as client:
            return client.post("/intake", json={}, headers=headers)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(request_once, range(2)))
    assert [result.status_code for result in results] == [200, 200]
    assert results[0].json()["plan_id"] == results[1].json()["plan_id"]
    with get_db_connection(test=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM study_plans WHERE student_id=%s", (test_student,))
        assert cur.fetchone()["n"] == 1


def test_web_writes_require_request_key(test_student):
    headers = signed_headers()
    headers.pop("Idempotency-Key")
    assert TestClient(app).post("/intake", json={}, headers=headers).status_code == 422
