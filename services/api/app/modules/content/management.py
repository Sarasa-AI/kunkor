"""Owner-managed drafts and lifecycle operations for the existing catalog tables."""

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

import psycopg
from psycopg import sql
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.content.models import ProvenanceSource

# The current authentication system has a shared owner credential, not personal admin
# identities. Record this role accurately; never accept a reviewer name from request data.
OWNER_ACTOR = "owner_admin"
UnitKind = Literal["chapter", "lesson", "section", "topic"]
Action = Literal["submit", "approve", "publish", "archive", "reject"]


class ContentFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(None, max_length=500)
    provenance_source: ProvenanceSource | None = None
    provenance_reference: str | None = Field(None, max_length=500)
    license_id: str | None = Field(None, max_length=200)
    rights_statement: str | None = None
    license_active: bool | None = None
    notes: str | None = None


class BookFields(ContentFields):
    publisher: str | None = Field(None, max_length=200)
    isbn: str | None = Field(None, max_length=50)
    edition: str | None = Field(None, max_length=50)
    subject_code: str | None = Field(None, max_length=100)
    grades: list[Literal[10, 11, 12]] | None = None
    track: str | None = Field(None, max_length=50)
    page_count: int | None = Field(None, ge=0)


class UnitFields(ContentFields):
    number: int | None = Field(None, gt=0)
    page_start: int | None = Field(None, gt=0)
    page_end: int | None = Field(None, gt=0)
    exercise_start: int | None = Field(None, gt=0)
    exercise_end: int | None = Field(None, gt=0)
    question_count: int | None = Field(None, ge=0)
    estimated_duration_minutes: int | None = Field(None, gt=0)
    prerequisites: list[UUID] | None = None

    @model_validator(mode="after")
    def ordered_ranges(self) -> "UnitFields":
        for start, end in [
            (self.page_start, self.page_end),
            (self.exercise_start, self.exercise_end),
        ]:
            if start is not None and end is not None and end < start:
                raise ValueError("Range end must be at least its start")
        return self


class UnitCreate(UnitFields):
    book_id: UUID
    kind: UnitKind
    parent_id: UUID | None = None


FIELD_COLUMNS = {
    "license_id": "provenance_license_id",
    "rights_statement": "provenance_rights_statement",
    "notes": "provenance_notes",
}
TABLES = {
    "chapter": "chapters",
    "lesson": "lessons",
    "section": "page_sections",
    "topic": "page_sections",
}


class ContentNotFound(ValueError):
    pass


class ContentConflict(ValueError):
    pass


class OwnerContentRepository:
    """Mutations preserve history and invalidate review of modified metadata."""

    @staticmethod
    def _book_response(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["grades"] = [grade for grade in (10, 11, 12) if row[f"grade_{grade}"]]
        for public, column in FIELD_COLUMNS.items():
            result[public] = result.pop(column)
        return result

    @staticmethod
    def _unit_response(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result.pop("ancestor_hidden", None)
        for public, column in FIELD_COLUMNS.items():
            result[public] = result.pop(column)
        return result

    def get_book(
        self, conn: psycopg.Connection[Any], book_id: UUID, *, lock: bool = False
    ) -> dict[str, Any]:
        query = "SELECT * FROM books WHERE id = %s" + (" FOR UPDATE" if lock else "")
        row = conn.execute(query, (book_id,)).fetchone()
        if not row:
            raise ContentNotFound("Book not found")
        return self._book_response(row)

    def list_books(self, conn: psycopg.Connection[Any]) -> list[dict[str, Any]]:
        return [
            self._book_response(row)
            for row in conn.execute("SELECT * FROM books ORDER BY created_at, id").fetchall()
        ]

    def get_unit(
        self, conn: psycopg.Connection[Any], unit_id: UUID, *, lock: bool = False
    ) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM v_content_units WHERE id = %s", (unit_id,)).fetchone()
        if not row:
            raise ContentNotFound("Content unit not found")
        if lock:
            conn.execute(
                sql.SQL("SELECT id FROM {} WHERE id = %s FOR UPDATE").format(
                    sql.Identifier(TABLES[row["kind"]])
                ),
                (unit_id,),
            )
            row = conn.execute("SELECT * FROM v_content_units WHERE id = %s", (unit_id,)).fetchone()
            assert row is not None
        return self._unit_response(row)

    def list_units(self, conn: psycopg.Connection[Any], book_id: UUID) -> list[dict[str, Any]]:
        self.get_book(conn, book_id)
        return [
            self._unit_response(row)
            for row in conn.execute(
                "SELECT * FROM v_content_units WHERE book_id = %s ORDER BY created_at, id",
                (book_id,),
            ).fetchall()
        ]

    @staticmethod
    def _columns(fields: ContentFields, *, section: bool = False) -> dict[str, Any]:
        values = fields.model_dump(exclude_unset=True, mode="python")
        for key in ("book_id", "kind", "parent_id"):
            values.pop(key, None)
        grades = values.pop("grades", None)
        if "grades" in fields.model_fields_set:
            values.update({f"grade_{grade}": grade in (grades or []) for grade in (10, 11, 12)})
        result = {FIELD_COLUMNS.get(key, key): value for key, value in values.items()}
        if "title" in result:
            result["title"] = (result["title"] or "").strip()
        if "publisher" in result:
            result["publisher"] = result["publisher"] or ""
        if result.get("provenance_source") is not None:
            result["provenance_source"] = result["provenance_source"].value
        elif "provenance_source" in result:
            result["provenance_source"] = "no_source"
        if "license_active" in result:
            result["license_active"] = bool(result["license_active"])
        if "prerequisites" in result:
            result["prerequisites"] = result["prerequisites"] or []
        if section and "title" in result:
            result["section_title"] = result.pop("title")
        return result

    @staticmethod
    def _set_actor(conn: psycopg.Connection[Any]) -> None:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('kunkor_content_owner'))")
        conn.execute("SELECT set_config('app.content_actor', %s, true)", (OWNER_ACTOR,))

    @staticmethod
    def _insert(conn: psycopg.Connection[Any], table: str, values: dict[str, Any]) -> UUID:
        query = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING id").format(
            sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, values)),
            sql.SQL(", ").join(sql.Placeholder() for _ in values),
        )
        row = conn.execute(query, tuple(values.values())).fetchone()
        assert row is not None
        return UUID(str(row["id"]))

    @staticmethod
    def _update(
        conn: psycopg.Connection[Any], table: str, item_id: UUID, values: dict[str, Any]
    ) -> None:
        query = sql.SQL("UPDATE {} SET {}, updated_at = NOW() WHERE id = %s").format(
            sql.Identifier(table),
            sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(key)) for key in values),
        )
        conn.execute(query, (*values.values(), item_id))

    def create_book(self, conn: psycopg.Connection[Any], fields: BookFields) -> dict[str, Any]:
        with conn.transaction():
            self._set_actor(conn)
            values = self._columns(fields)
            values.setdefault("title", "")
            values["owner_identity"] = OWNER_ACTOR
            item_id = self._insert(conn, "books", values)
            return self.get_book(conn, item_id)

    def create_unit(self, conn: psycopg.Connection[Any], fields: UnitCreate) -> dict[str, Any]:
        with conn.transaction():
            self._set_actor(conn)
            book = self.get_book(conn, fields.book_id, lock=True)
            if book["status"] in ("archived", "rejected", "superseded"):
                raise ContentConflict("Restore the book before adding content")
            values = self._columns(fields, section=fields.kind in ("section", "topic"))
            values["book_id"] = fields.book_id
            values["owner_identity"] = OWNER_ACTOR
            values.setdefault(
                "section_title" if fields.kind in ("section", "topic") else "title", ""
            )
            if fields.kind in ("section", "topic"):
                values["unit_kind"] = fields.kind
            if fields.parent_id:
                parent = self.get_unit(conn, fields.parent_id, lock=True)
                if parent["book_id"] != fields.book_id:
                    raise ContentConflict("Parent belongs to another book")
                if parent["status"] in ("archived", "rejected", "superseded"):
                    raise ContentConflict("Restore the parent before adding content")
                if fields.kind == "lesson" and parent["kind"] == "chapter":
                    values["chapter_id"] = fields.parent_id
                elif fields.kind in ("section", "topic") and parent["kind"] in (
                    "chapter",
                    "lesson",
                ):
                    values["chapter_id" if parent["kind"] == "chapter" else "lesson_id"] = (
                        fields.parent_id
                    )
                else:
                    raise ContentConflict("Invalid parent kind for content unit")
            item_id = self._insert(conn, TABLES[fields.kind], values)
            return self.get_unit(conn, item_id)

    def edit(
        self,
        conn: psycopg.Connection[Any],
        item_id: UUID,
        fields: BookFields | UnitFields,
        *,
        book: bool,
    ) -> dict[str, Any]:
        with conn.transaction():
            self._set_actor(conn)
            record = (
                self.get_book(conn, item_id, lock=True)
                if book
                else self.get_unit(conn, item_id, lock=True)
            )
            section = not book and record["kind"] in ("section", "topic")
            values = self._columns(fields, section=section)
            if not values:
                return record
            values.update(
                status="draft",
                approved_at=None,
                approved_by=None,
                published_at=None,
                provenance_verification_status="unverified",
                provenance_verified_by=None,
                provenance_verified_at=None,
            )
            self._update(conn, "books" if book else TABLES[record["kind"]], item_id, values)
            return self.get_book(conn, item_id) if book else self.get_unit(conn, item_id)

    @staticmethod
    def _approval_gate(record: dict[str, Any]) -> None:
        if record["provenance_source"] in ("no_source", "local_synthetic_fixture"):
            raise ContentConflict("Cannot publish content without owner-reviewed provenance")
        for key in ("title", "provenance_reference", "license_id", "rights_statement"):
            if not (record.get(key) or "").strip():
                raise ContentConflict(f"Review requires {key}")

    def transition(
        self, conn: psycopg.Connection[Any], item_id: UUID, action: Action, *, book: bool
    ) -> dict[str, Any]:
        with conn.transaction():
            self._set_actor(conn)
            record = (
                self.get_book(conn, item_id, lock=True)
                if book
                else self.get_unit(conn, item_id, lock=True)
            )
            state = record["status"]
            values: dict[str, Any] = {}
            if action == "submit":
                if state not in ("draft", "rejected", "archived"):
                    raise ContentConflict(
                        "Only drafts, rejected or archived content can be submitted"
                    )
                values.update(
                    status="pending_review",
                    approved_by=None,
                    approved_at=None,
                    published_at=None,
                    provenance_verification_status="pending_review",
                    provenance_verified_by=None,
                    provenance_verified_at=None,
                )
            elif action == "approve":
                if state not in ("draft", "pending_review"):
                    raise ContentConflict("Only draft or pending content can be approved")
                self._approval_gate(record)
                values.update(
                    approved_at=datetime.now(timezone.utc),
                    provenance_verified_at=datetime.now(timezone.utc),
                    status="approved",
                    approved_by=OWNER_ACTOR,
                    provenance_verified_by=OWNER_ACTOR,
                    provenance_verification_status="verified",
                )
            elif action == "publish":
                self._approval_gate(record)
                if state != "approved" or not record["approved_at"] or not record["approved_by"]:
                    raise ContentConflict("Explicit owner approval is required before publication")
                if not record["license_active"]:
                    raise ContentConflict(
                        "An active content usage grant is required before publication"
                    )
                if not book:
                    container = self.get_book(conn, record["book_id"], lock=True)
                    if container["status"] in ("archived", "rejected", "superseded"):
                        raise ContentConflict("Restore the book before publishing content")
                    if record.get("parent_id"):
                        parent = self.get_unit(conn, record["parent_id"], lock=True)
                        if parent["status"] in ("archived", "rejected", "superseded"):
                            raise ContentConflict("Restore the parent before publishing content")
                values["status"] = "published"
                values["published_at"] = datetime.now(timezone.utc)
            else:
                values.update(
                    status="archived" if action == "archive" else "rejected",
                    published_at=None,
                    approved_by=None,
                    approved_at=None,
                    provenance_verified_by=None,
                    provenance_verified_at=None,
                    provenance_verification_status="unverified",
                )
            table = "books" if book else TABLES[record["kind"]]
            self._update(conn, table, item_id, values)
            return self.get_book(conn, item_id) if book else self.get_unit(conn, item_id)

    @staticmethod
    def audit(conn: psycopg.Connection[Any], item_id: UUID) -> list[dict[str, Any]]:
        return conn.execute(
            "SELECT * FROM content_audit_events WHERE entity_id = %s ORDER BY occurred_at, id",
            (item_id,),
        ).fetchall()
