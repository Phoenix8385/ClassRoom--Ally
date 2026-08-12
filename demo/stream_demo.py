#!/usr/bin/env python
"""Stream a WAV file at the live WebSocket and print every frame the backend sends back.

This is the end-to-end demo: audio in, sign actions out, with the backend's own
latency numbers on every message. Audio is paced in real time so the output
appears at the speed a teacher would actually be speaking.

    python demo/stream_demo.py
    python demo/stream_demo.py --wav demo/demo_speech.wav --api http://localhost:8000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.request
import wave

import websockets

# Windows consoles default to cp1252 and would choke on the box characters.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CHUNK_MS = 100          # how much audio to send per frame
SAMPLE_RATE = 16000
BYTES_PER_MS = 32       # 16 kHz * 2 bytes / 1000 ms

BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
RED = "\033[31m"
OFF = "\033[0m"

_t0 = time.monotonic()


def log(symbol: str, label: str, body: str, colour: str = "") -> None:
    stamp = f"{time.monotonic() - _t0:6.2f}s"
    print(f"{DIM}[{stamp}]{OFF} {colour}{symbol} {label:<14}{OFF}{body}", flush=True)


def read_pcm(path: str) -> bytes:
    """Return raw PCM bytes, refusing anything the pipeline cannot handle."""
    with wave.open(path, "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != SAMPLE_RATE:
            raise SystemExit(
                f"{RED}{path} must be 16 kHz, mono, 16-bit PCM — got "
                f"{w.getframerate()} Hz, {w.getnchannels()} ch, "
                f"{w.getsampwidth() * 8}-bit{OFF}"
            )
        return w.readframes(w.getnframes())


def create_session(api: str, teacher: str) -> str:
    payload = json.dumps({"teacher_name": teacher, "language": "ISL"}).encode()
    req = urllib.request.Request(
        f"{api}/sessions", data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)["id"]


def render(msg: dict) -> None:
    """Print one server message in the shape that makes the pipeline stage obvious."""
    kind = msg.get("type")

    if kind == "connected":
        log("*", "CONNECTED", f"session={msg['session_id']}", GREEN)

    elif kind == "partial":
        log("~", "partial", f'{DIM}"{msg["text"]}"{OFF}   asr={msg.get("asr_ms", 0)}ms')

    elif kind == "final":
        log("=", "FINAL TEXT", f'{BOLD}"{msg["text"]}"{OFF}   '
                               f'asr={msg.get("asr_ms", 0)}ms', CYAN)

    elif kind == "gloss":
        tokens = " ".join(msg["tokens"])
        log(">", "ISL GLOSS", f'{BOLD}{YELLOW}{tokens}{OFF}   '
                              f'gloss={msg.get("gloss_ms", 0)}ms', YELLOW)

    elif kind == "sign_sequence":
        actions = msg["actions"]
        timing = msg.get("timing", {})
        clips = sum(1 for a in actions if a["type"] == "clip")
        log("#", "SIGN ACTIONS",
            f'{BOLD}{len(actions)} actions{OFF}  '
            f'({clips} clips, {len(actions) - clips} fingerspelled)  '
            f'total={timing.get("total_ms", 0)}ms', MAGENTA)
        for i, a in enumerate(actions, 1):
            if a["type"] == "clip":
                detail = f'{GREEN}clip{OFF}         {a["clip_web_path"]}'
            else:
                detail = f'{YELLOW}fingerspell{OFF}  ' + "-".join(a["letters"] or [])
            print(f"                    {i}. {a['token']:<12} {detail:<40} "
                  f"{DIM}{a['duration_ms']}ms{OFF}", flush=True)

    elif kind == "error":
        log("!", "ERROR", f'{msg.get("message")} (code={msg.get("code")})', RED)


async def receiver(ws: websockets.WebSocketClientProtocol) -> None:
    async for raw in ws:
        msg = json.loads(raw)
        if msg.get("type") == "ping":
            # Answer the heartbeat, otherwise the server closes us after 10 s.
            await ws.send(json.dumps({"type": "pong"}))
            continue
        render(msg)


async def sender(ws: websockets.WebSocketClientProtocol, pcm: bytes) -> None:
    chunk = CHUNK_MS * BYTES_PER_MS
    total = len(pcm)
    for offset in range(0, total, chunk):
        await ws.send(pcm[offset:offset + chunk])
        # Pace it like a real microphone rather than dumping the file at once.
        await asyncio.sleep(CHUNK_MS / 1000)
    log("_", "audio sent", f"{total / BYTES_PER_MS / 1000:.1f}s of speech streamed", DIM)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", default="demo/demo_speech.wav")
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--teacher", default="Demo Teacher")
    ap.add_argument("--tail", type=float, default=4.0,
                    help="seconds to keep listening after the audio ends")
    args = ap.parse_args()

    pcm = read_pcm(args.wav)
    print(f"\n{BOLD}Classroom Ally — live backend demo{OFF}")
    print(f"{DIM}{'-' * 78}{OFF}")
    print(f"{DIM}audio  : {args.wav}  ({len(pcm) / BYTES_PER_MS / 1000:.1f}s, "
          f"16 kHz mono PCM){OFF}")

    session_id = create_session(args.api, args.teacher)
    print(f"{DIM}session: {session_id}  (row written to PostgreSQL){OFF}")

    ws_url = args.api.replace("http://", "ws://").replace("https://", "wss://")
    url = f"{ws_url}/ws/stream/{session_id}"
    print(f"{DIM}socket : {url}{OFF}")
    print(f"{DIM}{'-' * 78}{OFF}\n")

    global _t0
    _t0 = time.monotonic()

    async with websockets.connect(url, max_size=None) as ws:
        recv_task = asyncio.create_task(receiver(ws))
        await sender(ws, pcm)
        # The last utterance only finalises after the silence timeout elapses.
        await asyncio.sleep(args.tail)
        recv_task.cancel()

    print(f"\n{DIM}{'-' * 78}{OFF}")
    print(f"{GREEN}{BOLD}Done.{OFF} Speech -> text -> ISL gloss -> sign actions, "
          f"all through the live backend.\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
