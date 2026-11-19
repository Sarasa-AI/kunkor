"""Student/agent context hides unreviewed suggestions and unavailable plan sources."""

from uuid import uuid4

from app.core.db import get_db_connection
from app.modules.consultation.repository import ConsultationRepository
from app.modules.content.management import (
    BookFields,
    OwnerContentRepository,
    UnitCreate,
    UnitFields,
)
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.service import IdentityService


def test_student_context_only_exposes_current_trusted_units_and_no_raw_ai_proposal():
    with get_db_connection(test=True) as conn, conn.transaction(force_rollback=True):
        owner = OwnerContentRepository()
        book = owner.create_book(
            conn,
            BookFields(title="Synthetic context resource", grades=[12], subject_code="biology"),
        )
        chapter = owner.create_unit(
            conn,
            UnitCreate(
                book_id=book["id"],
                kind="chapter",
                title="Synthetic context chapter",
                provenance_source="owner_entered",
                provenance_reference="synthetic-test-source",
                license_id="synthetic-test-grant",
                rights_statement="Automated test only",
                license_active=True,
                estimated_duration_minutes=20,
            ),
        )
        external = uuid4().int % 10**12 + 10**12
        student = IdentityRepository.get_or_create_student(conn, external, external)
        ConsultationRepository.save_study_plan(
            conn,
            uuid4(),
            student,
            1,
            "konkur",
            "synthetic-engine",
            "synthetic-rules",
            {"citations": ["UNREVIEWED_AI_CITATION"], "suggestion": "UNREVIEWED_AI_TEXT"},
            [
                {
                    "resource_version_id": str(chapter["id"]),
                    "stage_code": "konkur",
                    "duration_minutes": 20,
                }
            ],
            intake_slots={"grade": "G12", "track": "experimental"},
        )
        service = IdentityService()
        context = service.get_student_context(conn, student)
        assert context["active_plan"] is None
        assert context["content_status"] == "awaiting_content"
        owner.transition(conn, chapter["id"], "approve", book=False)
        owner.transition(conn, chapter["id"], "publish", book=False)
        # Publication does not retroactively validate an earlier unsupported plan.
        assert service.get_student_context(conn, student)["active_plan"] is None
        ConsultationRepository.save_study_plan(
            conn,
            uuid4(),
            student,
            2,
            "konkur",
            "synthetic-engine",
            "synthetic-rules",
            {"citations": ["UNREVIEWED_AI_CITATION"]},
            [
                {
                    "resource_version_id": str(chapter["id"]),
                    "stage_code": "konkur",
                    "duration_minutes": 20,
                }
            ],
            intake_slots={"grade": "G12", "track": "experimental"},
        )
        context = service.get_student_context(conn, student)
        assert context["active_plan"]["items"][0]["resource_version_id"] == str(chapter["id"])
        assert "raw_proposal" not in context["active_plan"]
        assert "UNREVIEWED_AI" not in str(context)
        owner.edit(conn, chapter["id"], UnitFields(license_active=False), book=False)
        context = service.get_student_context(conn, student)
        assert context["active_plan"] is None
        assert context["content_status"] == "awaiting_content"
