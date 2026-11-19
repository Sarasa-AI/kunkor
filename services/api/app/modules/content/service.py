"""Content domain facade. Catalog population is owner operation, never startup work."""

from typing import Any
from uuid import UUID

import psycopg

from app.modules.content.models import PublishedBookView, PublishedChapterView, PublishedLessonView
from app.modules.content.repository import ContentRepository


class ContentService:
    def __init__(self, repository: ContentRepository | None = None):
        self.repo = repository or ContentRepository()

    def get_published_books(
        self, conn: psycopg.Connection[Any], grade: int | None = None, track: str | None = None
    ) -> list[PublishedBookView]:
        return self.repo.get_published_books(conn, grade=grade, track=track)

    def get_published_book_by_id(
        self, conn: psycopg.Connection[Any], book_id: UUID
    ) -> PublishedBookView | None:
        return self.repo.get_published_book_by_id(conn, book_id)

    def get_published_chapters_for_book(
        self, conn: psycopg.Connection[Any], book_id: UUID
    ) -> list[PublishedChapterView]:
        return self.repo.get_published_chapters_for_book(conn, book_id)

    def get_published_lessons_for_chapter(
        self, conn: psycopg.Connection[Any], chapter_id: UUID
    ) -> list[PublishedLessonView]:
        return self.repo.get_published_lessons_for_chapter(conn, chapter_id)

    def get_published_units(
        self, conn: psycopg.Connection[Any], book_id: UUID | None = None
    ) -> list[dict[str, Any]]:
        return self.repo.get_published_units(conn, book_id)

    def get_agent_resources(
        self,
        conn: psycopg.Connection[Any],
        stage_code: str | None = None,
        grade: int | None = None,
        track: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.repo.get_agent_resources(conn, stage_code=stage_code, grade=grade, track=track)

    def publish_book(self, conn: psycopg.Connection[Any], book_id: UUID, verified_by: str) -> bool:
        return self.repo.publish_book(conn, book_id, verified_by)

    def lock_agent_resources(self, conn: psycopg.Connection[Any], resource_ids: list[str]) -> None:
        """Retain catalog and ancestor locks through the activation transaction."""
        self.repo.lock_agent_resources(conn, resource_ids)
