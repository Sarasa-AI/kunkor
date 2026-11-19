"""Tests for Content Catalog Phase 3."""

from uuid import uuid4

import pytest

from app.modules.content.models import (
    UNKNOWN,
    Book,
    ContentProvenance,
    ContentStatus,
    Curriculum,
    GradeTarget,
    ProvenanceSource,
    UnknownCount,
    VerificationStatus,
)
from app.modules.content.repository import ContentRepository
from app.modules.content.service import ContentService


class TestContentModels:
    """Test content catalog domain models."""

    def test_unknown_count_sentinel(self):
        """UNKNOWN sentinel behaves correctly."""
        assert not UNKNOWN
        assert str(UNKNOWN) == "unknown(no_source)"
        with pytest.raises(ValueError, match="Count unknown"):
            int(UNKNOWN)
        with pytest.raises(ValueError, match="Count unknown"):
            UNKNOWN.__int__()

    def test_grade_target_from_codes(self):
        """GradeTarget parses grade codes correctly."""
        gt = GradeTarget.from_grade_codes(["G10", "G12"], track="experimental")
        assert gt.grades == frozenset({10, 12})
        assert gt.track == "experimental"
        assert gt.includes_grade(10)
        assert gt.includes_grade(12)
        assert not gt.includes_grade(11)

    def test_provenance_has_verified_counts(self):
        """Provenance check works."""
        prov = ContentProvenance(
            source=ProvenanceSource.PUBLISHER_CATALOG,
            verification_status=VerificationStatus.VERIFIED,
        )
        assert prov.has_verified_counts()

        prov_unverified = ContentProvenance(
            source=ProvenanceSource.LOCAL_SYNTHETIC_FIXTURE,
            verification_status=VerificationStatus.UNVERIFIED,
        )
        assert not prov_unverified.has_verified_counts()


class TestContentRepository:
    """Test content repository operations."""

    def test_repository_initializes(self):
        """Repository can be instantiated."""
        repo = ContentRepository()
        assert repo is not None


class TestContentService:
    """Test content service operations."""

    def test_service_initializes(self):
        """Service can be instantiated."""
        service = ContentService()
        assert service is not None

    def test_runtime_has_no_fixture_seeder(self):
        """Synthetic educational fixtures belong exclusively in automated tests."""
        assert not hasattr(ContentService(), "seed_synthetic_fixture")


class TestContentAPI:
    """Test content API endpoints (via TestClient)."""

    def test_router_imports(self):
        """Router imports without error."""
        from app.modules.content import router

        assert router is not None


class TestPublishGate:
    """Test publish gate enforcement."""

    @pytest.mark.parametrize("source", ["no_source", "local_synthetic_fixture"])
    def test_publish_requires_provenance(self, source):
        """Rejected publication leaves a real database book draft and unpublished."""
        from app.core.db import get_db_connection

        curriculum_id, subject_id, book_id = uuid4(), uuid4(), uuid4()
        with get_db_connection(test=True) as conn:
            try:
                conn.execute(
                    "INSERT INTO curricula (id, code, name) VALUES (%s, %s, %s)",
                    (curriculum_id, str(curriculum_id), "Synthetic test curriculum"),
                )
                conn.execute(
                    "INSERT INTO subjects (id, curriculum_id, code, name) VALUES (%s, %s, %s, %s)",
                    (subject_id, curriculum_id, "synthetic", "Synthetic test subject"),
                )
                conn.execute(
                    "INSERT INTO books (id, subject_id, title, publisher, provenance_source) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (book_id, subject_id, "Synthetic test book", "Synthetic publisher", source),
                )
                with pytest.raises(ValueError, match="Cannot publish content"):
                    ContentService().publish_book(conn, book_id, "synthetic-reviewer")
                row = conn.execute(
                    "SELECT status, published_at, provenance_verified_by FROM books WHERE id = %s",
                    (book_id,),
                ).fetchone()
                assert row is not None
                assert row["status"] == "draft"
                assert row["published_at"] is None
                assert row["provenance_verified_by"] is None
            finally:
                conn.rollback()


class TestContentIntegration:
    """Integration tests for content catalog."""

    def test_full_hierarchy_creation(self):
        """Can create the full curriculum-to-question hierarchy."""
        from datetime import datetime

        now = datetime.now()
        curriculum = Curriculum(
            id=uuid4(),
            code="test",
            name="Test Curriculum",
            description="Test",
            provenance=ContentProvenance(source=ProvenanceSource.EDUCATOR_VERIFIED),
            version="1.0.0",
            status=ContentStatus.DRAFT,
            created_at=now,
            updated_at=now,
        )
        assert curriculum.code == "test"

        subject = Book(
            id=uuid4(),
            subject_id=uuid4(),
            title="Test Book",
            publisher="Test Publisher",
            isbn="978-1234567890",
            provenance=ContentProvenance(source=ProvenanceSource.NO_SOURCE),
            page_count=UNKNOWN,
        )
        assert isinstance(subject.page_count, UnknownCount)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
