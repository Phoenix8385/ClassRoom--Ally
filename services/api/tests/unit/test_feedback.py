"""
API-level tests for the feedback router.

The DB session is replaced via FastAPI's dependency_overrides, so these run
against the real routing/validation/serialisation stack with no Postgres.

NOTE: no async fixtures here on purpose — pytest-asyncio 0.23.0 pinned against
pytest 8.x blows up on them ('FixtureDef' object has no attribute 'unittest'),
so the client is built inside each test with `_client()`.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.main import app
from app.models.feedback import Feedback
from app.models.session import ClassroomSession

SESSION_ID = uuid.uuid4()


# ── helpers ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db() -> AsyncMock:
    """AsyncSession double. `add` is sync on the real session, so keep it sync."""
    session = AsyncMock()
    session.add = MagicMock()
    return session


@asynccontextmanager
async def _client(db: AsyncMock) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = lambda: db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_db, None)


def _payload(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "session_id": str(SESSION_ID),
        "segment_id": "seg-001",
        "gloss_shown": "I WATER WANT",
        "rating": 1,
        "corrected_gloss": None,
    }
    body.update(overrides)
    return body


def _existing_session() -> ClassroomSession:
    return ClassroomSession(id=SESSION_ID, teacher_name="Praveen", language="ISL")


def _populate_on_refresh(db: AsyncMock) -> None:
    """Stand in for the INSERT that assigns id / created_at."""

    async def _refresh(obj: Feedback) -> None:
        obj.id = uuid.uuid4()
        obj.created_at = datetime.now(UTC)

    db.refresh = AsyncMock(side_effect=_refresh)


def _row(segment: str, rating: int, offset_s: int) -> Feedback:
    row = Feedback(
        session_id=SESSION_ID,
        segment_id=segment,
        gloss_shown="I WATER WANT",
        rating=rating,
        corrected_gloss=None,
    )
    row.id = uuid.uuid4()
    row.created_at = datetime.now(UTC) + timedelta(seconds=offset_s)
    return row


def _result_returning(rows: list[Feedback]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


# ── POST /feedback — unknown session ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_feedback_returns_404_for_unknown_session(db: AsyncMock) -> None:
    """An unknown session must 404, not fall through to an FK violation."""
    db.get.return_value = None

    async with _client(db) as client:
        response = await client.post("/feedback", json=_payload())

    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


# ── POST /feedback — happy path ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_feedback_persists_and_returns_201(db: AsyncMock) -> None:
    db.get.return_value = _existing_session()
    _populate_on_refresh(db)

    async with _client(db) as client:
        response = await client.post(
            "/feedback", json=_payload(corrected_gloss="I WANT WATER")
        )

    assert response.status_code == 201
    body = response.json()
    assert body["session_id"] == str(SESSION_ID)
    assert body["segment_id"] == "seg-001"
    assert body["gloss_shown"] == "I WATER WANT"
    assert body["rating"] == 1
    assert body["corrected_gloss"] == "I WANT WATER"
    assert uuid.UUID(body["id"])          # a real id was assigned
    assert body["created_at"]

    db.add.assert_called_once()
    stored = db.add.call_args.args[0]
    assert isinstance(stored, Feedback)
    assert stored.session_id == SESSION_ID
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_feedback_defaults_corrected_gloss_to_null(db: AsyncMock) -> None:
    """corrected_gloss is optional and must round-trip as null when omitted."""
    db.get.return_value = _existing_session()
    _populate_on_refresh(db)

    payload = _payload()
    del payload["corrected_gloss"]

    async with _client(db) as client:
        response = await client.post("/feedback", json=payload)

    assert response.status_code == 201
    assert response.json()["corrected_gloss"] is None


@pytest.mark.parametrize("rating", [-1, 1])
@pytest.mark.asyncio
async def test_create_feedback_accepts_both_valid_ratings(
    db: AsyncMock, rating: int
) -> None:
    db.get.return_value = _existing_session()
    _populate_on_refresh(db)

    async with _client(db) as client:
        response = await client.post("/feedback", json=_payload(rating=rating))

    assert response.status_code == 201
    assert response.json()["rating"] == rating


# ── POST /feedback — validation ──────────────────────────────────────────────

@pytest.mark.parametrize("rating", [0, 2, -2, 5, "up", None, 1.5])
@pytest.mark.asyncio
async def test_create_feedback_rejects_invalid_rating(
    db: AsyncMock, rating: object
) -> None:
    """rating is Literal[-1, 1]; anything else is rejected before the handler."""
    async with _client(db) as client:
        response = await client.post("/feedback", json=_payload(rating=rating))

    assert response.status_code == 422
    assert any(err["loc"][-1] == "rating" for err in response.json()["detail"])
    db.get.assert_not_awaited()
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_create_feedback_rejects_non_uuid_session_id(db: AsyncMock) -> None:
    async with _client(db) as client:
        response = await client.post(
            "/feedback", json=_payload(session_id="not-a-uuid")
        )

    assert response.status_code == 422
    db.get.assert_not_awaited()


@pytest.mark.parametrize(
    "missing", ["session_id", "segment_id", "gloss_shown", "rating"]
)
@pytest.mark.asyncio
async def test_create_feedback_requires_all_mandatory_fields(
    db: AsyncMock, missing: str
) -> None:
    payload = _payload()
    del payload[missing]

    async with _client(db) as client:
        response = await client.post("/feedback", json=payload)

    assert response.status_code == 422
    db.add.assert_not_called()


# ── GET /feedback/{session_id} ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_feedback_returns_rows_in_db_order(db: AsyncMock) -> None:
    rows = [_row("seg-001", 1, 0), _row("seg-002", -1, 1), _row("seg-003", 1, 2)]
    db.execute = AsyncMock(return_value=_result_returning(rows))

    async with _client(db) as client:
        response = await client.get(f"/feedback/{SESSION_ID}")

    assert response.status_code == 200
    body = response.json()
    assert [r["segment_id"] for r in body] == ["seg-001", "seg-002", "seg-003"]
    assert [r["rating"] for r in body] == [1, -1, 1]


@pytest.mark.asyncio
async def test_list_feedback_filters_by_session_and_orders_by_created_at(
    db: AsyncMock,
) -> None:
    """The filtering/ordering must happen in SQL, not in Python."""
    db.execute = AsyncMock(return_value=_result_returning([]))

    async with _client(db) as client:
        await client.get(f"/feedback/{SESSION_ID}")

    statement = str(db.execute.await_args.args[0])
    assert "WHERE feedback.session_id" in statement
    assert "ORDER BY feedback.created_at" in statement


@pytest.mark.asyncio
async def test_list_feedback_returns_empty_list_for_session_with_no_rows(
    db: AsyncMock,
) -> None:
    db.execute = AsyncMock(return_value=_result_returning([]))

    async with _client(db) as client:
        response = await client.get(f"/feedback/{SESSION_ID}")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_feedback_rejects_non_uuid_session_id(db: AsyncMock) -> None:
    async with _client(db) as client:
        response = await client.get("/feedback/not-a-uuid")

    assert response.status_code == 422
    db.execute.assert_not_awaited()
