import os

import pytest

from scripts.migrate import apply_migrations
from scripts.migrate_check import require_test_database

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://kunkor:kunkor_dev_password@localhost:5435/kunkor_test",
)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    require_test_database(TEST_DB_URL)
    apply_migrations(TEST_DB_URL)
    yield


@pytest.fixture
def synthetic_planner_catalog(monkeypatch):
    """Opt-in test catalog; empty-catalog acceptance never requests this fixture."""
    from app.engines import catalog
    from app.modules.consultation import router, service
    from tests import synthetic_catalog

    for module in (catalog, router, service):
        monkeypatch.setattr(
            module, "get_resources_for_stage", synthetic_catalog.get_resources_for_stage
        )
    monkeypatch.setattr(catalog, "get_default_catalog", synthetic_catalog.get_default_catalog)
    monkeypatch.setattr(
        service.ContentService, "lock_agent_resources", lambda *args: None, raising=False
    )
