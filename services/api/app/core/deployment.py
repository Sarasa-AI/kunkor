"""Shared deployment input validation without loading settings or connecting."""

from psycopg.conninfo import conninfo_to_dict


def normalize_environment(value: str) -> str:
    environment = value.strip().lower()
    if environment not in {"development", "staging", "production", "test", "testing"}:
        raise ValueError("ENVIRONMENT must be development, staging, production, test or testing.")
    return environment


def validate_production_database_url(value: str) -> None:
    if not value.strip():
        raise ValueError("DATABASE_URL is required in production environment.")
    try:
        options = conninfo_to_dict(value)
    except Exception:
        raise ValueError("DATABASE_URL must be a valid PostgreSQL connection string.") from None
    if options.get("password") == "kunkor_dev_password":
        raise ValueError("Insecure default credentials prohibited in production.")
