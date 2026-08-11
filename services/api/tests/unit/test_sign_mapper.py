"""Unit tests for the gloss-token → sign-action mapper."""
from __future__ import annotations

import pytest

from app.services import sign_mapper
from app.services.sign_mapper import (
    CLIP_DURATION_MS,
    LONG_WORD_LETTER_MS,
    NUMBER_DURATION_MS,
    SHORT_WORD_LETTER_MS,
    MappingResult,
    SignAction,
)


async def map_one(token: str) -> SignAction:
    result = await sign_mapper.map([token])
    assert len(result.actions) == 1
    return result.actions[0]


# ── 1-4. Glossary hits ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hello_maps_to_a_clip() -> None:
    action = await map_one("hello")

    assert action.type == "clip"
    assert action.found_in_glossary is True
    assert action.word == "hello"
    assert action.clip_path == "data/isl_clips/hello.mp4"
    assert action.clip_web_path == "/signs/hello.mp4"
    assert action.letters is None
    assert action.duration_ms == CLIP_DURATION_MS


@pytest.mark.asyncio
async def test_pronoun_maps_to_a_clip() -> None:
    action = await map_one("I")

    assert action.type == "clip"
    assert action.word == "i"
    assert action.token == "I", "the original token is echoed back unchanged"
    assert action.found_in_glossary is True


@pytest.mark.asyncio
async def test_uppercase_gloss_tokens_are_matched() -> None:
    # The gloss converter emits uppercase; the glossary is keyed lowercase.
    for token in ("TEACHER", "Teacher", "  teacher  ", "teacher."):
        action = await map_one(token)
        assert action.word == "teacher"
        assert action.type == "clip"


@pytest.mark.asyncio
async def test_multiword_entry_is_matched() -> None:
    action = await map_one("good morning")

    assert action.type == "clip"
    assert action.word == "good morning"
    assert action.clip_web_path == "/signs/good_morning.mp4"


# ── 5-6. Aliases ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_alias_hi_resolves_to_hello() -> None:
    action = await map_one("hi")

    assert action.type == "clip"
    assert action.word == "hello"
    assert action.clip_path == "data/isl_clips/hello.mp4"
    assert action.token == "hi"


@pytest.mark.asyncio
async def test_pronoun_aliases_resolve_to_their_group() -> None:
    for alias, canonical in [
        ("me", "i"), ("myself", "i"), ("yours", "you"),
        ("him", "he"), ("hers", "she"), ("them", "they"), ("its", "it"),
    ]:
        action = await map_one(alias)
        assert (alias, action.word) == (alias, canonical)
        assert action.type == "clip"


# ── 7-9. Numbers ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_digit_maps_to_the_number_clip() -> None:
    action = await map_one("5")

    assert action.type == "clip"
    assert action.word == "five"
    assert action.clip_path == "data/isl_clips/five.mp4"
    assert action.duration_ms == NUMBER_DURATION_MS


@pytest.mark.asyncio
async def test_number_word_maps_to_the_number_clip() -> None:
    action = await map_one("five")

    assert action.type == "clip"
    assert action.word == "five"
    assert action.duration_ms == NUMBER_DURATION_MS


@pytest.mark.asyncio
async def test_number_above_twenty_is_signed_digit_by_digit() -> None:
    action = await map_one("42")

    assert action.type == "fingerspell"
    assert action.letters == ["4", "2"]
    assert action.duration_ms == NUMBER_DURATION_MS * 2


# ── 10-12. Fingerspelling ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unknown_word_is_fingerspelled() -> None:
    action = await map_one("photosynthesis")

    assert action.type == "fingerspell"
    assert action.found_in_glossary is False
    assert action.clip_path is None
    assert action.letters == list("photosynthesis")


@pytest.mark.asyncio
async def test_fingerspell_duration_follows_word_length() -> None:
    long_word = await map_one("photosynthesis")          # 14 letters, 4+ rule
    assert long_word.duration_ms == 14 * LONG_WORD_LETTER_MS == 4900

    short_word = await map_one("xyz")                    # 3 letters, short rule
    assert short_word.duration_ms == 3 * SHORT_WORD_LETTER_MS == 1200


@pytest.mark.asyncio
async def test_inflected_form_falls_back_to_its_stem() -> None:
    action = await map_one("teaching")

    assert action.type == "clip"
    assert action.word == "teach"


@pytest.mark.asyncio
async def test_unrelated_stems_do_not_collide() -> None:
    # "example" shares its first four letters with "exam" but is a different
    # sign; only inflectional endings are allowed to match.
    entries, aliases, _ = sign_mapper._snapshot()
    assert sign_mapper._prefix_match("example", entries) is None
    assert sign_mapper._prefix_match("studious", entries) is None

    action = await map_one("example")
    assert action.type == "fingerspell"


# ── 13-15. Whole-utterance mapping ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_list_returns_an_empty_result() -> None:
    result = await sign_mapper.map([])

    assert isinstance(result, MappingResult)
    assert result.actions == []
    assert result.coverage == 0.0
    assert result.unknown_words == []
    assert (result.total_tokens, result.covered_tokens) == (0, 0)


@pytest.mark.asyncio
async def test_mixed_sentence_splits_clips_and_fingerspelling() -> None:
    result = await sign_mapper.map(["I", "PHOTOSYNTHESIS", "UNDERSTAND", "NOT", "MITOCHONDRIA"])

    kinds = [action.type for action in result.actions]
    assert kinds == ["clip", "fingerspell", "clip", "clip", "fingerspell"]
    assert result.total_tokens == 5
    assert result.covered_tokens == 3
    assert result.coverage == 0.6
    assert result.unknown_words == ["PHOTOSYNTHESIS", "MITOCHONDRIA"]


@pytest.mark.asyncio
async def test_every_token_produces_exactly_one_action() -> None:
    tokens = ["GOOD", "MORNING", "STUDENT", "ZZZZ"]
    result = await sign_mapper.map(tokens)

    assert [a.token for a in result.actions] == tokens
    assert all(a.duration_ms > 0 for a in result.actions)


# ── 16-18. Coverage and stats ─────────────────────────────────────────────────

def test_coverage_reports_correct_percentages() -> None:
    report = sign_mapper.coverage(["hello", "teacher", "photosynthesis", "mitochondria"])

    assert report["total"] == 4
    assert report["covered_by_clip"] == 2
    assert report["covered_by_fingerspell"] == 2
    assert report["not_covered"] == 0
    assert report["coverage_pct"] == 50.0
    assert report["unknown_words"] == ["photosynthesis", "mitochondria"]


def test_coverage_of_an_empty_list_is_zero_not_a_crash() -> None:
    assert sign_mapper.coverage([]) == {
        "total": 0,
        "covered_by_clip": 0,
        "covered_by_fingerspell": 0,
        "not_covered": 0,
        "coverage_pct": 0.0,
        "unknown_words": [],
    }


def test_glossary_stats_match_the_shipped_file() -> None:
    stats = sign_mapper.stats()

    assert stats["total_words"] == 300
    assert stats["with_clip"] == 300
    assert stats["by_priority"]["priority_1"] == 50
    for category in ("greeting", "classroom", "number", "pronoun", "verb",
                     "adjective", "time", "question"):
        assert stats["by_category"][category] > 0


# ── 19-21. Glossary contents and loading ──────────────────────────────────────

def test_required_vocabulary_is_present() -> None:
    entries, aliases, _ = sign_mapper._snapshot()

    required = [
        "hello", "goodbye", "good morning", "thank you", "excuse me", "please",
        "teacher", "student", "homework", "exam", "today",
        "zero", "twenty", "i", "you", "he", "she", "we", "they", "it",
        "go", "come", "understand", "happy", "angry", "water", "doctor",
        "what", "where", "when", "why", "how", "who", "which",
    ]
    missing = [word for word in required if word not in entries]
    assert missing == []
    assert aliases["hi"] == "hello"


def test_lookup_resolves_words_aliases_and_numbers() -> None:
    assert sign_mapper.lookup("HELLO")[0] == "hello"
    assert sign_mapper.lookup("bye")[0] == "goodbye"
    assert sign_mapper.lookup("7")[0] == "seven"
    assert sign_mapper.lookup("mitochondria") is None


def test_entries_with_no_clip_are_fingerspelled(monkeypatch: pytest.MonkeyPatch) -> None:
    entries, aliases, _ = sign_mapper._snapshot()
    patched = dict(entries)
    patched["hello"] = {**patched["hello"], "has_clip": False}

    action = sign_mapper._resolve("hello", patched, aliases)
    assert action.type == "fingerspell"
    assert action.letters == list("hello")


def test_glossary_reload_is_atomic(tmp_path) -> None:
    """A failed reload leaves the loaded glossary in place."""
    before = sign_mapper.stats()["total_words"]

    original = sign_mapper._GLOSSARY_PATH
    try:
        sign_mapper._GLOSSARY_PATH = tmp_path / "missing.json"
        sign_mapper._load_glossary()
        assert sign_mapper.stats()["total_words"] == before
    finally:
        sign_mapper._GLOSSARY_PATH = original
