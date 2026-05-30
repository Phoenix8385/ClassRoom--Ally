from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.session import ClassroomSession
from app.services.asr import WhisperService
from app.services.gloss import GlossService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# ── Audio constants ───────────────────────────────────────────────────────────
# PCM Int16 @ 16 kHz mono: 2 bytes/sample, 32 bytes/ms
_BYTES_PER_MS: int = 32
WINDOW_BYTES: int = 1_000 * _BYTES_PER_MS   # 32 000 — 1-second window
OVERLAP_BYTES: int = 200 * _BYTES_PER_MS    #  6 400 — 200 ms tail kept for overlap
STRIDE_BYTES: int = WINDOW_BYTES - OVERLAP_BYTES  # 25 600 — advance per window

SILENCE_TIMEOUT: float = 0.6    # seconds of empty queue → end of utterance
HEARTBEAT_INTERVAL: float = 30.0
PONG_TIMEOUT: float = 10.0
QUEUE_MAX: int = 20


# ── Pydantic message models ───────────────────────────────────────────────────

class _Timing(BaseModel):
    asr_ms: int = 0
    gloss_ms: int = 0
    total_ms: int = 0


class ConnectedMessage(BaseModel):
    type: Literal["connected"] = "connected"
    session_id: str
    timestamp: str


class PartialMessage(_Timing):
    type: Literal["partial"] = "partial"
    text: str
    segment_id: str
    start_ms: int


class FinalMessage(_Timing):
    type: Literal["final"] = "final"
    text: str
    segment_id: str


class GlossMessage(_Timing):
    type: Literal["gloss"] = "gloss"
    tokens: list[str]
    segment_id: str


class PingMessage(BaseModel):
    type: Literal["ping"] = "ping"


class PongMessage(BaseModel):
    type: Literal["pong"] = "pong"


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _send(ws: WebSocket, msg: BaseModel) -> None:
    await ws.send_text(msg.model_dump_json())


# ── Background: heartbeat ─────────────────────────────────────────────────────

async def _heartbeat(ws: WebSocket, pong_event: asyncio.Event) -> None:
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            pong_event.clear()
            await _send(ws, PingMessage())
            try:
                await asyncio.wait_for(pong_event.wait(), timeout=PONG_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning("Pong timeout — closing WebSocket (going away)")
                await ws.close(code=1001)
                return
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Heartbeat error")


# ── Background: audio processing ─────────────────────────────────────────────

async def _process_audio(
    ws: WebSocket,
    queue: asyncio.Queue[bytes],
    session_id: str,
) -> None:
    asr = WhisperService()
    gloss_svc = GlossService()

    buffer = bytearray()
    segment_id = str(uuid.uuid4())
    bytes_consumed: int = 0   # total stream bytes that have left the buffer
    current_text: str = ""
    last_asr_ms: int = 0

    async def _emit_final_and_gloss() -> None:
        nonlocal current_text, segment_id, last_asr_ms
        if not current_text:
            return

        gloss_t0 = time.monotonic()
        tokens = await gloss_svc.convert(current_text)
        gloss_ms = int((time.monotonic() - gloss_t0) * 1000)
        total_ms = last_asr_ms + gloss_ms

        await _send(ws, FinalMessage(
            text=current_text,
            segment_id=segment_id,
            asr_ms=last_asr_ms,
            gloss_ms=gloss_ms,
            total_ms=total_ms,
        ))
        await _send(ws, GlossMessage(
            tokens=tokens,
            segment_id=segment_id,
            asr_ms=last_asr_ms,
            gloss_ms=gloss_ms,
            total_ms=total_ms,
        ))

        current_text = ""
        last_asr_ms = 0
        segment_id = str(uuid.uuid4())

    try:
        while True:
            # Block until a frame arrives or SILENCE_TIMEOUT elapses.
            try:
                frame = await asyncio.wait_for(queue.get(), timeout=SILENCE_TIMEOUT)
            except asyncio.TimeoutError:
                # 600 ms with no new audio → end of utterance
                await _emit_final_and_gloss()
                buffer.clear()
                continue

            buffer.extend(frame)

            # Process every full 1-second window, advancing by STRIDE_BYTES.
            while len(buffer) >= WINDOW_BYTES:
                window = bytes(buffer[:WINDOW_BYTES])
                start_ms = bytes_consumed // _BYTES_PER_MS

                asr_t0 = time.monotonic()
                text = await asr.transcribe(window)
                asr_ms = int((time.monotonic() - asr_t0) * 1000)
                last_asr_ms = asr_ms
                current_text = text

                await _send(ws, PartialMessage(
                    text=text,
                    segment_id=segment_id,
                    start_ms=start_ms,
                    asr_ms=asr_ms,
                    gloss_ms=0,
                    total_ms=asr_ms,
                ))

                # Slide forward, retaining OVERLAP_BYTES for the next window.
                buffer = buffer[STRIDE_BYTES:]
                bytes_consumed += STRIDE_BYTES

    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Audio processing error (session=%s)", session_id)


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.websocket("/ws/stream/{session_id}")
async def websocket_stream(
    websocket: WebSocket,
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    session = await db.get(ClassroomSession, session_id)
    if session is None:
        await websocket.close(code=4004)
        return

    await websocket.accept()
    logger.info("WebSocket connected: session=%s", session_id)

    await _send(websocket, ConnectedMessage(
        session_id=str(session_id),
        timestamp=datetime.now(timezone.utc).isoformat(),
    ))

    queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=QUEUE_MAX)
    pong_event = asyncio.Event()
    pong_event.set()  # start "healthy"

    process_task = asyncio.create_task(
        _process_audio(websocket, queue, str(session_id)),
        name=f"audio-{session_id}",
    )
    heartbeat_task = asyncio.create_task(
        _heartbeat(websocket, pong_event),
        name=f"heartbeat-{session_id}",
    )

    disconnect_reason = "normal"
    try:
        while True:
            message = await websocket.receive()

            # Starlette returns a dict; disconnect appears as a message type,
            # not an exception, when using the raw receive() call.
            if message.get("type") == "websocket.disconnect":
                code = message.get("code", 1000)
                raise WebSocketDisconnect(code=code)

            if message.get("bytes"):
                frame: bytes = message["bytes"]
                if queue.full():
                    # Drop the oldest frame to make room; log the loss.
                    queue.get_nowait()
                    logger.warning(
                        "Audio queue full — oldest frame dropped (session=%s)",
                        session_id,
                    )
                await queue.put(frame)

            elif message.get("text"):
                try:
                    data = json.loads(message["text"])
                    if data.get("type") == "pong":
                        pong_event.set()
                except json.JSONDecodeError:
                    logger.warning("Malformed text frame from client (session=%s)", session_id)

    except WebSocketDisconnect as exc:
        disconnect_reason = f"code={exc.code}"
    except Exception as exc:
        disconnect_reason = f"error={exc!r}"
        logger.exception("WebSocket receive error (session=%s)", session_id)
    finally:
        process_task.cancel()
        heartbeat_task.cancel()
        await asyncio.gather(process_task, heartbeat_task, return_exceptions=True)
        logger.info(
            "WebSocket closed: session=%s reason=%s", session_id, disconnect_reason
        )
