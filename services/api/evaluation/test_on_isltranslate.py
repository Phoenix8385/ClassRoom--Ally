#!/usr/bin/env python
"""Run the gloss engine over real ISLTranslate sentences.

    python services/api/evaluation/test_on_isltranslate.py
    python services/api/evaluation/test_on_isltranslate.py --limit 500 --seed 7
    python services/api/evaluation/test_on_isltranslate.py --data <file.json>

ISLTranslate ships **no gloss annotations** — it pairs ISL *video* with English
(schema `uid,text`; see evaluation/datasets/get_isltranslate.py). There is
therefore no reference gloss to compare against, and no exact-match or token
accuracy can be computed from it. This script will not print one: a number
computed against absent references would be zero by construction and would read
as "the engine scores 0% on the real benchmark", which is not what it means.

What it does instead, on the same real sentences:

  * scores accuracy for any rows that DO carry a reference gloss (so pointing
    --data at a signer-annotated file gives the full accuracy report), and
  * reports the reference-free measures that are meaningful without one —
    glossary coverage, fingerspelling load, compression, degradation rate.

Glossary coverage is the number ADR-001 actually rests on: it claims Tier 1
"handles the majority of classroom content" and currently has no measurement
behind it. That claim is testable against this corpus; exact match is not.

Writes docs/real-evaluation-report.md.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent
API_DIR = EVAL_DIR.parent
REPO_ROOT = API_DIR.parent.parent

# train.json holds the real ISLTranslate rows; test.json in that directory is
# the hand-written regression corpus and is not ISLTranslate.
DEFAULT_DATA_PATH = REPO_ROOT / "data" / "isltranslate" / "train.json"
REPORT_PATH = REPO_ROOT / "docs" / "real-evaluation-report.md"

DEFAULT_LIMIT = 500
DEFAULT_SEED = 20260816
TOP_MISTAKES = 10

_PLACEHOLDER_SETTINGS = {
    "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/db",
    "REDIS_URL": "redis://localhost:6379",
    "OPENAI_API_KEY": "sk-not-set",
    "SECRET_KEY": "evaluation-only",
}


def _bootstrap_app_imports() -> None:
    """Put `app.*` on the path and satisfy Settings' required fields."""
    if str(API_DIR) not in sys.path:
        sys.path.insert(0, str(API_DIR))
    for env_path in (API_DIR / ".env", REPO_ROOT / ".env"):
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())
    for key, value in _PLACEHOLDER_SETTINGS.items():
        os.environ.setdefault(key, value)


_bootstrap_app_imports()

from app.services import sign_mapper  # noqa: E402
from app.services.gloss import GlossService, rules_available  # noqa: E402

_WORD_RE = re.compile(r"[A-Za-z0-9']+")


def normalise(value: Any) -> list[str]:
    if isinstance(value, list):
        value = " ".join(str(v) for v in value)
    if not isinstance(value, str):
        return []
    return [m.group(0).upper() for m in _WORD_RE.finditer(value)]


@dataclass
class Row:
    english: str
    expected: list[str]
    ours: list[str]


def load_rows(path: Path, limit: int, seed: int) -> list[dict[str, Any]]:
    if not path.is_file():
        raise SystemExit(
            f"\n{path} not found.\n"
            "  Fetch the corpus first:\n"
            "    python services/api/evaluation/datasets/get_isltranslate.py\n"
        )
    raw = json.load(open(path, encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit(f"Expected a JSON list in {path}.")

    usable = [r for r in raw if isinstance(r, dict) and str(r.get("english", "")).strip()]
    if not usable:
        raise SystemExit(f"No rows with English text in {path}.")

    rng = random.Random(seed)
    return rng.sample(usable, min(limit, len(usable)))


async def run_engine(rows: list[dict[str, Any]]) -> list[Row]:
    service = GlossService()
    out: list[Row] = []
    for i, row in enumerate(rows, start=1):
        english = str(row["english"]).strip()
        try:
            ours = normalise(await service.convert(english))
        except Exception as exc:
            print(f"  [{i}] convert() failed: {type(exc).__name__}: {exc}")
            ours = []
        out.append(Row(english, normalise(row.get("isl_gloss", "")), ours))
        if i % 100 == 0 or i == len(rows):
            print(f"  ...{i}/{len(rows)}")
    return out


def score_accuracy(rows: list[Row]) -> dict[str, Any] | None:
    """Accuracy over rows that carry a reference gloss, or None if none do."""
    scorable = [r for r in rows if r.expected]
    if not scorable:
        return None

    exact = sum(1 for r in scorable if r.ours == r.expected)
    accs, mistakes = [], Counter()
    for r in scorable:
        ours, expected = Counter(r.ours), Counter(r.expected)
        hits = sum((ours & expected).values())
        accs.append(hits / len(r.expected))
        mistakes.update(("MISSING", t) for t in (expected - ours).elements())
        mistakes.update(("EXTRA", t) for t in (ours - expected).elements())

    return {
        "scorable": len(scorable),
        "exact_match": exact / len(scorable) * 100,
        "token_accuracy": sum(accs) / len(accs) * 100,
        "mistakes": [(k, t, n) for (k, t), n in mistakes.most_common(TOP_MISTAKES)],
    }


def score_coverage(rows: list[Row]) -> dict[str, Any]:
    """Glossary coverage and shape statistics — computable without references."""
    tokens = [t for r in rows for t in r.ours]
    cov = sign_mapper.coverage(tokens) if tokens else {"coverage_pct": 0.0}

    english_words = sum(len(_WORD_RE.findall(r.english)) for r in rows)
    empty = sum(1 for r in rows if not r.ours)

    per_sentence = []
    for r in rows:
        if r.ours:
            hit = sign_mapper.coverage(r.ours)["covered_by_clip"]
            per_sentence.append(hit / len(r.ours))

    fully_covered = sum(1 for p in per_sentence if p == 1.0)

    return {
        "sentences": len(rows),
        "gloss_tokens": len(tokens),
        "english_words": english_words,
        "compression": len(tokens) / english_words if english_words else 0.0,
        "clip_covered": cov.get("covered_by_clip", 0),
        "fingerspelled": cov.get("covered_by_fingerspell", 0),
        "coverage_pct": cov.get("coverage_pct", 0.0),
        "fully_covered_sentences": fully_covered,
        "fully_covered_pct": fully_covered / len(rows) * 100 if rows else 0.0,
        "empty_outputs": empty,
        "top_oov": Counter(cov.get("unknown_words", [])).most_common(TOP_MISTAKES),
    }


def describe_corpus(data_path: Path) -> str:
    """Name the corpus honestly — only ISLTranslate's own files claim its name."""
    try:
        relative = data_path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        relative = data_path
    if data_path.resolve() == DEFAULT_DATA_PATH.resolve():
        return "ISLTranslate (IIT Kanpur)"
    return str(relative)


def print_report(
    accuracy: dict[str, Any] | None, cov: dict[str, Any], data_path: Path
) -> None:
    bar = "=" * 52
    print(f"\n{bar}\nREAL DATASET EVALUATION\nDataset: {describe_corpus(data_path)}\n{bar}")
    print(f"Total tested:    {cov['sentences']}")

    if accuracy:
        print(f"Exact match:     {accuracy['exact_match']:.1f}%")
        print(f"Token accuracy:  {accuracy['token_accuracy']:.1f}%")
        print(f"  (over {accuracy['scorable']} rows carrying a reference gloss)")
        print("Top 10 mistakes:")
        for kind, token, n in accuracy["mistakes"]:
            label = "we omit" if kind == "MISSING" else "we add "
            print(f"  {label}  {token:<18} {n}x")
    else:
        print("Exact match:     NOT MEASURABLE")
        print("Token accuracy:  NOT MEASURABLE")
        print("Top 10 mistakes: NOT MEASURABLE")
        print()
        print("  ISLTranslate carries no reference gloss — it pairs ISL video with")
        print("  English. With nothing to compare against, an accuracy figure here")
        print("  would be 0% by construction and would misread as an engine result.")

    print(f"\n{'-' * 52}\nMEASURABLE WITHOUT REFERENCES\n{'-' * 52}")
    print(f"Gloss tokens produced:      {cov['gloss_tokens']}")
    print(f"Compression:                {cov['compression']:.2f} tokens per English word")
    print(f"Glossary coverage (Tier 1): {cov['coverage_pct']:.1f}% of tokens have a sign clip")
    print(f"Fingerspelled (Tier 3):     {cov['fingerspelled']} tokens")
    print(f"Fully-covered sentences:    {cov['fully_covered_pct']:.1f}% need no fingerspelling")
    if cov["empty_outputs"]:
        print(f"Empty outputs:              {cov['empty_outputs']}")
    print("\nMost frequent out-of-vocabulary tokens:")
    for token, n in cov["top_oov"]:
        print(f"  {token:<20} {n}x")
    print(bar)


def write_report(
    accuracy: dict[str, Any] | None,
    cov: dict[str, Any],
    data_path: Path,
    healthy: bool,
) -> None:
    lines = [
        f"# Real-Dataset Evaluation — {describe_corpus(data_path)}",
        "",
        f"_Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        f"- **Corpus:** `{data_path}`",
        f"- **Sentences tested:** {cov['sentences']}",
        f"- **Grammar rules:** {'active' if healthy else 'UNAVAILABLE (degraded run)'}",
        "",
    ]

    if accuracy is None:
        lines += [
            "## Accuracy: not measurable on this corpus",
            "",
            "ISLTranslate pairs ISL **video** with English sentences (schema `uid,text`).",
            "It ships no gloss annotations, so there is no reference to score against.",
            "Exact match and token accuracy are therefore **not reported** — computing",
            "them here would yield 0% by construction and would be misread as an engine",
            "result rather than an absent reference.",
            "",
            "To get an accuracy number, a signer-annotated gloss corpus is required.",
            "",
        ]
    else:
        lines += [
            "## Accuracy",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Rows with a reference gloss | {accuracy['scorable']} |",
            f"| Exact match | {accuracy['exact_match']:.1f}% |",
            f"| Token accuracy | {accuracy['token_accuracy']:.1f}% |",
            "",
            "### Top mistakes",
            "",
            "| Kind | Token | Count |",
            "|---|---|---|",
        ]
        for kind, token, n in accuracy["mistakes"]:
            label = "Omitted by us" if kind == "MISSING" else "Added by us"
            lines.append(f"| {label} | `{token}` | {n} |")
        lines.append("")

    lines += [
        "## Measured on the real corpus",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Gloss tokens produced | {cov['gloss_tokens']} |",
        f"| Compression | {cov['compression']:.2f} tokens per English word |",
        f"| **Glossary coverage (Tier 1)** | **{cov['coverage_pct']:.1f}%** of tokens have a sign clip |",
        f"| Fingerspelled (Tier 3) | {cov['fingerspelled']} tokens |",
        f"| Sentences needing no fingerspelling | {cov['fully_covered_pct']:.1f}% |",
        f"| Empty outputs | {cov['empty_outputs']} |",
        "",
        "Glossary coverage is the figure ADR-001 depends on when it claims Tier 1",
        "\"handles the majority of classroom content\". Note that ISLTranslate is",
        "general-domain (storybook and lesson prose), so this is a lower bound for",
        "classroom vocabulary specifically.",
        "",
        "## Most frequent out-of-vocabulary tokens",
        "",
        "These fall through to fingerspelling and are the highest-value additions",
        "to the glossary.",
        "",
        "| Token | Occurrences |",
        "|---|---|",
    ]
    for token, n in cov["top_oov"]:
        lines.append(f"| `{token}` | {n} |")
    lines.append("")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written to {REPORT_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the gloss engine on ISLTranslate.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="sampling seed")
    parser.add_argument("--no-llm", action="store_true", help="score the spaCy rules alone")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not args.verbose:
        logging.getLogger("app.services.gloss").setLevel(logging.ERROR)

    healthy = rules_available()
    if not healthy:
        raise SystemExit(
            f"\n  spaCy model 'en_core_web_sm' is not loadable in {sys.executable}.\n"
            "  Every gloss would degrade to English word order, making these\n"
            "  measurements meaningless.\n\n"
            f"  Fix:  {sys.executable} -m pip install \\\n"
            "          https://github.com/explosion/spacy-models/releases/download/"
            "en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl\n"
        )

    if args.no_llm:
        from app.services import gloss as gloss_module

        gloss_module._MIN_TOKENS = 0

    rows_raw = load_rows(args.data, args.limit, args.seed)
    print(f"Sampling {len(rows_raw)} sentence(s) from {args.data} (seed {args.seed})...")

    rows = asyncio.run(run_engine(rows_raw))
    accuracy = score_accuracy(rows)
    cov = score_coverage(rows)

    print_report(accuracy, cov, args.data)
    write_report(accuracy, cov, args.data, healthy)


if __name__ == "__main__":
    main()
