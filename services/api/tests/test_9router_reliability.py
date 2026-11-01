"""Automated tests for 9router reliability, deadlines, budget guards, and fallback (ADR-0006)."""

import asyncio
import json

import httpx
import pytest

from app.ai.pii import mask_pii_text
from app.ai.provider import (
    DeterministicRuleFallbackPlanner,
    NineRouterProvider,
    ProviderBudget,
)
from app.schemas.planning import IntakeSlots


@pytest.fixture
def sample_intake():
    return IntakeSlots(
        stage_code="konkur",
        grade="G12",
        track="experimental",
        daily_study_capacity_minutes=180,
        weak_subjects=["mathematics"],
    )


@pytest.fixture
def sample_catalog():
    return [
        {
            "resource_id": "res_math_1",
            "stage_code": "konkur",
            "status": "Published",
            "license_active": True,
            "duration_minutes": 60,
        },
        {
            "resource_id": "res_phys_1",
            "stage_code": "konkur",
            "status": "Published",
            "license_active": True,
            "duration_minutes": 60,
        },
        {
            "resource_id": "res_bio_draft",
            "stage_code": "konkur",
            "status": "Draft",
            "license_active": True,
            "duration_minutes": 60,
        },
    ]


@pytest.mark.asyncio
async def test_fallback_planner_respects_stage_resources(sample_intake, sample_catalog):
    fallback = DeterministicRuleFallbackPlanner.generate_fallback_plan(
        sample_intake, sample_catalog
    )
    assert fallback["source"] == "deterministic_fallback_planner"
    assert len(fallback["items"]) == 2
    item_ids = [it["resource_version_id"] for it in fallback["items"]]
    assert "res_bio_draft" not in item_ids
    total_time = sum(it["duration_minutes"] for it in fallback["items"])
    assert total_time <= sample_intake.daily_study_capacity_minutes


@pytest.mark.asyncio
async def test_9router_fallback_on_budget_exhaustion(sample_intake, sample_catalog):
    budget = ProviderBudget(budget_limit_usd=0.01, current_spend_usd=0.01)
    provider = NineRouterProvider(budget=budget)

    proposal = await provider.propose_study_plan(sample_intake, sample_catalog)
    assert proposal["source"] == "deterministic_fallback_planner"


@pytest.mark.asyncio
async def test_9router_fallback_on_timeout(sample_intake, sample_catalog):
    async def delayed_handler(request):
        await asyncio.sleep(0.5)
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(delayed_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = NineRouterProvider(
            timeout_seconds=0.05,
            max_retries=0,
            client=client,
        )
        proposal = await provider.propose_study_plan(sample_intake, sample_catalog)
        assert proposal["source"] == "deterministic_fallback_planner"


@pytest.mark.asyncio
async def test_9router_fallback_on_http_500(sample_intake, sample_catalog):
    async def error_handler(request):
        return httpx.Response(500, text="Internal Model Gateway Error")

    transport = httpx.MockTransport(error_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = NineRouterProvider(
            timeout_seconds=5.0,
            max_retries=0,
            client=client,
        )
        proposal = await provider.propose_study_plan(sample_intake, sample_catalog)
        assert proposal["source"] == "deterministic_fallback_planner"


@pytest.mark.asyncio
async def test_9router_success_records_spend(sample_intake, sample_catalog):
    async def success_handler(request):
        json_content = (
            '{"items": [{"item_id": "1", "resource_version_id": "res_math_1", '
            '"stage_code": "konkur", "duration_minutes": 60, "prerequisites": []}]}'
        )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json_content}}]},
        )

    transport = httpx.MockTransport(success_handler)
    budget = ProviderBudget(budget_limit_usd=1.0, current_spend_usd=0.0)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = NineRouterProvider(
            timeout_seconds=5.0,
            budget=budget,
            client=client,
        )
        proposal = await provider.propose_study_plan(sample_intake, sample_catalog)
        assert proposal["source"] == "9router"
        assert budget.current_spend_usd > 0.0


@pytest.mark.asyncio
async def test_9router_handles_http_429_with_retry_and_success(sample_intake, sample_catalog):
    call_count = 0

    async def rate_limited_handler(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, headers={"Retry-After": "0.01"})
        json_content = (
            '{"items": [{"item_id": "1", "resource_version_id": "res_math_1", '
            '"stage_code": "konkur", "duration_minutes": 60, "prerequisites": []}]}'
        )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json_content}}]},
        )

    transport = httpx.MockTransport(rate_limited_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = NineRouterProvider(
            timeout_seconds=5.0,
            max_retries=2,
            client=client,
        )
        proposal = await provider.propose_study_plan(sample_intake, sample_catalog)
        assert proposal["source"] == "9router"
        assert call_count == 2


@pytest.mark.asyncio
async def test_9router_handles_http_429_exhausted_falls_back(sample_intake, sample_catalog):
    call_count = 0

    async def always_429_handler(request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(429, headers={"Retry-After": "0.01"})

    transport = httpx.MockTransport(always_429_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = NineRouterProvider(
            timeout_seconds=5.0,
            max_retries=1,
            client=client,
        )
        proposal = await provider.propose_study_plan(sample_intake, sample_catalog)
        assert proposal["source"] == "deterministic_fallback_planner"
        assert call_count == 2  # 1 initial + 1 retry


@pytest.mark.asyncio
async def test_pii_masking_in_ai_request_payload(sample_catalog):
    # Intake with injected PII in free-text fields
    intake = IntakeSlots(
        stage_code="konkur",
        grade="G12",
        track="experimental",
        daily_study_capacity_minutes=180,
        weak_subjects=["biology contact 09123456789 or @ali_konkuri"],
        target_exam="Konkur 1406 for student 0012345678",
    )

    captured_payloads = []

    async def interceptor_handler(request):
        captured_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"items": []}'}}]},
        )

    transport = httpx.MockTransport(interceptor_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = NineRouterProvider(client=client)
        await provider.propose_study_plan(intake, sample_catalog)

    assert len(captured_payloads) == 1
    sent_text = json.dumps(captured_payloads[0])
    # Assert zero PII
    assert "09123456789" not in sent_text
    assert "@ali_konkuri" not in sent_text
    assert "0012345678" not in sent_text
    assert "[MASKED_PHONE]" in sent_text
    assert "[MASKED_HANDLE]" in sent_text
    assert "[MASKED_NATIONAL_ID]" in sent_text


def test_pii_masking_utility():
    text = (
        "Call me at 09351234567 or +989128765432. My email is student@example.com. "
        "National ID: 0019876543. Handle: @student_test_1. TG: tg_user_123456789"
    )
    masked = mask_pii_text(text)
    assert "09351234567" not in masked
    assert "+989128765432" not in masked
    assert "student@example.com" not in masked
    assert "0019876543" not in masked
    assert "@student_test_1" not in masked
    assert "123456789" not in masked
    assert "[MASKED_PHONE]" in masked
    assert "[MASKED_EMAIL]" in masked
    assert "[MASKED_NATIONAL_ID]" in masked
    assert "[MASKED_HANDLE]" in masked
