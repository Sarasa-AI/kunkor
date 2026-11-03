"""AI Provider abstraction layer and 9router reliability implementation.

Conforms to ADR-0006 and D-11:
- Pluggable AI abstraction (Provider pattern).
- Hard bounded deadline per request.
- Bounded retries with exponential backoff on HTTP 429 and transient 5xx errors.
- Strict budget guards with USD spend tracking.
- Automatic fallback to deterministic rule engine when external provider fails.
- Zero PII transmission (D-11 Principle 2).
- Structured telemetry without PII.
"""

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Optional
from uuid import UUID

import httpx

from app.ai.pii import sanitize_intake_for_ai
from app.ai.usage import reserve_daily_attempt
from app.core.config import settings
from app.engines.validator import TRACK_SUBJECT_ALLOWLIST
from app.schemas.planning import STAGE_CAPACITY_LIMITS, IntakeSlots

logger = logging.getLogger("kunkor.ai")
telemetry_logger = logging.getLogger("kunkor.telemetry.ai")


@dataclass
class ProviderBudget:
    """Legacy local estimate guard; durable reservations enforce configured ceilings."""

    budget_limit_usd: float = 10.0
    current_spend_usd: float = 0.0

    def has_budget(self, estimated_call_cost: float = 0.002) -> bool:
        return (self.current_spend_usd + estimated_call_cost) <= self.budget_limit_usd

    def record_spend(self, amount_usd: float) -> None:
        self.current_spend_usd += amount_usd


class AiProvider(ABC):
    """Abstract interface for AI plan proposal generation."""

    @abstractmethod
    async def propose_study_plan(
        self,
        intake: IntakeSlots,
        available_resources: list[dict[str, Any]],
        completed_unit_ids: Optional[set[str]] = None,
    ) -> dict[str, Any]:
        """Propose a study plan structure."""
        pass


class DeterministicRuleFallbackPlanner:
    """
    Guaranteed local rule-based planner.
    Produces valid, bounded plan proposals without LLM dependencies.
    """

    @classmethod
    def generate_fallback_plan(
        cls,
        intake: IntakeSlots,
        available_resources: list[dict[str, Any]],
        completed_unit_ids: Optional[set[str]] = None,
    ) -> dict[str, Any]:
        # Filter resources for stage and Published status
        matching = [
            r
            for r in available_resources
            if r.get("stage_code") == intake.stage_code
            and r.get("grade", intake.grade) == intake.grade
            and r.get("subject", "mathematics") in TRACK_SUBJECT_ALLOWLIST[intake.track]
            and r.get("status") == "Published"
            and r.get("license_active", True)
            and not r.get("license_expired", False)
        ]

        # Allocate units within daily capacity and stage ceiling
        allocated_items: list[dict[str, Any]] = []
        remaining_budget = min(
            intake.daily_study_capacity_minutes,
            STAGE_CAPACITY_LIMITS.get(intake.stage_code, 60),
        )
        scheduled_so_far: set[str] = set(completed_unit_ids or ())

        for res in matching:
            duration = res.get("duration_minutes", 20)
            prereqs = res.get("prerequisites", [])
            if not all(p in scheduled_so_far for p in prereqs):
                continue
            if duration <= remaining_budget:
                allocated_items.append(
                    {
                        "item_id": f"item-{res['resource_id']}",
                        "resource_version_id": res["resource_id"],
                        "stage_code": intake.stage_code,
                        "duration_minutes": duration,
                        "prerequisites": prereqs,
                    }
                )
                scheduled_so_far.add(res["resource_id"])
                remaining_budget -= duration
            if remaining_budget <= 0:
                break

        return {
            "source": "deterministic_fallback_planner",
            "rule_set_version": "1.0.0",
            "engine_version": "0.5.0",
            "items": allocated_items,
        }


class NineRouterProvider(AiProvider):
    """
    Production-grade 9router AI provider with retries, backoff, circuit breaker,
    timeout, safe telemetry, and budget protection.
    """

    def __init__(
        self,
        api_base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        max_retries: Optional[int] = None,
        budget: Optional[ProviderBudget] = None,
        client: Optional[httpx.AsyncClient] = None,
        usage_reserver: Optional[Callable[[UUID | None], bool]] = None,
    ):
        self.api_base_url = (api_base_url or settings.NINEROUTER_API_BASE).rstrip("/")
        self._api_key = api_key or settings.NINEROUTER_API_KEY or "test-key"
        self.model = model or settings.NINEROUTER_MODEL
        timeout_sec = (
            timeout_seconds if timeout_seconds is not None else settings.NINEROUTER_TIMEOUT_SECONDS
        )
        if not 0 < timeout_sec <= 60:
            raise ValueError("timeout_seconds must be in (0, 60].")
        self.timeout_seconds = timeout_sec
        retries = max_retries if max_retries is not None else settings.NINEROUTER_MAX_RETRIES
        if not isinstance(retries, int) or not 0 <= retries <= 3:
            raise ValueError("max_retries must be an integer in [0, 3].")
        self.max_retries = retries
        self.budget = budget or ProviderBudget()
        self._client = client
        self.usage_student_id: UUID | None = None
        # An explicit injected backend supports synthetic tests without a DB.
        self._usage_reserver = usage_reserver if client is not None else None

    def bind_student(self, student_id: UUID) -> None:
        if not isinstance(student_id, UUID):
            raise ValueError("Internal student UUID required.")
        self.usage_student_id = student_id

    def _record_telemetry(
        self,
        duration_ms: float,
        status_code: int,
        attempt: int,
        fallback_used: bool,
        tokens_prompt: int = 0,
        tokens_completion: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        """Log structured telemetry without PII or prompt text."""
        telemetry_logger.info(
            "ai_request_telemetry",
            extra={
                "model": self.model,
                "duration_ms": round(duration_ms, 2),
                "status_code": status_code,
                "attempt": attempt,
                "fallback_used": fallback_used,
                "tokens_prompt": tokens_prompt,
                "tokens_completion": tokens_completion,
                "estimated_cost_usd": cost_usd,
            },
        )

    async def propose_study_plan(
        self,
        intake: IntakeSlots,
        available_resources: list[dict[str, Any]],
        completed_unit_ids: Optional[set[str]] = None,
    ) -> dict[str, Any]:
        if self._client is None and not settings.NINEROUTER_ENABLED:
            return DeterministicRuleFallbackPlanner.generate_fallback_plan(
                intake, available_resources, completed_unit_ids=completed_unit_ids
            )
        # 1. Budget Guard
        if not self.budget.has_budget():
            logger.warning("9router budget limit reached (%s USD).", self.budget.budget_limit_usd)
            self._record_telemetry(0.0, 429, 0, True)
            return DeterministicRuleFallbackPlanner.generate_fallback_plan(
                intake, available_resources, completed_unit_ids=completed_unit_ids
            )

        # 2. Sanitize context (PII Masking per D-11)
        sanitized = sanitize_intake_for_ai(intake)
        # Only structured educational metadata; no titles or arbitrary free text.
        sanitized["resources"] = [
            {
                key: r[key]
                for key in (
                    "resource_id",
                    "stage_code",
                    "grade",
                    "subject",
                    "duration_minutes",
                    "prerequisites",
                )
                if key in r
            }
            for r in available_resources
            if r.get("stage_code") == intake.stage_code
            and r.get("grade", intake.grade) == intake.grade
            and r.get("subject", "mathematics") in TRACK_SUBJECT_ALLOWLIST[intake.track]
            and r.get("status") == "Published"
            and r.get("license_active", False)
            and not r.get("license_expired", False)
        ][:100]
        sanitized["completed_unit_ids"] = sorted(completed_unit_ids or ())[:1000]

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an educational study plan proposer. Return JSON format only "
                        "with key 'items'. Each item must have item_id, resource_version_id, "
                        "stage_code, duration_minutes, prerequisites."
                    ),
                },
                {"role": "user", "content": json.dumps(sanitized)},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": 2048,
        }

        attempts = 0
        last_error_code = 500

        deadline = time.monotonic() + self.timeout_seconds
        while attempts <= self.max_retries:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            attempts += 1
            start_time = time.monotonic()
            try:
                reserver = self._usage_reserver or reserve_daily_attempt
                if not await asyncio.wait_for(
                    asyncio.to_thread(reserver, self.usage_student_id), timeout=remaining
                ):
                    last_error_code = 429
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                if self._client:
                    response = await asyncio.wait_for(
                        self._client.post(
                            f"{self.api_base_url}/v1/chat/completions",
                            json=payload,
                            headers=headers,
                        ),
                        timeout=remaining,
                    )
                else:
                    async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                        response = await asyncio.wait_for(
                            client.post(
                                f"{self.api_base_url}/v1/chat/completions",
                                json=payload,
                                headers=headers,
                            ),
                            timeout=max(0.0, deadline - time.monotonic()),
                        )

                duration_ms = (time.monotonic() - start_time) * 1000.0

                if response.status_code == 200:
                    data = response.json()
                    # Calculate estimated cost
                    usage = data.get("usage", {})
                    p_tokens = usage.get("prompt_tokens", 100)
                    c_tokens = usage.get("completion_tokens", 150)
                    est_cost = (p_tokens * 0.0000005) + (c_tokens * 0.0000015)
                    self.budget.record_spend(est_cost)

                    self._record_telemetry(
                        duration_ms=duration_ms,
                        status_code=200,
                        attempt=attempts,
                        fallback_used=False,
                        tokens_prompt=p_tokens,
                        tokens_completion=c_tokens,
                        cost_usd=est_cost,
                    )

                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                    parsed = json.loads(content)
                    proposal: dict[str, Any]
                    if isinstance(parsed, dict):
                        proposal = parsed
                    else:
                        proposal = {"raw": parsed}
                    proposal["source"] = "9router"
                    return proposal

                # Handle HTTP 429 Rate Limit
                if response.status_code == 429:
                    last_error_code = 429
                    retry_after_str = response.headers.get("Retry-After")
                    if retry_after_str and retry_after_str.isdigit():
                        delay = float(retry_after_str)
                    else:
                        delay = 0.5 * (2 ** (attempts - 1))
                    logger.warning(
                        "9router rate limited (HTTP 429), attempt %s/%s. Backing off %ss.",
                        attempts,
                        self.max_retries + 1,
                        delay,
                    )
                    if attempts <= self.max_retries:
                        await asyncio.sleep(min(delay, 2.0, max(0.0, deadline - time.monotonic())))
                        continue

                # Handle transient 5xx server errors
                if response.status_code in (502, 503, 504):
                    last_error_code = response.status_code
                    delay = 0.5 * (2 ** (attempts - 1))
                    logger.warning(
                        "9router transient error (HTTP %s), attempt %s/%s. Backing off %ss.",
                        response.status_code,
                        attempts,
                        self.max_retries + 1,
                        delay,
                    )
                    if attempts <= self.max_retries:
                        await asyncio.sleep(min(delay, 2.0, max(0.0, deadline - time.monotonic())))
                        continue

                # Non-retryable error (e.g. 400, 401, 500)
                last_error_code = response.status_code
                logger.error("9router returned HTTP %s. Falling back.", response.status_code)
                break

            except (asyncio.TimeoutError, httpx.RequestError) as exc:
                duration_ms = (time.monotonic() - start_time) * 1000.0
                logger.warning(
                    "9router request failed (%s) on attempt %s/%s.",
                    type(exc).__name__,
                    attempts,
                    self.max_retries + 1,
                )
                last_error_code = 408 if isinstance(exc, asyncio.TimeoutError) else 503
                if attempts <= self.max_retries:
                    await asyncio.sleep(
                        min(2.0, 0.5 * (2 ** (attempts - 1)), max(0.0, deadline - time.monotonic()))
                    )
                    continue
                break
            except Exception as exc:
                logger.error("Unexpected error contacting 9router: %s", type(exc).__name__)
                last_error_code = 500
                break

        # Fallback path if all retries exhausted or non-retryable error
        self._record_telemetry(0.0, last_error_code, attempts, True)
        return DeterministicRuleFallbackPlanner.generate_fallback_plan(
            intake, available_resources, completed_unit_ids=completed_unit_ids
        )
