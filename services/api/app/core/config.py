import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://kunkor:kunkor_dev_password@localhost:5435/kunkor_dev",
    )
    TEST_DATABASE_URL: str = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql://kunkor:kunkor_dev_password@localhost:5435/kunkor_test",
    )
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    APP_PORT: int = int(os.getenv("PORT", "8000"))

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
