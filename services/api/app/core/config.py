from __future__ import annotations

from typing import Literal

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

    # Whisper checkpoint to load. "base" keeps a CPU-only laptop comfortably
    # faster than real time; GPU deployments set WHISPER_MODEL=large-v3-turbo,
    # which needs faster-whisper >= 1.1.0 (see ADR-003).
    WHISPER_MODEL: str = "base"


# Values are supplied at runtime from the environment / .env file, which mypy
# cannot see — hence the required-field arguments look "missing" to it.
settings = Settings()  # type: ignore[call-arg]
