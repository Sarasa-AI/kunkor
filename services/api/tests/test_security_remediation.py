import os

import psycopg
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from scripts.check_authz_matrix import has_valid_authz

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://kunkor:kunkor_dev_password@localhost:5435/kunkor_test",
)


def test_sec_01_cors_allowed_origin():
    client = TestClient(app)
    response = client.get(
        "/healthz",
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_sec_01_cors_disallowed_origin_rejected():
    client = TestClient(app)
    response = client.get(
        "/healthz",
        headers={"Origin": "http://malicious-attacker.com"},
    )
    assert response.status_code == 200
    # Disallowed origin must not be reflected or granted access
    assert "access-control-allow-origin" not in response.headers


def test_sec_01_cors_wildcard_never_allowed_with_credentials():
    settings = Settings(
        ENVIRONMENT="development",
        CORS_ALLOWED_ORIGINS="*, http://localhost:3000",
    )
    assert "*" not in settings.CORS_ALLOWED_ORIGINS
    assert "http://localhost:3000" in settings.CORS_ALLOWED_ORIGINS


def test_sec_02_production_missing_database_url_fails(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL is required in production"):
        Settings(ENVIRONMENT="production", DATABASE_URL="")


def test_sec_02_production_insecure_default_password_fails():
    with pytest.raises(ValueError, match="Insecure default credentials prohibited"):
        Settings(
            ENVIRONMENT="production",
            DATABASE_URL="postgresql://kunkor:kunkor_dev_password@prod-host:5432/kunkor_prod",
        )


def test_sec_02_migrate_rejects_insecure_password_in_production(monkeypatch):
    from scripts.migrate import get_db_url

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://kunkor:kunkor_dev_password@prod-host:5432/kunkor_prod",
    )
    with pytest.raises(ValueError, match="Insecure default credentials prohibited"):
        get_db_url()


def test_sec_02_development_defaults_allowed(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    cfg = Settings(ENVIRONMENT="development", DATABASE_URL="")
    assert "kunkor_dev_password" in cfg.DATABASE_URL
    assert cfg.ENVIRONMENT == "development"


def test_sec_05_authz_checker_rejects_dummy_dependency():
    test_app = FastAPI()

    def dummy_dep():
        return None

    @test_app.get("/unprotected", dependencies=[Depends(dummy_dep)])
    def unprotected_endpoint():
        return {"data": "secret"}

    route = test_app.routes[-1]
    assert not has_valid_authz(route)


def test_sec_05_authz_checker_accepts_security_marker():
    test_app = FastAPI()

    def protected_endpoint():
        return {"data": "protected"}

    protected_endpoint.__authz_required__ = True
    test_app.add_api_route("/protected", protected_endpoint)

    route = test_app.routes[-1]
    assert has_valid_authz(route)


def test_outbox_worker_increments_retry_on_failure(monkeypatch):
    with psycopg.connect(TEST_DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO outbox_events (
                    event_type, aggregate_type, aggregate_id, payload, retry_count
                )
                VALUES (%s, %s, %s, %s, 0)
                RETURNING id;
                """,
                ("test.failure", "test", "t-fail", '{"data": "bad"}'),
            )
            event_id = cur.fetchone()[0]
        conn.commit()

    import app.workers.outbox_worker as ow

    def mock_publish(event):
        if event.get("id") == event_id:
            raise RuntimeError("Intentional delivery failure")

    monkeypatch.setattr(ow, "publish_to_queue", mock_publish)

    ow.process_pending_outbox_events(limit=50, test=True)

    with psycopg.connect(TEST_DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT retry_count, processed_at FROM outbox_events WHERE id = %s;",
                (event_id,),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] >= 1
            assert row[1] is None  # processed_at remains None
