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
            usage_reserver=lambda _: True,
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
            usage_reserver=lambda _: True,
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
            usage_reserver=lambda _: True,
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
            usage_reserver=lambda _: True,
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
            usage_reserver=lambda _: True,
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
        provider = NineRouterProvider(client=client, usage_reserver=lambda _: True)
        await provider.propose_study_plan(intake, sample_catalog)

    assert len(captured_payloads) == 1
    sent_text = json.dumps(captured_payloads[0])
    # Assert zero PII
    assert "09123456789" not in sent_text
    assert "@ali_konkuri" not in sent_text
    assert "0012345678" not in sent_text
    context = json.loads(captured_payloads[0]["messages"][1]["content"])
    assert context["weak_subjects"] == []
    assert "target_exam" not in context


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


@pytest.mark.asyncio
async def test_total_deadline_includes_retries(sample_intake, sample_catalog):
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = NineRouterProvider(
            client=client, usage_reserver=lambda _: True, timeout_seconds=0.03, max_retries=3
        )
        started = asyncio.get_running_loop().time()
        proposal = await provider.propose_study_plan(sample_intake, sample_catalog)
        assert asyncio.get_running_loop().time() - started < 0.2
        assert calls == 1
        assert proposal["source"] == "deterministic_fallback_planner"


@pytest.mark.asyncio
async def test_prompt_contains_only_structured_context(sample_intake, sample_catalog):
    captured = []

    async def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"items": []}'}}]})

    intake = sample_intake.model_copy(
        update={
            "weak_subjects": ["biology", "علی رضایی t.me/private_name 0912 345 6789"],
            "target_exam": "علی رضایی",
        }
    )
    sample_catalog[0]["title"] = "untrusted private name"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await NineRouterProvider(client=client, usage_reserver=lambda _: True).propose_study_plan(
            intake, sample_catalog, completed_unit_ids={"res_math_1"}
        )
    context = json.loads(captured[0]["messages"][1]["content"])
    assert context["weak_subjects"] == ["biology"]
    assert "target_exam" not in context
    assert all("title" not in r for r in context["resources"])
    assert context["completed_unit_ids"] == ["res_math_1"]
    assert context["resources"][0]["resource_id"] == "res_math_1"


@pytest.mark.parametrize(
    "options",
    [
        {"timeout_seconds": 0},
        {"timeout_seconds": 61},
        {"max_retries": -1},
        {"max_retries": 4},
    ],
)
def test_provider_rejects_unbounded_options(options):
    with pytest.raises(ValueError):
        NineRouterProvider(**options)


def test_fallback_filters_track_and_grade(sample_intake, sample_catalog):
    sample_catalog[0].update(grade="G11", subject="mathematics")
    sample_catalog[1].update(grade="G12", subject="sociology")
    assert (
        DeterministicRuleFallbackPlanner.generate_fallback_plan(sample_intake, sample_catalog)[
            "items"
        ]
        == []
    )


@pytest.mark.asyncio
async def test_disabled_provider_never_opens_network(monkeypatch, sample_intake, sample_catalog):
    from app.core.config import settings

    monkeypatch.setattr(settings, "NINEROUTER_ENABLED", False)

    def unexpected_client(*args, **kwargs):
        raise AssertionError("Network client must not be constructed")

    monkeypatch.setattr(httpx, "AsyncClient", unexpected_client)
    proposal = await NineRouterProvider().propose_study_plan(sample_intake, sample_catalog)
    assert proposal["source"] == "deterministic_fallback_planner"
