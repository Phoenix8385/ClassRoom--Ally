#!/usr/bin/env python
"""Download the ISLTranslate corpus from GitHub into data/isltranslate/.

    python services/api/evaluation/datasets/get_isltranslate.py
    python services/api/evaluation/datasets/get_isltranslate.py --force

IMPORTANT — this corpus cannot score the gloss engine.

ISLTranslate is an ISL-*video* ↔ English corpus: 30k signed video segments paired
with the English sentence they render. Its schema is `uid,text` — there is no
gloss column, and the signer-validation file's "Gold Translation" is natural
English prose, not gloss notation. So every row written here has an empty
`isl_gloss`, and `evaluate_gloss.py` will correctly report them all as
unscorable rather than inventing a number.

What it *is* good for: 31k real ISL-aligned English sentences to measure
glossary coverage against, and a source pool to hand a signer for gloss
annotation. See docs/ADR/ADR-001-hybrid-sign-architecture.md.

Upstream ships one flat file with no train/test split, so the split below is
ours: a deterministic hash of each uid, stable across runs and machines.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
OUTPUT_DIR = REPO_ROOT / "data" / "isltranslate"

RAW_BASE = "https://raw.githubusercontent.com/Exploration-Lab/ISLTranslate/main/data/"
MAIN_CSV = "ISLTranslate.csv"           # columns: uid, text
VALIDATION_CSV = "ISL-signer_validation.csv"  # uid, transcribed, gold English

# Share of rows routed to the test split, by uid hash.
TEST_SHARE = 10  # 1 in 10
TIMEOUT_SECONDS = 120


def fetch(name: str) -> str:
    """GET one file from the repo's raw endpoint as text."""
    url = RAW_BASE + name
    print(f"  fetching {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "classroom-ally"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            f"\n{url}\n  HTTP {exc.code}. The repo layout may have changed —\n"
            "  check https://github.com/Exploration-Lab/ISLTranslate for the current\n"
            "  file names and update RAW_BASE / MAIN_CSV in this script.\n"
        ) from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"\nCould not reach GitHub: {exc.reason}\n") from exc


def is_test_row(uid: str) -> bool:
    """Deterministic split — same uid lands in the same split on every machine."""
    digest = hashlib.md5(uid.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % TEST_SHARE == 0


def parse_main(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split the main corpus into (train, test) rows in our output format."""
    train: list[dict[str, Any]] = []
    test: list[dict[str, Any]] = []

    for row in csv.DictReader(io.StringIO(text)):
        sentence = (row.get("text") or "").strip()
        if not sentence:
            continue
        uid = (row.get("uid") or "").strip()
        # isl_gloss is empty by necessity: the source has no gloss column.
        entry = {"english": sentence, "isl_gloss": "", "uid": uid}
        (test if is_test_row(uid) else train).append(entry)

    return train, test


def parse_validation(text: str) -> list[dict[str, Any]]:
    """The 291 signer-checked rows, keeping the signer's English as reference."""
    rows: list[dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(text)):
        # Column headers are long sentences in the source file; match by prefix
        # so a wording tweak upstream does not silently produce empty rows.
        gold = next((v for k, v in row.items() if k and k.startswith("Gold")), "")
        transcribed = next(
            (v for k, v in row.items() if k and k.startswith("Transcribed")), ""
        )
        sentence = (transcribed or "").strip()
        if not sentence:
            continue
        rows.append(
            {
                "english": sentence,
                "isl_gloss": "",
                "signer_english": (gold or "").strip(),
                "uid": (row.get("uid") or "").strip(),
            }
        )
    return rows


def write_json(path: Path, rows: list[dict[str, Any]], force: bool) -> bool:
    """Write rows to path. Refuses to clobber an existing file unless forced."""
    if path.exists() and not force:
        print(
            f"  SKIPPED {path.name} — already exists.\n"
            f"          {path} may be your hand-written regression corpus.\n"
            "          Move it aside, or pass --force to overwrite."
        )
        return False
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote {len(rows):>6} rows to {path}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the ISLTranslate corpus.")
    parser.add_argument(
        "--force", action="store_true", help="overwrite existing JSON files"
    )
    args = parser.parse_args()

    print("Downloading ISLTranslate from GitHub...")
    main_text = fetch(MAIN_CSV)
    validation_text = fetch(VALIDATION_CSV)

    train, test = parse_main(main_text)
    validation = parse_validation(validation_text)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_json(OUTPUT_DIR / "train.json", train, args.force)
    write_json(OUTPUT_DIR / "test.json", test, args.force)
    write_json(OUTPUT_DIR / "signer_validation.json", validation, args.force)

    print()
    print(f"Train: {len(train)} sentences")
    print(f"Test:  {len(test)} sentences")
    print(f"Signer-validated: {len(validation)} sentences")
    print()
    print("NOTE: isl_gloss is empty on every row — ISLTranslate pairs ISL *video*")
    print("      with English, and ships no gloss annotations. Scoring the gloss")
    print("      engine against this file will report 100% unscorable, which is")
    print("      the honest result. Use it for glossary-coverage checks, or as a")
    print("      source pool for signer annotation.")


if __name__ == "__main__":
    main()
