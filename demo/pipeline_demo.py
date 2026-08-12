#!/usr/bin/env python
"""Show the text half of the pipeline: English -> ISL gloss -> sign actions.

No audio, no microphone, no Whisper — so it answers in milliseconds and cannot
be derailed by a slow laptop. Run it with sentences of your own to prove the
grammar engine is really parsing, not replaying canned answers:

    python demo/pipeline_demo.py
    python demo/pipeline_demo.py "The teacher explained the lesson"
    python demo/pipeline_demo.py --interactive
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

import redis.asyncio as aioredis

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from app.core import state  # noqa: E402
from app.core.config import settings  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BOLD, DIM, OFF = "\033[1m", "\033[2m", "\033[0m"
CYAN, GREEN, YELLOW, MAGENTA = "\033[36m", "\033[32m", "\033[33m", "\033[35m"

DEFAULT_SENTENCES = [
    "Good morning students",
    "I am not going to class today",
    "Where is the library?",
    "What is your name?",
    "Open your books to page five",
    "The teacher explained the lesson",
    "We need to finish the homework",
    "How many students are in the class?",
    "My name is Praveen",
]


async def show(sentence: str) -> None:
    from app.services import sign_mapper
    from app.services.gloss import convert

    t0 = time.monotonic()
    tokens = await convert(sentence)
    gloss_ms = (time.monotonic() - t0) * 1000

    t1 = time.monotonic()
    mapping = await sign_mapper.map(tokens)
    map_ms = (time.monotonic() - t1) * 1000

    print(f"\n{DIM}{'=' * 74}{OFF}")
    print(f"{BOLD}ENGLISH   {OFF}{CYAN}{sentence}{OFF}")
    print(f"{BOLD}ISL GLOSS {OFF}{YELLOW}{BOLD}{' '.join(tokens)}{OFF}"
          f"   {DIM}({gloss_ms:.0f} ms){OFF}")
    print(f"{BOLD}SIGNS     {OFF}{MAGENTA}{mapping.covered_tokens}/{mapping.total_tokens} "
          f"have a real clip — {mapping.coverage:.0%} coverage{OFF}"
          f"   {DIM}({map_ms:.0f} ms){OFF}")

    for i, a in enumerate(mapping.actions, 1):
        if a.type == "clip":
            what = f"{GREEN}clip{OFF}         {a.clip_web_path}"
        else:
            what = f"{YELLOW}fingerspell{OFF}  " + "-".join(a.letters or [])
        print(f"   {i}. {a.token:<12} {what:<44} {DIM}{a.duration_ms} ms{OFF}")

    if mapping.unknown_words:
        print(f"   {DIM}no sign for {', '.join(mapping.unknown_words)} "
              f"-> spelled out letter by letter{OFF}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sentences", nargs="*", help="sentences to convert")
    ap.add_argument("--interactive", "-i", action="store_true",
                    help="keep asking for sentences until you press Ctrl-C")
    args = ap.parse_args()

    state.redis_client = aioredis.from_url(
        settings.REDIS_URL, encoding="utf-8", decode_responses=True
    )

    print(f"\n{BOLD}Classroom Ally — English to Indian Sign Language{OFF}")
    print(f"{DIM}spaCy grammar engine + 300-word ISL glossary. No audio involved.{OFF}")

    try:
        for sentence in (args.sentences or DEFAULT_SENTENCES):
            await show(sentence)

        if args.interactive:
            print(f"\n{DIM}{'=' * 74}{OFF}")
            print(f"{BOLD}Type any English sentence (Ctrl-C to quit){OFF}")
            while True:
                try:
                    line = input(f"\n{CYAN}> {OFF}").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if line:
                    await show(line)
    finally:
        close = getattr(state.redis_client, "aclose", state.redis_client.close)
        await close()
        print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print()
