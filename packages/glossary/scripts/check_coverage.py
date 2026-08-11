#!/usr/bin/env python
"""Report how much of a text the ISL glossary can sign.

Standalone on purpose — it reads isl_glossary.json directly rather than
importing the API, so it runs without a database, Redis or a .env file.

    python check_coverage.py --input ncert_sample.txt
    python check_coverage.py --input ncert_sample.txt --top 40 --show-covered
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path

logger = logging.getLogger("check_coverage")

GLOSSARY_PATH = Path(__file__).resolve().parents[1] / "isl_glossary.json"

WORD_RE = re.compile(r"[A-Za-z0-9']+")

MIN_PREFIX_LEN = 4
MAX_SUFFIX_DELTA = 3
INFLECTIONAL_SUFFIXES = frozenset(
    {"s", "es", "ed", "d", "ing", "er", "ers", "est", "ly", "ies", "n", "en"}
)

NUMBER_WORDS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20,
}
WORD_FOR_NUMBER: dict[int, str] = {v: k for k, v in NUMBER_WORDS.items()}

# Function words carry no sign and are dropped by the gloss converter before
# mapping ever happens, so counting them as misses would understate coverage.
STOP_WORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "is", "am", "are", "was", "were", "be", "been",
        "being", "do", "does", "did", "has", "have", "had", "will", "would",
        "shall", "should", "can", "could", "may", "might", "must", "of", "to",
        "in", "on", "at", "by", "for", "with", "from", "into", "onto", "as",
        "and", "but", "or", "so", "that", "this", "these", "those", "than",
        "then", "there", "s", "t",
    }
)


def load_glossary(path: Path) -> tuple[dict[str, dict], dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = {str(k).lower(): v for k, v in data.items()}
    aliases: dict[str, str] = {}
    for word, entry in entries.items():
        for alias in entry.get("aliases") or []:
            key = str(alias).lower()
            if key not in entries and key not in aliases:
                aliases[key] = word
    return entries, aliases


def prefix_match(word: str, entries: dict[str, dict]) -> str | None:
    """Same conservative stem match the API's sign_mapper uses."""
    if len(word) < MIN_PREFIX_LEN:
        return None
    best: str | None = None
    best_delta = MAX_SUFFIX_DELTA + 1
    for candidate in entries:
        if candidate == word or " " in candidate:
            continue
        shorter, longer = sorted((candidate, word), key=len)
        if len(shorter) < MIN_PREFIX_LEN or not longer.startswith(shorter):
            continue
        if longer[len(shorter):] not in INFLECTIONAL_SUFFIXES:
            continue
        delta = len(longer) - len(shorter)
        if delta < best_delta or (delta == best_delta and best is not None and candidate < best):
            best, best_delta = candidate, delta
    return best


def resolve(word: str, entries: dict[str, dict], aliases: dict[str, str]) -> str | None:
    """The glossary word this token would play, or None if it is fingerspelled."""
    if word in entries:
        return word
    if word in aliases:
        return aliases[word]

    value = int(word) if word.isdigit() else NUMBER_WORDS.get(word)
    if value is not None:
        number_word = WORD_FOR_NUMBER.get(value)
        if number_word in entries:
            return number_word

    return prefix_match(word, entries)


def analyse(
    text: str, entries: dict[str, dict], aliases: dict[str, str], *, keep_stop_words: bool
) -> dict:
    tokens = [m.group(0).lower() for m in WORD_RE.finditer(text)]
    if not keep_stop_words:
        tokens = [t for t in tokens if t not in STOP_WORDS]

    covered = Counter()
    missing = Counter()
    for token in tokens:
        if resolve(token, entries, aliases) is not None:
            covered[token] += 1
        else:
            missing[token] += 1

    total = len(tokens)
    covered_count = sum(covered.values())
    return {
        "total_words": total,
        "unique_words": len(set(tokens)),
        "covered": covered_count,
        "missing": total - covered_count,
        "coverage_pct": round(covered_count / total * 100, 1) if total else 0.0,
        "covered_counter": covered,
        "missing_counter": missing,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="UTF-8 text file to score")
    parser.add_argument("--glossary", type=Path, default=GLOSSARY_PATH, help="Glossary JSON")
    parser.add_argument("--top", type=int, default=20, help="How many missing words to list")
    parser.add_argument(
        "--keep-stop-words",
        action="store_true",
        help="Count articles and auxiliaries too (the gloss converter drops them)",
    )
    parser.add_argument(
        "--show-covered", action="store_true", help="Also list the most frequent covered words"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv)

    try:
        text = args.input.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("Could not read %s: %s", args.input, exc)
        return 1

    try:
        entries, aliases = load_glossary(args.glossary)
    except (OSError, ValueError) as exc:
        logger.error("Could not load glossary %s: %s", args.glossary, exc)
        return 1

    report = analyse(text, entries, aliases, keep_stop_words=args.keep_stop_words)

    logger.info("Glossary : %s (%d words, %d aliases)", args.glossary, len(entries), len(aliases))
    logger.info("Input    : %s", args.input)
    logger.info("")
    logger.info("Words scored     : %d (%d unique)", report["total_words"], report["unique_words"])
    logger.info("Covered by sign  : %d", report["covered"])
    logger.info("Fingerspelled    : %d", report["missing"])
    logger.info("Coverage         : %.1f%%", report["coverage_pct"])

    missing = report["missing_counter"].most_common(args.top)
    if missing:
        logger.info("")
        logger.info("Top %d missing words:", len(missing))
        for rank, (word, count) in enumerate(missing, start=1):
            logger.info("  %2d. %-24s %d", rank, word, count)

    if args.show_covered:
        logger.info("")
        logger.info("Most frequent covered words:")
        for word, count in report["covered_counter"].most_common(args.top):
            logger.info("      %-24s %d", word, count)

    return 0


if __name__ == "__main__":
    sys.exit(main())
