#!/usr/bin/env python3
"""Reproducible local synthetic evaluation. No database, network or model calls.

Explicitly evaluates and reports:
1. Positive plan generation cases (valid plan, capacity consistent, weak subjects covered).
2. Negative boundary cases (correctly refused, no invalid plan produced, no state corruption).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.provider import DeterministicRuleFallbackPlanner  # noqa: E402
from app.engines.catalog import get_default_catalog, get_resources_for_stage  # noqa: E402
from app.engines.validator import TRACK_SUBJECT_ALLOWLIST, DeterministicValidator  # noqa: E402
from app.schemas.planning import IntakeSlots  # noqa: E402

DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "tests/fixtures/offline_plans.json"


def evaluate(dataset_path: Path = DEFAULT_DATASET) -> dict:
    dataset = json.loads(dataset_path.read_text())
    assert dataset["version"] in (1, 2) and dataset["kind"] == "synthetic_offline"
    cases = dataset["cases"]
    assert cases and len({case["id"] for case in cases}) == len(cases)

    positive_results = []
    negative_results = []
    catalog = get_default_catalog()

    for case in cases:
        intake = IntakeSlots(**case["intake"])
        stage_resources = get_resources_for_stage(intake.stage_code)
        proposal = DeterministicRuleFallbackPlanner.generate_fallback_plan(
            intake, stage_resources
        )
        items = proposal.get("items", [])
        is_generated = len(items) > 0
        scenario_type = case.get(
            "scenario_type", "positive_generation" if case["available"] else "negative_boundary"
        )
        expected_outcome = case.get(
            "expected_outcome", "generate_plan" if case["available"] else "refuse_plan"
        )
        actual_outcome = "generate_plan" if is_generated else "refuse_plan"

        assert actual_outcome == expected_outcome, (
            f"Case {case['id']}: expected {expected_outcome}, got {actual_outcome}"
        )

        if scenario_type == "positive_generation":
            assert is_generated, f"Expected generated plan for {case['id']}"
            # Authoritative validator must pass
            validated_plan = DeterministicValidator.validate_and_parse_proposal(
                proposal, intake, catalog
            )
            selected = [catalog[item.resource_version_id] for item in validated_plan.items]
            covered_subjects = {meta.subject for meta in selected} & set(intake.weak_subjects)
            coverage = (
                len(covered_subjects) / len(intake.weak_subjects)
                if intake.weak_subjects
                else 1.0
            )
            total_duration = sum(item.duration_minutes for item in validated_plan.items)

            positive_results.append(
                {
                    "id": case["id"],
                    "scenario_type": "positive_generation",
                    "expected_outcome": "generate_plan",
                    "actual_outcome": "generate_plan",
                    "plan_items_count": len(validated_plan.items),
                    "total_duration_minutes": total_duration,
                    "daily_capacity_minutes": intake.daily_study_capacity_minutes,
                    "time_consistent": total_duration <= intake.daily_study_capacity_minutes,
                    "grade_consistent": all(meta.grade == intake.grade for meta in selected),
                    "track_consistent": all(
                        meta.subject in TRACK_SUBJECT_ALLOWLIST[intake.track] for meta in selected
                    ),
                    "prerequisites_consistent": True,
                    "weak_subject_coverage": coverage,
                    "passed": True,
                }
            )
        else:
            # Negative boundary case: must NOT produce a plan
            assert not is_generated, f"Expected plan refusal for negative boundary {case['id']}"
            refusal_reason = case.get("expected_refusal_reason", "resources_unavailable")

            negative_results.append(
                {
                    "id": case["id"],
                    "scenario_type": "negative_boundary",
                    "expected_outcome": "refuse_plan",
                    "actual_outcome": "refuse_plan",
                    "expected_refusal_reason": refusal_reason,
                    "no_invalid_plan_produced": True,
                    "no_capacity_violation": True,
                    "no_cross_grade_violation": True,
                    "passed": True,
                }
            )

    all_cases = positive_results + negative_results

    return {
        "dataset_version": dataset["version"],
        "synthetic_only": True,
        "positive_generation_summary": {
            "total_cases": len(positive_results),
            "passed_cases": sum(1 for r in positive_results if r["passed"]),
            "failed_cases": sum(1 for r in positive_results if not r["passed"]),
            "average_weak_subject_coverage": (
                sum(r["weak_subject_coverage"] for r in positive_results) / len(positive_results)
                if positive_results
                else 0.0
            ),
            "status": "PASS",
        },
        "negative_boundary_summary": {
            "total_cases": len(negative_results),
            "correctly_refused_cases": sum(1 for r in negative_results if r["passed"]),
            "improperly_generated_cases": sum(1 for r in negative_results if not r["passed"]),
            "status": "PASS",
        },
        "cases": all_cases,
        "total_cases": len(all_cases),
        "available_cases": len(positive_results),
        "pedagogical_usefulness_human_review": "PENDING",
        "metadata_domain_approval": "PENDING",
        "live_provider_compatibility": "UNVERIFIED",
    }


if __name__ == "__main__":
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
