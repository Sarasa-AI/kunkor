"""Deterministic validator for Kunkor Stage 0.5 educational plans.

Enforces ADR-0004 (isolated deterministic educational logic) before DB persistence.
All checks run in pure Python without LLM dependencies.
"""

from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.schemas.planning import STAGE_CAPACITY_LIMITS, IntakeSlots, StudyPlan, StudyPlanItem


class DeterministicValidationError(Exception):
    """Base class for all deterministic validation errors."""
    pass


class StudyTimeLimitExceededError(DeterministicValidationError):
    """Raised when plan duration exceeds student daily capacity or stage ceiling."""
    pass


class CyclicDependencyError(DeterministicValidationError):
    """Raised when a cycle is detected in prerequisite graphs."""
    pass


class PrerequisiteNotSatisfiedError(DeterministicValidationError):
    """Raised when a plan item has unsatisfied prerequisites."""
    pass


class ResourceLicenseError(DeterministicValidationError):
    """Raised when a resource is draft, unlicensed, or expired."""
    pass


class StageMismatchError(DeterministicValidationError):
    """Raised when a resource stage does not match student stage."""
    pass


class TrackSubjectMismatchError(DeterministicValidationError):
    """Raised when a subject does not belong to the selected academic track."""
    pass


class RevisionConflictError(DeterministicValidationError):
    """Raised when revision numbers are non-sequential or conflicting."""
    pass


class MalformedPlanError(DeterministicValidationError):
    """Raised when an AI plan proposal has invalid JSON structure or missing fields."""
    pass


@dataclass(frozen=True)
class ResourceMeta:
    """Metadata for curriculum resources in the catalog."""
    resource_id: str
    stage_code: str
    status: str = "Published"  # "Published", "Draft", "Archived"
    license_active: bool = True
    license_expired: bool = False


# Allowed specialized subjects per track in upper_secondary / konkur
TRACK_SUBJECT_ALLOWLIST: dict[str, set[str]] = {
    "experimental": {
        "biology", "biology_specialized", "chemistry", "physics", "mathematics",
        "geology", "persian", "arabic", "english", "religion"
    },
    "mathematics": {
        "calculus", "geometry", "discrete_math", "physics", "chemistry",
        "persian", "arabic", "english", "religion"
    },
    "humanities": {
        "literature", "arabic_specialized", "sociology", "history", "geography",
        "philosophy_logic", "economics", "mathematics_humanities", "religion"
    },
    "general": {
        "reading_fluency", "persian", "mathematics", "science", "quran",
        "social_studies", "english", "term_exams"
    }
}


class DeterministicValidator:
    """
    Authoritative deterministic validator for study plans.
    Guarantees that no unvalidated plan reaches the persistence layer.
    """

    @staticmethod
    def validate_study_time_limits(plan: StudyPlan, intake: IntakeSlots) -> None:
        total_duration = sum(item.duration_minutes for item in plan.items)
        if total_duration > intake.daily_study_capacity_minutes:
            raise StudyTimeLimitExceededError(
                f"Total plan duration ({total_duration} min) exceeds student daily capacity "
                f"({intake.daily_study_capacity_minutes} min)."
            )

        stage_ceiling = STAGE_CAPACITY_LIMITS.get(intake.stage_code, 600)
        if total_duration > stage_ceiling:
            raise StudyTimeLimitExceededError(
                f"Total plan duration ({total_duration} min) exceeds stage ceiling "
                f"for '{intake.stage_code}' ({stage_ceiling} min)."
            )

    @staticmethod
    def validate_prerequisites(
        items: list[StudyPlanItem],
        completed_unit_ids: Optional[set[str]] = None
    ) -> None:
        completed = set(completed_unit_ids or ())

        # 1. Check for cycles using DFS
        adj: dict[str, list[str]] = {}
        for item in items:
            adj[item.resource_version_id] = list(item.prerequisites)

        # ponytail: simple cycle check using standard 3-color DFS. Upgrade when graph > 10k nodes.
        visited: dict[str, int] = {}  # 0: unvisited, 1: visiting, 2: visited

        def has_cycle(node: str) -> bool:
            visited[node] = 1
            for neighbor in adj.get(node, []):
                state = visited.get(neighbor, 0)
                if state == 1:
                    return True
                if state == 0 and has_cycle(neighbor):
                    return True
            visited[node] = 2
            return False

        for node in adj:
            if visited.get(node, 0) == 0:
                if has_cycle(node):
                    raise CyclicDependencyError(
                        f"Circular dependency detected involving resource '{node}'."
                    )

        # 2. Check topological order and satisfaction in current plan
        scheduled_so_far: set[str] = set(completed)
        for idx, item in enumerate(items):
            for prereq in item.prerequisites:
                if prereq not in scheduled_so_far:
                    raise PrerequisiteNotSatisfiedError(
                        f"Item {idx} ('{item.resource_version_id}') requires prereq '{prereq}'."
                    )
            scheduled_so_far.add(item.resource_version_id)

    @staticmethod
    def validate_resource_licensing(
        items: list[StudyPlanItem],
        catalog: dict[str, ResourceMeta],
        student_stage: str,
    ) -> None:
        for item in items:
            meta = catalog.get(item.resource_version_id)
            if not meta:
                raise ResourceLicenseError(
                    f"Resource '{item.resource_version_id}' not found in curriculum catalog."
                )

            if meta.status != "Published":
                raise ResourceLicenseError(
                    f"Resource '{item.resource_version_id}' status '{meta.status}', not Published."
                )

            if not meta.license_active or meta.license_expired:
                raise ResourceLicenseError(
                    f"Resource '{item.resource_version_id}' has inactive or expired license."
                )

            if meta.stage_code != student_stage:
                raise StageMismatchError(
                    f"Resource '{item.resource_version_id}' stage '{meta.stage_code}' "
                    f"does not match student stage '{student_stage}'."
                )

    @staticmethod
    def validate_track_subjects(intake: IntakeSlots) -> None:
        allowed = TRACK_SUBJECT_ALLOWLIST.get(intake.track, set())
        for subject in intake.weak_subjects:
            if subject not in allowed:
                raise TrackSubjectMismatchError(
                    f"Subject '{subject}' not in track '{intake.track}'. Allowed: {sorted(allowed)}"
                )

    @classmethod
    def validate_study_plan(
        cls,
        plan: StudyPlan,
        intake: IntakeSlots,
        catalog: dict[str, ResourceMeta],
        completed_unit_ids: Optional[set[str]] = None
    ) -> None:
        """
        Master deterministic validation check.
        Must be invoked before database writes.
        """
        cls.validate_track_subjects(intake)
        cls.validate_study_time_limits(plan, intake)
        cls.validate_resource_licensing(plan.items, catalog, intake.stage_code)
        cls.validate_prerequisites(plan.items, completed_unit_ids)

    @classmethod
    def validate_and_parse_proposal(
        cls,
        proposal: Any,
        intake: IntakeSlots,
        catalog: dict[str, ResourceMeta],
        student_id: Optional[UUID] = None,
        revision_no: int = 1,
        completed_unit_ids: Optional[set[str]] = None,
    ) -> StudyPlan:
        """
        Validate and parse an untrusted AI plan proposal into a verified StudyPlan.
        Rejects malformed JSON, missing fields, or domain rule violations.
        """
        if not isinstance(proposal, dict):
            raise MalformedPlanError("Plan proposal must be a JSON object dictionary.")

        raw_items = proposal.get("items")
        if raw_items is None or not isinstance(raw_items, list):
            raise MalformedPlanError("Plan proposal missing mandatory 'items' list.")

        if len(raw_items) == 0:
            raise MalformedPlanError("Plan proposal 'items' list cannot be empty.")

        parsed_items: list[StudyPlanItem] = []
        for idx, it in enumerate(raw_items):
            if not isinstance(it, dict):
                raise MalformedPlanError(f"Plan item at index {idx} is not an object.")
            try:
                # Ensure stage_code defaults to intake.stage_code if missing
                item_dict = dict(it)
                if "stage_code" not in item_dict:
                    item_dict["stage_code"] = intake.stage_code
                parsed_item = StudyPlanItem(**item_dict)
                parsed_items.append(parsed_item)
            except ValidationError as ve:
                raise MalformedPlanError(f"Malformed study plan item at index {idx}: {ve}") from ve

        sid = student_id or uuid4()
        plan = StudyPlan(
            student_id=sid,
            revision_no=revision_no,
            items=parsed_items,
            rule_set_version=str(proposal.get("rule_set_version", "1.0.0")),
            engine_version=str(proposal.get("engine_version", "0.5.0")),
            status="active",
        )

        cls.validate_study_plan(plan, intake, catalog, completed_unit_ids=completed_unit_ids)
        return plan
