from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core import state
from app.core.config import settings
from app.core.database import create_tables
from app.routers import health, sessions, signs, ws

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await create_tables()
    logger.info("Database tables created / verified.")

    state.redis_client = aioredis.from_url(
        settings.REDIS_URL, encoding="utf-8", decode_responses=True
    )
    await state.redis_client.ping()
    logger.info("Redis connection established.")

    yield

    await state.redis_client.aclose()
    logger.info("Redis connection closed.")


app = FastAPI(
    title="Classroom Ally API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error: %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


app.include_router(health.router)
app.include_router(sessions.router)
app.include_router(signs.router)
app.include_router(ws.router)
