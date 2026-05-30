from __future__ import annotations

from typing import Literal

from pydantic import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    DATABASE_URL: str
    REDIS_URL: str
    OPENAI_API_KEY: str
    ENVIRONMENT: Literal["development", "production"] = "development"
    SECRET_KEY: str
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]


settings = Settings()
