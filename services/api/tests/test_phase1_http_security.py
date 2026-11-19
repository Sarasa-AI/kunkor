"""HTTP boundary regressions; run only against an isolated test database."""

import hashlib
import hmac
import http.client
import importlib
import json
import os
import socket
import subprocess
import sys
import time
from urllib.parse import urlencode
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, settings
from app.core.db import get_db_connection


@pytest.fixture
def configured_app(monkeypatch):
    import app.main as main

    original = settings.CORS_ALLOWED_ORIGINS

    def build(origins):
        monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGINS", origins)
        return importlib.reload(main).app

    yield build
    monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGINS", original)
    importlib.reload(main)


@pytest.mark.parametrize("origins", [[], ["https://school.example"]])
def test_cors_uses_exact_configured_origins(configured_app, origins):
    client = TestClient(configured_app(origins))
    for origin in ["https://school.example", "http://localhost:3000", "http://localhost:3002"]:
        response = client.get("/healthz", headers={"Origin": origin})
        assert response.headers.get("access-control-allow-origin") == (
            origin if origin in origins else None
        )


def test_explicit_empty_cors_stays_empty():
    assert Settings(_env_file=None, CORS_ALLOWED_ORIGINS=[]).CORS_ALLOWED_ORIGINS == []


@pytest.mark.parametrize(
    "origin",
    [
        "https://school.example/path",
        "null",
        "file:///tmp/a",
        "https://user:pass@school.example",
        "https://school.example?x=1",
    ],
)
def test_invalid_cors_origin_rejected(origin):
    with pytest.raises(ValueError):
        Settings(_env_file=None, CORS_ALLOWED_ORIGINS=[origin])


def test_wildcard_cors_removed_without_expansion():
    assert Settings(_env_file=None, CORS_ALLOWED_ORIGINS=["*"]).CORS_ALLOWED_ORIGINS == []


def test_validation_response_does_not_echo_sensitive_input(configured_app, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "synthetic-webhook-secret")
    client = TestClient(configured_app([]))
    marker = "synthetic-private-name-and-credential"
    response = client.post(
        "/api/v1/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "synthetic-webhook-secret"},
        json=[{"text": marker}],
    )
    assert response.status_code == 422
    assert marker not in response.text
    assert "input" not in response.text


@pytest.mark.parametrize("origins", [[], ["https://school.example"]])
def test_public_server_error_is_generic(configured_app, origins):
    application = configured_app(origins)

    @application.get("/__synthetic_failure")
    def failure():
        raise RuntimeError("synthetic-private-name-and-credential")

    response = TestClient(application, raise_server_exceptions=False).get(
        "/__synthetic_failure", headers={"Origin": "https://school.example"}
    )
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert response.headers.get("access-control-allow-origin") == (
        "https://school.example" if origins else None
    )


def test_server_error_does_not_escape_asgi_or_log_sensitive_details(configured_app, caplog):
    application = configured_app([])
    marker = "synthetic-private-sql-detail-and-credential"

    @application.get("/__synthetic_logged_failure")
    def failure():
        raise RuntimeError(marker)

    response = TestClient(application).get("/__synthetic_logged_failure")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert marker not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def _signed_header(user_id, token):
    fields = {"auth_date": str(int(time.time())), "user": json.dumps({"id": user_id})}
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return {"Authorization": "tma " + urlencode(fields)}


@pytest.mark.parametrize(
    "path",
    [
        "/content/books",
        "/content/books/00000000-0000-0000-0000-000000000001",
        "/content/books/00000000-0000-0000-0000-000000000001/chapters",
        "/content/chapters/00000000-0000-0000-0000-000000000001/lessons",
    ],
)
def test_content_requires_student_authentication(configured_app, path):
    response = TestClient(configured_app([]), raise_server_exceptions=False).get(path)
    assert response.status_code == 401


def test_content_signed_student_reads_real_database(configured_app, monkeypatch):
    token = "synthetic-bot-token"
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", token)
    user_id = uuid4().int % (2**62) + 1
    with get_db_connection(test=True) as conn:
        conn.execute(
            "INSERT INTO students (telegram_chat_id, telegram_user_id) VALUES (%s, %s)",
            (user_id, user_id),
        )
        conn.commit()
    try:
        response = TestClient(configured_app([]), raise_server_exceptions=False).get(
            "/content/books", headers=_signed_header(user_id, token)
        )
        assert response.status_code == 200, response.text
        assert isinstance(response.json(), list)
    finally:
        with get_db_connection(test=True) as conn:
            conn.execute("DELETE FROM students WHERE telegram_chat_id = %s", (user_id,))
            conn.commit()


@pytest.mark.parametrize("failure_kind", ["early", "stream", "background", "missing"])
def test_real_uvicorn_logs_exclude_credentials_and_late_exceptions(tmp_path, failure_kind):
    """Exercise the actual server, including failures after headers/body are sent."""
    marker = "synthetic-private-sql-detail-and-credential"
    source = """
import socket
import sys
import uvicorn
from fastapi import BackgroundTasks, Depends
from starlette.responses import StreamingResponse
from app.main import app

def synthetic_test_policy():
    pass

synthetic_test_policy.__authz_enforcing__ = True

@app.get('/__early/{marker}', dependencies=[Depends(synthetic_test_policy)])
def early(marker: str):
    raise RuntimeError(marker)

@app.get('/__stream/{marker}', dependencies=[Depends(synthetic_test_policy)])
def stream(marker: str):
    async def body():
        yield b'start'
        raise RuntimeError(marker)
    return StreamingResponse(body())

@app.get('/__background/{marker}', dependencies=[Depends(synthetic_test_policy)])
def background(marker: str, background_tasks: BackgroundTasks):
    def fail():
        raise RuntimeError(marker)
    background_tasks.add_task(fail)
    return {'status': 'accepted'}

sock = socket.socket(fileno=int(sys.argv[1]))
uvicorn.Server(uvicorn.Config(app, log_level='info')).run(sockets=[sock])
"""
    log_path = tmp_path / "uvicorn.log"
    environment = os.environ.copy()
    environment.update(
        ENVIRONMENT="testing", NINEROUTER_ENABLED="false", TELEGRAM_DELIVERY_ENABLED="false"
    )
    with socket.socket() as listener, log_path.open("w") as log:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen()
        process = subprocess.Popen(
            [sys.executable, "-c", source, str(listener.fileno())],
            pass_fds=(listener.fileno(),),
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 10
            while True:
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.2)
                try:
                    connection.request("GET", "/healthz")
                    response = connection.getresponse()
                    response.read()
                    assert response.status == 200
                    break
                except (OSError, http.client.HTTPException):
                    assert process.poll() is None, "Synthetic Uvicorn server exited"
                    assert time.monotonic() < deadline, "Synthetic Uvicorn server timed out"
                    time.sleep(0.02)
                finally:
                    connection.close()
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            try:
                connection.request(
                    "GET", f"/__{failure_kind}/{marker}?credential={marker}",
                    headers={"Authorization": f"Bearer {marker}"},
                )
                response = connection.getresponse()
                if failure_kind == "stream":
                    try:
                        response.read()
                    except http.client.IncompleteRead:
                        pass
                    assert response.status == 200
                else:
                    body = response.read()
                    assert response.status == {"early": 500, "background": 200, "missing": 404}[
                        failure_kind
                    ]
                    assert marker.encode() not in body
            finally:
                connection.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
    output = log_path.read_text()
    assert "Started server process" in output
    assert marker not in output
    assert "Traceback" not in output
