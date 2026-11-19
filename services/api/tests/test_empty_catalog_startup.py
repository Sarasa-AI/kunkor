"""Phase 2 acceptance: a real API process starts against a fresh empty catalog."""

import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from scripts.migrate import apply_migrations
from scripts.migrate_check import require_test_database


@pytest.fixture
def empty_catalog_database():
    base_dsn = os.environ["TEST_DATABASE_URL"]
    require_test_database(base_dsn)
    database_name = f"kunkor_empty_catalog_{uuid4().hex}_test"
    admin_dsn = make_conninfo(base_dsn, dbname="postgres")
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    fresh_dsn = make_conninfo(base_dsn, dbname=database_name)
    try:
        apply_migrations(fresh_dsn)
        yield fresh_dsn
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))


def catalog_counts(dsn):
    tables = (
        "curricula",
        "subjects",
        "books",
        "editions",
        "chapters",
        "lessons",
        "page_sections",
        "questions",
    )
    with psycopg.connect(dsn) as conn:
        return {
            table: conn.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
            ).fetchone()[0]
            for table in tables
        }


def signed_student_credentials(token, user_id):
    fields = {"auth_date": str(int(time.time())), "user": json.dumps({"id": user_id})}
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return "tma " + urlencode(fields)


def test_real_api_starts_with_zero_content_and_authorized_empty_responses(
    empty_catalog_database, tmp_path
):
    dsn = empty_catalog_database
    assert all(count == 0 for count in catalog_counts(dsn).values())
    user_id = 910000000001
    # Identity infrastructure remains usable without creating any content.
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO students(telegram_user_id,telegram_chat_id) VALUES(%s,%s)",
            (user_id, user_id),
        )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    admin_key = "synthetic-empty-catalog-admin"
    bot_token = "synthetic-empty-catalog-bot"
    process_env = {
        **os.environ,
        "ENVIRONMENT": "test",
        "DATABASE_URL": dsn,
        "TEST_DATABASE_URL": dsn,
        "ADMIN_API_KEY": admin_key,
        "TELEGRAM_BOT_TOKEN": bot_token,
        "TELEGRAM_DELIVERY_ENABLED": "false",
        "NINEROUTER_ENABLED": "false",
        "NINEROUTER_API_KEY": "",
        "NINE_ROUTER_API_KEY": "",
    }
    api_root = Path(__file__).resolve().parents[1]
    with (tmp_path / "startup.log").open("w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-access-log",
            ],
            cwd=api_root,
            env=process_env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2) as client:
                ready = False
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        response = client.get("/healthz")
                        if response.status_code == 200:
                            assert response.json() == {"status": "ok"}
                            ready = True
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                assert ready, "API must start successfully with an empty educational catalog"
                student_headers = {"Authorization": signed_student_credentials(bot_token, user_id)}
                missing_id = uuid4()
                for path in (
                    "/content/books",
                    "/content/books?grade=10",
                    "/content/units",
                    f"/content/units?book_id={missing_id}",
                    f"/content/books/{missing_id}/chapters",
                    f"/content/books/{missing_id}/units",
                    f"/content/chapters/{missing_id}/lessons",
                ):
                    response = client.get(path, headers=student_headers)
                    assert response.status_code == 200, path
                    assert response.json() == [], path
                response = client.get(f"/content/books/{missing_id}", headers=student_headers)
                assert response.status_code == 404
                response = client.get(
                    "/admin/content/books", headers={"X-Admin-Api-Key": admin_key}
                )
                assert response.status_code == 200
                assert response.json() == []
                assert client.get("/admin/content/books").status_code == 403
                assert client.get("/content/books").status_code == 401
                # Startup and querying must never fabricate or insert content.
                assert all(count == 0 for count in catalog_counts(dsn).values())
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
