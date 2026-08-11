#!/usr/bin/env python
"""Publish downloaded clips to the web app.

Copies data/isl_clips/*.mp4 into apps/web/public/signs/ (only what changed) and
writes two files the frontend can fetch: index.json for a quick "what do we
have" view, and manifest.json for per-word playback details.

    python sync_clips.py
    python sync_clips.py --force
    python sync_clips.py --clean
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("sync_clips")

SCRIPT_DIR = Path(__file__).resolve().parent
GLOSSARY_DIR = SCRIPT_DIR.parent
REPO_ROOT = GLOSSARY_DIR.parent.parent

GLOSSARY_PATH = GLOSSARY_DIR / "isl_glossary.json"
SOURCE_DIR = REPO_ROOT / "data" / "isl_clips"
PUBLIC_DIR = REPO_ROOT / "apps" / "web" / "public" / "signs"
INDEX_PATH = PUBLIC_DIR / "index.json"
MANIFEST_PATH = PUBLIC_DIR / "manifest.json"

DEFAULT_DURATION_MS = 4000  # what download_signs.py trims to
FFPROBE_TIMEOUT_SECONDS = 30


@dataclass
class SyncedClip:
    word: str
    filename: str
    size_bytes: int
    duration_ms: int
    category: str


def load_glossary() -> dict[str, dict]:
    try:
        data = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("No glossary at %s — categories will be reported as unknown", GLOSSARY_PATH)
        return {}
    except ValueError as exc:
        logger.warning("Glossary is not valid JSON (%s) — continuing without it", exc)
        return {}
    return {str(key).lower(): value for key, value in data.items()}


def word_for_filename(stem: str, by_slug: dict[str, str]) -> str:
    """Map a file stem back to its glossary word ("good_morning" → "good morning")."""
    return by_slug.get(stem, stem.replace("_", " "))


def probe_duration_ms(path: Path, ffprobe: str | None) -> int:
    if ffprobe is None:
        return DEFAULT_DURATION_MS
    command = [
        ffprobe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=FFPROBE_TIMEOUT_SECONDS, check=False
        )
        if completed.returncode != 0:
            return DEFAULT_DURATION_MS
        return int(float(completed.stdout.decode("utf-8", "replace").strip()) * 1000)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return DEFAULT_DURATION_MS


def needs_copy(source: Path, destination: Path, force: bool) -> bool:
    if force or not destination.exists():
        return True
    try:
        src_stat, dst_stat = source.stat(), destination.stat()
    except OSError:
        return True
    # Size differences catch a re-download that happens to keep the mtime.
    return src_stat.st_mtime > dst_stat.st_mtime or src_stat.st_size != dst_stat.st_size


def clean_stale(source_names: set[str]) -> list[str]:
    """Delete clips in public/signs that no longer exist in data/isl_clips."""
    removed: list[str] = []
    for path in PUBLIC_DIR.glob("*.mp4"):
        if path.name not in source_names:
            try:
                path.unlink()
                removed.append(path.name)
            except OSError as exc:
                logger.error("Could not remove %s: %s", path.name, exc)
    return removed


def write_index(clips: list[SyncedClip], glossary_size: int) -> None:
    categories: dict[str, list[str]] = {}
    for clip in clips:
        categories.setdefault(clip.category, []).append(clip.word)

    payload = {
        "total": len(clips),
        "words": sorted(clip.word for clip in clips),
        "categories": {key: sorted(value) for key, value in sorted(categories.items())},
        "last_updated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "coverage_pct": round(len(clips) / glossary_size * 100, 1) if glossary_size else 0.0,
    }
    INDEX_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_manifest(clips: list[SyncedClip]) -> None:
    payload = {
        clip.word: {
            "path": f"/signs/{clip.filename}",
            "size_bytes": clip.size_bytes,
            "duration_ms": clip.duration_ms,
            "category": clip.category,
        }
        for clip in sorted(clips, key=lambda c: c.word)
    }
    MANIFEST_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-copy every clip")
    parser.add_argument("--clean", action="store_true",
                        help="delete clips in public/signs that are no longer in data/isl_clips")
    return parser.parse_args(argv)


def _use_utf8_console() -> None:
    """A Windows console defaults to cp1252 and mangles non-ASCII output."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - console dependent
            pass


def main(argv: list[str] | None = None) -> int:
    _use_utf8_console()
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    args = parse_args(argv)

    if not SOURCE_DIR.is_dir():
        logger.error("No clips at %s — run download_signs.py first", SOURCE_DIR)
        return 1

    try:
        PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error("Could not create %s: %s", PUBLIC_DIR, exc)
        return 1

    glossary = load_glossary()
    by_slug = {word.replace(" ", "_"): word for word in glossary}
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        logger.warning(
            "ffprobe not found — manifest durations default to %dms", DEFAULT_DURATION_MS
        )

    sources = sorted(p for p in SOURCE_DIR.glob("*.mp4") if p.is_file())
    if not sources:
        logger.info("No clips in %s yet.", SOURCE_DIR)

    copied = 0
    skipped = 0
    clips: list[SyncedClip] = []

    for source in sources:
        destination = PUBLIC_DIR / source.name
        try:
            if needs_copy(source, destination, args.force):
                shutil.copy2(source, destination)
                copied += 1
                logger.debug("copied %s", source.name)
            else:
                skipped += 1
        except OSError as exc:
            logger.error("Could not copy %s: %s", source.name, exc)
            continue

        word = word_for_filename(source.stem, by_slug)
        entry = glossary.get(word.lower(), {})
        clips.append(
            SyncedClip(
                word=word,
                filename=source.name,
                size_bytes=destination.stat().st_size,
                duration_ms=probe_duration_ms(destination, ffprobe),
                category=str(entry.get("category", "unknown")),
            )
        )

    removed: list[str] = []
    if args.clean:
        removed = clean_stale({p.name for p in sources})
        clips = [c for c in clips if c.filename not in removed]

    try:
        write_index(clips, len(glossary))
        write_manifest(clips)
    except OSError as exc:
        logger.error("Could not write index/manifest: %s", exc)
        return 1

    public_bytes = sum(p.stat().st_size for p in PUBLIC_DIR.glob("*.mp4"))

    logger.info("Synced: %d clips", copied)
    logger.info("Skipped (up to date): %d", skipped)
    if removed:
        logger.info("Removed (stale): %d", len(removed))
    logger.info("Total size in public/signs: %.1f MB", public_bytes / (1024 * 1024))
    logger.info("Wrote %s and %s", INDEX_PATH.name, MANIFEST_PATH.name)
    if glossary:
        logger.info(
            "Glossary coverage: %.1f%% (%d/%d words have a clip)",
            len(clips) / len(glossary) * 100, len(clips), len(glossary),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
