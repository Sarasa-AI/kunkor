"""Content Catalog Router.

Read-only API for approved (published) content.
No write operations - those go through ContentService with explicit gates.
"""

from collections.abc import Generator
from typing import Any, Optional
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from app.core.db import get_db_connection
from app.modules.content.models import (
    ContentProvenance,
    PublishedBookView,
    PublishedChapterView,
    PublishedLessonView,
    UnknownCount,
)
from app.modules.content.service import ContentService
from app.modules.identity.auth import require_student_access

router = APIRouter(
    prefix="/content",
    tags=["Content Catalog"],
    dependencies=[Depends(require_student_access)],
)


def content_connection() -> Generator[psycopg.Connection[Any], None, None]:
    with get_db_connection() as conn:
        yield conn


# Response models
class ProvenanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    source_reference: Optional[str] = None
    license_id: Optional[str] = None
    rights_statement: Optional[str] = None
    verified_by: Optional[str] = None
    verified_at: Optional[str] = None
    verification_status: str
    notes: Optional[str] = None


class PublishedBookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    publisher: str
    edition: Optional[str] = None
    grade_target: dict[str, Any]
    page_count: Any  # int or "unknown"
    chapter_count: int
    provenance: ProvenanceResponse
    version: str
    published_at: str


class PublishedChapterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    book_id: UUID
    number: int | None
    title: str
    page_start: Any
    page_end: Any
    page_count: Any
    question_count: Any
    prerequisites: list[str]
    provenance: ProvenanceResponse
    version: str
    published_at: str


class PublishedLessonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    chapter_id: UUID | None
    number: int | None
    title: str
    page_start: Any
    page_end: Any
    page_count: Any
    estimated_duration_minutes: Any
    question_count: Any
    prerequisites: list[str]
    learning_objectives: list[str]
    provenance: ProvenanceResponse
    version: str
    published_at: str


# Conversion helpers
def _to_provenance_resp(p: ContentProvenance) -> ProvenanceResponse:
    return ProvenanceResponse(
        source=p.source.value,
        source_reference=p.source_reference,
        license_id=p.license_id,
        rights_statement=p.rights_statement,
        verified_by=p.verified_by,
        verified_at=p.verified_at.isoformat() if p.verified_at else None,
        verification_status=p.verification_status.value,
        notes=p.notes,
    )


def _to_count_resp(count: int | UnknownCount) -> int | str:
    return str(count) if isinstance(count, UnknownCount) else count


def _book_to_resp(b: PublishedBookView) -> PublishedBookResponse:
    grades = list(b.grade_target.grades)
    return PublishedBookResponse(
        id=b.id,
        title=b.title,
        publisher=b.publisher,
        edition=b.edition,
        grade_target={"grades": grades, "track": b.grade_target.track},
        page_count=_to_count_resp(b.page_count),
        chapter_count=b.chapter_count,
        provenance=_to_provenance_resp(b.provenance),
        version=b.version,
        published_at=b.published_at.isoformat(),
    )


def _chapter_to_resp(c: PublishedChapterView) -> PublishedChapterResponse:
    prereqs = [str(p) for p in c.prerequisites] if c.prerequisites else []
    return PublishedChapterResponse(
        id=c.id,
        book_id=c.book_id,
        number=c.number,
        title=c.title,
        page_start=_to_count_resp(c.page_start),
        page_end=_to_count_resp(c.page_end),
        page_count=_to_count_resp(c.page_count),
        question_count=_to_count_resp(c.question_count),
        prerequisites=prereqs,
        provenance=_to_provenance_resp(c.provenance),
        version=c.version,
        published_at=c.published_at.isoformat(),
    )


def _lesson_to_resp(lesson: PublishedLessonView) -> PublishedLessonResponse:
    prereqs = [str(p) for p in lesson.prerequisites] if lesson.prerequisites else []
    objectives = list(lesson.learning_objectives) if lesson.learning_objectives else []
    return PublishedLessonResponse(
        id=lesson.id,
        chapter_id=lesson.chapter_id,
        number=lesson.number,
        title=lesson.title,
        page_start=_to_count_resp(lesson.page_start),
        page_end=_to_count_resp(lesson.page_end),
        page_count=_to_count_resp(lesson.page_count),
        estimated_duration_minutes=_to_count_resp(lesson.estimated_duration_minutes),
        question_count=_to_count_resp(lesson.question_count),
        prerequisites=prereqs,
        learning_objectives=objectives,
        provenance=_to_provenance_resp(lesson.provenance),
        version=lesson.version,
        published_at=lesson.published_at.isoformat(),
    )


# Endpoints
@router.get(
    "/books",
    response_model=list[PublishedBookResponse],
    summary="List published books for grades 10-12",
)
def list_published_books(
    grade: Optional[int] = Query(None, ge=10, le=12, description="Filter by grade (10, 11, 12)"),
    track: Optional[str] = Query(
        None, description="Filter by track (mathematics, experimental, humanities)"
    ),
    conn: psycopg.Connection[Any] = Depends(content_connection),
) -> list[PublishedBookResponse]:
    """Get all published books.

    Only returns content with status='published' AND published_at IS NOT NULL.
    Unknown counts return as "unknown(no_source)" strings.
    """
    service = ContentService()
    books = service.get_published_books(conn, grade=grade, track=track)
    return [_book_to_resp(b) for b in books]


@router.get(
    "/books/{book_id}",
    response_model=PublishedBookResponse,
    summary="Get published book by ID",
)
def get_published_book(
    book_id: UUID, conn: psycopg.Connection[Any] = Depends(content_connection)
) -> PublishedBookResponse:
    """Get a single published book by ID.

    Returns 404 if book is not published or doesn't exist.
    """
    service = ContentService()
    book = service.get_published_book_by_id(conn, book_id)
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Published book not found",
        )
    return _book_to_resp(book)


@router.get(
    "/books/{book_id}/chapters",
    response_model=list[PublishedChapterResponse],
    summary="Get published chapters for a book",
)
def get_published_chapters(
    book_id: UUID, conn: psycopg.Connection[Any] = Depends(content_connection)
) -> list[PublishedChapterResponse]:
    """Get all published chapters for a book.

    Returns empty list if book has no published chapters.
    """
    service = ContentService()
    chapters = service.get_published_chapters_for_book(conn, book_id)
    return [_chapter_to_resp(c) for c in chapters]


@router.get(
    "/chapters/{chapter_id}/lessons",
    response_model=list[PublishedLessonResponse],
    summary="Get published lessons for a chapter",
)
def get_published_lessons(
    chapter_id: UUID, conn: psycopg.Connection[Any] = Depends(content_connection)
) -> list[PublishedLessonResponse]:
    """Get all published lessons for a chapter.

    Returns empty list if chapter has no published lessons.
    """
    service = ContentService()
    lessons = service.get_published_lessons_for_chapter(conn, chapter_id)
    return [_lesson_to_resp(lesson) for lesson in lessons]


@router.get("/units", summary="List independently published, approved content units")
def list_published_units(
    book_id: UUID | None = None,
    conn: psycopg.Connection[Any] = Depends(content_connection),
) -> list[dict[str, Any]]:
    """Draft parents need not be published for an independently reviewed unit."""
    return ContentService().get_published_units(conn, book_id)


@router.get("/books/{book_id}/units", summary="List approved published units of a partial book")
def list_published_book_units(
    book_id: UUID,
    conn: psycopg.Connection[Any] = Depends(content_connection),
) -> list[dict[str, Any]]:
    return ContentService().get_published_units(conn, book_id)
