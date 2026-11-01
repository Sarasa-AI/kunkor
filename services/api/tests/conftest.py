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
