"""Phase 1 privacy boundaries; synthetic transports/errors, no provider calls."""

import json
import logging

import httpx
import pytest

from app.ai.provider import NineRouterProvider
from app.core import db
from app.core.config import settings
from app.schemas.planning import IntakeSlots
from app.workers import outbox_worker
from scripts import check_imports
from tests.synthetic_catalog import get_resources_for_stage

SENTINEL = "PRIVATE_STUDENT_ALICE_09123456789"


@pytest.fixture(autouse=True)
def synthetic_enabled_provider(monkeypatch):
    monkeypatch.setattr(settings, "NINEROUTER_ENABLED", True)
    monkeypatch.setattr(settings, "NINEROUTER_API_KEY", "synthetic-provider-key")


@pytest.mark.asyncio
async def test_provider_uses_opaque_identifiers_and_maps_response_back():
    captured = []

    async def handler(request):
        captured.append(request.content.decode())
        context = json.loads(json.loads(request.content)["messages"][1]["content"])
        resource = context["resources"][0]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "items": [
                                        {
                                            "item_id": "one",
                                            "resource_version_id": resource["resource_id"],
                                            "stage_code": "konkur",
                                            "duration_minutes": 20,
                                            "prerequisites": resource["prerequisites"],
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    resources = [
        {
            "resource_id": SENTINEL,
            "stage_code": "konkur",
            "grade": "G12",
            "subject": "biology",
            "status": "Published",
            "license_active": True,
            "duration_minutes": 20,
            "prerequisites": [SENTINEL + "_prior"],
        }
    ]
    intake = IntakeSlots(
        stage_code="konkur", grade="G12", track="experimental", daily_study_capacity_minutes=60
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = NineRouterProvider(client=client, usage_reserver=lambda _: True)
        result = await provider.propose_study_plan(intake, resources, {SENTINEL + "_prior"})
    assert captured
    assert SENTINEL not in captured[0]
    assert result["items"][0]["resource_version_id"] == SENTINEL
    assert result["items"][0]["prerequisites"] == [SENTINEL + "_prior"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("resource_id", {"name": SENTINEL}),
        ("duration_minutes", {"name": SENTINEL}),
        ("prerequisites", [{"name": SENTINEL}]),
    ],
)
async def test_provider_rejects_nested_untrusted_resource_values(field, value):
    captured = []

    async def handler(request):
        captured.append(request.content.decode())
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"items": []}'}}]})

    resource = {
        "resource_id": "unit",
        "stage_code": "konkur",
        "grade": "G12",
        "subject": "biology",
        "status": "Published",
        "license_active": True,
        "duration_minutes": 20,
        "prerequisites": [],
    }
    resource[field] = value
    intake = IntakeSlots(
        stage_code="konkur", grade="G12", track="experimental", daily_study_capacity_minutes=60
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await NineRouterProvider(client=client, usage_reserver=lambda _: True).propose_study_plan(
            intake, [resource]
        )
    assert all(SENTINEL not in payload for payload in captured)


def test_db_health_errors_do_not_log_exception_text(monkeypatch, caplog):
    def fail(**kwargs):
        raise RuntimeError(SENTINEL)

    monkeypatch.setattr(db, "get_db_connection", fail)
    with caplog.at_level(logging.ERROR):
        assert not db.check_db_health()
    assert caplog.records
    assert SENTINEL not in caplog.text


def test_worker_poll_errors_do_not_log_exception_text(monkeypatch, caplog):
    def fail():
        raise RuntimeError(SENTINEL)

    monkeypatch.setattr(outbox_worker, "process_pending_outbox_events", fail)
    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError):
        outbox_worker.run_worker(once=True)
    assert caplog.records
    assert SENTINEL not in caplog.text


@pytest.mark.asyncio
async def test_provider_exception_text_not_logged(caplog):
    async def handler(request):
        raise httpx.ConnectError(SENTINEL, request=request)

    intake = IntakeSlots(stage_code="konkur", grade="G12", daily_study_capacity_minutes=60)
    with caplog.at_level(logging.WARNING):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await NineRouterProvider(
                client=client, usage_reserver=lambda _: True, max_retries=0
            ).propose_study_plan(
                intake, get_resources_for_stage(intake.stage_code, grade=intake.grade)
            )
    assert caplog.records
    assert SENTINEL not in caplog.text


@pytest.mark.parametrize(
    "source",
    [
        "from app.core.db import get_db_connection",
        "import app.core.db",
        "import psycopg",
        "from ..core.db import get_db_connection",
        "from app.modules.consultation.repository import ConsultationRepository",
        "from ..modules.consultation import repository",
    ],
)
def test_boundary_checker_rejects_ai_persistence_imports(tmp_path, monkeypatch, source):
    app_dir = tmp_path / "app"
    (app_dir / "modules").mkdir(parents=True)
    (app_dir / "ai").mkdir()
    (app_dir / "ai" / "agent.py").write_text(source + "\n")
    monkeypatch.setattr(check_imports, "MODULES_DIR", app_dir / "modules")
    assert check_imports.check_module_boundaries() == 1


def test_current_ai_tree_has_no_direct_persistence_imports():
    assert check_imports.check_module_boundaries() == 0


@pytest.mark.parametrize("namespace", ["agents", "engines"])
def test_boundary_checker_rejects_persistence_in_other_pure_namespaces(
    tmp_path, monkeypatch, namespace
):
    app_dir = tmp_path / "app"
    (app_dir / "modules").mkdir(parents=True)
    (app_dir / namespace).mkdir()
    (app_dir / namespace / "writer.py").write_text("import psycopg\n")
    monkeypatch.setattr(check_imports, "MODULES_DIR", app_dir / "modules")
    assert check_imports.check_module_boundaries() == 1


@pytest.mark.asyncio
async def test_enabled_provider_constructs_transport_and_reserves_before_request(monkeypatch):
    from uuid import uuid4

    constructed = []
    reservations = []
    requests = []
    student = uuid4()
    original_client = httpx.AsyncClient

    async def handler(request):
        requests.append(request)
        assert reservations == [student]
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"items": []}'}}]})

    def synthetic_client(*args, **kwargs):
        constructed.append(True)
        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    def reserve(student_id):
        reservations.append(student_id)
        return True

    monkeypatch.setattr(httpx, "AsyncClient", synthetic_client)
    monkeypatch.setattr("app.ai.provider.reserve_daily_attempt", reserve)
    provider = NineRouterProvider(max_retries=0)
    provider.bind_student(student)
    intake = IntakeSlots(stage_code="konkur", grade="G12", daily_study_capacity_minutes=60)
    result = await provider.propose_study_plan(
        intake, get_resources_for_stage(intake.stage_code, grade=intake.grade)
    )
    assert constructed == [True]
    assert len(requests) == 1
    assert reservations == [student]
    assert str(student) not in requests[0].content.decode()
    assert requests[0].headers["Authorization"] == "Bearer synthetic-provider-key"
    assert result["source"] == "9router"


@pytest.mark.asyncio
async def test_enabled_provider_accepts_general_async_transport():
    requests = []

    class SyntheticTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            requests.append(request)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": '{"items": []}'}}]}
            )

    intake = IntakeSlots(stage_code="konkur", grade="G12", daily_study_capacity_minutes=60)
    async with httpx.AsyncClient(transport=SyntheticTransport()) as client:
        provider = NineRouterProvider(client=client, usage_reserver=lambda _: True)
        result = await provider.propose_study_plan(
            intake, get_resources_for_stage(intake.stage_code, grade=intake.grade)
        )
    assert len(requests) == 1
    assert result["source"] == "9router"


@pytest.mark.asyncio
async def test_disabled_provider_does_not_use_injected_transport(monkeypatch):
    async def unexpected_request(request):
        raise AssertionError("Disabled provider must not send a request")

    def unexpected_reservation(student_id):
        raise AssertionError("Disabled provider must not reserve a call")

    monkeypatch.setattr(settings, "NINEROUTER_ENABLED", False)
    intake = IntakeSlots(stage_code="konkur", grade="G12", daily_study_capacity_minutes=60)
    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected_request)) as client:
        result = await NineRouterProvider(
            client=client, usage_reserver=unexpected_reservation
        ).propose_study_plan(intake, get_resources_for_stage(intake.stage_code, grade=intake.grade))
    assert result["source"] == "deterministic_fallback_planner"


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["", "   ", "kunkor_local_key"])
async def test_missing_or_default_credentials_prevent_provider_requests(monkeypatch, key):
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"items": []}'}}]})

    monkeypatch.setattr(settings, "NINEROUTER_API_KEY", key)
    intake = IntakeSlots(stage_code="konkur", grade="G12", daily_study_capacity_minutes=60)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = NineRouterProvider(client=client, usage_reserver=lambda _: True)
        result = await provider.propose_study_plan(
            intake, get_resources_for_stage(intake.stage_code, grade=intake.grade)
        )
    assert not calls
    assert result["source"] == "deterministic_fallback_planner"


@pytest.mark.asyncio
async def test_provider_trace_has_run_and_version_metadata(caplog):
    async def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"items": []}'}}]})

    intake = IntakeSlots(stage_code="konkur", grade="G12", daily_study_capacity_minutes=60)
    with caplog.at_level(logging.INFO, logger="kunkor.telemetry.ai"):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await NineRouterProvider(
                client=client, usage_reserver=lambda _: True
            ).propose_study_plan(
                intake, get_resources_for_stage(intake.stage_code, grade=intake.grade)
            )
    from uuid import UUID

    records = [
        record for record in caplog.records if record.message.startswith("ai_request_telemetry ")
    ]
    assert len(records) == 1
    record = records[0]
    assert UUID(record.run_id)
    assert record.provider == "9router"
    assert record.provider_adapter_version
    assert record.prompt_version
    assert record.model
    assert result["run_id"] == record.run_id
    assert result["model"] == record.model
    logged = json.loads(record.message.partition(" ")[2])
    assert logged["run_id"] == result["run_id"]
    assert logged["provider_adapter_version"] == record.provider_adapter_version
    assert logged["prompt_version"] == record.prompt_version
    assert SENTINEL not in record.message


def test_settings_error_text_does_not_disclose_secret_input():
    from app.core.config import Settings

    with pytest.raises(ValueError) as caught:
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            DATABASE_URL="postgresql://student:private-config-password@localhost/prod",
            ADMIN_API_KEY="",
            NINEROUTER_ENABLED=False,
        )
    assert "private-config-password" not in str(caught.value)
