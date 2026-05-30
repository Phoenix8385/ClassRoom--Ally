from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.routers.ws import (
    ConnectedMessage,
    FinalMessage,
    GlossMessage,
    PartialMessage,
    PingMessage,
    _process_audio,
    websocket_stream,
)
from app.services.asr import WhisperService
from app.services.gloss import GlossService


# ── 1. Message model serialisation ───────────────────────────────────────────

def test_message_type_discriminators():
    """Every outbound model round-trips through JSON with the correct type tag."""
    sid = str(uuid.uuid4())

    connected = json.loads(ConnectedMessage(session_id=sid, timestamp="2024-01-01T00:00:00+00:00").model_dump_json())
    assert connected["type"] == "connected"
    assert connected["session_id"] == sid

    partial = json.loads(PartialMessage(text="hi", segment_id=sid, start_ms=0, asr_ms=210, gloss_ms=0, total_ms=210).model_dump_json())
    assert partial["type"] == "partial"
    assert partial["asr_ms"] == 210
    assert "gloss_ms" in partial and "total_ms" in partial

    final = json.loads(FinalMessage(text="hi", segment_id=sid, asr_ms=210, gloss_ms=55, total_ms=265).model_dump_json())
    assert final["type"] == "final"

    gloss = json.loads(GlossMessage(tokens=["HELLO"], segment_id=sid, asr_ms=210, gloss_ms=55, total_ms=265).model_dump_json())
    assert gloss["type"] == "gloss"
    assert gloss["tokens"] == ["HELLO"]

    ping = json.loads(PingMessage().model_dump_json())
    assert ping["type"] == "ping"


# ── 2. WhisperService transcribe interface ────────────────────────────────────

@pytest.mark.asyncio
async def test_whisper_service_transcribe_returns_string():
    """transcribe() must return a str; inject mock model to avoid loading weights."""
    from unittest.mock import MagicMock
    from app.services.asr import TranscriptResult

    seg = MagicMock()
    seg.text = "hello stub"
    seg.words = []
    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter([seg]), MagicMock())

    svc = WhisperService()
    svc._model = mock_model

    result = await svc.transcribe(b"\x00" * 32_000)
    assert isinstance(result, str)
    assert result == "hello stub"


# ── 3. GlossService stub ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gloss_service_returns_uppercase_token_list():
    svc = GlossService()
    tokens = await svc.convert("hello world")
    assert isinstance(tokens, list)
    assert len(tokens) >= 1
    assert all(isinstance(t, str) for t in tokens)
    # Stub uppercases every word.
    assert tokens == ["HELLO", "WORLD"]


@pytest.mark.asyncio
async def test_gloss_service_empty_text_returns_fallback():
    svc = GlossService()
    tokens = await svc.convert("   ")
    assert tokens == ["HELLO"]  # fallback defined in stub


# ── 4. Queue backpressure: oldest frame is dropped when queue is full ─────────

@pytest.mark.asyncio
async def test_queue_backpressure_drops_oldest():
    """Simulate the handler logic: when full, discard oldest then enqueue new."""
    queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=3)

    # Fill to capacity with identifiable payloads.
    for i in range(3):
        await queue.put(bytes([i]) * 4)

    assert queue.full()

    # Replicate the handler's drop-oldest strategy.
    new_frame = bytes([99]) * 4
    if queue.full():
        queue.get_nowait()          # drop oldest (payload [0, 0, 0, 0])
    await queue.put(new_frame)

    assert queue.qsize() == 3
    oldest_remaining = queue.get_nowait()
    assert oldest_remaining == bytes([1]) * 4   # frame 0 was dropped
    newest = None
    while not queue.empty():
        newest = queue.get_nowait()
    assert newest == new_frame


# ── 5. Invalid session → close code 4004 without accept ──────────────────────

@pytest.mark.asyncio
async def test_invalid_session_closes_4004_without_accept():
    """Handler must close with 4004 and never call accept() for unknown sessions."""
    mock_ws = AsyncMock()
    mock_db = AsyncMock()
    mock_db.get.return_value = None   # session not found

    await websocket_stream(mock_ws, uuid.uuid4(), mock_db)

    mock_ws.close.assert_awaited_once_with(code=4004)
    mock_ws.accept.assert_not_awaited()
