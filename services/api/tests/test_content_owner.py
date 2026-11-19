"""Empty-to-grow acceptance uses rollback-isolated, clearly synthetic metadata only."""

from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import get_db_connection
from app.main import app
from app.modules.content.router import content_connection
from app.modules.content.service import ContentService
from app.modules.identity.auth import require_student_access

OWNER_HEADERS = {"X-Admin-Api-Key": "synthetic-owner-api-key-for-tests"}
REVIEW = {
    "provenance_source": "owner_entered",
    "provenance_reference": "synthetic-automated-test-record",
    "license_id": "synthetic-test-license",
    "rights_statement": "Synthetic automated testing metadata only",
    "license_active": True,
}


@pytest.fixture
def catalog_client(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_API_KEY", OWNER_HEADERS["X-Admin-Api-Key"])
    saved = dict(app.dependency_overrides)
    with get_db_connection(test=True) as conn:
        with conn.transaction(force_rollback=True):

            def connection_override():
                yield conn

            app.dependency_overrides[content_connection] = connection_override
            app.dependency_overrides[require_student_access] = lambda: uuid4()
            try:
                with TestClient(app) as client:
                    yield client, conn
            finally:
                app.dependency_overrides.clear()
                app.dependency_overrides.update(saved)


def book(client, **fields):
    response = client.post(
        "/admin/content/books",
        json={"title": "Synthetic Test Book", **fields},
        headers=OWNER_HEADERS,
    )
    assert response.status_code == 201, response.text
    return response.json()


def unit(client, book_id, **fields):
    response = client.post(
        "/admin/content/units",
        json={"book_id": book_id, "kind": "chapter", "title": "Synthetic Test Unit", **fields},
        headers=OWNER_HEADERS,
    )
    assert response.status_code == 201, response.text
    return response.json()


def action(client, record, value, *, kind="units", expected=200):
    response = client.post(
        f"/admin/content/{kind}/{record['id']}/{value}", json={}, headers=OWNER_HEADERS
    )
    assert response.status_code == expected, response.text
    return response.json()


def published(client, record):
    response = client.get(f"/content/books/{record['id']}/units")
    assert response.status_code == 200, response.text
    return response.json()


def test_single_draft_book_persists_without_other_catalog_records(catalog_client):
    client, conn = catalog_client
    record = book(client)
    assert record["subject_id"] is None
    assert record["status"] == "draft"
    assert (
        client.get(f"/admin/content/books/{record['id']}", headers=OWNER_HEADERS).json()["id"]
        == record["id"]
    )
    assert (
        client.get(f"/admin/content/books/{record['id']}/units", headers=OWNER_HEADERS).json() == []
    )
    assert published(client, record) == []
    assert client.get(f"/content/books/{record['id']}").status_code == 404
    assert (
        conn.execute(
            "SELECT COUNT(*) AS n FROM editions WHERE book_id = %s", (record["id"],)
        ).fetchone()["n"]
        == 0
    )


def test_independent_numberless_chapter_publishes_and_more_units_can_follow(catalog_client):
    client, conn = catalog_client
    record = book(client, grades=[10], subject_code="synthetic-subject")
    first = unit(client, record["id"], **REVIEW)
    assert first["number"] is None
    assert first["page_start"] is None
    action(client, first, "submit")
    action(client, first, "approve")
    assert published(client, record) == []
    result = action(client, first, "publish")
    assert result["status"] == "published"
    assert result["approved_by"] == "owner_admin"
    assert len(published(client, record)) == 1
    chapter_response = client.get(f"/content/books/{record['id']}/chapters")
    assert chapter_response.status_code == 200
    assert chapter_response.json()[0]["number"] is None
    assert chapter_response.json()[0]["page_count"] == "unknown(no_source)"
    second = unit(client, record["id"], number=2, page_start=3)
    assert second["page_end"] is None
    assert len(published(client, record)) == 1
    assert (
        conn.execute("SELECT status FROM books WHERE id = %s", (record["id"],)).fetchone()["status"]
        == "draft"
    )
    resources = ContentService().get_agent_resources(conn, stage_code="upper_secondary", grade=10)
    assert [r["resource_id"] for r in resources if str(r["book_id"]) == record["id"]] == [
        first["id"]
    ]
    assert resources[-1]["duration_minutes"] is None


@pytest.mark.parametrize("kind", ["lesson", "section", "topic"])
def test_smaller_units_publish_under_draft_parents(catalog_client, kind):
    client, _ = catalog_client
    record = book(client)
    parent = unit(client, record["id"])
    child = unit(
        client,
        record["id"],
        kind=kind,
        parent_id=parent["id"],
        page_start=1,
        page_end=2,
        exercise_start=1,
        exercise_end=3,
        **REVIEW,
    )
    action(client, child, "approve")
    action(client, child, "publish")
    assert [r["id"] for r in published(client, record)] == [child["id"]]
    if kind == "lesson":
        response = client.get(f"/content/chapters/{parent['id']}/lessons")
        assert response.status_code == 200
        assert response.json()[0]["number"] is None
    action(client, parent, "archive")
    assert published(client, record) == []


def test_draft_edit_invalidates_approval_and_audit_is_immutable(catalog_client):
    client, conn = catalog_client
    record = book(client)
    first = unit(client, record["id"], **REVIEW)
    action(client, first, "approve")
    action(client, first, "publish")
    edited = client.patch(
        f"/admin/content/units/{first['id']}",
        json={"title": "Synthetic Revised Unit"},
        headers=OWNER_HEADERS,
    )
    assert edited.status_code == 200
    assert edited.json()["status"] == "draft"
    assert edited.json()["approved_at"] is None
    assert published(client, record) == []
    action(client, first, "publish", expected=409)
    audit = client.get(f"/admin/content/units/{first['id']}/audit", headers=OWNER_HEADERS).json()
    assert len(audit) >= 4
    assert all(r["actor_identity"] == "owner_admin" for r in audit)
    assert any(r["after_record"]["title"] == "Synthetic Revised Unit" for r in audit)
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="append-only"):
        with conn.transaction():
            conn.execute(
                "UPDATE content_audit_events SET actor_identity = 'spoof' WHERE entity_id = %s",
                (first["id"],),
            )


def test_rights_enforced_separately_from_availability_and_owner_review(catalog_client):
    client, _ = catalog_client
    record = book(client)
    first = unit(client, record["id"], **{**REVIEW, "license_active": False})
    action(client, first, "approve")
    action(client, first, "publish", expected=409)
    response = client.patch(
        f"/admin/content/units/{first['id']}", json={"license_active": True}, headers=OWNER_HEADERS
    )
    assert response.status_code == 200
    action(client, first, "approve")
    action(client, first, "publish")
    assert len(published(client, record)) == 1
    client.patch(
        f"/admin/content/units/{first['id']}", json={"license_active": False}, headers=OWNER_HEADERS
    )
    assert published(client, record) == []


def test_unreviewed_and_ai_suggested_content_never_leaks(catalog_client):
    client, conn = catalog_client
    record = book(client, grades=[12])
    first = unit(client, record["id"], **{**REVIEW, "provenance_source": "ai_suggestion"})
    action(client, first, "publish", expected=409)
    assert published(client, record) == []
    assert ContentService().get_agent_resources(conn, "konkur") == []
    action(client, first, "approve")
    action(client, first, "publish")
    assert len(published(client, record)) == 1
    action(client, first, "reject")
    assert published(client, record) == []


@pytest.mark.parametrize(
    "metadata",
    [{}, {"provenance_source": "no_source"}, {"provenance_source": "local_synthetic_fixture"}],
)
def test_unverified_provenance_cannot_be_approved(catalog_client, metadata):
    client, _ = catalog_client
    record = book(client)
    first = unit(client, record["id"], **metadata)
    action(client, first, "approve", expected=409)
    assert published(client, record) == []


def test_archive_does_not_corrupt_other_books_or_siblings(catalog_client):
    client, _ = catalog_client
    first_book, second_book = book(client), book(client)
    first = unit(client, first_book["id"], **REVIEW)
    sibling = unit(client, first_book["id"], **REVIEW)
    unrelated = unit(client, second_book["id"], **REVIEW)
    for item in (first, sibling, unrelated):
        action(client, item, "approve")
        action(client, item, "publish")
    action(client, first, "archive")
    assert [r["id"] for r in published(client, first_book)] == [sibling["id"]]
    assert [r["id"] for r in published(client, second_book)] == [unrelated["id"]]
    action(client, first_book, "archive", kind="books")
    assert published(client, first_book) == []
    assert [r["id"] for r in published(client, second_book)] == [unrelated["id"]]


def test_owner_auth_and_cross_book_parent_are_enforced(catalog_client):
    client, _ = catalog_client
    assert client.get("/admin/content/books").status_code == 403
    assert client.post("/admin/content/books", json={}).status_code == 403
    first_book, second_book = book(client), book(client)
    parent = unit(client, first_book["id"])
    response = client.post(
        "/admin/content/units",
        json={"book_id": second_book["id"], "kind": "lesson", "parent_id": parent["id"]},
        headers=OWNER_HEADERS,
    )
    assert response.status_code == 409
    response = client.patch(
        f"/admin/content/books/{first_book['id']}",
        json={"approved_by": "attacker", "status": "published"},
        headers=OWNER_HEADERS,
    )
    assert response.status_code == 422


def test_validated_ranges_can_be_saved_incrementally_without_fabrication(catalog_client):
    client, _ = catalog_client
    record = book(client)
    first = unit(client, record["id"], page_start=10, exercise_start=4)
    response = client.patch(
        f"/admin/content/units/{first['id']}", json={"page_end": 5}, headers=OWNER_HEADERS
    )
    assert response.status_code == 409
    response = client.patch(
        f"/admin/content/units/{first['id']}",
        json={"page_end": 12, "exercise_end": 9},
        headers=OWNER_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["page_start"] == 10
    assert response.json()["page_end"] == 12
    assert response.json()["question_count"] is None
    assert response.json()["estimated_duration_minutes"] is None


def test_legacy_status_flags_do_not_bypass_owner_approval(catalog_client):
    client, conn = catalog_client
    record = book(client, **REVIEW)
    conn.execute(
        "UPDATE books SET status='published', published_at=NOW(), "
        "provenance_verification_status='verified' WHERE id=%s",
        (record["id"],),
    )
    assert client.get(f"/content/books/{record['id']}").status_code == 404
    assert published(client, record) == []


def test_published_book_with_zero_chapters_is_available(catalog_client):
    client, _ = catalog_client
    record = book(client, **REVIEW)
    action(client, record, "approve", kind="books")
    action(client, record, "publish", kind="books")
    response = client.get(f"/content/books/{record['id']}")
    assert response.status_code == 200
    assert response.json()["chapter_count"] == 0
    assert published(client, record) == []


def test_catalog_rollback_preserves_owner_data_when_old_hierarchy_cannot_represent_it(
    catalog_client,
):
    from pathlib import Path

    client, conn = catalog_client
    record = book(client)
    first = unit(client, record["id"])
    before = conn.execute("SELECT * FROM v_content_units WHERE id=%s", (first["id"],)).fetchone()
    audit_before = conn.execute(
        "SELECT * FROM content_audit_events WHERE entity_id=%s ORDER BY id", (first["id"],)
    ).fetchall()
    script = (
        Path(__file__).parents[1] / "migrations/0011_empty_to_grow_catalog.down.sql"
    ).read_text()
    with pytest.raises(psycopg.errors.RaiseException, match="data-preserving plan"):
        with conn.transaction():
            conn.execute(script)
    assert (
        conn.execute("SELECT * FROM v_content_units WHERE id=%s", (first["id"],)).fetchone()
        == before
    )
    assert (
        conn.execute(
            "SELECT * FROM content_audit_events WHERE entity_id=%s ORDER BY id", (first["id"],)
        ).fetchall()
        == audit_before
    )
