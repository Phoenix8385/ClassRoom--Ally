from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.core import state
from app.core.database import AsyncSessionFactory

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, object]:
    db_status = "ok"
    redis_status = "ok"

    try:
        async with AsyncSessionFactory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = f"error: {exc}"

    try:
        await state.redis_client.ping()
    except Exception as exc:
        redis_status = f"error: {exc}"

    return {
        "status": "ok" if db_status == "ok" and redis_status == "ok" else "degraded",
        "database": db_status,
        "redis": redis_status,
    }
