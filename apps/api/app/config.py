from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url


ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    database_url: str = Field(min_length=1)
    cors_origins: str = "http://localhost:3000"
    environment: str = "development"
    abandonment_timeout_minutes: int = Field(default=30, ge=1, le=10080)
    internal_audit_token: str = ""
    # Live AI is the normal product path. The service still falls back to the
    # curated provider when no key is configured or a provider call fails.
    ai_mode: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    ai_timeout_seconds: float = 30.0

    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env.local", ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def sqlalchemy_database_url(self) -> URL:
        url = make_url(self.database_url)
        if url.drivername in {"postgres", "postgresql"}:
            url = url.set(drivername="postgresql+psycopg")
        if url.drivername != "postgresql+psycopg":
            raise ValueError("DATABASE_URL must be a PostgreSQL connection string")
        if "sslmode" not in url.query:
            url = url.update_query_dict({"sslmode": "require"})
        return url

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
