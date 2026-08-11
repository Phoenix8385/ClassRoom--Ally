#!/usr/bin/env python
"""Check that every clip in data/isl_clips/ is a usable sign video.

Three checks per file: it is big enough to contain video, it is a real MP4
container, and it runs for a plausible sign duration. Duration needs ffprobe;
without it that check is reported as unknown rather than failed.

    python verify_clips.py
    python verify_clips.py --remove-invalid   # quarantine and queue a re-download
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("verify_clips")

SCRIPT_DIR = Path(__file__).resolve().parent
GLOSSARY_DIR = SCRIPT_DIR.parent
REPO_ROOT = GLOSSARY_DIR.parent.parent

CLIPS_DIR = REPO_ROOT / "data" / "isl_clips"
FAILED_DIR = CLIPS_DIR / "failed"
FAILED_WORDS_PATH = FAILED_DIR / "failed_words.txt"
GLOSSARY_PATH = GLOSSARY_DIR / "isl_glossary.json"

MIN_FILE_BYTES = 10 * 1024
MIN_DURATION_SECONDS = 1.0
MAX_DURATION_SECONDS = 10.0
FFPROBE_TIMEOUT_SECONDS = 30


@dataclass
class ClipReport:
    path: Path
    size_bytes: int
    duration: float | None = None
    problems: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.problems is None:
            self.problems = []

    @property
    def valid(self) -> bool:
        return not self.problems

    @property
    def word(self) -> str:
        return self.path.stem.replace("_", " ")


def _ffprobe() -> str | None:
    return shutil.which("ffprobe")


def probe_duration(path: Path, ffprobe: str) -> tuple[float | None, str | None]:
    """Duration in seconds, or (None, reason) when ffprobe cannot read the file."""
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
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"ffprobe failed: {exc}"

    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip().splitlines()
        return None, f"unreadable: {detail[-1] if detail else 'ffprobe error'}"

    raw = completed.stdout.decode("utf-8", "replace").strip()
    try:
        return float(raw), None
    except ValueError:
        return None, "duration missing from container"


def looks_like_mp4(path: Path) -> bool:
    """An MP4 starts with a box header whose type is 'ftyp'."""
    try:
        with path.open("rb") as handle:
            header = handle.read(12)
    except OSError:
        return False
    return len(header) >= 12 and header[4:8] == b"ftyp"


def verify_clip(path: Path, ffprobe: str | None) -> ClipReport:
    size = path.stat().st_size if path.exists() else 0
    report = ClipReport(path=path, size_bytes=size)

    if size <= MIN_FILE_BYTES:
        report.problems.append(f"too small ({size} bytes)")
        return report  # nothing else is worth checking

    if not looks_like_mp4(path):
        report.problems.append("not a valid MP4 container")

    if ffprobe is not None:
        duration, error = probe_duration(path, ffprobe)
        report.duration = duration
        if error is not None:
            report.problems.append(error)
        elif duration is not None and not (
            MIN_DURATION_SECONDS <= duration <= MAX_DURATION_SECONDS
        ):
            report.problems.append(
                f"duration {duration:.1f}s outside "
                f"{MIN_DURATION_SECONDS:.0f}-{MAX_DURATION_SECONDS:.0f}s"
            )
    return report


def quarantine(reports: list[ClipReport]) -> None:
    """Move bad clips aside and queue their words for another download."""
    FAILED_DIR.mkdir(parents=True, exist_ok=True)

    existing: list[str] = []
    if FAILED_WORDS_PATH.exists():
        existing = [
            line.strip() for line in FAILED_WORDS_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    words = list(existing)
    for report in reports:
        try:
            shutil.move(str(report.path), str(FAILED_DIR / report.path.name))
        except OSError as exc:
            logger.error("Could not move %s: %s", report.path.name, exc)
            continue
        if report.word not in words:
            words.append(report.word)
        _clear_glossary_flag(report.word)

    FAILED_WORDS_PATH.write_text("\n".join(words) + ("\n" if words else ""), encoding="utf-8")
    logger.info("Quarantined %d clip(s); words queued in %s", len(reports), FAILED_WORDS_PATH)


def _clear_glossary_flag(word: str) -> None:
    """Mark a quarantined word as not downloaded so the mapper stops promising it."""
    try:
        glossary = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.debug("Could not update glossary for %r: %s", word, exc)
        return

    entry = glossary.get(word) or glossary.get(word.lower())
    if entry is None:
        return
    entry["clip_downloaded"] = False
    try:
        GLOSSARY_PATH.write_text(
            json.dumps(glossary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except OSError as exc:  # pragma: no cover - permissions dependent
        logger.debug("Could not write glossary: %s", exc)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clips-dir", type=Path, default=CLIPS_DIR, help="directory to check")
    parser.add_argument("--remove-invalid", action="store_true",
                        help="move invalid clips to failed/ and queue a re-download")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero when any clip is invalid")
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

    clips_dir: Path = args.clips_dir
    if not clips_dir.is_dir():
        logger.error("No clips directory at %s — run download_signs.py first", clips_dir)
        return 1

    ffprobe = _ffprobe()
    if ffprobe is None:
        logger.warning("ffprobe not found — duration checks skipped (install ffmpeg to enable)")

    clips = sorted(p for p in clips_dir.glob("*.mp4") if p.is_file())
    if not clips:
        logger.info("No clips in %s yet.", clips_dir)
        return 0

    reports = [verify_clip(path, ffprobe) for path in clips]

    valid = [r for r in reports if r.valid]
    too_small = [r for r in reports if any("too small" in p for p in r.problems)]
    wrong_duration = [r for r in reports if any("duration" in p for p in r.problems)]
    corrupted = [
        r for r in reports
        if any("MP4" in p or "unreadable" in p or "ffprobe" in p for p in r.problems)
    ]
    invalid = [r for r in reports if not r.valid]

    logger.info("Checked %s", clips_dir)
    logger.info("")
    logger.info("Valid clips:          %d", len(valid))
    logger.info("Too small (corrupted): %d", len(too_small))
    logger.info("Wrong duration:       %d", len(wrong_duration))
    logger.info("Unreadable/corrupt:   %d", len(corrupted))
    logger.info("Total:                %d", len(reports))
    total_bytes = sum(r.size_bytes for r in reports)
    logger.info("Total size:           %.1f MB", total_bytes / (1024 * 1024))

    if invalid:
        logger.info("")
        logger.info("Invalid clips — re-download these:")
        for report in invalid:
            logger.info("  %-28s %s", report.path.name, "; ".join(report.problems))
        logger.info("")
        logger.info(
            "  python download_signs.py --word %s",
            " ".join(f'"{r.word}"' for r in invalid[:3]) or "WORD",
        )
        if args.remove_invalid:
            quarantine(invalid)
    else:
        logger.info("")
        logger.info("All clips look good.")

    return 1 if (invalid and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
