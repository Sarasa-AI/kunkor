"""Phase 5 Integration Tests: Operations, Admin, Feature Flags & Entitlements.

Verifies:
1. Admin authentication guards (X-Admin-Api-Key and Bearer token).
2. Consultation review endpoints (students, versioned plans, progress logs).
3. Feature flag management (list, update, toggle).
4. Subscription entitlement gating (feature flag toggle, entitlement grant/revoke).
5. Audit log recording and querying for administrative actions.
"""

import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import get_connection_string
from app.main import app

client = TestClient(app)

ADMIN_HEADERS = {"X-Admin-Api-Key": settings.ADMIN_API_KEY}


def _create_sample_student_with_plan(chat_id: int) -> dict[str, str]:
    tg_user_id = chat_id + 1000
    # Step 1: /start
    client.post(
        "/api/v1/telegram/webhook",
        json={
            "update_id": chat_id * 10 + 1,
            "message": {
                "message_id": 1,
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": tg_user_id, "first_name": "مریم"},
                "text": "/start",
            },
        },
    )
    # Step 2: stage
    client.post(
        "/api/v1/telegram/webhook",
        json={
            "update_id": chat_id * 10 + 2,
            "message": {
                "message_id": 2,
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": tg_user_id, "first_name": "مریم"},
                "text": "دوازدهم تجربی",
            },
        },
    )
    # Step 3: track
    client.post(
        "/api/v1/telegram/webhook",
        json={
            "update_id": chat_id * 10 + 3,
            "message": {
                "message_id": 3,
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": tg_user_id, "first_name": "مریم"},
                "text": "تجربی",
            },
        },
    )
    # Step 4: capacity
    client.post(
        "/api/v1/telegram/webhook",
        json={
            "update_id": chat_id * 10 + 4,
            "message": {
                "message_id": 4,
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": tg_user_id, "first_name": "مریم"},
                "text": "۳ ساعت",
            },
        },
    )
    # Step 5: weak subjects
    res5 = client.post(
        "/api/v1/telegram/webhook",
        json={
            "update_id": chat_id * 10 + 5,
            "message": {
                "message_id": 5,
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": tg_user_id, "first_name": "مریم"},
                "text": "زیست‌شناسی",
            },
        },
    )
    data = res5.json()
    return {"student_id": data["student_id"], "plan_id": data["plan_id"]}


def test_admin_authentication_guards():
    """Verify admin endpoints reject missing or invalid credentials."""
    # 1. No credentials -> 403
    res_no_auth = client.get("/api/v1/admin/students")
    assert res_no_auth.status_code == 403

    # 2. Invalid API key -> 403
    res_bad_auth = client.get(
        "/api/v1/admin/students",
        headers={"X-Admin-Api-Key": "wrong_key"},
    )
    assert res_bad_auth.status_code == 403

    # 3. Valid X-Admin-Api-Key -> 200
    res_good_key = client.get(
        "/api/v1/admin/students",
        headers={"X-Admin-Api-Key": settings.ADMIN_API_KEY},
    )
    assert res_good_key.status_code == 200

    # 4. Valid Bearer Token in Authorization header -> 200
    res_bearer = client.get(
        "/api/v1/admin/students",
        headers={"Authorization": f"Bearer {settings.ADMIN_API_KEY}"},
    )
    assert res_bearer.status_code == 200


def test_consultation_review_endpoints():
    """Verify admin can inspect students, plan revisions, and progress logs."""
    chat_id = int(str(uuid.uuid4().int)[:9])
    student_info = _create_sample_student_with_plan(chat_id)
    student_id = student_info["student_id"]

    # 1. List students
    res_students = client.get("/api/v1/admin/students", headers=ADMIN_HEADERS)
    assert res_students.status_code == 200
    data_students = res_students.json()
    student_ids = [s["id"] for s in data_students["items"]]
    assert student_id in student_ids

    # 2. Get student versioned plans
    res_plans = client.get(
        f"/api/v1/admin/students/{student_id}/plans",
        headers=ADMIN_HEADERS,
    )
    assert res_plans.status_code == 200
    data_plans = res_plans.json()
    assert data_plans["student_id"] == student_id
    assert len(data_plans["plans"]) >= 1
    assert data_plans["plans"][0]["revision_no"] == 1
    assert len(data_plans["plans"][0]["items"]) > 0

    # 3. Get student progress logs
    res_progress = client.get(
        f"/api/v1/admin/students/{student_id}/progress",
        headers=ADMIN_HEADERS,
    )
    assert res_progress.status_code == 200
    data_prog = res_progress.json()
    assert data_prog["student_id"] == student_id
    assert isinstance(data_prog["progress_logs"], list)


def test_feature_flag_management():
    """Verify creating, listing, and updating feature flags with audit trail."""
    flag_name = f"test_flag_{uuid.uuid4().hex[:6]}"

    # 1. Create / update flag
    res_set = client.post(
        "/api/v1/admin/flags",
        headers=ADMIN_HEADERS,
        json={
            "name": flag_name,
            "is_enabled": True,
            "description": "Test operational feature flag",
            "rules": {"cohort": "beta_testers"},
        },
    )
    assert res_set.status_code == 200
    flag_data = res_set.json()
    assert flag_data["name"] == flag_name
    assert flag_data["is_enabled"] is True

    # 2. List flags
    res_list = client.get("/api/v1/admin/flags", headers=ADMIN_HEADERS)
    assert res_list.status_code == 200
    flags = res_list.json()["flags"]
    matched = [f for f in flags if f["name"] == flag_name]
    assert len(matched) == 1
    assert matched[0]["is_enabled"] is True

    # 3. Verify audit log entry
    res_audit = client.get(
        "/api/v1/admin/audit-logs?action=feature_flag.update",
        headers=ADMIN_HEADERS,
    )
    assert res_audit.status_code == 200
    audit_events = res_audit.json()["items"]
    flag_events = [e for e in audit_events if e["resource_id"] == flag_name]
    assert len(flag_events) >= 1
    assert flag_events[0]["action"] == "feature_flag.update"


def test_student_entitlement_gating_integration():
    """
    Verify end-to-end entitlement gating:
    1. Enable enforce_subscription_entitlements flag.
    2. Student without entitlement is blocked.
    3. Grant entitlement via admin API.
    4. Student is now admitted to consultation.
    5. Expire entitlement -> Student blocked again.
    """
    chat_id = int(str(uuid.uuid4().int)[:9])
    tg_user_id = chat_id + 1000

    # 1. Enable subscription entitlement gating flag
    res_flag = client.post(
        "/api/v1/admin/flags",
        headers=ADMIN_HEADERS,
        json={
            "name": "enforce_subscription_entitlements",
            "is_enabled": True,
            "description": "Enforce subscription for consultation",
        },
    )
    assert res_flag.status_code == 200

    try:
        # 2. Student attempts /start without entitlement
        res_blocked = client.post(
            "/api/v1/telegram/webhook",
            json={
                "update_id": chat_id * 10 + 1,
                "message": {
                    "message_id": 1,
                    "chat": {"id": chat_id, "type": "private"},
                    "from": {"id": tg_user_id, "first_name": "امید"},
                    "text": "/start",
                },
            },
        )
        assert res_blocked.status_code == 200
        blocked_data = res_blocked.json()
        assert blocked_data["status"] == "subscription_required"
        assert "نیازمند اشتراک فعال است" in blocked_data["response_text"]
        student_id = blocked_data["student_id"]

        # 3. Grant active entitlement to student via Admin API
        future_expiry = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        res_grant = client.post(
            "/api/v1/admin/entitlements",
            headers=ADMIN_HEADERS,
            json={
                "student_id": student_id,
                "feature_key": "ai_consultant",
                "is_granted": True,
                "valid_to": future_expiry,
            },
        )
        assert res_grant.status_code == 200
        grant_data = res_grant.json()
        assert grant_data["feature_key"] == "ai_consultant"
        assert grant_data["is_granted"] is True

        # Check student entitlements list
        res_ent_list = client.get(
            f"/api/v1/admin/entitlements/{student_id}",
            headers=ADMIN_HEADERS,
        )
        assert res_ent_list.status_code == 200
        ents = res_ent_list.json()["entitlements"]
        assert len(ents) >= 1
        assert ents[0]["feature_key"] == "ai_consultant"

        # 4. Student retries /start -> Now admitted!
        res_admitted = client.post(
            "/api/v1/telegram/webhook",
            json={
                "update_id": chat_id * 10 + 2,
                "message": {
                    "message_id": 2,
                    "chat": {"id": chat_id, "type": "private"},
                    "from": {"id": tg_user_id, "first_name": "امید"},
                    "text": "/start",
                },
            },
        )
        assert res_admitted.status_code == 200
        admitted_data = res_admitted.json()
        assert admitted_data["status"] == "intake_in_progress"
        assert admitted_data["step"] == "stage"

        # 5. Revoke entitlement
        res_revoke = client.post(
            "/api/v1/admin/entitlements",
            headers=ADMIN_HEADERS,
            json={
                "student_id": student_id,
                "feature_key": "ai_consultant",
                "is_granted": False,
            },
        )
        assert res_revoke.status_code == 200

        # Student sends message -> blocked again
        res_blocked_again = client.post(
            "/api/v1/telegram/webhook",
            json={
                "update_id": chat_id * 10 + 3,
                "message": {
                    "message_id": 3,
                    "chat": {"id": chat_id, "type": "private"},
                    "from": {"id": tg_user_id, "first_name": "امید"},
                    "text": "دوازدهم تجربی",
                },
            },
        )
        assert res_blocked_again.status_code == 200
        assert res_blocked_again.json()["status"] == "subscription_required"

    finally:
        # Reset flag to disabled so subsequent tests are not affected
        client.post(
            "/api/v1/admin/flags",
            headers=ADMIN_HEADERS,
            json={
                "name": "enforce_subscription_entitlements",
                "is_enabled": False,
                "description": "Enforce subscription for consultation",
            },
        )


def test_audit_log_querying_and_isolation():
    """Verify admin audit log query endpoint with filtering."""
    test_dsn = get_connection_string(test=True)
    random_action = f"audit_test_{uuid.uuid4().hex[:6]}"

    # Trigger action through admin API
    client.post(
        "/api/v1/admin/flags",
        headers=ADMIN_HEADERS,
        json={
            "name": f"flag_{random_action}",
            "is_enabled": True,
        },
    )

    # Query audit logs
    res_logs = client.get(
        "/api/v1/admin/audit-logs?limit=10&offset=0",
        headers=ADMIN_HEADERS,
    )
    assert res_logs.status_code == 200
    data = res_logs.json()
    assert "items" in data
    assert len(data["items"]) >= 1

    # Verify append-only protection on audit_events
    with psycopg.connect(test_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM audit_events LIMIT 1;")
            first_event_id = cur.fetchone()[0]
            with pytest.raises(psycopg.Error) as exc_info:
                cur.execute(
                    "UPDATE audit_events SET action = 'tampered' WHERE id = %s;",
                    (first_event_id,),
                )
            assert "append-only" in str(exc_info.value)
