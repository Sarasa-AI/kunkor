"""Run bounded planning strategies and select a validated candidate."""

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from app.ai.provider import AiProvider, DeterministicRuleFallbackPlanner
from app.core.config import settings
from app.engines.catalog import catalog_from_resources
from app.engines.validator import DeterministicValidationError, DeterministicValidator
from app.schemas.planning import IntakeSlots, StudyPlan

Strategy = Literal["provider", "priority"]


@dataclass(frozen=True)
class PlanningCandidate:
    strategy: Strategy
    plan: StudyPlan
    score: tuple[int, int, int]


class PlanningOrchestrator:
    def __init__(self, provider: AiProvider) -> None:
        self.provider = provider

    async def propose(
        self,
        intake: IntakeSlots,
        resources: list[dict[str, Any]],
        completed: set[str] | None = None,
        preferred: set[str] | None = None,
    ) -> dict[str, Any]:
        preferred = preferred or set()
        focus = set(intake.weak_subjects)
        catalog = catalog_from_resources(resources)
        ranked = sorted(
            resources,
            key=lambda item: (
                item["resource_id"] not in preferred,
                item.get("subject") not in focus,
            ),
        )
        local = DeterministicRuleFallbackPlanner.generate_fallback_plan(intake, ranked, completed)
        if not local["items"]:
            return local

        # The provider gets context only. The adapter reserves each network attempt.
        proposals: dict[Strategy, Any] = {}
        outcomes: dict[Strategy, str] = {}
        try:
            proposals["provider"] = await asyncio.wait_for(
                self.provider.propose_study_plan(
                    intake.model_copy(deep=True), deepcopy(resources), set(completed or ())
                ),
                timeout=settings.NINEROUTER_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            outcomes["provider"] = "timeout"
        except Exception:
            outcomes["provider"] = "error"
        proposals["priority"] = local

        candidates: list[PlanningCandidate] = []
        for strategy, proposal in proposals.items():
            try:
                plan = DeterministicValidator.validate_and_parse_proposal(
                    {"items": proposal.get("items")} if isinstance(proposal, dict) else None,
                    intake,
                    catalog,
                    completed_unit_ids=completed,
                )
            except (ValueError, DeterministicValidationError):
                outcomes[strategy] = "rejected"
                continue
            outcomes[strategy] = "validated"
            ids = {item.resource_version_id for item in plan.items}
            weak_subjects = {catalog[resource_id].subject for resource_id in ids} & focus
            score = (
                len(ids & preferred),
                len(weak_subjects),
                sum(item.duration_minutes for item in plan.items),
            )
            candidates.append(PlanningCandidate(strategy, plan, score))

        if not candidates:
            return {"items": []}
        selected = max(candidates, key=lambda candidate: candidate.score)
        return {
            "source": selected.strategy,
            "engine_version": selected.plan.engine_version,
            "rule_set_version": selected.plan.rule_set_version,
            "items": [item.model_dump() for item in selected.plan.items],
            "orchestration": {
                "version": 1,
                "selected": selected.strategy,
                "outcomes": outcomes,
                "score": list(selected.score),
            },
        }
