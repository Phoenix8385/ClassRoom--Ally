#!/usr/bin/env python
"""Download the INCLUDE sign vocabulary from AI4Bharat's GitHub into data/include/.

    python services/api/evaluation/datasets/get_include.py
    python services/api/evaluation/datasets/get_include.py --force

INCLUDE is an isolated-sign recognition dataset: 4292 video clips covering 263
ISL signs, recorded by Deaf signers at St. Louis School for the Deaf. It is a
*vocabulary* resource, not a translation corpus — there are no sentences and no
gloss sequences, so it cannot score the gloss engine. What it gives us is 263
signer-validated ISL word labels with categories, which is directly comparable
against packages/glossary/isl_glossary.json for coverage.

The repo ships no `data/` directory. Two sources are combined here:

  label_maps/label_map_include.json   263 sign words → class index
  train_test_paths/include_*.txt      clip paths, "Category/N. word/MVI_x.MOV"

The category is only recoverable from that path prefix, so the path files are
fetched to attach one to each word. Matching between the two is done on a
punctuation-stripped key: the label map writes "goodmorning" where the paths
write "good morning", and "biglarge" for "big/large".
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
OUTPUT_DIR = REPO_ROOT / "data" / "include"

RAW_BASE = "https://raw.githubusercontent.com/AI4Bharat/INCLUDE/master/"
LABEL_MAP = "label_maps/label_map_include.json"
LABEL_MAP_50 = "label_maps/label_map_include50.json"
PATH_FILES = (
    "train_test_paths/include_train.txt",
    "train_test_paths/include_val.txt",
    "train_test_paths/include_test.txt",
)

EXPECTED_SIGNS = 263
TIMEOUT_SECONDS = 120

# "Adjectives/1. loud/MVI_9289.MOV" → the "1. " is an ordering prefix, not part
# of the word.
_ORDER_PREFIX = re.compile(r"^\s*\d+\.\s*")


def fetch(path: str) -> str:
    """GET one file from the repo's raw endpoint as text."""
    url = RAW_BASE + path
    print(f"  fetching {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "classroom-ally"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            f"\n{url}\n  HTTP {exc.code}. The repo layout may have changed —\n"
            "  check https://github.com/AI4Bharat/INCLUDE and update the\n"
            "  RAW_BASE / LABEL_MAP / PATH_FILES constants in this script.\n"
        ) from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"\nCould not reach GitHub: {exc.reason}\n") from exc


def match_key(word: str) -> str:
    """Punctuation-free lowercase key, so 'good morning' == 'goodmorning'."""
    return re.sub(r"[^a-z0-9]", "", word.lower())


def category_index(path_texts: list[str]) -> tuple[dict[str, str], Counter[str]]:
    """Build {match_key: category} and a per-category clip count from clip paths."""
    by_word: dict[str, str] = {}
    clips: Counter[str] = Counter()

    for text in path_texts:
        for line in text.splitlines():
            line = line.strip().replace("\\", "/")
            if not line:
                continue
            parts = line.split("/")
            if len(parts) < 2:
                continue
            category = parts[0].strip()
            word = _ORDER_PREFIX.sub("", parts[1]).strip()
            clips[category] += 1
            by_word.setdefault(match_key(word), category)

    return by_word, clips


def build_signs(
    label_map: dict[str, int],
    subset_50: dict[str, int],
    by_word: dict[str, str],
) -> list[dict[str, Any]]:
    """One record per sign: word, class index, category, include50 membership."""
    subset_keys = {match_key(w) for w in subset_50}
    signs: list[dict[str, Any]] = []

    for word, index in sorted(label_map.items(), key=lambda kv: kv[1]):
        key = match_key(word)
        signs.append(
            {
                "word": word,
                "class_index": index,
                "category": by_word.get(key, "unknown"),
                "in_include50": key in subset_keys,
            }
        )
    return signs


def write_json(path: Path, payload: Any, force: bool) -> None:
    if path.exists() and not force:
        print(f"  SKIPPED {path.name} — already exists. Pass --force to overwrite.")
        return
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the INCLUDE ISL vocabulary.")
    parser.add_argument(
        "--force", action="store_true", help="overwrite existing output files"
    )
    args = parser.parse_args()

    print("Downloading INCLUDE from AI4Bharat GitHub...")
    label_map = json.loads(fetch(LABEL_MAP))
    subset_50 = json.loads(fetch(LABEL_MAP_50))
    path_texts = [fetch(p) for p in PATH_FILES]

    by_word, clips = category_index(path_texts)
    signs = build_signs(label_map, subset_50, by_word)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_json(OUTPUT_DIR / "classes.json", [s["word"] for s in signs], args.force)
    write_json(OUTPUT_DIR / "signs.json", signs, args.force)

    unknown = [s["word"] for s in signs if s["category"] == "unknown"]

    print()
    print(f"Total ISL signs in INCLUDE: {len(signs)}")
    print(f"Total video clips:          {sum(clips.values())}")
    print(f"Categories ({len(clips)}):")
    for category, count in clips.most_common():
        words = sum(1 for s in signs if s["category"] == category)
        print(f"  {category:<26} {words:>4} signs   {count:>5} clips")

    if len(signs) != EXPECTED_SIGNS:
        print(f"\nNOTE: expected {EXPECTED_SIGNS} signs, got {len(signs)} — upstream changed.")
    if unknown:
        print(f"\nNOTE: {len(unknown)} sign(s) had no category in the path files: {unknown}")

    print()
    print("NOTE: INCLUDE is isolated-sign video, not sentences — there are no gloss")
    print("      sequences here, so it cannot score the gloss engine. Use it to")
    print("      measure vocabulary coverage against packages/glossary/.")


if __name__ == "__main__":
    main()
