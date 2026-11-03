"""Offline metrics describe synthetic consistency and boundary handling, never educational usefulness."""

from app.engines.catalog import RESOURCE_METADATA_DETAILS
from scripts.evaluate_plans import evaluate


def test_synthetic_catalog_never_claims_content_authorization():
    for resource in RESOURCE_METADATA_DETAILS:
        assert resource["verification_status"] == "UNVERIFIED"
        assert resource["domain_approval"] == "PENDING"
        assert resource["provenance"] == "local_synthetic_fixture"
        assert resource["full_content_access"] is False
        assert resource["content_license_id"] is None


def test_offline_positive_and_negative_evaluations_are_reproducible():
    report = evaluate()
    assert report == evaluate()
    assert report["total_cases"] == 9
    assert report["available_cases"] == 7
    assert report["pedagogical_usefulness_human_review"] == "PENDING"
    assert report["metadata_domain_approval"] == "PENDING"

    # Verify positive generation summary
    pos_summary = report["positive_generation_summary"]
    assert pos_summary["total_cases"] == 7
    assert pos_summary["passed_cases"] == 7
    assert pos_summary["failed_cases"] == 0
    assert pos_summary["average_weak_subject_coverage"] == 1.0

    # Verify negative boundary summary
    neg_summary = report["negative_boundary_summary"]
    assert neg_summary["total_cases"] == 2
    assert neg_summary["correctly_refused_cases"] == 2
    assert neg_summary["improperly_generated_cases"] == 0

    # Verify all positive cases meet constraints
    for case in report["cases"]:
        if case["scenario_type"] == "positive_generation":
            assert case["time_consistent"]
            assert case["grade_consistent"]
            assert case["track_consistent"]
            assert case["prerequisites_consistent"]
            assert case["weak_subject_coverage"] == 1.0
        else:
            assert case["actual_outcome"] == "refuse_plan"
            assert case["no_invalid_plan_produced"]
            assert case["no_capacity_violation"]
            assert case["no_cross_grade_violation"]
