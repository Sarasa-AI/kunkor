import json
import os
from decimal import Decimal
from typing import Any

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    DATABASE_URL: str = ""
    TEST_DATABASE_URL: str = ""
    APP_PORT: int = 8000
    CORS_ALLOWED_ORIGINS: list[str] = []

    # AI & 9router configuration (ADR-0006, D-11)
    NINEROUTER_ENABLED: bool = False
    NINEROUTER_API_BASE: str = "http://127.0.0.1:14747"
    NINEROUTER_API_KEY: str = Field(
        default="", validation_alias=AliasChoices("NINEROUTER_API_KEY", "NINE_ROUTER_API_KEY")
    )
    NINEROUTER_MODEL: str = "ag/gemini-2.5-flash"
    NINEROUTER_TIMEOUT_SECONDS: float = Field(default=15.0, gt=0, le=60)
    NINEROUTER_MAX_RETRIES: int = Field(default=2, ge=0, le=3)
    NINEROUTER_GLOBAL_DAILY_CALLS: int = Field(default=1000, ge=0, le=100000)
    NINEROUTER_STUDENT_DAILY_CALLS: int = Field(default=20, ge=0, le=10000)
    NINEROUTER_GLOBAL_DAILY_RESERVED_USD: Decimal = Field(
        default=Decimal("10"), ge=0, le=10000, allow_inf_nan=False
    )
    NINEROUTER_STUDENT_DAILY_RESERVED_USD: Decimal = Field(
        default=Decimal("1"), ge=0, le=1000, allow_inf_nan=False
    )
    # Zero means unknown pricing: fail closed, even if the provider is enabled.
    NINEROUTER_ATTEMPT_COST_CEILING_USD: Decimal = Field(
        default=Decimal("0"), ge=0, le=100, decimal_places=8, allow_inf_nan=False
    )

    # Telegram configuration (Phase 3)
    TELEGRAM_DELIVERY_ENABLED: bool = False
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""

    # Admin & Operations configuration (Phase 5)
    ADMIN_API_KEY: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("CORS_ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            if v.startswith("[") and v.endswith("]"):
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(x).strip() for x in parsed if str(x).strip()]
                except Exception:
                    pass
            return [x.strip() for x in v.split(",") if x.strip()]
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []

    @model_validator(mode="after")
    def validate_environment_and_credentials(self) -> "Settings":
        env = self.ENVIRONMENT.lower()
        if env == "production":
            if not self.DATABASE_URL:
                raise ValueError("DATABASE_URL is required in production environment.")
            if "kunkor_dev_password" in self.DATABASE_URL:
                raise ValueError("Insecure default credentials prohibited in production.")
            if not self.ADMIN_API_KEY.strip() or self.ADMIN_API_KEY == "kunkor_admin_secret_key":
                raise ValueError("Explicit ADMIN_API_KEY is required in production.")
        if self.NINEROUTER_ENABLED and (
            not self.NINEROUTER_API_KEY.strip() or self.NINEROUTER_API_KEY == "kunkor_local_key"
        ):
            raise ValueError("Explicit NINEROUTER_API_KEY is required when AI is enabled.")
        if self.TELEGRAM_DELIVERY_ENABLED and (
            not self.TELEGRAM_BOT_TOKEN.strip() or not self.TELEGRAM_WEBHOOK_SECRET.strip()
        ):
            raise ValueError("Telegram delivery requires bot token and webhook secret.")
        if env != "production":
            if not self.DATABASE_URL:
                self.DATABASE_URL = os.getenv(
                    "DATABASE_URL",
                    "postgresql://kunkor:kunkor_dev_password@localhost:5435/kunkor_dev",
                )
            if not self.TEST_DATABASE_URL:
                self.TEST_DATABASE_URL = os.getenv(
                    "TEST_DATABASE_URL",
                    "postgresql://kunkor:kunkor_dev_password@localhost:5435/kunkor_test",
                )
            if not self.CORS_ALLOWED_ORIGINS:
                self.CORS_ALLOWED_ORIGINS = [
                    "http://localhost:3000",
                    "http://127.0.0.1:3000",
                ]

        self.CORS_ALLOWED_ORIGINS = [o for o in self.CORS_ALLOWED_ORIGINS if o != "*"]
        return self


settings = Settings()
