"""Unit tests for the English → ISL gloss converter.

The rule engine is exercised through `gloss_sync` (pure, no I/O). Everything
that touches Redis or OpenAI goes through `convert`, with both dependencies
replaced by fakes — no test in this file opens a socket.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import pytest

from app.core import state
from app.services import gloss as gloss_module
from app.services.gloss import (
    _CACHE_TTL_SECONDS,
    _cache_key,
    _pronoun_gloss,
    convert,
    gloss_sync,
)


def gloss(text: str) -> list[str]:
    """The rule engine alone — no cache, no LLM."""
    return gloss_sync(text)


# ── Fakes ─────────────────────────────────────────────────────────────────────

class FakeRedis:
    """Minimal async stand-in for the two commands the gloss cache uses."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.get_calls: list[str] = []
        self.setex_calls: list[tuple[str, int, str]] = []

    async def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.setex_calls.append((key, ttl, value))
        self.store[key] = value


class BrokenRedis:
    async def get(self, key: str) -> str | None:
        raise ConnectionError("redis is down")

    async def setex(self, key: str, ttl: int, value: str) -> None:
        raise ConnectionError("redis is down")


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    client = FakeRedis()
    monkeypatch.setattr(state, "redis_client", client, raising=False)
    return client


@pytest.fixture
def no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the LLM layer unavailable, so the last-resort path is what is tested."""

    async def _fail(sentence: str) -> list[str]:
        raise RuntimeError("openai unavailable")

    monkeypatch.setattr(gloss_module, "_llm_gloss", _fail)


# ── 1-15. Required golden tests ───────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("Good morning students",            ["GOOD", "MORNING", "STUDENT"]),
    ("What is your name?",               ["YOUR", "NAME", "WHAT"]),
    ("I am not going to class today",    ["I", "CLASS", "GO", "NOT", "TODAY"]),
    ("Please sit down",                  ["SIT", "DOWN"]),
    ("She did not eat the apple",        ["SHE", "APPLE", "EAT", "NOT"]),
    ("Where is the library?",            ["LIBRARY", "WHERE"]),
    ("I want water",                     ["I", "WATER", "WANT"]),
    ("Are you hungry?",                  ["YOU", "HUNGRY"]),
    ("The teacher explained the lesson", ["TEACHER", "LESSON", "EXPLAIN"]),
    ("I do not understand",              ["I", "UNDERSTAND", "NOT"]),
    ("He is not coming to school",       ["HE", "SCHOOL", "COME", "NOT"]),
    ("Open your books",                  ["BOOK", "OPEN"]),
    ("The exam is tomorrow",             ["EXAM", "TOMORROW"]),
    ("How many students?",               ["STUDENT", "HOW", "MANY"]),
    ("I love learning",                  ["I", "LEARNING", "LOVE"]),
])
def test_required_golden(text: str, expected: list[str]) -> None:
    assert gloss(text) == expected


# ── 16. Wider grammar coverage ────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    # SOV reordering
    ("I see the dog",                    ["I", "DOG", "SEE"]),
    ("We need help",                     ["WE", "HELP", "NEED"]),
    ("They watch television",            ["THEY", "TELEVISION", "WATCH"]),
    ("The doctor helped the patient",    ["DOCTOR", "PATIENT", "HELP"]),
    ("She teaches mathematics",          ["SHE", "MATHEMATICS", "TEACH"]),
    ("I love you",                       ["I", "YOU", "LOVE"]),
    # Embedded clause: the inner object comes forward with its own verb, and
    # "need" is auxiliary here — the complement "finish" is the predicate.
    ("We need to finish the homework",   ["WE", "HOMEWORK", "FINISH"]),
    # ...but with a nominal object "need" is the predicate and must survive.
    ("I need water",                     ["I", "WATER", "NEED"]),
    # WH questions
    ("Why are you late?",                ["YOU", "LATE", "WHY"]),
    ("How are you?",                     ["YOU", "HOW"]),
    ("Who is your teacher?",             ["YOUR", "TEACHER", "WHO"]),
    # Negation
    ("He does not speak English",        ["HE", "ENGLISH", "SPEAK", "NOT"]),
    ("I cannot hear",                    ["I", "HEAR", "NOT"]),
    # Auxiliaries and time adverbs
    ("I will help you tomorrow",         ["I", "YOU", "HELP", "TOMORROW"]),
])
def test_additional_golden(text: str, expected: list[str]) -> None:
    assert gloss(text) == expected


# ── 17-20. Empty / degenerate input ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_string_returns_empty(fake_redis: FakeRedis) -> None:
    assert await convert("") == []


@pytest.mark.asyncio
async def test_none_input_returns_empty(fake_redis: FakeRedis) -> None:
    assert await convert(None) == []  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_whitespace_only_returns_empty(fake_redis: FakeRedis) -> None:
    assert await convert("   \n\t ") == []


@pytest.mark.asyncio
async def test_non_string_input_returns_empty(fake_redis: FakeRedis) -> None:
    assert await convert(42) == []  # type: ignore[arg-type]


# ── 21. Single word ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_single_word_is_returned_uppercased(
    fake_redis: FakeRedis, no_llm: None
) -> None:
    """One word is below the LLM threshold; with no LLM the word itself survives."""
    assert await convert("water") == ["WATER"]
    assert await convert("Hello") == ["HELLO"]


# ── 22-23. Numbers ────────────────────────────────────────────────────────────

def test_number_words_become_digits() -> None:
    assert gloss("I have three books") == ["I", "BOOK", "3", "HAVE"]


@pytest.mark.parametrize("word,digit", [
    ("one", "1"), ("two", "2"), ("five", "5"), ("ten", "10"), ("twenty", "20"),
])
def test_number_vocabulary(word: str, digit: str) -> None:
    assert digit in gloss(f"I want {word} apples")


# ── 24-26. Pronouns ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("forms,expected", [
    (["I", "me", "myself"],              "I"),
    (["you", "yourself"],                "YOU"),
    (["he", "him", "himself"],           "HE"),
    (["she", "her", "herself"],          "SHE"),
    (["we", "us", "ourselves"],          "WE"),
    (["they", "them", "themselves"],     "THEY"),
    (["it", "itself"],                   "IT"),
])
def test_pronoun_groups(forms: list[str], expected: str) -> None:
    for form in forms:
        assert _pronoun_gloss(form) == expected
        assert _pronoun_gloss(form.upper()) == expected


@pytest.mark.parametrize("form,expected", [
    ("my", "MY"), ("mine", "MY"), ("your", "YOUR"), ("yours", "YOUR"),
    ("his", "HIS"), ("her", "HER"), ("hers", "HER"), ("our", "OUR"),
    ("their", "THEIR"), ("its", "ITS"),
])
def test_possessive_pronouns_keep_possessive_gloss(form: str, expected: str) -> None:
    # A verbless clause is all the possessive has to carry the meaning:
    # "What is your name?" must gloss YOUR NAME WHAT, not YOU NAME WHAT.
    assert _pronoun_gloss(form, True) == expected


def test_ambiguous_her_reads_from_context() -> None:
    assert _pronoun_gloss("her") == "SHE"           # "I saw her"
    assert _pronoun_gloss("her", True) == "HER"     # "her book"
    assert gloss("It is her book") == ["IT", "HER", "BOOK"]


def test_pronoun_lookup_is_cached() -> None:
    _pronoun_gloss.cache_clear()
    _pronoun_gloss("she")
    _pronoun_gloss("she")
    assert _pronoun_gloss.cache_info().hits >= 1


def test_pronouns_in_sentences() -> None:
    assert gloss("She gave him her book") == ["SHE", "HE", "BOOK", "GIVE"]
    assert gloss("We understand the problem") == ["WE", "PROBLEM", "UNDERSTAND"]


# ── 27-29. Output shape ───────────────────────────────────────────────────────

def test_output_is_uppercase_without_punctuation() -> None:
    tokens = gloss("Well, the teacher explained the lesson!")
    assert tokens == [t.upper() for t in tokens]
    assert all(t.isalnum() for t in tokens)


def test_output_has_no_empty_strings() -> None:
    assert all(t.strip() for t in gloss("  The   teacher  explained the lesson  "))


def test_output_has_no_duplicates() -> None:
    tokens = gloss("The teacher explained the lesson and the teacher explained")
    assert len(tokens) == len(set(tokens))


# ── 30-31. Positional rules ───────────────────────────────────────────────────

def test_wh_word_moves_to_the_end() -> None:
    for text in ("Where is the library?", "What is your name?", "Why are you late?"):
        assert gloss(text)[-1] in {"WHERE", "WHAT", "WHY"}


def test_negation_follows_the_verb() -> None:
    tokens = gloss("She did not eat the apple")
    assert tokens.index("NOT") == tokens.index("EAT") + 1


def test_time_words_keep_their_position() -> None:
    assert gloss("I am not going to class today")[-1] == "TODAY"
    assert gloss("The exam is tomorrow") == ["EXAM", "TOMORROW"]


# ── 32-35. Redis cache ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cache_hit_is_faster_on_second_call(
    fake_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    real = gloss_module.gloss_sync

    def counting(sentence: str) -> list[str]:
        calls.append(sentence)
        return real(sentence)

    monkeypatch.setattr(gloss_module, "gloss_sync", counting)

    sentence = "The teacher explained the lesson"

    t0 = time.perf_counter()
    first = await convert(sentence)
    first_elapsed = time.perf_counter() - t0

    t1 = time.perf_counter()
    second = await convert(sentence)
    second_elapsed = time.perf_counter() - t1

    assert first == second
    assert calls == [sentence], "second call must be served from cache"
    assert second_elapsed < first_elapsed


@pytest.mark.asyncio
async def test_cache_key_ignores_case_and_surrounding_space(
    fake_redis: FakeRedis
) -> None:
    assert _cache_key("  Hello World  ") == _cache_key("hello world")

    await convert("I want water")
    await convert("  i want WATER ")
    assert len(fake_redis.setex_calls) == 1


@pytest.mark.asyncio
async def test_result_is_stored_with_a_24_hour_ttl(fake_redis: FakeRedis) -> None:
    tokens = await convert("I want water")

    key, ttl, payload = fake_redis.setex_calls[0]
    assert key.startswith("gloss:")
    assert ttl == _CACHE_TTL_SECONDS == 86_400
    assert json.loads(payload) == tokens


@pytest.mark.asyncio
async def test_cached_value_is_returned_verbatim(fake_redis: FakeRedis) -> None:
    fake_redis.store[_cache_key("I want water")] = json.dumps(["CACHED", "VALUE"])
    assert await convert("I want water") == ["CACHED", "VALUE"]


@pytest.mark.asyncio
async def test_malformed_cache_entry_is_ignored(fake_redis: FakeRedis) -> None:
    fake_redis.store[_cache_key("I want water")] = "not json at all"
    assert await convert("I want water") == ["I", "WATER", "WANT"]


@pytest.mark.asyncio
async def test_redis_failure_does_not_break_conversion(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(state, "redis_client", BrokenRedis(), raising=False)
    assert await convert("I want water") == ["I", "WATER", "WANT"]


@pytest.mark.asyncio
async def test_missing_redis_client_does_not_break_conversion(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delattr(state, "redis_client", raising=False)
    assert await convert("I want water") == ["I", "WATER", "WANT"]


# ── 36-39. LLM fallback ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_llm_fallback_used_when_rules_yield_too_little(
    fake_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    async def fake_llm(sentence: str) -> list[str]:
        seen.append(sentence)
        return ["HELLO", "EVERYONE"]

    monkeypatch.setattr(gloss_module, "_llm_gloss", fake_llm)

    assert await convert("Hello") == ["HELLO", "EVERYONE"]
    assert seen == ["Hello"]


@pytest.mark.asyncio
async def test_llm_fallback_is_logged_with_the_sentence(
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fake_llm(sentence: str) -> list[str]:
        return ["HELLO", "THERE"]

    monkeypatch.setattr(gloss_module, "_llm_gloss", fake_llm)

    with caplog.at_level("INFO", logger=gloss_module.__name__):
        await convert("Hello")

    assert any("Hello" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_spacy_failure_falls_back_to_the_llm(
    fake_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gloss_module, "_get_nlp", lambda: None)

    async def fake_llm(sentence: str) -> list[str]:
        return ["TEACHER", "LESSON", "EXPLAIN"]

    monkeypatch.setattr(gloss_module, "_llm_gloss", fake_llm)

    assert await convert("The teacher explained the lesson") == [
        "TEACHER", "LESSON", "EXPLAIN"
    ]


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_raw_words(
    fake_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch, no_llm: None
) -> None:
    monkeypatch.setattr(gloss_module, "_get_nlp", lambda: None)
    assert await convert("Hello, everyone!") == ["HELLO", "EVERYONE"]


def test_llm_response_parsing_strips_prose_and_punctuation() -> None:
    assert gloss_module._parse_llm_response("Output: I WATER WANT") == [
        "I", "WATER", "WANT"
    ]
    assert gloss_module._parse_llm_response(" she apple eat not.\n") == [
        "SHE", "APPLE", "EAT", "NOT"
    ]
    assert gloss_module._parse_llm_response("") == []


# ── 40-43. Wiring and robustness ──────────────────────────────────────────────

def test_prompt_file_carries_the_few_shot_examples() -> None:
    prompt = gloss_module._load_prompt()
    assert prompt.count("Input:") >= 15
    assert prompt.count("Output:") >= 15
    assert "YOUR NAME WHAT" in prompt


def test_spacy_model_is_loaded_once() -> None:
    assert gloss_module._get_nlp() is gloss_module._get_nlp()


@pytest.mark.asyncio
async def test_gloss_service_delegates_to_convert(fake_redis: FakeRedis) -> None:
    service = gloss_module.GlossService()
    assert await service.convert("I want water") == ["I", "WATER", "WANT"]


@pytest.mark.asyncio
async def test_convert_never_raises(
    fake_redis: FakeRedis, no_llm: None
) -> None:
    odd_inputs: list[Any] = [
        "!!!",
        "🙂🙂",
        "a" * 5000,
        "Where where where?",
        "n't",
        [],
        None,
        3.14,
    ]
    for value in odd_inputs:
        result = await convert(value)
        assert isinstance(result, list)
        assert all(isinstance(token, str) and token.strip() for token in result)


@pytest.mark.asyncio
async def test_concurrent_conversions_are_independent(fake_redis: FakeRedis) -> None:
    sentences = [
        "I want water",
        "The teacher explained the lesson",
        "She did not eat the apple",
    ]
    results = await asyncio.gather(*(convert(s) for s in sentences))
    assert results == [
        ["I", "WATER", "WANT"],
        ["TEACHER", "LESSON", "EXPLAIN"],
        ["SHE", "APPLE", "EAT", "NOT"],
    ]
