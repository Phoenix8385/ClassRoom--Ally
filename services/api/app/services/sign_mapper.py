"""Map ISL gloss tokens onto playable sign actions.

Each token is resolved against packages/glossary/isl_glossary.json in order of
confidence — exact word, alias, number, then a conservative prefix match — and
anything still unresolved is fingerspelled letter by letter. Fingerspelling is
always possible, so mapping never fails; `MappingResult.coverage` reports how
much of the utterance had a real sign behind it.

The glossary is read once at import and, in development, re-read whenever the
file changes so clip work shows up without a restart.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

_GLOSSARY_PATH = (
    Path(__file__).parents[4] / "packages" / "glossary" / "isl_glossary.json"
)

# ── Duration model ────────────────────────────────────────────────────────────
# A recorded clip runs at its own pace; fingerspelling is charged per letter, a
# little faster for long words so a 14-letter term does not stall the stream.
CLIP_DURATION_MS = 1500
NUMBER_DURATION_MS = 1200
SHORT_WORD_LETTER_MS = 400   # words of 1-3 letters
LONG_WORD_LETTER_MS = 350    # words of 4 letters or more
SHORT_WORD_MAX_LETTERS = 3

# Prefix matching: "teach" ↔ "teacher" is worth catching, "exam" ↔ "example"
# is not. Both sides must share a real stem and differ by an ending that looks
# like inflection rather than a different word.
_MIN_PREFIX_LEN = 4
_MAX_SUFFIX_DELTA = 3
_INFLECTIONAL_SUFFIXES: frozenset[str] = frozenset(
    {"s", "es", "ed", "d", "ing", "er", "ers", "est", "ly", "ies", "n", "en"}
)

_NUMBER_WORDS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20,
}
_WORD_FOR_NUMBER: dict[int, str] = {value: key for key, value in _NUMBER_WORDS.items()}

_PUNCTUATION = ".,!?;:\"'()[]{}…-—"


# ── Models ────────────────────────────────────────────────────────────────────

class SignAction(BaseModel):
    """One playable unit: either a clip or a run of fingerspelled letters."""

    token: str
    type: Literal["clip", "fingerspell", "keypoints"]
    clip_path: str | None = None
    clip_web_path: str | None = None
    letters: list[str] | None = None
    duration_ms: int
    word: str = ""
    found_in_glossary: bool = False


class MappingResult(BaseModel):
    actions: list[SignAction]
    coverage: float
    unknown_words: list[str]
    total_tokens: int
    covered_tokens: int


# ── Glossary state ────────────────────────────────────────────────────────────

_lock = threading.Lock()
_entries: dict[str, dict] = {}      # canonical lowercase word → entry
_alias_index: dict[str, str] = {}   # alias → canonical word
_generation = 0                     # bumped on every successful reload


def _load_glossary() -> None:
    """Read the glossary file into the lookup tables. Never raises."""
    global _generation
    try:
        raw = json.loads(_GLOSSARY_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load ISL glossary from %s", _GLOSSARY_PATH)
        return

    entries: dict[str, dict] = {}
    aliases: dict[str, str] = {}
    for key, entry in raw.items():
        word = str(key).lower().strip()
        if not word or not isinstance(entry, dict):
            continue
        entries[word] = entry
        for alias in entry.get("aliases") or []:
            alias_key = str(alias).lower().strip()
            # A real word always beats an alias, and the first claim wins.
            if alias_key and alias_key not in raw and alias_key not in aliases:
                aliases[alias_key] = word

    with _lock:
        _entries.clear()
        _entries.update(entries)
        _alias_index.clear()
        _alias_index.update(aliases)
        _generation += 1

    logger.info(
        "ISL glossary loaded: %d words, %d aliases, %d with clips (from %s)",
        len(entries),
        len(aliases),
        sum(1 for e in entries.values() if e.get("has_clip")),
        _GLOSSARY_PATH,
    )


def _watch_thread() -> None:
    try:
        from watchfiles import watch  # type: ignore[import]

        for _ in watch(str(_GLOSSARY_PATH)):
            logger.info("Glossary file changed — reloading")
            _load_glossary()
    except Exception:
        logger.exception("Glossary file watcher stopped unexpectedly")


_load_glossary()

if settings.ENVIRONMENT == "development":
    threading.Thread(target=_watch_thread, daemon=True, name="glossary-watcher").start()


def _snapshot() -> tuple[dict[str, dict], dict[str, str], int]:
    with _lock:
        return dict(_entries), dict(_alias_index), _generation


# ── Lookup steps ──────────────────────────────────────────────────────────────

def _normalize(token: str) -> str:
    return token.lower().strip().strip(_PUNCTUATION).strip()


def _as_number(token: str) -> int | None:
    """The integer a token denotes, whether written "7" or "seven"."""
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token)


def _prefix_match(token: str, entries: dict[str, dict]) -> str | None:
    """A glossary word differing from the token only by a short ending.

    Catches the inflections the gloss converter did not lemmatize ("teaching" →
    TEACH) without letting unrelated stems collide.
    """
    if len(token) < _MIN_PREFIX_LEN:
        return None

    best: str | None = None
    best_delta = _MAX_SUFFIX_DELTA + 1
    for word in entries:
        if word == token or " " in word:
            continue
        shorter, longer = sorted((word, token), key=len)
        if len(shorter) < _MIN_PREFIX_LEN or not longer.startswith(shorter):
            continue
        if longer[len(shorter):] not in _INFLECTIONAL_SUFFIXES:
            continue
        delta = len(longer) - len(shorter)
        # Ties break alphabetically so the result never depends on dict order.
        if delta < best_delta or (delta == best_delta and best is not None and word < best):
            best, best_delta = word, delta
    return best


def _fingerspell_action(token: str, word: str, *, letters: list[str] | None = None) -> SignAction:
    spelled = letters if letters is not None else list(word)
    per_letter = (
        SHORT_WORD_LETTER_MS
        if len(spelled) <= SHORT_WORD_MAX_LETTERS
        else LONG_WORD_LETTER_MS
    )
    return SignAction(
        token=token,
        type="fingerspell",
        clip_path=None,
        clip_web_path=None,
        letters=spelled,
        duration_ms=per_letter * len(spelled),
        word=word,
        found_in_glossary=False,
    )


def _clip_action(token: str, word: str, entry: dict, *, duration_ms: int) -> SignAction:
    return SignAction(
        token=token,
        type="clip",
        clip_path=entry.get("clip_local_path"),
        clip_web_path=entry.get("clip_web_path"),
        letters=None,
        duration_ms=duration_ms,
        word=word,
        found_in_glossary=True,
    )


def _resolve(
    token: str, entries: dict[str, dict], aliases: dict[str, str]
) -> SignAction:
    """Turn one token into an action, trying each lookup in confidence order."""
    normalized = _normalize(token)
    if not normalized:
        return _fingerspell_action(token, "", letters=[])

    # 1. Exact word.
    entry = entries.get(normalized)
    word = normalized

    # 2. Alias of a word.
    if entry is None:
        canonical = aliases.get(normalized)
        if canonical is not None:
            entry = entries.get(canonical)
            word = canonical

    # 3. A number, written either way.
    if entry is None:
        value = _as_number(normalized)
        if value is not None:
            number_word = _WORD_FOR_NUMBER.get(value)
            if number_word is not None and number_word in entries:
                return _clip_action(
                    token, number_word, entries[number_word],
                    duration_ms=NUMBER_DURATION_MS,
                )
            # Above twenty there is no single sign — sign the digits in turn.
            digits = list(str(value))
            action = _fingerspell_action(token, str(value), letters=digits)
            return action.model_copy(update={"duration_ms": NUMBER_DURATION_MS * len(digits)})

    # 4. An inflected form of a word we do have.
    if entry is None:
        matched = _prefix_match(normalized, entries)
        if matched is not None:
            entry = entries[matched]
            word = matched

    # 5. Nothing matched, or the entry has no clip to play.
    if entry is None or not entry.get("has_clip", False):
        return _fingerspell_action(token, word if entry is not None else normalized)

    duration = (
        NUMBER_DURATION_MS if entry.get("category") == "number" else CLIP_DURATION_MS
    )
    return _clip_action(token, word, entry, duration_ms=duration)


# ── Public API ────────────────────────────────────────────────────────────────

async def map(tokens: list[str]) -> MappingResult:  # noqa: A001
    """Map gloss tokens to sign actions, reporting how many had a real sign."""
    entries, aliases, _ = _snapshot()

    actions = [_resolve(token, entries, aliases) for token in tokens]
    covered = sum(1 for action in actions if action.type == "clip")
    unknown = [
        action.token for action in actions
        if action.type == "fingerspell" and not action.found_in_glossary
    ]

    return MappingResult(
        actions=actions,
        coverage=round(covered / len(actions), 4) if actions else 0.0,
        unknown_words=unknown,
        total_tokens=len(actions),
        covered_tokens=covered,
    )


def coverage(words: list[str]) -> dict:
    """Glossary coverage for a list of words, without building the actions."""
    entries, aliases, _ = _snapshot()

    by_clip = 0
    unknown: list[str] = []
    for word in words:
        action = _resolve(word, entries, aliases)
        if action.type == "clip":
            by_clip += 1
        else:
            unknown.append(action.token)

    total = len(words)
    return {
        "total": total,
        "covered_by_clip": by_clip,
        "covered_by_fingerspell": total - by_clip,
        "not_covered": 0,  # fingerspelling always works, so nothing is unplayable
        "coverage_pct": round(by_clip / total * 100, 1) if total else 0.0,
        "unknown_words": unknown,
    }


def lookup(word: str) -> tuple[str, dict] | None:
    """The canonical word and entry a term resolves to, or None."""
    entries, aliases, _ = _snapshot()
    normalized = _normalize(word)

    if normalized in entries:
        return normalized, entries[normalized]

    canonical = aliases.get(normalized)
    if canonical is not None and canonical in entries:
        return canonical, entries[canonical]

    value = _as_number(normalized)
    number_word = _WORD_FOR_NUMBER.get(value) if value is not None else None
    if number_word is not None and number_word in entries:
        return number_word, entries[number_word]

    matched = _prefix_match(normalized, entries)
    if matched is not None:
        return matched, entries[matched]
    return None


def stats() -> dict:
    """Glossary totals, used by the /signs/glossary/stats endpoint."""
    entries, aliases, _ = _snapshot()

    by_category: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    for entry in entries.values():
        category = str(entry.get("category", "uncategorized"))
        by_category[category] = by_category.get(category, 0) + 1
        priority = f"priority_{entry.get('priority', 2)}"
        by_priority[priority] = by_priority.get(priority, 0) + 1

    return {
        "total_words": len(entries),
        "total_aliases": len(aliases),
        "with_clip": sum(1 for e in entries.values() if e.get("has_clip")),
        "clips_downloaded": sum(1 for e in entries.values() if e.get("clip_downloaded")),
        "fingerspell_fallback": sum(
            1 for e in entries.values() if e.get("fingerspell_fallback")
        ),
        "by_category": dict(sorted(by_category.items())),
        "by_priority": dict(sorted(by_priority.items())),
        "glossary_path": str(_GLOSSARY_PATH),
    }
