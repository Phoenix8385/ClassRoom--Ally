"""
Top-level test configuration.

os.environ must be set BEFORE any app module is imported because
app.core.config.Settings() is instantiated at module-load time.
This conftest is processed first, so these values satisfy Pydantic
validation without a real .env file being present in the test CWD.
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only")
