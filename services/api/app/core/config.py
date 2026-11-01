import json
import os
from typing import Any

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    DATABASE_URL: str = ""
    TEST_DATABASE_URL: str = ""
    APP_PORT: int = 8000
    CORS_ALLOWED_ORIGINS: list[str] = []

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
        else:
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
