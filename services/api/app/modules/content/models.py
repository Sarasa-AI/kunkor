"""Content Catalog domain models.

Hierarchy: Curriculum → Subject → Book → Edition → Chapter → Lesson → Page/Section → Question

All counts nullable; provenance required; publish gate enforced.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID


class ContentStatus(str, Enum):
    """Content publication status."""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    SUPERSEDED = "superseded"


class ProvenanceSource(str, Enum):
    """Source of content metadata."""

    PUBLISHER_CATALOG = "publisher_catalog"
    OFFICIAL_CURRICULUM = "official_curriculum"
    LOCAL_SYNTHETIC_FIXTURE = "local_synthetic_fixture"
    EDUCATOR_VERIFIED = "educator_verified"
    OWNER_ENTERED = "owner_entered"
    AI_SUGGESTION = "ai_suggestion"
    NO_SOURCE = "no_source"


class VerificationStatus(str, Enum):
    """Verification state of content counts/structure."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    PENDING_REVIEW = "pending_review"
    DISPUTED = "disputed"


@dataclass(frozen=True)
class ContentProvenance:
    """Provenance metadata for a content item."""

    source: ProvenanceSource
    source_reference: Optional[str] = None  # ISBN, publisher doc ID, URL, etc.
    license_id: Optional[str] = None
    rights_statement: Optional[str] = None
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    notes: Optional[str] = None

    def has_verified_counts(self) -> bool:
        return self.verification_status == VerificationStatus.VERIFIED


@dataclass(frozen=True)
class GradeTarget:
    """Grade targeting for content (grades 10, 11, 12)."""

    grades: frozenset[int]  # {10, 11, 12}
    track: Optional[str] = None  # nullable per D-01

    @classmethod
    def from_grade_codes(cls, codes: list[str], track: Optional[str] = None) -> "GradeTarget":
        grade_map = {"G10": 10, "G11": 11, "G12": 12}
        return cls(
            grades=frozenset(grade_map.get(c, 0) for c in codes if c in grade_map), track=track
        )

    def includes_grade(self, grade: int) -> bool:
        return grade in self.grades


class UnknownCount:
    """Sentinel for unknown/not-sourced counts."""

    def __init__(self, reason: str = "no_source"):
        self.reason = reason

    def __bool__(self) -> bool:
        return False

    def __int__(self) -> int:
        raise ValueError(f"Count unknown: {self.reason}")

    def __str__(self) -> str:
        return f"unknown({self.reason})"

    def __repr__(self) -> str:
        return f"UnknownCount({self.reason!r})"


UNKNOWN = UnknownCount("no_source")
NO_SOURCE = UnknownCount("no_source")


@dataclass(frozen=True)
class Curriculum:
    """Top-level curriculum (e.g., Iranian National Curriculum)."""

    id: UUID
    code: str
    name: str
    description: Optional[str]
    provenance: ContentProvenance
    version: str
    status: ContentStatus
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime] = None


@dataclass(frozen=True)
class Subject:
    """Subject within a curriculum (e.g., Mathematics, Biology)."""

    id: UUID
    curriculum_id: UUID
    code: str
    name: str
    description: Optional[str]
    provenance: ContentProvenance
    version: str
    status: ContentStatus
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime] = None


@dataclass(frozen=True)
class Book:
    """Book within a subject."""

    id: UUID
    subject_id: UUID
    title: str
    publisher: str
    isbn: Optional[str]
    edition: Optional[str] = None
    grade_target: GradeTarget = GradeTarget(grades=frozenset())
    provenance: ContentProvenance = ContentProvenance(source=ProvenanceSource.NO_SOURCE)
    page_count: int | UnknownCount = UNKNOWN
    version: str = "1.0.0"
    status: ContentStatus = ContentStatus.DRAFT
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()
    published_at: Optional[datetime] = None


@dataclass(frozen=True)
class Edition:
    """Specific edition of a book."""

    id: UUID
    book_id: UUID
    edition_number: int
    publication_year: Optional[int]
    isbn: Optional[str]
    page_count: int | UnknownCount = UNKNOWN
    provenance: ContentProvenance = ContentProvenance(source=ProvenanceSource.NO_SOURCE)
    version: str = "1.0.0"
    status: ContentStatus = ContentStatus.DRAFT
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()
    published_at: Optional[datetime] = None


@dataclass(frozen=True)
class Chapter:
    """Chapter within a book edition."""

    id: UUID
    edition_id: UUID
    number: int | None
    title: str
    page_start: int | UnknownCount = UNKNOWN
    page_end: int | UnknownCount = UNKNOWN
    question_count: int | UnknownCount = UNKNOWN
    prerequisites: frozenset[UUID] = frozenset()
    provenance: ContentProvenance = ContentProvenance(source=ProvenanceSource.NO_SOURCE)
    version: str = "1.0.0"
    status: ContentStatus = ContentStatus.DRAFT
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()
    published_at: Optional[datetime] = None

    def page_count(self) -> int | UnknownCount:
        if isinstance(self.page_start, int) and isinstance(self.page_end, int):
            return self.page_end - self.page_start + 1
        return UNKNOWN


@dataclass(frozen=True)
class Lesson:
    """Lesson within a chapter."""

    id: UUID
    chapter_id: UUID | None
    number: int | None
    title: str
    page_start: int | UnknownCount = UNKNOWN
    page_end: int | UnknownCount = UNKNOWN
    estimated_duration_minutes: int | UnknownCount = UNKNOWN
    question_count: int | UnknownCount = UNKNOWN
    prerequisites: frozenset[UUID] = frozenset()
    learning_objectives: frozenset[str] = frozenset()
    provenance: ContentProvenance = ContentProvenance(source=ProvenanceSource.NO_SOURCE)
    version: str = "1.0.0"
    status: ContentStatus = ContentStatus.DRAFT
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()
    published_at: Optional[datetime] = None

    def page_count(self) -> int | UnknownCount:
        if isinstance(self.page_start, int) and isinstance(self.page_end, int):
            return self.page_end - self.page_start + 1
        return UNKNOWN


@dataclass(frozen=True)
class PageSection:
    """Page or section within a lesson."""

    id: UUID
    lesson_id: UUID
    page_number: int | UnknownCount = UNKNOWN
    section_title: Optional[str] = None
    content_summary: Optional[str] = None
    question_count: int | UnknownCount = UNKNOWN
    provenance: ContentProvenance = ContentProvenance(source=ProvenanceSource.NO_SOURCE)
    version: str = "1.0.0"
    status: ContentStatus = ContentStatus.DRAFT
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()
    published_at: Optional[datetime] = None


@dataclass(frozen=True)
class Question:
    """Question within a page/section."""

    id: UUID
    page_section_id: UUID
    question_number: int
    question_type: str
    difficulty: Optional[str] = None
    estimated_time_minutes: int | UnknownCount = UNKNOWN
    tags: frozenset[str] = frozenset()
    provenance: ContentProvenance = ContentProvenance(source=ProvenanceSource.NO_SOURCE)
    version: str = "1.0.0"
    status: ContentStatus = ContentStatus.DRAFT
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()
    published_at: Optional[datetime] = None


# Read-only view models for API


@dataclass(frozen=True)
class PublishedBookView:
    """Published book view for Content Intelligence Agent."""

    id: UUID
    title: str
    publisher: str
    edition: Optional[str]
    grade_target: GradeTarget
    page_count: int | UnknownCount
    chapter_count: int
    provenance: ContentProvenance
    version: str
    published_at: datetime


@dataclass(frozen=True)
class PublishedChapterView:
    """Published chapter view."""

    id: UUID
    book_id: UUID
    number: int | None
    title: str
    page_start: int | UnknownCount
    page_end: int | UnknownCount
    page_count: int | UnknownCount
    question_count: int | UnknownCount
    prerequisites: frozenset[UUID]
    provenance: ContentProvenance
    version: str
    published_at: datetime


@dataclass(frozen=True)
class PublishedLessonView:
    """Published lesson view."""

    id: UUID
    chapter_id: UUID | None
    number: int | None
    title: str
    page_start: int | UnknownCount
    page_end: int | UnknownCount
    page_count: int | UnknownCount
    estimated_duration_minutes: int | UnknownCount
    question_count: int | UnknownCount
    prerequisites: frozenset[UUID]
    learning_objectives: frozenset[str]
    provenance: ContentProvenance
    version: str
    published_at: datetime


# Type aliases for counts that may be unknown
CountOrUnknown = int | UnknownCount
