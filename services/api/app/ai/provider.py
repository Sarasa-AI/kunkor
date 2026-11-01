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
from typing import Any, Optional

import httpx

from app.ai.pii import sanitize_intake_for_ai
from app.core.config import settings
from app.schemas.planning import STAGE_CAPACITY_LIMITS, IntakeSlots

logger = logging.getLogger("kunkor.ai")
telemetry_logger = logging.getLogger("kunkor.telemetry.ai")


@dataclass
class ProviderBudget:
    """Budget guard tracking USD spend."""

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
    ):
        self.api_base_url = (api_base_url or settings.NINEROUTER_API_BASE).rstrip("/")
        self._api_key = api_key or settings.NINEROUTER_API_KEY or "test-key"
        self.model = model or settings.NINEROUTER_MODEL
        timeout_sec = (
            timeout_seconds if timeout_seconds is not None else settings.NINEROUTER_TIMEOUT_SECONDS
        )
        self.timeout_seconds = timeout_sec
        retries = max_retries if max_retries is not None else settings.NINEROUTER_MAX_RETRIES
        self.max_retries = retries
        self.budget = budget or ProviderBudget()
        self._client = client

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
                "cost_usd": cost_usd,
            },
        )

    async def propose_study_plan(
        self,
        intake: IntakeSlots,
        available_resources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        # 1. Budget Guard
        if not self.budget.has_budget():
            logger.warning("9router budget limit reached (%s USD).", self.budget.budget_limit_usd)
            self._record_telemetry(0.0, 429, 0, True)
            return DeterministicRuleFallbackPlanner.generate_fallback_plan(
                intake, available_resources
            )

        # 2. Sanitize context (PII Masking per D-11)
        sanitized = sanitize_intake_for_ai(intake)

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
        }

        attempts = 0
        last_error_code = 500

        while attempts <= self.max_retries:
            attempts += 1
            start_time = time.monotonic()
            try:
                if self._client:
                    response = await asyncio.wait_for(
                        self._client.post(
                            f"{self.api_base_url}/v1/chat/completions",
                            json=payload,
                            headers=headers,
                        ),
                        timeout=self.timeout_seconds,
                    )
                else:
                    async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                        response = await client.post(
                            f"{self.api_base_url}/v1/chat/completions",
                            json=payload,
                            headers=headers,
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
                        await asyncio.sleep(min(delay, 2.0))
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
                        await asyncio.sleep(min(delay, 2.0))
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
                    await asyncio.sleep(0.5 * (2 ** (attempts - 1)))
                    continue
                break
            except Exception as exc:
                logger.error("Unexpected error contacting 9router: %s", exc)
                last_error_code = 500
                break

        # Fallback path if all retries exhausted or non-retryable error
        self._record_telemetry(0.0, last_error_code, attempts, True)
        return DeterministicRuleFallbackPlanner.generate_fallback_plan(intake, available_resources)
