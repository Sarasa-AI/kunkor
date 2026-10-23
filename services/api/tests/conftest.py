import os

import pytest

from scripts.migrate import apply_migrations

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://kunkor:kunkor_dev_password@localhost:5435/kunkor_test",
)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    apply_migrations(TEST_DB_URL)
    yield
