"""Synthetic aggregate monitoring and atomic, authorized outbox recovery."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import get_db_connection
from app.main import app


def test_dead_letter_retry_requires_admin_and_is_audited(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "synthetic-recovery-admin")
    client = TestClient(app)
    headers = {"X-Admin-Api-Key": "synthetic-recovery-admin"}
    event_id = uuid4()
    with get_db_connection(test=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO outbox_events(id, event_type, aggregate_type, aggregate_id,
                                          payload, retry_count, occurred_at)
                VALUES (%s, 'synthetic.recovery', 'test', 'synthetic', '{}', 5,
                        NOW() - INTERVAL '2 hours');
            """, (event_id,))
        conn.commit()
    route = f"/api/v1/admin/outbox/{event_id}/retry"
    assert client.get("/api/v1/admin/outbox/health").status_code == 403
    assert client.post(route).status_code == 403
    before = client.get("/api/v1/admin/outbox/health", headers=headers).json()
    assert before["dead_letter"] >= 1
    assert before["oldest_pending_seconds"] >= 7199
    assert set(before) == {"pending", "dead_letter", "oldest_pending_seconds"}
    assert client.post(route, headers=headers).status_code == 200
    assert client.post(route, headers=headers).status_code == 409
    with get_db_connection(test=True) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT retry_count, processed_at FROM outbox_events WHERE id = %s", (event_id,)
        )
        row = cur.fetchone()
        assert row == {"retry_count": 0, "processed_at": None}
        cur.execute("""
            SELECT COUNT(*) AS n FROM audit_events
            WHERE action = 'outbox.retry' AND resource_id = %s;
        """, (str(event_id),))
        assert cur.fetchone()["n"] == 1
