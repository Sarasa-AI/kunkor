"""Authoritative catalog reads. Empty queries are successful; unknown counts stay unknown."""

from typing import Any, Optional
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.modules.content.management import OwnerContentRepository
from app.modules.content.models import (
    UNKNOWN,
    ContentProvenance,
    ContentStatus,
    Curriculum,
    GradeTarget,
    ProvenanceSource,
    PublishedBookView,
    PublishedChapterView,
    PublishedLessonView,
    UnknownCount,
    VerificationStatus,
)


class ContentRepository:
    @staticmethod
    def _to_provenance(row: dict[str, Any]) -> ContentProvenance:
        return ContentProvenance(
            source=ProvenanceSource(row.get("provenance_source", "no_source")),
            source_reference=row.get("provenance_reference"),
            license_id=row.get("provenance_license_id"),
            rights_statement=row.get("provenance_rights_statement"),
            verified_by=row.get("provenance_verified_by"),
            verified_at=row.get("provenance_verified_at"),
            verification_status=VerificationStatus(
                row.get("provenance_verification_status", "unverified")
            ),
            notes=row.get("provenance_notes"),
        )

    @staticmethod
    def _to_count(value: Optional[int]) -> int | UnknownCount:
        return value if value is not None else UNKNOWN

    @classmethod
    def get_curriculum_by_code(
        cls, conn: psycopg.Connection[Any], code: str
    ) -> Optional[Curriculum]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM curricula WHERE code = %s", (code,))
            row = cur.fetchone()
        if not row:
            return None
        return Curriculum(
            id=UUID(str(row["id"])),
            code=row["code"],
            name=row["name"],
            description=row["description"],
            provenance=cls._to_provenance(row),
            version=row["version"],
            status=ContentStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            published_at=row["published_at"],
        )

    @classmethod
    def _book(cls, row: dict[str, Any]) -> PublishedBookView:
        return PublishedBookView(
            id=UUID(str(row["id"])),
            title=row["title"],
            publisher=row["publisher"],
            edition=row["edition"],
            grade_target=GradeTarget(
                grades=frozenset(g for g in (10, 11, 12) if row[f"grade_{g}"]), track=row["track"]
            ),
            page_count=cls._to_count(row["page_count"]),
            chapter_count=row["chapter_count"],
            provenance=cls._to_provenance(row),
            version=row["version"],
            published_at=row["published_at"],
        )

    @classmethod
    def get_published_books(
        cls, conn: psycopg.Connection[Any], grade: Optional[int] = None, track: Optional[str] = None
    ) -> list[PublishedBookView]:
        query = "SELECT * FROM v_published_books WHERE TRUE"
        params: list[Any] = []
        if grade in (10, 11, 12):
            query += f" AND grade_{grade} = TRUE"
        if track:
            query += " AND (track = %s OR track IS NULL)"
            params.append(track)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query + " ORDER BY title, id", tuple(params))
            return [cls._book(row) for row in cur.fetchall()]

    @classmethod
    def get_published_book_by_id(
        cls, conn: psycopg.Connection[Any], book_id: UUID
    ) -> Optional[PublishedBookView]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM v_published_books WHERE id = %s", (book_id,))
            row = cur.fetchone()
            return cls._book(row) if row else None

    @classmethod
    def get_published_chapters_for_book(
        cls, conn: psycopg.Connection[Any], book_id: UUID
    ) -> list[PublishedChapterView]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM v_trusted_content_units WHERE book_id = %s "
                "AND kind = 'chapter' ORDER BY number NULLS LAST, id",
                (book_id,),
            )
            result = []
            for row in cur.fetchall():
                start, end = row["page_start"], row["page_end"]
                result.append(
                    PublishedChapterView(
                        id=UUID(str(row["id"])),
                        book_id=UUID(str(row["book_id"])),
                        number=row["number"],
                        title=row["title"],
                        page_start=cls._to_count(start),
                        page_end=cls._to_count(end),
                        page_count=end - start + 1
                        if start is not None and end is not None
                        else UNKNOWN,
                        question_count=cls._to_count(row["question_count"]),
                        prerequisites=frozenset(UUID(str(pid)) for pid in row["prerequisites"]),
                        provenance=cls._to_provenance(row),
                        version=row["version"],
                        published_at=row["published_at"],
                    )
                )
            return result

    @classmethod
    def get_published_lessons_for_chapter(
        cls, conn: psycopg.Connection[Any], chapter_id: UUID
    ) -> list[PublishedLessonView]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT u.*, l.learning_objectives FROM v_trusted_content_units u "
                "JOIN lessons l ON l.id = u.id WHERE u.kind = 'lesson' "
                "AND u.parent_id = %s ORDER BY u.number NULLS LAST, u.id",
                (chapter_id,),
            )
            result = []
            for row in cur.fetchall():
                start, end = row["page_start"], row["page_end"]
                result.append(
                    PublishedLessonView(
                        id=UUID(str(row["id"])),
                        chapter_id=UUID(str(chapter_id)),
                        number=row["number"],
                        title=row["title"],
                        page_start=cls._to_count(start),
                        page_end=cls._to_count(end),
                        page_count=end - start + 1
                        if start is not None and end is not None
                        else UNKNOWN,
                        estimated_duration_minutes=cls._to_count(row["estimated_duration_minutes"]),
                        question_count=cls._to_count(row["question_count"]),
                        prerequisites=frozenset(UUID(str(pid)) for pid in row["prerequisites"]),
                        learning_objectives=frozenset(row["learning_objectives"]),
                        provenance=cls._to_provenance(row),
                        version=row["version"],
                        published_at=row["published_at"],
                    )
                )
            return result

    @classmethod
    def get_published_units(
        cls, conn: psycopg.Connection[Any], book_id: UUID | None = None
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM v_trusted_content_units"
        params: tuple[Any, ...] = ()
        if book_id is not None:
            query += " WHERE book_id = %s"
            params = (book_id,)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query + " ORDER BY created_at, id", params)
            return [OwnerContentRepository._unit_response(row) for row in cur.fetchall()]

    @classmethod
    def get_agent_resources(
        cls,
        conn: psycopg.Connection[Any],
        stage_code: str | None = None,
        grade: int | None = None,
        track: str | None = None,
    ) -> list[dict[str, Any]]:
        """Only reviewed, published, licensed units; nullable quantities are preserved."""
        # Existing intake cohorts use upper_secondary and konkur. No default curriculum
        # is implied for other cohorts, and an unset grade targets no student cohort.
        if stage_code is not None and stage_code not in ("upper_secondary", "konkur"):
            return []
        query = """SELECT u.*, b.grade_10, b.grade_11, b.grade_12, b.track, b.subject_code
                   FROM v_trusted_content_units u JOIN books b ON b.id = u.book_id WHERE TRUE"""
        params: list[Any] = []
        if grade in (10, 11, 12):
            query += f" AND b.grade_{grade} = TRUE"
        elif stage_code == "konkur":
            query += " AND b.grade_12 = TRUE"
        elif stage_code == "upper_secondary":
            query += " AND (b.grade_10 OR b.grade_11 OR b.grade_12)"
        if track:
            query += " AND (b.track = %s OR b.track IS NULL)"
            params.append(track)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query + " ORDER BY u.created_at, u.id", tuple(params))
            result = []
            for row in cur.fetchall():
                item = OwnerContentRepository._unit_response(row)
                item["resource_id"] = str(row["id"])
                item["grades"] = [g for g in (10, 11, 12) if row[f"grade_{g}"]]
                item["subject"] = row["subject_code"]
                item["duration_minutes"] = row["estimated_duration_minutes"]
                item["page_count"] = (
                    row["page_end"] - row["page_start"] + 1
                    if row["page_start"] is not None and row["page_end"] is not None
                    else None
                )
                item["test_count"] = row["question_count"]
                item["stage_code"] = stage_code
                result.append(item)
            return result

    @classmethod
    def publish_book(cls, conn: psycopg.Connection[Any], book_id: UUID, verified_by: str) -> bool:
        """Legacy caller compatibility: publishing cannot implicitly approve content."""
        repo = OwnerContentRepository()
        try:
            repo.transition(conn, book_id, "publish", book=True)
        except ValueError as exc:
            from app.modules.content.management import ContentNotFound

            if isinstance(exc, ContentNotFound):
                return False
            raise
        return True

    @classmethod
    def lock_agent_resources(cls, conn: psycopg.Connection[Any], resource_ids: list[str]) -> None:
        # Owner mutations take the same transaction lock before acquiring rows. This
        # avoids lock-order races between publication, ancestor archival and activation.
        conn.execute("SELECT pg_advisory_xact_lock_shared(hashtext('kunkor_content_owner'))")
        ids = {UUID(value) for value in resource_ids}
        tables: dict[str, set[UUID]] = {
            name: set() for name in ("books", "chapters", "lessons", "page_sections", "editions")
        }
        seen: set[UUID] = set()
        pending = set(ids)
        with conn.cursor(row_factory=dict_row) as cur:
            while pending:
                cur.execute(
                    "SELECT id, book_id, parent_id, kind FROM v_content_units WHERE id = ANY(%s)",
                    (list(pending),),
                )
                rows = cur.fetchall()
                seen.update(pending)
                pending = set()
                for row in rows:
                    table = {
                        "chapter": "chapters",
                        "lesson": "lessons",
                        "section": "page_sections",
                        "topic": "page_sections",
                    }[row["kind"]]
                    tables[table].add(row["id"])
                    if row["book_id"]:
                        tables["books"].add(row["book_id"])
                    if row["parent_id"] and row["parent_id"] not in seen:
                        pending.add(row["parent_id"])
            if tables["chapters"]:
                cur.execute(
                    "SELECT edition_id FROM chapters WHERE id = ANY(%s)",
                    (list(tables["chapters"]),),
                )
                tables["editions"].update(
                    row["edition_id"] for row in cur.fetchall() if row["edition_id"]
                )
            for table, table_ids in tables.items():
                if table_ids:
                    cur.execute(
                        sql.SQL(
                            "SELECT id FROM {} WHERE id = ANY(%s) ORDER BY id FOR SHARE"
                        ).format(sql.Identifier(table)),
                        (sorted(table_ids),),
                    )
                    cur.fetchall()
