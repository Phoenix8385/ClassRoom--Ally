from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock

import pytest

from app.routers.ws import (
    QUEUE_MAX,
    WINDOW_BYTES,
    ConnectedMsg,
    Connection,
    ErrorMsg,
    FinalTranscriptMsg,
    GlossMsg,
    PartialTranscriptMsg,
    PingMsg,
    PipelineServices,
    PongMsg,
    SignSequenceMsg,
    TimingInfo,
    _enqueue_frame,
    _process_audio,
    active_connections,
    websocket_stream,
)
from app.services.asr import TranscriptResult
from app.services.sign_mapper import MappingResult, SignAction

# ── Fixtures / doubles ───────────────────────────────────────────────────────


def _transcript(text: str) -> TranscriptResult:
    return TranscriptResult(text=text, segments=[], confidence=0.9, latency_ms=12)


def _pipeline(
    *,
    texts: list[str],
    speech: bool = True,
    tokens: list[str] | None = None,
) -> tuple[PipelineServices, AsyncMock]:
    """Pipeline whose ASR yields `texts` in order, then repeats the last one."""
    asr = AsyncMock()
    asr.transcribe_chunk.side_effect = [_transcript(t) for t in texts] + [
        _transcript(texts[-1] if texts else "")
    ] * 32

    vad = AsyncMock()
    vad.is_speech.return_value = speech

    gloss = AsyncMock()
    gloss.convert.return_value = tokens if tokens is not None else ["I", "WATER", "WANT"]

    async def map_signs(toks: list[str]) -> MappingResult:
        actions = [
            SignAction(
                token=t, type="fingerspell", clip_path=None, letters=list(t), duration_ms=400
            )
            for t in toks
        ]
        return MappingResult(
            actions=actions,
            coverage=0.0,
            unknown_words=toks,
            total_tokens=len(toks),
            covered_tokens=0,
        )

    return PipelineServices(asr=asr, vad=vad, gloss=gloss, map_signs=map_signs), asr


def _fake_ws() -> tuple[AsyncMock, list[dict]]:
    """A WebSocket double that records every JSON frame sent to the client."""
    sent: list[dict] = []
    ws = AsyncMock()
    ws.send_text.side_effect = lambda raw: sent.append(json.loads(raw))
    return ws, sent


async def _run_until_sign_sequence(
    conn: Connection,
    services: PipelineServices,
    sent: list[dict],
    timeout: float = 5.0,
) -> None:
    """Run the pipeline until a sign_sequence lands, then cancel it."""
    task = asyncio.create_task(_process_audio(conn, services))
    deadline = asyncio.get_running_loop().time() + timeout
    try:
        while not any(m["type"] == "sign_sequence" for m in sent):
            if task.done() or asyncio.get_running_loop().time() > deadline:
                break
            await asyncio.sleep(0.02)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


# ── 1. Message models: discriminators, timing fields, wire shape ─────────────


def test_message_models_carry_type_and_timing():
    """Every outbound model round-trips to the shape ws-client.ts expects."""
    sid = str(uuid.uuid4())

    connected = json.loads(
        ConnectedMsg(session_id=sid, timestamp="2024-01-01T00:00:00+00:00").model_dump_json()
    )
    assert connected == {
        "type": "connected",
        "session_id": sid,
        "timestamp": "2024-01-01T00:00:00+00:00",
    }

    partial = json.loads(
        PartialTranscriptMsg(
            text="hi", segment_id=sid, start_ms=0, asr_ms=210, gloss_ms=0, total_ms=210
        ).model_dump_json()
    )
    assert partial["type"] == "partial"
    assert (partial["asr_ms"], partial["gloss_ms"], partial["total_ms"]) == (210, 0, 210)

    final = json.loads(
        FinalTranscriptMsg(
            text="hi", segment_id=sid, asr_ms=210, gloss_ms=55, total_ms=265
        ).model_dump_json()
    )
    assert final["type"] == "final"
    assert final["total_ms"] == 265

    gloss = json.loads(
        GlossMsg(
            tokens=["HELLO"], segment_id=sid, asr_ms=210, gloss_ms=55, total_ms=265
        ).model_dump_json()
    )
    assert gloss["type"] == "gloss"
    assert gloss["tokens"] == ["HELLO"]

    seq = json.loads(
        SignSequenceMsg(
            segment_id=sid,
            actions=[
                SignAction(
                    token="HELLO",
                    type="clip",
                    clip_path="/clips/hello.mp4",
                    letters=None,
                    duration_ms=800,
                )
            ],
            timing=TimingInfo(asr_ms=210, gloss_ms=55, total_ms=266),
        ).model_dump_json()
    )
    assert seq["type"] == "sign_sequence"
    # sign_sequence nests its timing; partial/final/gloss keep it flat.
    assert seq["timing"] == {"asr_ms": 210, "gloss_ms": 55, "total_ms": 266}
    assert seq["actions"][0]["clip_path"] == "/clips/hello.mp4"

    assert json.loads(PingMsg().model_dump_json())["type"] == "ping"
    assert json.loads(PongMsg().model_dump_json())["type"] == "pong"
    assert json.loads(ErrorMsg(message="boom").model_dump_json()) == {
        "type": "error",
        "message": "boom",
        "code": None,
    }


# ── 2. Unknown / malformed session → accepted, told why, closed 4004 ─────────


def _sole_error_frame(ws) -> dict:
    """The one JSON frame a rejected socket should have been sent."""
    ws.send_text.assert_awaited_once()
    return json.loads(ws.send_text.await_args.args[0])


@pytest.mark.asyncio
async def test_unknown_and_malformed_session_are_told_why_then_closed_4004():
    """Rejections are accepted first so the client receives a real close code.

    Closing mid-handshake reaches the browser as an opaque HTTP 403 — no code,
    no body — which the reconnect loop cannot distinguish from an outage.
    """
    missing_ws = AsyncMock()
    db = AsyncMock()
    db.get.return_value = None  # session not in DB

    await websocket_stream(missing_ws, str(uuid.uuid4()), db)

    missing_ws.accept.assert_awaited_once()
    missing_ws.close.assert_awaited_once_with(code=4004)
    assert _sole_error_frame(missing_ws) == {
        "type": "error",
        "message": "Unknown session",
        "code": "unknown_session",
    }

    # A non-UUID path param is rejected the same way, before touching the DB.
    bad_ws = AsyncMock()
    bad_db = AsyncMock()

    await websocket_stream(bad_ws, "not-a-uuid", bad_db)

    bad_ws.accept.assert_awaited_once()
    bad_ws.close.assert_awaited_once_with(code=4004)
    assert _sole_error_frame(bad_ws)["code"] == "bad_session_id"
    bad_db.get.assert_not_awaited()
    assert active_connections == {}


# ── 3. Backpressure: oldest frame is dropped when the queue saturates ────────


@pytest.mark.asyncio
async def test_enqueue_frame_drops_oldest_when_full(caplog):
    """At capacity the head is discarded so the newest audio still gets in."""
    conn = Connection(session_id="s1", websocket=AsyncMock())

    for i in range(QUEUE_MAX):
        _enqueue_frame(conn, bytes([i % 256]) * 4)
    assert conn.queue.full()
    assert conn.frames_dropped == 0

    newest = b"\xff\xff\xff\xff"
    with caplog.at_level("WARNING"):
        _enqueue_frame(conn, newest)

    assert conn.queue.qsize() == QUEUE_MAX  # bounded, not grown
    assert conn.frames_dropped == 1
    assert "queue full" in caplog.text.lower()

    # Frame 0 is gone; frame 1 is now the head and the new frame is the tail.
    assert conn.queue.get_nowait() == bytes([1]) * 4
    drained = [conn.queue.get_nowait() for _ in range(conn.queue.qsize())]
    assert drained[-1] == newest


# ── 4. VAD gating: silent windows never reach Whisper ────────────────────────


@pytest.mark.asyncio
async def test_silent_windows_are_skipped_before_asr():
    """is_speech() == False must short-circuit the window: no ASR, no frames."""
    ws, sent = _fake_ws()
    conn = Connection(session_id="s2", websocket=ws)
    services, asr = _pipeline(texts=["should never be transcribed"], speech=False)

    # Three full windows' worth of "audio".
    conn.queue.put_nowait(b"\x00" * (WINDOW_BYTES * 3))

    task = asyncio.create_task(_process_audio(conn, services))
    await asyncio.sleep(1.0)  # well past SILENCE_TIMEOUT
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    services.vad.is_speech.assert_awaited()
    asr.transcribe_chunk.assert_not_awaited()
    services.gloss.convert.assert_not_awaited()
    assert sent == []


# ── 5. Full pipeline: partial → final → gloss → sign_sequence ────────────────


@pytest.mark.asyncio
async def test_pipeline_emits_partial_then_final_gloss_and_sign_sequence():
    """Speech produces partials, and 600 ms of silence closes out the segment."""
    ws, sent = _fake_ws()
    conn = Connection(session_id="s3", websocket=ws)
    # Overlapping windows repeat "water" — the merge must not duplicate it.
    services, _ = _pipeline(
        texts=["I want water", "water now"], tokens=["I", "WATER", "WANT"]
    )

    conn.queue.put_nowait(b"\x01" * (WINDOW_BYTES * 2))

    await _run_until_sign_sequence(conn, services, sent)

    kinds = [m["type"] for m in sent]
    assert kinds.count("partial") >= 1
    assert kinds[-3:] == ["final", "gloss", "sign_sequence"]

    final = next(m for m in sent if m["type"] == "final")
    assert final["text"] == "I want water now"  # overlap de-duplicated
    assert final["asr_ms"] >= 0 and final["total_ms"] >= final["gloss_ms"]

    gloss = next(m for m in sent if m["type"] == "gloss")
    assert gloss["tokens"] == ["I", "WATER", "WANT"]
    assert gloss["segment_id"] == final["segment_id"]

    seq = next(m for m in sent if m["type"] == "sign_sequence")
    assert seq["segment_id"] == final["segment_id"]
    assert [a["token"] for a in seq["actions"]] == ["I", "WATER", "WANT"]
    assert set(seq["timing"]) == {"asr_ms", "gloss_ms", "total_ms"}
    assert seq["timing"]["total_ms"] >= seq["timing"]["asr_ms"]

    # Every partial also carries the full timing triple.
    for msg in (m for m in sent if m["type"] == "partial"):
        assert {"asr_ms", "gloss_ms", "total_ms"} <= set(msg)
