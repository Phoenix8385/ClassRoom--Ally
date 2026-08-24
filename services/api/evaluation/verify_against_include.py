#!/usr/bin/env python
"""Validate our sign glossary against AI4Bharat's INCLUDE vocabulary.

    python services/api/evaluation/verify_against_include.py

INCLUDE is 263 ISL signs recorded by Deaf signers at St. Louis School for the
Deaf — human-validated, unlike our own clips, which `download_signs.py` scrapes
from YouTube search results and its own docstring flags as unverified guesses.

So the overlap is not just a coverage statistic: for every word in both sets we
have a signer-recorded reference against which our scraped clip can be checked.
That subset is the cheapest available quality win on the sign dictionary.

Matching ignores case, spaces and punctuation ("good morning" == "goodmorning"),
and our glossary's aliases count as matches.

Writes docs/clip-validation-report.md.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
INCLUDE_CLASSES = REPO_ROOT / "data" / "include" / "classes.json"
INCLUDE_SIGNS = REPO_ROOT / "data" / "include" / "signs.json"
GLOSSARY_PATH = REPO_ROOT / "packages" / "glossary" / "isl_glossary.json"
REPORT_PATH = REPO_ROOT / "docs" / "clip-validation-report.md"


def match_key(word: str) -> str:
    """Case/space/punctuation-free key so 'good morning' == 'goodmorning'."""
    return re.sub(r"[^a-z0-9]", "", str(word).lower())


def load_json(path: Path, hint: str) -> Any:
    if not path.is_file():
        raise SystemExit(f"\n{path} not found.\n  {hint}\n")
    return json.loads(path.read_text(encoding="utf-8"))


def build_include_index() -> dict[str, dict[str, Any]]:
    """{match_key: {word, category, in_include50}} for all 263 signs."""
    words = load_json(
        INCLUDE_CLASSES,
        "Fetch it: python services/api/evaluation/datasets/get_include.py",
    )
    # signs.json carries the categories; fall back to bare words without it.
    try:
        detail = {
            match_key(s["word"]): s
            for s in load_json(INCLUDE_SIGNS, "run get_include.py")
        }
    except SystemExit:
        detail = {}

    index: dict[str, dict[str, Any]] = {}
    for word in words:
        key = match_key(word)
        entry = detail.get(key, {})
        index[key] = {
            "word": word,
            "category": entry.get("category", "unknown"),
            "in_include50": entry.get("in_include50", False),
        }
    return index


def build_glossary_index() -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """Return ({match_key: canonical word}, {canonical word: entry}).

    Aliases map onto their canonical word, so a match through an alias counts
    as covering that word rather than appearing as a separate entry.
    """
    glossary = load_json(GLOSSARY_PATH, "Expected the 300-word ISL glossary here.")
    by_key: dict[str, str] = {}
    for word, entry in glossary.items():
        by_key.setdefault(match_key(word), word)
        for alias in entry.get("aliases") or []:
            by_key.setdefault(match_key(alias), word)
    return by_key, glossary


def group_by(rows: list[dict[str, Any]], field: str) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        grouped[row.get(field) or "unknown"].append(row["word"])
    return {k: sorted(v) for k, v in sorted(grouped.items(), key=lambda kv: -len(kv[1]))}


def analyse() -> dict[str, Any]:
    include = build_include_index()
    glossary_keys, glossary = build_glossary_index()

    overlap: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for key, meta in include.items():
        canonical = glossary_keys.get(key)
        if canonical is None:
            missing.append(meta)
            continue
        entry = glossary.get(canonical, {})
        overlap.append(
            {
                "word": meta["word"],
                "our_word": canonical,
                "include_category": meta["category"],
                "our_category": entry.get("category", "unknown"),
                "clip_downloaded": bool(entry.get("clip_downloaded")),
                "via_alias": match_key(canonical) != key,
            }
        )

    matched_canonical = {row["our_word"] for row in overlap}
    extra = [
        {"word": word, "category": entry.get("category", "unknown"),
         "clip_downloaded": bool(entry.get("clip_downloaded"))}
        for word, entry in glossary.items()
        if word not in matched_canonical
    ]

    return {
        "our_total": len(glossary),
        "include_total": len(include),
        "overlap": sorted(overlap, key=lambda r: r["word"]),
        "missing": sorted(missing, key=lambda r: r["word"]),
        "extra": sorted(extra, key=lambda r: r["word"]),
        "our_downloaded": sum(1 for e in glossary.values() if e.get("clip_downloaded")),
    }


def print_report(data: dict[str, Any]) -> None:
    bar = "=" * 52
    overlap, missing, extra = data["overlap"], data["missing"], data["extra"]
    pct = len(overlap) / data["include_total"] * 100 if data["include_total"] else 0.0
    verifiable = [r for r in overlap if r["clip_downloaded"]]

    print(f"\n{bar}\nSIGN DICTIONARY VALIDATION")
    print(f"Reference: INCLUDE (AI4Bharat, {data['include_total']} signs)\n{bar}")
    print(f"Our words:          {data['our_total']}")
    print(f"INCLUDE words:      {data['include_total']}")
    print(f"Overlap:            {len(overlap)} words ({pct:.1f}% of INCLUDE)")
    print(f"We are missing:     {len(missing)} words")
    print(f"Extra coverage:     {len(extra)} words")
    print(bar)

    print(f"\nOf the {len(overlap)} overlapping words, {len(verifiable)} have a clip")
    print("downloaded and can be checked against INCLUDE's signer-recorded video:")
    for row in verifiable[:20]:
        via = "  (via alias)" if row["via_alias"] else ""
        print(f"  {row['word']:<18} {row['include_category']}{via}")
    if len(verifiable) > 20:
        print(f"  ... and {len(verifiable) - 20} more")

    print("\nINCLUDE signs we lack, by category:")
    # `missing` rows come straight from the INCLUDE index, where the field is
    # "category"; only `overlap` rows carry the disambiguated "include_category".
    for category, words in group_by(missing, "category").items():
        print(f"  {category:<26} {len(words):>3}  {', '.join(words[:6])}"
              f"{'...' if len(words) > 6 else ''}")


def write_report(data: dict[str, Any]) -> None:
    overlap, missing, extra = data["overlap"], data["missing"], data["extra"]
    pct = len(overlap) / data["include_total"] * 100 if data["include_total"] else 0.0
    verifiable = [r for r in overlap if r["clip_downloaded"]]
    unverifiable = [r for r in overlap if not r["clip_downloaded"]]

    lines = [
        "# Sign Dictionary Validation — against INCLUDE",
        "",
        f"_Generated from `{INCLUDE_CLASSES.name}` and `{GLOSSARY_PATH.name}`_",
        "",
        "INCLUDE (AI4Bharat) is 263 ISL signs recorded by Deaf signers at St. Louis",
        "School for the Deaf. Our own clips are YouTube search results, which",
        "`download_signs.py` documents as unverified guesses — so every overlapping",
        "word is one we can check against a human-validated reference.",
        "",
        "## Summary",
        "",
        "| | Count |",
        "|---|---|",
        f"| Our glossary | {data['our_total']} words |",
        f"| INCLUDE | {data['include_total']} signs |",
        f"| **Overlap** | **{len(overlap)}** ({pct:.1f}% of INCLUDE) |",
        f"| In INCLUDE, missing from ours | {len(missing)} |",
        f"| In ours, not in INCLUDE | {len(extra)} |",
        f"| Our clips actually downloaded | {data['our_downloaded']} / {data['our_total']} |",
        "",
        "## Verifiable now",
        "",
        f"{len(verifiable)} overlapping words have a downloaded clip. These can be",
        "compared against INCLUDE video directly — the highest-value review queue.",
        "",
        "| Word | Our category | INCLUDE category | Matched via alias |",
        "|---|---|---|---|",
    ]
    for row in verifiable:
        lines.append(
            f"| `{row['word']}` | {row['our_category']} | {row['include_category']} |"
            f" {'yes' if row['via_alias'] else ''} |"
        )

    lines += [
        "",
        "## Overlapping but no clip yet",
        "",
        f"{len(unverifiable)} words appear in both sets but have no downloaded clip.",
        "INCLUDE has signer-recorded video for each, making them the best candidates",
        "to source next.",
        "",
        "| Word | INCLUDE category |",
        "|---|---|",
    ]
    for row in unverifiable:
        lines.append(f"| `{row['word']}` | {row['include_category']} |")

    lines += ["", "## In INCLUDE, missing from our glossary", ""]
    for category, words in group_by(missing, "category").items():
        lines.append(f"**{category}** ({len(words)}): {', '.join(f'`{w}`' for w in words)}")
        lines.append("")

    lines += [
        "## In our glossary, not in INCLUDE",
        "",
        f"{len(extra)} words — mostly classroom vocabulary, which INCLUDE does not",
        "cover. These have no external reference and rest entirely on our own clips.",
        "",
    ]
    for category, words in group_by(extra, "category").items():
        lines.append(f"**{category}** ({len(words)}): {', '.join(f'`{w}`' for w in words)}")
        lines.append("")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written to {REPORT_PATH}")


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    data = analyse()
    print_report(data)
    write_report(data)


if __name__ == "__main__":
    main()
