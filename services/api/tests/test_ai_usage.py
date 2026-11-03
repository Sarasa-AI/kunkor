"""Durable conservative quotas; synthetic HTTP clients only."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from app.ai import usage
from app.ai.provider import NineRouterProvider
from app.core.config import Settings, settings
from app.core.db import get_db_connection
from app.schemas.planning import IntakeSlots


def test_unpriced_or_unbound_usage_never_opens_database(monkeypatch):
    def unexpected_connection():
        raise AssertionError("No DB without identity and price ceiling")

    monkeypatch.setattr(usage, "get_db_connection", unexpected_connection)
    monkeypatch.setattr(settings, "NINEROUTER_ATTEMPT_COST_CEILING_USD", Decimal("0"))
    assert not usage.reserve_daily_attempt(uuid4())
    monkeypatch.setattr(settings, "NINEROUTER_ATTEMPT_COST_CEILING_USD", Decimal("0.01"))
    assert not usage.reserve_daily_attempt(None)


@pytest.mark.parametrize(
    "field,value",
    [
        ("NINEROUTER_GLOBAL_DAILY_CALLS", -1),
        ("NINEROUTER_STUDENT_DAILY_CALLS", 10001),
        ("NINEROUTER_ATTEMPT_COST_CEILING_USD", "NaN"),
        ("NINEROUTER_ATTEMPT_COST_CEILING_USD", "0.000000001"),
        ("NINEROUTER_GLOBAL_DAILY_RESERVED_USD", "Infinity"),
        ("NINEROUTER_STUDENT_DAILY_RESERVED_USD", -1),
    ],
)
def test_quota_configuration_rejects_invalid_limits(field, value):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **{field: value})


@pytest.mark.asyncio
async def test_every_http_retry_requires_reservation():
    reservations = []
    calls = []
    student = uuid4()

    def reserve(student_id):
        reservations.append(student_id)
        return len(reservations) == 1

    async def handler(request):
        calls.append(request)
        return httpx.Response(503)

    intake = IntakeSlots(stage_code="konkur", grade="G12", daily_study_capacity_minutes=60)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = NineRouterProvider(client=client, usage_reserver=reserve)
        provider.bind_student(student)
        result = await provider.propose_study_plan(intake, [])
    assert reservations == [student, student]
    assert len(calls) == 1
    assert result["source"] == "deterministic_fallback_planner"
    assert str(student) not in calls[0].content.decode()


@pytest.mark.asyncio
async def test_reservation_failure_prevents_http():
    async def handler(request):
        raise AssertionError("Quota backend failure must fail closed")

    def broken_reservation(student):
        raise RuntimeError("synthetic backend unavailable")

    intake = IntakeSlots(stage_code="konkur", grade="G12", daily_study_capacity_minutes=60)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = NineRouterProvider(client=client, usage_reserver=broken_reservation)
        result = await provider.propose_study_plan(intake, [])
    assert result["source"] == "deterministic_fallback_planner"


@pytest.fixture
def quota_store(monkeypatch):
    monkeypatch.setattr(settings, "NINEROUTER_ATTEMPT_COST_CEILING_USD", Decimal("0.10"))
    monkeypatch.setattr(settings, "NINEROUTER_GLOBAL_DAILY_CALLS", 20)
    monkeypatch.setattr(settings, "NINEROUTER_STUDENT_DAILY_CALLS", 2)
    monkeypatch.setattr(settings, "NINEROUTER_GLOBAL_DAILY_RESERVED_USD", Decimal("10"))
    monkeypatch.setattr(settings, "NINEROUTER_STUDENT_DAILY_RESERVED_USD", Decimal("1"))
    with get_db_connection() as conn:
        conn.execute("DELETE FROM ai_daily_usage")
        conn.commit()
    yield
    with get_db_connection() as conn:
        conn.execute("DELETE FROM ai_daily_usage")
        conn.commit()


def test_durable_quota_survives_caller_rollback_and_new_connection(quota_store):
    student = uuid4()
    with get_db_connection() as caller:
        caller.execute("SELECT 1")
        assert usage.reserve_daily_attempt(student)
        caller.rollback()
    assert usage.reserve_daily_attempt(student)
    assert not usage.reserve_daily_attempt(student)
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT attempts, reserved_usd FROM ai_daily_usage WHERE scope_key = %s",
            (f"student:{student}",),
        ).fetchone()
    assert row == {"attempts": 2, "reserved_usd": Decimal("0.20")}


def test_durable_global_call_and_reserved_cost_caps(quota_store, monkeypatch):
    monkeypatch.setattr(settings, "NINEROUTER_GLOBAL_DAILY_CALLS", 1)
    assert usage.reserve_daily_attempt(uuid4())
    assert not usage.reserve_daily_attempt(uuid4())
    monkeypatch.setattr(settings, "NINEROUTER_GLOBAL_DAILY_CALLS", 20)
    monkeypatch.setattr(settings, "NINEROUTER_GLOBAL_DAILY_RESERVED_USD", Decimal("0.15"))
    assert not usage.reserve_daily_attempt(uuid4())


def test_durable_student_cost_cap(quota_store, monkeypatch):
    monkeypatch.setattr(settings, "NINEROUTER_STUDENT_DAILY_RESERVED_USD", Decimal("0.15"))
    student = uuid4()
    assert usage.reserve_daily_attempt(student)
    assert not usage.reserve_daily_attempt(student)
    assert usage.reserve_daily_attempt(uuid4())


def test_durable_concurrent_reservations_never_exceed_global_cap(quota_store, monkeypatch):
    monkeypatch.setattr(settings, "NINEROUTER_GLOBAL_DAILY_CALLS", 3)
    with ThreadPoolExecutor(max_workers=6) as pool:
        accepted = list(pool.map(usage.reserve_daily_attempt, [uuid4() for _ in range(6)]))
    assert sum(accepted) == 3
