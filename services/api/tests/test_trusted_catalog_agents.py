"""Empty/partial catalog agent acceptance without educational content fixtures."""

import asyncio
import uuid

import httpx
import pytest

from app.ai.orchestration import PlanningOrchestrator
from app.ai.provider import AiProvider, DeterministicRuleFallbackPlanner, NineRouterProvider
from app.core.config import settings
from app.engines import catalog
from app.modules.consultation.service import ConsultationService
from app.schemas.planning import IntakeSlots, StudyPlan, StudyPlanItem


def test_runtime_catalog_has_no_bundled_content():
    assert catalog.RESOURCE_METADATA_DETAILS == []
    assert catalog.DEFAULT_RESOURCE_CATALOG == {}
    assert catalog.get_default_catalog() == {}
    assert catalog.get_resources_for_stage("konkur") == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("offered", "selected", "outcome"),
    [
        ("physics", "provider", "validated"),
        ("biology", "priority", "validated"),
        ("missing", "priority", "rejected"),
        (None, "priority", "timeout"),
    ],
)
async def test_orchestrator_only_selects_validated_candidates(
    monkeypatch, offered, selected, outcome
):
    intake = IntakeSlots(
        stage_code="konkur", grade="G12", track="experimental",
        daily_study_capacity_minutes=30, weak_subjects=["physics"],
    )
    resources = [
        {
            "resource_id": subject, "subject": subject, "duration_minutes": 30,
            "stage_code": "konkur", "grade": "G12", "status": "Published", "license_active": True,
        }
        for subject in ("biology", "physics")
    ]
    calls = []

    class StubProvider(AiProvider):
        async def propose_study_plan(self, student, offered_resources, completed_unit_ids=None):
            calls.append(True)
            student.weak_subjects.clear()
            offered_resources.clear()
            if offered is None:
                await asyncio.sleep(1)
            return {
                "items": [{
                    "item_id": "provider-item", "resource_version_id": offered,
                    "duration_minutes": 30,
                }],
                "untrusted_extra": "omitted",
            }

    monkeypatch.setattr(settings, "NINEROUTER_TIMEOUT_SECONDS", 0.01)
    planner = PlanningOrchestrator(StubProvider())
    assert (await planner.propose(intake, []))["items"] == []
    assert not calls
    proposal = await planner.propose(intake, resources)
    assert calls == [True]
    assert len(resources) == 2 and intake.weak_subjects == ["physics"]
    assert proposal["items"][0]["resource_version_id"] == "physics"
    assert proposal["orchestration"]["selected"] == selected
    assert proposal["orchestration"]["outcomes"]["provider"] == outcome
    assert "untrusted_extra" not in proposal


@pytest.mark.asyncio
async def test_empty_catalog_does_not_call_provider_or_reserve_usage(monkeypatch):
    monkeypatch.setattr(settings, "NINEROUTER_ENABLED", True)
    monkeypatch.setattr(settings, "NINEROUTER_API_KEY", "synthetic-provider-key")
    calls = []
    reservations = []

    async def unexpected_request(request):
        calls.append(request)
        raise AssertionError("Empty catalog must not send an AI request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected_request)) as client:
        provider = NineRouterProvider(
            client=client, usage_reserver=lambda student: reservations.append(student)
        )
        intake = IntakeSlots(
            stage_code="konkur", grade="G12", track="experimental", daily_study_capacity_minutes=60
        )
        response = await provider.propose_study_plan(intake, [])
    assert response["status"] == "awaiting_content"
    assert response["items"] == response["citations"] == []
    assert calls == reservations == []


@pytest.mark.parametrize("duration", [None, 0, -1, True, "20"])
def test_partial_units_never_receive_fabricated_scheduling_duration(duration):
    intake = IntakeSlots(
        stage_code="konkur", grade="G12", track="experimental", daily_study_capacity_minutes=60
    )
    resources = [
        {
            "resource_id": "synthetic-partial-unit",
            "subject": "biology",
            "stage_code": "konkur",
            "grade": "G12",
            "status": "Published",
            "license_active": True,
            "duration_minutes": duration,
        }
    ]
    assert DeterministicRuleFallbackPlanner.generate_fallback_plan(intake, resources)["items"] == []


def test_missing_title_formats_explicit_unavailability_without_fabricating_citation():
    intake = IntakeSlots(
        stage_code="konkur", grade="G12", track="experimental", daily_study_capacity_minutes=60
    )
    plan = StudyPlan(
        student_id=uuid.uuid4(),
        items=[
            StudyPlanItem(
                item_id="one",
                resource_version_id="removed-unit",
                stage_code="konkur",
                duration_minutes=20,
            )
        ],
    )
    message = ConsultationService()._format_study_plan_message(plan, intake, [])
    assert "منبع تأییدشده در دسترس نیست" in message


@pytest.mark.asyncio
async def test_real_trusted_catalog_adapter_plans_independent_chapter():
    from app.core.db import get_db_connection
    from app.modules.content.management import BookFields, OwnerContentRepository, UnitCreate

    repo = OwnerContentRepository()
    with get_db_connection(test=True) as conn, conn.transaction(force_rollback=True):
        book = repo.create_book(
            conn, BookFields(title="Synthetic Agent Test Book", grades=[12], subject_code="biology")
        )
        unit = repo.create_unit(
            conn,
            UnitCreate(
                book_id=book["id"],
                kind="chapter",
                title="Synthetic Agent Test Unit",
                estimated_duration_minutes=30,
                provenance_source="owner_entered",
                provenance_reference="synthetic-automated-test",
                license_id="synthetic-test-license",
                rights_statement="Automated testing only",
                license_active=True,
            ),
        )
        repo.transition(conn, unit["id"], "approve", book=False)
        repo.transition(conn, unit["id"], "publish", book=False)
        followup = repo.create_unit(
            conn,
            UnitCreate(
                book_id=book["id"],
                kind="chapter",
                title="Synthetic Test Dependent Unit",
                estimated_duration_minutes=10,
                prerequisites=[unit["id"]],
                provenance_source="owner_entered",
                provenance_reference="synthetic-automated-test",
                license_id="synthetic-test-license",
                rights_statement="Automated testing only",
                license_active=True,
            ),
        )
        repo.transition(conn, followup["id"], "approve", book=False)
        repo.transition(conn, followup["id"], "publish", book=False)
        resources = catalog.get_resources_for_stage(
            "konkur", conn, grade="G12", track="experimental"
        )
        resources = [
            r for r in resources if r["resource_id"] in {str(unit["id"]), str(followup["id"])}
        ]
        assert len(resources) == 2
        by_id = {row["resource_id"]: row for row in resources}
        assert by_id[str(followup["id"])]["prerequisites"] == [str(unit["id"])]
        # Database UUID ordering can return a dependent unit before its prerequisite.
        resources = [by_id[str(followup["id"])], by_id[str(unit["id"])]]
        assert resources[0]["status"] == "Published"
        assert resources[0]["grade"] == "G12"
        intake = IntakeSlots(
            stage_code="konkur", grade="G12", track="experimental", daily_study_capacity_minutes=60
        )
        proposal = DeterministicRuleFallbackPlanner.generate_fallback_plan(intake, resources)
        plan, _ = await ConsultationService().validate_or_repair(
            proposal, intake, resources, uuid.uuid4(), 1, conn=conn
        )
        assert plan.items[0].resource_version_id == str(unit["id"])
        assert plan.items[0].duration_minutes == 30
        assert plan.items[1].prerequisites == [str(unit["id"])]
        assert repo.get_book(conn, book["id"])["status"] == "draft"


@pytest.mark.asyncio
async def test_fresh_validation_rejects_revoked_catalog_source():
    from app.core.db import get_db_connection
    from app.modules.consultation.service import TrustedContentUnavailable
    from app.modules.content.management import BookFields, OwnerContentRepository, UnitCreate

    repo = OwnerContentRepository()
    with get_db_connection(test=True) as conn, conn.transaction(force_rollback=True):
        book = repo.create_book(
            conn,
            BookFields(title="Synthetic Revocation Test Book", grades=[12], subject_code="biology"),
        )
        unit = repo.create_unit(
            conn,
            UnitCreate(
                book_id=book["id"],
                kind="chapter",
                title="Synthetic Revocation Test Unit",
                estimated_duration_minutes=30,
                provenance_source="owner_entered",
                provenance_reference="synthetic-automated-test",
                license_id="synthetic-test-license",
                rights_statement="Automated testing only",
                license_active=True,
            ),
        )
        repo.transition(conn, unit["id"], "approve", book=False)
        repo.transition(conn, unit["id"], "publish", book=False)
        resources = [
            r
            for r in catalog.get_resources_for_stage(
                "konkur", conn, grade="G12", track="experimental"
            )
            if r["resource_id"] == str(unit["id"])
        ]
        intake = IntakeSlots(
            stage_code="konkur", grade="G12", track="experimental", daily_study_capacity_minutes=60
        )
        proposal = DeterministicRuleFallbackPlanner.generate_fallback_plan(intake, resources)
        repo.transition(conn, unit["id"], "archive", book=False)
        with pytest.raises(TrustedContentUnavailable):
            await ConsultationService().validate_or_repair(
                proposal, intake, resources, uuid.uuid4(), 1, conn=conn
            )


@pytest.mark.asyncio
async def test_custom_provider_cannot_invent_duration_for_partial_trusted_unit():
    intake = IntakeSlots(
        stage_code="konkur", grade="G12", track="experimental", daily_study_capacity_minutes=60
    )
    common = {
        "subject": "biology",
        "stage_code": "konkur",
        "grade": "G12",
        "status": "Published",
        "license_active": True,
    }
    resources = [
        {**common, "resource_id": "synthetic-timed-unit", "duration_minutes": 20},
        {**common, "resource_id": "synthetic-partial-unit", "duration_minutes": None},
    ]
    invented = {
        "items": [
            {
                "item_id": "invented",
                "resource_version_id": "synthetic-partial-unit",
                "stage_code": "konkur",
                "duration_minutes": 20,
                "prerequisites": [],
            }
        ]
    }

    class InventingProvider:
        async def propose_study_plan(self, *args, **kwargs):
            return invented

    plan, _ = await ConsultationService(ai_provider=InventingProvider()).validate_or_repair(
        invented, intake, resources, uuid.uuid4(), 1
    )
    assert [item.resource_version_id for item in plan.items] == ["synthetic-timed-unit"]
    assert "synthetic-partial-unit" not in catalog.catalog_from_resources(resources)


def test_saved_plan_replay_withholds_republished_unit_and_provider_citations():
    from app.core.db import get_db_connection
    from app.modules.consultation.repository import ConsultationRepository
    from app.modules.consultation.service import trusted_plan_view
    from app.modules.content.management import BookFields, OwnerContentRepository, UnitCreate

    owner = OwnerContentRepository()
    service = ConsultationService()
    with get_db_connection(test=True) as conn, conn.transaction(force_rollback=True):
        book = owner.create_book(
            conn, BookFields(title="Synthetic Replay Book", grades=[12], subject_code="biology")
        )
        unit = owner.create_unit(
            conn,
            UnitCreate(
                book_id=book["id"],
                kind="chapter",
                title="Synthetic Replay Unit",
                estimated_duration_minutes=20,
                provenance_source="owner_entered",
                provenance_reference="synthetic-automated-test",
                license_id="synthetic-test-license",
                rights_statement="Automated testing only",
                license_active=True,
            ),
        )
        owner.transition(conn, unit["id"], "approve", book=False)
        owner.transition(conn, unit["id"], "publish", book=False)
        user = int(str(uuid.uuid4().int)[:12])
        student_id = conn.execute(
            "INSERT INTO students (telegram_chat_id, telegram_user_id) "
            "VALUES (%s, %s) RETURNING id",
            (user, user),
        ).fetchone()["id"]
        intake = IntakeSlots(
            stage_code="konkur", grade="G12", track="experimental", daily_study_capacity_minutes=60
        )
        item = {
            "item_id": "one",
            "resource_version_id": str(unit["id"]),
            "stage_code": "konkur",
            "duration_minutes": 20,
            "prerequisites": [],
        }
        plan_id = uuid.uuid4()
        ConsultationRepository.save_study_plan(
            conn,
            plan_id,
            student_id,
            1,
            "konkur",
            "test",
            "test",
            {"items": [item], "citations": ["FABRICATED_PROVIDER_CITATION"]},
            [item],
            intake.model_dump(),
        )
        saved = ConsultationRepository.get_active_study_plan(conn, student_id)
        assert "FABRICATED_PROVIDER_CITATION" in str(saved["raw_proposal"])
        cached = {"status": "plan_generated", "plan_id": str(plan_id), "plan": saved}
        reviewed = service.trusted_student_result(conn, student_id, cached)
        assert reviewed["status"] == "plan_generated"
        assert "raw_proposal" not in reviewed["plan"]
        assert "FABRICATED_PROVIDER_CITATION" not in str(reviewed)
        owner.transition(conn, unit["id"], "archive", book=False)
        assert (
            service.trusted_student_result(conn, student_id, cached)["status"] == "awaiting_content"
        )
        from app.modules.content.management import UnitFields

        owner.edit(conn, unit["id"], UnitFields(title="Synthetic Reviewed Replacement"), book=False)
        owner.transition(conn, unit["id"], "approve", book=False)
        owner.transition(conn, unit["id"], "publish", book=False)
        assert trusted_plan_view(conn, saved) is None
        assert service.trusted_student_result(conn, student_id, cached)["plan"] is None
        new_id = uuid.uuid4()
        ConsultationRepository.save_study_plan(
            conn,
            new_id,
            student_id,
            2,
            "konkur",
            "test",
            "test",
            {"items": [item]},
            [item],
            intake.model_dump(),
        )
        new_plan = ConsultationRepository.get_active_study_plan(conn, student_id)
        assert trusted_plan_view(conn, new_plan) is not None
