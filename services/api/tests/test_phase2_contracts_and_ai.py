"""Phase 2 comprehensive tests: Product contracts and Deterministic Validator."""

import uuid

import pytest

from app.engines.catalog import (
    get_default_catalog,
    get_resources_for_stage,
)
from app.engines.validator import (
    CyclicDependencyError,
    DeterministicValidator,
    MalformedPlanError,
    PrerequisiteNotSatisfiedError,
    ResourceLicenseError,
    StageMismatchError,
    StudyTimeLimitExceededError,
)
from app.schemas.planning import IntakeSlots, StudyPlan


@pytest.fixture
def default_catalog():
    return get_default_catalog()


@pytest.fixture
def konkur_intake():
    return IntakeSlots(
        stage_code="konkur",
        grade="G12",
        track="experimental",
        daily_study_capacity_minutes=240,
        weak_subjects=["mathematics", "biology"],
    )


def test_resource_whitelist_catalog_contains_all_stages():
    """Verify initial resource whitelist provides coverage across all educational stages."""
    catalog = get_default_catalog()
    assert len(catalog) >= 15

    stages = {res.stage_code for res in catalog.values()}
    assert "konkur" in stages
    assert "upper_secondary" in stages
    assert "lower_secondary" in stages
    assert "primary_high" in stages
    assert "primary_low" in stages

    konkur_resources = get_resources_for_stage("konkur")
    assert len(konkur_resources) >= 5


def test_validator_rejects_non_dict_proposal(konkur_intake, default_catalog):
    with pytest.raises(MalformedPlanError, match="must be a JSON object"):
        DeterministicValidator.validate_and_parse_proposal(
            "this is a raw string, not json object",
            konkur_intake,
            default_catalog,
        )


def test_validator_rejects_missing_items_key(konkur_intake, default_catalog):
    with pytest.raises(MalformedPlanError, match="missing mandatory 'items'"):
        DeterministicValidator.validate_and_parse_proposal(
            {"status": "ok", "summary": "study well"},
            konkur_intake,
            default_catalog,
        )


def test_validator_rejects_empty_items_list(konkur_intake, default_catalog):
    with pytest.raises(MalformedPlanError, match="cannot be empty"):
        DeterministicValidator.validate_and_parse_proposal(
            {"items": []},
            konkur_intake,
            default_catalog,
        )


def test_validator_rejects_item_not_an_object(konkur_intake, default_catalog):
    with pytest.raises(MalformedPlanError, match="is not an object"):
        DeterministicValidator.validate_and_parse_proposal(
            {"items": ["item1", "item2"]},
            konkur_intake,
            default_catalog,
        )


def test_validator_rejects_malformed_item_missing_duration(konkur_intake, default_catalog):
    with pytest.raises(MalformedPlanError, match="Malformed study plan item"):
        DeterministicValidator.validate_and_parse_proposal(
            {
                "items": [
                    {
                        "item_id": "1",
                        "resource_version_id": "konkur_bio_g12_ch1",
                        # duration_minutes missing
                    }
                ]
            },
            konkur_intake,
            default_catalog,
        )


def test_validator_rejects_negative_or_zero_duration(konkur_intake, default_catalog):
    with pytest.raises(MalformedPlanError, match="Malformed study plan item"):
        DeterministicValidator.validate_and_parse_proposal(
            {
                "items": [
                    {
                        "item_id": "1",
                        "resource_version_id": "konkur_bio_g12_ch1",
                        "duration_minutes": 0,
                    }
                ]
            },
            konkur_intake,
            default_catalog,
        )


def test_validator_rejects_plan_exceeding_daily_capacity(konkur_intake, default_catalog):
    # Intake capacity is 240m; propose 300m
    proposal = {
        "items": [
            {
                "item_id": "1",
                "resource_version_id": "konkur_bio_g12_ch1",
                "duration_minutes": 150,
            },
            {
                "item_id": "2",
                "resource_version_id": "konkur_bio_g12_ch2",
                "duration_minutes": 150,
                "prerequisites": ["konkur_bio_g12_ch1"],
            },
        ]
    }
    with pytest.raises(StudyTimeLimitExceededError):
        DeterministicValidator.validate_and_parse_proposal(
            proposal,
            konkur_intake,
            default_catalog,
        )


def test_validator_rejects_unlisted_resource(konkur_intake, default_catalog):
    proposal = {
        "items": [
            {
                "item_id": "1",
                "resource_version_id": "unapproved_pirated_book_pdf",
                "duration_minutes": 60,
            }
        ]
    }
    with pytest.raises(ResourceLicenseError, match="not found in curriculum catalog"):
        DeterministicValidator.validate_and_parse_proposal(
            proposal,
            konkur_intake,
            default_catalog,
        )


def test_validator_rejects_cyclic_prerequisites_in_ai_proposal(konkur_intake, default_catalog):
    proposal = {
        "items": [
            {
                "item_id": "1",
                "resource_version_id": "konkur_bio_g12_ch1",
                "duration_minutes": 60,
                "prerequisites": ["konkur_bio_g12_ch2"],
            },
            {
                "item_id": "2",
                "resource_version_id": "konkur_bio_g12_ch2",
                "duration_minutes": 60,
                "prerequisites": ["konkur_bio_g12_ch1"],
            },
        ]
    }
    with pytest.raises(CyclicDependencyError):
        DeterministicValidator.validate_and_parse_proposal(
            proposal,
            konkur_intake,
            default_catalog,
        )


def test_validator_rejects_unsatisfied_topological_order(konkur_intake, default_catalog):
    # ch2 requires ch1, but ch2 is placed first without ch1 completed
    proposal = {
        "items": [
            {
                "item_id": "1",
                "resource_version_id": "konkur_bio_g12_ch2",
                "duration_minutes": 60,
                "prerequisites": ["konkur_bio_g12_ch1"],
            },
            {
                "item_id": "2",
                "resource_version_id": "konkur_bio_g12_ch1",
                "duration_minutes": 60,
                "prerequisites": [],
            },
        ]
    }
    with pytest.raises(PrerequisiteNotSatisfiedError):
        DeterministicValidator.validate_and_parse_proposal(
            proposal,
            konkur_intake,
            default_catalog,
        )


def test_validator_rejects_cross_stage_resource(konkur_intake, default_catalog):
    # konkur student attempting to study primary reading
    proposal = {
        "items": [
            {
                "item_id": "1",
                "resource_version_id": "primary_read_g02_ch1",
                "duration_minutes": 15,
            }
        ]
    }
    with pytest.raises(StageMismatchError):
        DeterministicValidator.validate_and_parse_proposal(
            proposal,
            konkur_intake,
            default_catalog,
        )


def test_validator_accepts_valid_proposal_and_creates_study_plan(konkur_intake, default_catalog):
    student_id = uuid.uuid4()
    proposal = {
        "rule_set_version": "1.2.0",
        "engine_version": "0.6.0",
        "items": [
            {
                "item_id": "item-1",
                "resource_version_id": "konkur_bio_g12_ch1",
                "stage_code": "konkur",
                "duration_minutes": 60,
                "prerequisites": [],
            },
            {
                "item_id": "item-2",
                "resource_version_id": "konkur_bio_g12_ch2",
                "stage_code": "konkur",
                "duration_minutes": 60,
                "prerequisites": ["konkur_bio_g12_ch1"],
            },
            {
                "item_id": "item-3",
                "resource_version_id": "konkur_chem_g12_ch1",
                "stage_code": "konkur",
                "duration_minutes": 60,
                "prerequisites": [],
            },
        ],
    }

    plan = DeterministicValidator.validate_and_parse_proposal(
        proposal,
        konkur_intake,
        default_catalog,
        student_id=student_id,
        revision_no=1,
    )

    assert isinstance(plan, StudyPlan)
    assert plan.student_id == student_id
    assert plan.revision_no == 1
    assert plan.status == "active"
    assert len(plan.items) == 3
    assert sum(it.duration_minutes for it in plan.items) == 180
    assert plan.rule_set_version == "1.2.0"
