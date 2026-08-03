from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.session import ClassroomSession
from app.services import sign_mapper
from app.services.asr import SileroVAD, WhisperService
from app.services.gloss import GlossService
from app.services.sign_mapper import SignAction

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# ── Audio constants ───────────────────────────────────────────────────────────
# PCM Int16 @ 16 kHz mono: 2 bytes/sample, 32 bytes/ms
_BYTES_PER_MS: int = 32
WINDOW_BYTES: int = 1_000 * _BYTES_PER_MS   # 32 000 — 1-second window
OVERLAP_BYTES: int = 200 * _BYTES_PER_MS    #  6 400 — 200 ms tail kept for overlap
STRIDE_BYTES: int = WINDOW_BYTES - OVERLAP_BYTES  # 25 600 — advance per window

SILENCE_TIMEOUT: float = 0.6    # seconds without speech → end of utterance
POLL_INTERVAL: float = 0.1      # how often the pipeline re-checks the silence clock
HEARTBEAT_INTERVAL: float = 30.0
PONG_TIMEOUT: float = 10.0
QUEUE_MAX: int = 20


# ── Pydantic message models ───────────────────────────────────────────────────
# The wire contract mirrors apps/web/src/lib/ws-client.ts: partial/final/gloss
# carry the timing fields flat, sign_sequence nests them under `timing`.

class TimingInfo(BaseModel):
    asr_ms: int = 0
    gloss_ms: int = 0
    total_ms: int = 0


class ConnectedMsg(BaseModel):
    type: Literal["connected"] = "connected"
    session_id: str
    timestamp: str


class PartialTranscriptMsg(TimingInfo):
    type: Literal["partial"] = "partial"
    text: str
    segment_id: str
    start_ms: int


class FinalTranscriptMsg(TimingInfo):
    type: Literal["final"] = "final"
    text: str
    segment_id: str


class GlossMsg(TimingInfo):
    type: Literal["gloss"] = "gloss"
    tokens: list[str]
    segment_id: str


class SignSequenceMsg(BaseModel):
    type: Literal["sign_sequence"] = "sign_sequence"
    segment_id: str
    actions: list[SignAction]
    timing: TimingInfo


class PingMsg(BaseModel):
    type: Literal["ping"] = "ping"


class PongMsg(BaseModel):
    type: Literal["pong"] = "pong"


class ErrorMsg(BaseModel):
    type: Literal["error"] = "error"
    message: str
    code: str | None = None


# ── Connection registry ───────────────────────────────────────────────────────

@dataclass
class Connection:
    """Everything owned by one live socket, so teardown can be exhaustive."""

    session_id: str
    websocket: WebSocket
    queue: asyncio.Queue[bytes] = field(
        default_factory=lambda: asyncio.Queue(maxsize=QUEUE_MAX)
    )
    pong_event: asyncio.Event = field(default_factory=asyncio.Event)
    audio_task: asyncio.Task[None] | None = None
    heartbeat_task: asyncio.Task[None] | None = None
    connected_at: float = field(default_factory=time.monotonic)
    frames_received: int = 0
    frames_dropped: int = 0


active_connections: dict[str, Connection] = {}


# ── Pipeline services ─────────────────────────────────────────────────────────

@dataclass
class PipelineServices:
    """Injected so the audio task can be unit-tested without loading models."""

    asr: WhisperService
    vad: SileroVAD
    gloss: GlossService
    map_signs: Callable[[list[str]], list[SignAction]]


_gloss_service: GlossService | None = None


def build_pipeline() -> PipelineServices:
    global _gloss_service
    if _gloss_service is None:
        _gloss_service = GlossService()
    return PipelineServices(
        asr=WhisperService.get_instance(),
        vad=SileroVAD.get_instance(),
        gloss=_gloss_service,
        map_signs=sign_mapper.map,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _send(ws: WebSocket, msg: BaseModel) -> None:
    await ws.send_text(msg.model_dump_json())


def _enqueue_frame(conn: Connection, frame: bytes) -> None:
    """Push a frame, dropping the oldest one when the queue is saturated.

    Dropping the head rather than the tail keeps the most recent audio, which is
    what the listener is waiting on; falling behind is better than going stale.
    """
    if conn.queue.full():
        try:
            conn.queue.get_nowait()
        except asyncio.QueueEmpty:  # pragma: no cover — drained concurrently
            pass
        else:
            conn.frames_dropped += 1
            logger.warning(
                "Audio queue full — dropped oldest frame (session=%s dropped=%d)",
                conn.session_id,
                conn.frames_dropped,
            )
    conn.queue.put_nowait(frame)
    conn.frames_received += 1


def _merge_transcript(existing: str, new: str) -> str:
    """Concatenate consecutive window transcripts, de-duplicating the overlap.

    Windows share their trailing 200 ms with the next window, so Whisper often
    repeats the last word or two. Longest word-suffix/prefix match wins.
    """
    if not existing:
        return new.strip()
    if not new.strip():
        return existing

    head = existing.split()
    tail = new.split()

    def norm(words: list[str]) -> list[str]:
        return [w.lower().strip(".,!?;:") for w in words]

    for n in range(min(len(head), len(tail)), 0, -1):
        if norm(head[-n:]) == norm(tail[:n]):
            return " ".join(head + tail[n:])
    return " ".join(head + tail)


# ── Background: heartbeat ─────────────────────────────────────────────────────

async def _heartbeat(conn: Connection) -> None:
    ws = conn.websocket
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            conn.pong_event.clear()
            await _send(ws, PingMsg())
            try:
                await asyncio.wait_for(conn.pong_event.wait(), timeout=PONG_TIMEOUT)
            except TimeoutError:
                logger.warning(
                    "Pong timeout after %.0fs — closing (session=%s)",
                    PONG_TIMEOUT,
                    conn.session_id,
                )
                await ws.close(code=1001)
                return
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Heartbeat failed (session=%s)", conn.session_id)


# ── Background: audio pipeline ────────────────────────────────────────────────

async def _process_audio(conn: Connection, services: PipelineServices) -> None:
    """Buffer PCM into overlapping 1 s windows, then VAD → ASR → gloss → signs."""
    ws = conn.websocket
    buffer = bytearray()

    segment_id = str(uuid.uuid4())
    segment_text = ""
    segment_asr_ms = 0
    segment_start_ms = 0
    bytes_consumed = 0          # stream bytes that have left the buffer
    last_speech_at: float | None = None

    async def finalize() -> None:
        nonlocal segment_id, segment_text, segment_asr_ms, last_speech_at
        if not segment_text:
            last_speech_at = None
            return

        text = segment_text

        gloss_t0 = time.monotonic()
        tokens = await services.gloss.convert(text)
        gloss_ms = int((time.monotonic() - gloss_t0) * 1000)

        await _send(ws, FinalTranscriptMsg(
            text=text,
            segment_id=segment_id,
            asr_ms=segment_asr_ms,
            gloss_ms=gloss_ms,
            total_ms=segment_asr_ms + gloss_ms,
        ))
        await _send(ws, GlossMsg(
            tokens=tokens,
            segment_id=segment_id,
            asr_ms=segment_asr_ms,
            gloss_ms=gloss_ms,
            total_ms=segment_asr_ms + gloss_ms,
        ))

        map_t0 = time.monotonic()
        actions = services.map_signs(tokens)
        map_ms = int((time.monotonic() - map_t0) * 1000)

        await _send(ws, SignSequenceMsg(
            segment_id=segment_id,
            actions=actions,
            timing=TimingInfo(
                asr_ms=segment_asr_ms,
                gloss_ms=gloss_ms,
                total_ms=segment_asr_ms + gloss_ms + map_ms,
            ),
        ))

        # Start a fresh utterance.
        segment_id = str(uuid.uuid4())
        segment_text = ""
        segment_asr_ms = 0
        last_speech_at = None

    async def is_speech(window: bytes) -> bool:
        try:
            return await services.vad.is_speech(window)
        except Exception:
            # A VAD failure must not silence the stream — fall through to ASR.
            logger.warning(
                "VAD failed, treating window as speech (session=%s)",
                conn.session_id,
                exc_info=True,
            )
            return True

    try:
        while True:
            try:
                frame = await asyncio.wait_for(conn.queue.get(), timeout=POLL_INTERVAL)
            except TimeoutError:
                frame = None

            if frame is not None:
                buffer.extend(frame)

            while len(buffer) >= WINDOW_BYTES:
                window = bytes(buffer[:WINDOW_BYTES])
                window_start_ms = bytes_consumed // _BYTES_PER_MS

                # Slide forward before any await, retaining the 200 ms overlap.
                del buffer[:STRIDE_BYTES]
                bytes_consumed += STRIDE_BYTES

                if not await is_speech(window):
                    continue

                asr_t0 = time.monotonic()
                result = await services.asr.transcribe_chunk(window)
                asr_ms = int((time.monotonic() - asr_t0) * 1000)

                last_speech_at = time.monotonic()
                if not result.text.strip():
                    continue

                if not segment_text:
                    segment_start_ms = window_start_ms
                segment_text = _merge_transcript(segment_text, result.text)
                segment_asr_ms += asr_ms

                await _send(ws, PartialTranscriptMsg(
                    text=segment_text,
                    segment_id=segment_id,
                    start_ms=segment_start_ms,
                    asr_ms=asr_ms,
                    gloss_ms=0,
                    total_ms=asr_ms,
                ))

            if (
                last_speech_at is not None
                and time.monotonic() - last_speech_at >= SILENCE_TIMEOUT
            ):
                await finalize()

    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Audio pipeline failed (session=%s)", conn.session_id)
        try:
            await _send(ws, ErrorMsg(message="Audio pipeline failure", code="pipeline"))
        except Exception:  # pragma: no cover — socket already gone
            pass


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.websocket("/ws/stream/{session_id}")
async def websocket_stream(
    websocket: WebSocket,
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        session_uuid = uuid.UUID(str(session_id))
    except (ValueError, AttributeError, TypeError):
        logger.info("Rejecting WebSocket: malformed session id %r", session_id)
        await websocket.close(code=4004)
        return

    session = await db.get(ClassroomSession, session_uuid)
    if session is None:
        logger.info("Rejecting WebSocket: unknown session %s", session_uuid)
        await websocket.close(code=4004)
        return

    key = str(session_uuid)
    await websocket.accept()
    logger.info("WebSocket connected: session=%s", key)

    await _send(websocket, ConnectedMsg(
        session_id=key,
        timestamp=datetime.now(UTC).isoformat(),
    ))

    conn = Connection(session_id=key, websocket=websocket)
    conn.pong_event.set()  # start out healthy

    if key in active_connections:
        logger.warning("Replacing existing registration for session=%s", key)
    active_connections[key] = conn

    conn.audio_task = asyncio.create_task(
        _process_audio(conn, build_pipeline()), name=f"audio-{key}"
    )
    conn.heartbeat_task = asyncio.create_task(
        _heartbeat(conn), name=f"heartbeat-{key}"
    )

    disconnect_reason = "normal"
    try:
        while True:
            message = await websocket.receive()

            # receive() surfaces disconnects as a message type, not an exception.
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect(code=message.get("code", 1000))

            if message.get("bytes") is not None:
                _enqueue_frame(conn, message["bytes"])

            elif message.get("text") is not None:
                try:
                    data = json.loads(message["text"])
                except json.JSONDecodeError:
                    logger.warning("Malformed text frame (session=%s)", key)
                    continue
                if data.get("type") == "pong":
                    conn.pong_event.set()

    except WebSocketDisconnect as exc:
        disconnect_reason = f"code={exc.code}"
    except Exception as exc:
        disconnect_reason = f"error={exc!r}"
        logger.exception("WebSocket receive failed (session=%s)", key)
    finally:
        for task in (conn.audio_task, conn.heartbeat_task):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(t for t in (conn.audio_task, conn.heartbeat_task) if t is not None),
            return_exceptions=True,
        )
        # Only unregister ourselves — a reconnect may already own the slot.
        if active_connections.get(key) is conn:
            del active_connections[key]

        logger.info(
            "WebSocket closed: session=%s reason=%s duration=%.1fs "
            "frames=%d dropped=%d active=%d",
            key,
            disconnect_reason,
            time.monotonic() - conn.connected_at,
            conn.frames_received,
            conn.frames_dropped,
            len(active_connections),
        )
