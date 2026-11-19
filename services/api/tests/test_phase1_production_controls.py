"""Synthetic regressions for production configuration and migration log boundaries."""

import logging
import sys

import pytest

from app.core.config import Settings
from scripts import migrate


@pytest.mark.parametrize("environment", ["prod", "production-typo", "", "testingg"])
def test_unknown_environment_cannot_bypass_production_guards(environment, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", environment)
    with pytest.raises(ValueError, match="ENVIRONMENT"):
        Settings(_env_file=None, ENVIRONMENT=environment, DATABASE_URL="", ADMIN_API_KEY="")
    with pytest.raises(ValueError, match="ENVIRONMENT"):
        migrate.get_db_url("postgresql://user:synthetic@localhost/app")


@pytest.mark.parametrize("dsn", ["not-a-dsn", "postgresql://user:%broken@host/app"])
def test_malformed_production_dsn_is_rejected_without_disclosure(dsn, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(ValueError, match="valid PostgreSQL") as settings_error:
        Settings(
            _env_file=None, ENVIRONMENT="production", DATABASE_URL=dsn,
            ADMIN_API_KEY="synthetic-admin",
        )
    assert dsn not in str(settings_error.value)
    with pytest.raises(ValueError, match="valid PostgreSQL") as cli_error:
        migrate.get_db_url(dsn)
    assert dsn not in str(cli_error.value)


def test_custom_production_dsn_cannot_bypass_default_password_guard(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    dsn = "postgresql://user:kunkor_dev_password@localhost/app"
    with pytest.raises(ValueError, match="Insecure default credentials"):
        migrate.get_db_url(dsn)


def test_production_without_explicit_cors_allowlist_denies_origins(monkeypatch):
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    settings = Settings(
        _env_file=None, ENVIRONMENT="production",
        DATABASE_URL="postgresql://user:synthetic@localhost/app", ADMIN_API_KEY="synthetic-admin",
    )
    assert settings.CORS_ALLOWED_ORIGINS == []


@pytest.mark.parametrize("failure_stage", ["configuration", "migration"])
def test_migration_cli_contains_private_error_values(monkeypatch, caplog, failure_stage):
    private = "PRIVATE_SYNTHETIC_DATABASE_SENTINEL"

    def fail(*args, **kwargs):
        raise RuntimeError(private)

    monkeypatch.setattr(sys, "argv", ["migrate.py"])
    if failure_stage == "configuration":
        monkeypatch.setattr(migrate, "get_db_url", fail)
    else:
        monkeypatch.setattr(migrate, "get_db_url", lambda *args: "synthetic-unused")
        monkeypatch.setattr(migrate, "apply_migrations", fail)
    with caplog.at_level(logging.ERROR, logger="migrate"):
        assert migrate.main() == 1
    assert "Migration failed" in caplog.text
    assert "RuntimeError" in caplog.text
    assert private not in caplog.text
    assert "Traceback" not in caplog.text
