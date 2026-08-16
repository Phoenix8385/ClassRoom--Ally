#!/usr/bin/env python
"""Evaluate GlossService against an ISL gloss reference corpus.

Loads `data/isltranslate/test.json` (a list of {"english", "isl_gloss"} rows),
runs the first N sentences through the real `GlossService.convert`, and scores
the output against the reference gloss.

    python services/api/evaluation/evaluate_gloss.py
    python services/api/evaluation/evaluate_gloss.py --limit 500
    python services/api/evaluation/evaluate_gloss.py --data path/to/other.json
    python services/api/evaluation/evaluate_gloss.py --no-llm

Writes a Markdown report to docs/evaluation-report.md and prints a summary.

Scoring is on normalised token lists: both sides are uppercased and stripped of
punctuation, so "I WATER WANT" and "i water want." compare equal.

  exact_match     — share of sentences whose token list matches the reference
  token_accuracy  — mean per-sentence multiset overlap / reference length
  precision       — mean overlap / our length (are the tokens we emit correct?)

Token accuracy alone flatters a verbose system: emitting every word of the
sentence scores high overlap. Read it next to precision.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ── Paths ─────────────────────────────────────────────────────────────────────

EVAL_DIR = Path(__file__).resolve().parent
API_DIR = EVAL_DIR.parent
REPO_ROOT = API_DIR.parent.parent

DEFAULT_DATA_PATH = REPO_ROOT / "data" / "isltranslate" / "test.json"
REPORT_PATH = REPO_ROOT / "docs" / "evaluation-report.md"

DEFAULT_LIMIT = 200
TOP_MISTAKES = 10
WORST_EXAMPLES = 15

# Required by app.core.config.Settings; only used to let the import succeed when
# the evaluation runs outside a configured deployment.
_PLACEHOLDER_SETTINGS: dict[str, str] = {
    "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/db",
    "REDIS_URL": "redis://localhost:6379",
    "OPENAI_API_KEY": "sk-not-set",
    "SECRET_KEY": "evaluation-only",
}


def _bootstrap_app_imports() -> None:
    """Make `app.*` importable and satisfy Settings' required fields.

    `Settings` reads `.env` relative to the *current working directory*, so an
    evaluation run from anywhere but services/api would fail at import time on
    missing required fields. Real values from a .env file are loaded first and
    win; placeholders only fill what is still absent.
    """
    if str(API_DIR) not in sys.path:
        sys.path.insert(0, str(API_DIR))

    for env_path in (API_DIR / ".env", REPO_ROOT / ".env"):
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

    for key, value in _PLACEHOLDER_SETTINGS.items():
        os.environ.setdefault(key, value)


_bootstrap_app_imports()

from app.services import gloss as gloss_module  # noqa: E402
from app.services.gloss import GlossService  # noqa: E402

# ── Normalisation ─────────────────────────────────────────────────────────────

_WORD_RE = re.compile(r"[A-Za-z0-9']+")


def normalise(value: Any) -> list[str]:
    """Uppercase word tokens, punctuation dropped. Accepts a string or a list."""
    if isinstance(value, list):
        value = " ".join(str(v) for v in value)
    if not isinstance(value, str):
        return []
    return [m.group(0).upper() for m in _WORD_RE.finditer(value)]


def overlap(ours: list[str], expected: list[str]) -> int:
    """Multiset intersection size — counts repeats correctly."""
    return sum((Counter(ours) & Counter(expected)).values())


# ── Data loading ──────────────────────────────────────────────────────────────

def ensure_dataset(data_path: Path) -> None:
    """Download the corpus if `data_path` is absent.

    Delegates to download_isltranslate.py, which pulls from HuggingFace. The
    failure here is worth reading carefully: the Hub repo may not exist or may
    be gated, and neither produces an obvious error on its own.
    """
    if data_path.is_file():
        return

    print(f"{data_path} not found — attempting download from HuggingFace...")
    try:
        from download_isltranslate import download
    except ImportError:
        sys.path.insert(0, str(EVAL_DIR))
        from download_isltranslate import download

    try:
        download()
    except Exception as exc:
        raise SystemExit(
            f"\nCould not download the dataset: {type(exc).__name__}: {exc}\n\n"
            "Check, in order:\n"
            "  1. Does the Hub repo exist? Verify the name at huggingface.co/datasets.\n"
            "  2. Is it gated? Gated repos need access granted on the dataset page\n"
            "     plus `huggingface-cli login` with a token.\n"
            "  3. Already have the data locally? Skip the download entirely:\n"
            "     --data path/to/your.json  (list of {\"english\", \"isl_gloss\"} rows)\n"
        ) from exc

    if not data_path.is_file():
        available = sorted(p.name for p in data_path.parent.glob("*.json")) if data_path.parent.is_dir() else []
        raise SystemExit(
            f"\nDownload finished but {data_path.name} was not produced.\n"
            f"Files in {data_path.parent}: {available or 'none'}\n"
            "Point --data at the split you want to score."
        )


def load_rows(data_path: Path, limit: int) -> list[dict[str, Any]]:
    """First `limit` rows that have a non-empty English sentence."""
    with open(data_path, encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, list):
        raise SystemExit(f"Expected a JSON list in {data_path}, got {type(raw).__name__}.")

    rows = [r for r in raw if isinstance(r, dict) and str(r.get("english", "")).strip()]
    skipped = len(raw) - len(rows)
    if skipped:
        print(f"Skipped {skipped} row(s) with no English text.")
    if not rows:
        raise SystemExit(
            f"No usable rows in {data_path}. Every row had an empty 'english' field —\n"
            "the download step's column mapping is probably wrong. Inspect the raw\n"
            "dataset's column names and adjust download_isltranslate.py."
        )
    return rows[:limit]


# ── Evaluation ────────────────────────────────────────────────────────────────

@dataclass
class Result:
    english: str
    expected: list[str]
    ours: list[str]
    exact: bool
    token_accuracy: float
    precision: float
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)


def score_one(english: str, expected: list[str], ours: list[str]) -> Result:
    hits = overlap(ours, expected)
    expected_counts = Counter(expected)
    ours_counts = Counter(ours)
    return Result(
        english=english,
        expected=expected,
        ours=ours,
        exact=ours == expected,
        token_accuracy=hits / len(expected) if expected else 0.0,
        precision=hits / len(ours) if ours else 0.0,
        missing=sorted((expected_counts - ours_counts).elements()),
        extra=sorted((ours_counts - expected_counts).elements()),
    )


async def evaluate(rows: list[dict[str, Any]]) -> list[Result]:
    """Run every row through GlossService, in order."""
    service = GlossService()
    results: list[Result] = []

    for i, row in enumerate(rows, start=1):
        english = str(row.get("english", "")).strip()
        expected = normalise(row.get("isl_gloss", ""))
        try:
            ours = normalise(await service.convert(english))
        except Exception as exc:
            print(f"  [{i}] convert() failed on {english!r}: {type(exc).__name__}: {exc}")
            ours = []
        results.append(score_one(english, expected, ours))

        if i % 25 == 0 or i == len(rows):
            print(f"  ...{i}/{len(rows)}")

    return results


def collect_mistakes(results: list[Result]) -> list[tuple[str, str, int]]:
    """Top token-level errors as (kind, token, count), most frequent first."""
    counter: Counter[tuple[str, str]] = Counter()
    for r in results:
        if not r.expected:
            continue
        counter.update(("MISSING", t) for t in r.missing)
        counter.update(("EXTRA", t) for t in r.extra)
    return [(kind, token, n) for (kind, token), n in counter.most_common(TOP_MISTAKES)]


# ── Reporting ─────────────────────────────────────────────────────────────────

def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarise(results: list[Result]) -> dict[str, Any]:
    scorable = [r for r in results if r.expected]
    return {
        "total": len(results),
        "scorable": len(scorable),
        "unscorable": len(results) - len(scorable),
        "exact_match": (
            sum(1 for r in scorable if r.exact) / len(scorable) * 100 if scorable else 0.0
        ),
        "token_accuracy": _mean([r.token_accuracy for r in scorable]) * 100,
        "precision": _mean([r.precision for r in scorable]) * 100,
        "avg_expected_len": _mean([float(len(r.expected)) for r in scorable]),
        "avg_our_len": _mean([float(len(r.ours)) for r in scorable]),
    }


def print_summary(stats: dict[str, Any], mistakes: list[tuple[str, str, int]]) -> None:
    print("\n" + "=" * 52)
    print("GLOSS EVALUATION SUMMARY")
    print("=" * 52)
    print(f"Total tested:    {stats['total']}")
    print(f"Exact match:     {stats['exact_match']:.1f}%")
    print(f"Token accuracy:  {stats['token_accuracy']:.1f}%")
    print(f"Precision:       {stats['precision']:.1f}%")
    print(f"Avg length:      ours {stats['avg_our_len']:.1f} vs reference {stats['avg_expected_len']:.1f}")
    if stats["unscorable"]:
        print(f"Unscorable:      {stats['unscorable']} row(s) had no reference gloss")
    print("\nTop mistakes:")
    if mistakes:
        for kind, token, n in mistakes:
            label = "we omit" if kind == "MISSING" else "we add "
            print(f"  {label}  {token:<18} {n}x")
    else:
        print("  (none)")
    print("=" * 52)


def write_report(
    stats: dict[str, Any],
    mistakes: list[tuple[str, str, int]],
    results: list[Result],
    data_path: Path,
    llm_enabled: bool,
) -> None:
    scorable = [r for r in results if r.expected]
    worst = sorted(scorable, key=lambda r: (r.token_accuracy, r.precision))[:WORST_EXAMPLES]

    lines = [
        "# Gloss Engine Evaluation Report",
        "",
        f"_Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        f"- **Corpus:** `{data_path}`",
        f"- **Sentences tested:** {stats['total']}",
        f"- **LLM fallback:** {'enabled' if llm_enabled else 'disabled (spaCy rules only)'}",
        "",
        "## Scores",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Exact match | {stats['exact_match']:.1f}% |",
        f"| Token accuracy (recall) | {stats['token_accuracy']:.1f}% |",
        f"| Token precision | {stats['precision']:.1f}% |",
        f"| Avg tokens — ours | {stats['avg_our_len']:.1f} |",
        f"| Avg tokens — reference | {stats['avg_expected_len']:.1f} |",
        f"| Rows without a reference gloss | {stats['unscorable']} |",
        "",
        "Token accuracy is multiset overlap against the reference, so a system that",
        "emits extra tokens is not penalised by it — read it alongside precision.",
        "",
        "## Top mistakes",
        "",
        "| Kind | Token | Count |",
        "|---|---|---|",
    ]
    if mistakes:
        for kind, token, n in mistakes:
            kind_label = "Omitted by us" if kind == "MISSING" else "Added by us"
            lines.append(f"| {kind_label} | `{token}` | {n} |")
    else:
        lines.append("| — | — | 0 |")

    lines += ["", "## Worst-scoring examples", ""]
    if worst:
        lines += ["| English | Reference | Ours |", "|---|---|---|"]
        for r in worst:
            english = r.english.replace("|", "\\|")
            lines.append(
                f"| {english} | `{' '.join(r.expected)}` | `{' '.join(r.ours) or '(empty)'}` |"
            )
    else:
        lines.append("_No scorable rows._")
    lines.append("")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written to {REPORT_PATH}")


# ── Entry point ───────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH, help="corpus JSON path")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="sentences to score")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="never fall back to the OpenAI model; score the spaCy rules alone",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="show gloss-engine warnings (Redis misses, LLM fallbacks)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.verbose:
        # convert() logs a warning with a full traceback every time the Redis
        # cache is unreachable, which in an offline evaluation is once per
        # sentence per lookup. Errors still surface.
        logging.getLogger("app.services.gloss").setLevel(logging.ERROR)

    if args.no_llm:
        # convert() consults the LLM only when the rules yield fewer than
        # _MIN_TOKENS tokens; a threshold of 0 means that never happens.
        gloss_module._MIN_TOKENS = 0
        print("LLM fallback disabled — scoring the spaCy rule engine alone.")

    ensure_dataset(args.data)
    rows = load_rows(args.data, args.limit)
    print(f"Scoring {len(rows)} sentence(s) from {args.data}...")

    results = asyncio.run(evaluate(rows))
    stats = summarise(results)
    mistakes = collect_mistakes(results)

    print_summary(stats, mistakes)
    write_report(stats, mistakes, results, args.data, llm_enabled=not args.no_llm)


if __name__ == "__main__":
    main()
