#!/usr/bin/env python
"""Download the ISLTranslate dataset from HuggingFace into data/isltranslate/.

Writes one JSON file per split, each a list of {"english", "isl_gloss"} rows,
for use as an evaluation set against the gloss engine.

    python services/api/evaluation/download_isltranslate.py
"""
from __future__ import annotations

import json
from pathlib import Path

from datasets import load_dataset

# Anchor the output at the repo root so the destination does not depend on the
# directory the script happens to be run from.
REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = REPO_ROOT / "data" / "isltranslate"


def download() -> None:
    print("Downloading ISLTranslate from HuggingFace...")
    ds = load_dataset("Exploration-Lab/ISLTranslate")

    output_dir = OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    for split in ds.keys():
        rows = []
        for item in ds[split]:
            rows.append({
                "english": item.get("english") or item.get("sentence") or "",
                "isl_gloss": item.get("isl") or item.get("gloss") or "",
            })

        out_file = output_dir / f"{split}.json"
        # encoding is explicit: Windows would otherwise write cp1252 and choke
        # on any non-ASCII character in the corpus.
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
        print(f"Saved {len(rows)} rows to {out_file}")

    print("Download complete!")


if __name__ == "__main__":
    download()
