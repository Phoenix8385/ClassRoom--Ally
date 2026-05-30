from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_GLOSSARY_PATH = (
    Path(__file__).parents[4] / "packages" / "glossary" / "isl_glossary.json"
)

_CLIP_DURATION_MS = 800
_LETTER_DURATION_MS = 400

_glossary: dict[str, dict] = {}
_lock = threading.Lock()


def _load_glossary() -> None:
    try:
        data = json.loads(_GLOSSARY_PATH.read_text(encoding="utf-8"))
        with _lock:
            _glossary.clear()
            _glossary.update(data)
        logger.info("ISL glossary loaded: %d entries", len(_glossary))
    except Exception:
        logger.exception("Failed to load ISL glossary from %s", _GLOSSARY_PATH)


def _watch_thread() -> None:
    try:
        from watchfiles import watch  # type: ignore[import]
        for _ in watch(str(_GLOSSARY_PATH)):
            logger.info("Glossary file changed — reloading")
            _load_glossary()
    except Exception:
        logger.exception("Glossary file watcher stopped unexpectedly")


_load_glossary()
threading.Thread(target=_watch_thread, daemon=True, name="glossary-watcher").start()


class SignAction(BaseModel):
    token: str
    type: Literal["clip", "keypoints", "fingerspell"]
    clip_path: str | None = None
    letters: list[str] | None = None
    duration_ms: int


def map(tokens: list[str]) -> list[SignAction]:  # noqa: A001
    actions: list[SignAction] = []
    with _lock:
        snapshot = _glossary.copy()

    for token in tokens:
        upper = token.upper()
        entry = snapshot.get(upper)
        if entry and entry.get("has_clip"):
            actions.append(
                SignAction(
                    token=token,
                    type="clip",
                    clip_path=entry["clip_local_path"],
                    letters=None,
                    duration_ms=_CLIP_DURATION_MS,
                )
            )
        else:
            letters = list(upper)
            actions.append(
                SignAction(
                    token=token,
                    type="fingerspell",
                    clip_path=None,
                    letters=letters,
                    duration_ms=_LETTER_DURATION_MS * len(letters),
                )
            )
    return actions


def coverage(words: list[str]) -> dict:
    with _lock:
        snapshot = _glossary.copy()

    total = len(words)
    covered = sum(
        1 for w in words
        if snapshot.get(w.upper(), {}).get("has_clip", False)
    )
    return {
        "total": total,
        "covered": covered,
        "coverage_pct": round(covered / total * 100, 1) if total else 0.0,
    }
