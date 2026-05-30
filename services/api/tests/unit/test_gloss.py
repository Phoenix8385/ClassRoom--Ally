from __future__ import annotations

import pytest

from app.services.gloss import _apply_isl_rules, _get_nlp


def gloss(text: str) -> list[str]:
    doc = _get_nlp()(text)
    return _apply_isl_rules(doc)


# ── Required golden tests (must all pass) ─────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("Good morning students",              ["GOOD", "MORNING", "STUDENT"]),
    ("What is your name?",                 ["YOUR", "NAME", "WHAT"]),
    ("I am not going to class today",      ["I", "CLASS", "GO", "NOT", "TODAY"]),
    ("Please sit down",                    ["SIT", "DOWN"]),
    ("She did not eat the apple",          ["SHE", "APPLE", "EAT", "NOT"]),
    ("The teacher explained the lesson",   ["TEACHER", "LESSON", "EXPLAIN"]),
    ("Where is the library?",              ["LIBRARY", "WHERE"]),
    ("I want water",                       ["I", "WATER", "WANT"]),
    ("Are you hungry?",                    ["YOU", "HUNGRY"]),
    ("I do not understand",                ["I", "UNDERSTAND", "NOT"]),
])
def test_required_golden(text: str, expected: list[str]) -> None:
    assert gloss(text) == expected


# ── Additional golden tests ───────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    # Simple SOV sentences
    ("I see the dog",                      ["I", "DOG", "SEE"]),
    ("We need help",                       ["WE", "HELP", "NEED"]),
    ("I like coffee",                      ["I", "COFFEE", "LIKE"]),
    ("I love you",                         ["I", "YOU", "LOVE"]),
    ("They watch television",              ["THEY", "TELEVISION", "WATCH"]),
    ("They know the answer",               ["THEY", "ANSWER", "KNOW"]),
    ("We understand the problem",          ["WE", "PROBLEM", "UNDERSTAND"]),
    ("I read the newspaper",               ["I", "NEWSPAPER", "READ"]),
    ("The doctor helped the patient",      ["DOCTOR", "PATIENT", "HELP"]),
    ("She teaches mathematics",            ["SHE", "MATHEMATICS", "TEACH"]),
    # WH questions
    ("Why are you late?",                  ["YOU", "LATE", "WHY"]),
    ("How are you?",                       ["YOU", "HOW"]),
    # Negation
    ("He does not speak English",          ["HE", "ENGLISH", "SPEAK", "NOT"]),
    ("I cannot hear",                      ["I", "HEAR", "NOT"]),
    # Future / time adverbs
    ("I will help you tomorrow",           ["I", "YOU", "HELP", "TOMORROW"]),
])
def test_additional_golden(text: str, expected: list[str]) -> None:
    assert gloss(text) == expected
