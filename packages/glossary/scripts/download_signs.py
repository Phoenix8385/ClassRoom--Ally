#!/usr/bin/env python
"""Fetch ISL sign clips from YouTube into data/isl_clips/.

One word at a time: search YouTube with a few ISLRTC-flavoured queries, take the
first result short enough to be a single sign, trim it to the first few seconds,
and record it in isl_glossary.json. A word that cannot be fetched is written to
failed_words.txt and the run moves on — a single failure never stops the batch.

    python download_signs.py --priority-only
    python download_signs.py --word "good morning"
    python download_signs.py --category greeting --max 10
    python download_signs.py --retry-failed
    python download_signs.py --dry-run

Search results are a guess, not a guarantee: YouTube may return the wrong sign,
a channel trailer, or a lesson about the word rather than the sign itself. Every
download records the source URL and title in the glossary so a signer can review
what actually landed before the clips go in front of students.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:  # Only needed for real downloads — --dry-run works without it.
    import yt_dlp
except ImportError:  # pragma: no cover - depends on the environment
    yt_dlp = None  # type: ignore[assignment]

logger = logging.getLogger("download_signs")

# ── Paths ─────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
GLOSSARY_DIR = SCRIPT_DIR.parent
REPO_ROOT = GLOSSARY_DIR.parent.parent

GLOSSARY_PATH = GLOSSARY_DIR / "isl_glossary.json"
PRIORITY_WORDS_PATH = GLOSSARY_DIR / "priority_words.txt"

CLIPS_DIR = REPO_ROOT / "data" / "isl_clips"
FAILED_DIR = CLIPS_DIR / "failed"
FAILED_WORDS_PATH = FAILED_DIR / "failed_words.txt"
LOG_DIR = REPO_ROOT / "logs"
LOG_PATH = LOG_DIR / "download_signs.log"

# ── Tuning ────────────────────────────────────────────────────────────────────

SEARCH_QUERIES: tuple[str, ...] = (
    "ISLRTC {word} Indian Sign Language",
    "ISL {word} sign language India",
    "{word} Indian Sign Language tutorial",
    "ISLRTC {word}",
)
SEARCH_RESULTS_PER_QUERY = 5

MAX_DURATION_SECONDS = 60
TRIM_SECONDS = 4
MIN_FILE_BYTES = 10 * 1024

NETWORK_RETRIES = 3
RETRY_DELAY_SECONDS = 5.0
DEFAULT_DELAY_SECONDS = 2.0
BATCH_PAUSE_EVERY = 20
BATCH_PAUSE_SECONDS = 10.0

FFMPEG_TIMEOUT_SECONDS = 180


class _YtDlpLogger:
    """Route yt-dlp's chatter into our debug log instead of the progress display.

    "This video is not available" is routine here — we try several candidates
    per word — and printing it would bury the one line that matters.
    """

    def debug(self, message: str) -> None:
        logger.debug("yt-dlp: %s", message.strip())

    def info(self, message: str) -> None:
        logger.debug("yt-dlp: %s", message.strip())

    def warning(self, message: str) -> None:
        logger.debug("yt-dlp: %s", message.strip())

    def error(self, message: str) -> None:
        logger.debug("yt-dlp: %s", message.strip())


BASE_YDL_OPTS: dict[str, Any] = {
    "format": "best[height<=480]",
    "quiet": True,
    "no_warnings": True,
    "extract_flat": False,
    "socket_timeout": 30,
    "noprogress": True,
    "ignoreerrors": True,
    "nocheckcertificate": False,
    "retries": 2,
    "logger": _YtDlpLogger(),
}

# Errors worth another attempt; anything else is a dead end for this query.
_TRANSIENT_MARKERS = (
    "timed out", "timeout", "temporary failure", "connection", "unable to download",
    "http error 5", "http error 429", "too many requests", "network", "reset by peer",
)


# ── Logging ───────────────────────────────────────────────────────────────────

def _supports_unicode(stream: Any) -> bool:
    encoding = getattr(stream, "encoding", None) or ""
    try:
        "✅⏭️❌".encode(encoding or "ascii")
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def setup_logging(verbose: bool = False) -> dict[str, str]:
    """Log to the console and to logs/download_signs.log. Returns status symbols."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # A Windows console defaults to cp1252 and would raise on the status emoji.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - console dependent
            pass

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(message)s"))

    handlers: list[logging.Handler] = [console]
    try:
        file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
        )
        handlers.append(file_handler)
    except OSError as exc:  # pragma: no cover - permissions dependent
        console.setLevel(logging.INFO)
        logger.warning("Could not open %s (%s) — logging to console only", LOG_PATH, exc)

    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    for handler in handlers:
        logger.addHandler(handler)
    logger.propagate = False

    if _supports_unicode(sys.stdout):
        return {"ok": "✅", "skip": "⏭️ ", "fail": "❌", "dry": "🔍"}
    return {"ok": "[ok]", "skip": "[--]", "fail": "[!!]", "dry": "[??]"}


# ── Glossary ──────────────────────────────────────────────────────────────────

def slugify(word: str) -> str:
    """Filename stem for a word: "good morning" → "good_morning"."""
    return word.lower().strip().replace(" ", "_").replace("'", "")


def load_glossary() -> dict[str, dict]:
    try:
        data = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.error("Glossary not found at %s", GLOSSARY_PATH)
        return {}
    except ValueError as exc:
        logger.error("Glossary at %s is not valid JSON: %s", GLOSSARY_PATH, exc)
        return {}
    return {str(key).lower(): value for key, value in data.items()}


def save_glossary(glossary: dict[str, dict]) -> None:
    """Write the glossary atomically so an interrupted run cannot truncate it."""
    temp_path = GLOSSARY_PATH.with_suffix(".json.tmp")
    try:
        temp_path.write_text(
            json.dumps(glossary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(temp_path, GLOSSARY_PATH)
    except OSError as exc:
        logger.error("Could not write glossary: %s", exc)
        temp_path.unlink(missing_ok=True)


def clip_path_for(word: str, glossary: dict[str, dict]) -> Path:
    """Where a word's clip lives, honouring the path already in the glossary."""
    entry = glossary.get(word.lower())
    if entry:
        recorded = entry.get("clip_local_path")
        if isinstance(recorded, str) and recorded.strip():
            return REPO_ROOT / recorded
    return CLIPS_DIR / f"{slugify(word)}.mp4"


# ── Failed-word bookkeeping ───────────────────────────────────────────────────

def read_failed_words() -> list[str]:
    if not FAILED_WORDS_PATH.exists():
        return []
    try:
        lines = FAILED_WORDS_PATH.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.error("Could not read %s: %s", FAILED_WORDS_PATH, exc)
        return []
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def write_failed_words(words: list[str]) -> None:
    """Replace the failed list, keeping first-seen order and no duplicates."""
    seen: set[str] = set()
    ordered: list[str] = []
    for word in words:
        if word not in seen:
            seen.add(word)
            ordered.append(word)
    try:
        FAILED_DIR.mkdir(parents=True, exist_ok=True)
        FAILED_WORDS_PATH.write_text("\n".join(ordered) + ("\n" if ordered else ""), encoding="utf-8")
    except OSError as exc:
        logger.error("Could not write %s: %s", FAILED_WORDS_PATH, exc)


# ── Search and download ───────────────────────────────────────────────────────

@dataclass
class SearchResult:
    url: str
    title: str
    video_id: str
    duration: float | None


@dataclass
class WordOutcome:
    word: str
    status: str          # downloaded | exists | failed | dry-run
    detail: str = ""
    size_bytes: int = 0
    source: SearchResult | None = None


def _is_transient(error: BaseException) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in _TRANSIENT_MARKERS)


def _search(query: str) -> list[SearchResult]:
    """YouTube search results for one query, shortest usable clips first."""
    if yt_dlp is None:  # pragma: no cover - guarded by the caller
        return []

    opts = {**BASE_YDL_OPTS, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{SEARCH_RESULTS_PER_QUERY}:{query}", download=False)

    results: list[SearchResult] = []
    for entry in (info or {}).get("entries") or []:
        if not entry:
            continue
        video_id = str(entry.get("id") or "")
        url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
        if not url and video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
        if not url:
            continue

        raw_duration = entry.get("duration")
        duration = float(raw_duration) if isinstance(raw_duration, (int | float)) else None
        if duration is not None and duration > MAX_DURATION_SECONDS:
            logger.debug("  skipping %r — %.0fs is over the %ds limit",
                         entry.get("title"), duration, MAX_DURATION_SECONDS)
            continue

        results.append(
            SearchResult(
                url=str(url),
                title=str(entry.get("title") or ""),
                video_id=video_id,
                duration=duration,
            )
        )

    # Known-short clips are much more likely to be the sign itself.
    results.sort(key=lambda r: (r.duration is None, r.duration or 0.0))
    return results


def _download_to_temp(result: SearchResult, stem: Path) -> Path | None:
    """Download one video to `stem.<ext>`; returns the file actually written."""
    if yt_dlp is None:  # pragma: no cover - guarded by the caller
        return None

    for leftover in stem.parent.glob(stem.name + ".*"):
        leftover.unlink(missing_ok=True)

    opts = {**BASE_YDL_OPTS, "outtmpl": f"{stem}.%(ext)s", "overwrites": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([result.url])

    produced = sorted(stem.parent.glob(stem.name + ".*"))
    return produced[0] if produced else None


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def _trim(source: Path, destination: Path, seconds: int) -> bool:
    """Trim to the first `seconds`. Falls back to a plain move without ffmpeg."""
    ffmpeg = _ffmpeg()
    if ffmpeg is None:
        if source.suffix.lower() != ".mp4":
            logger.warning(
                "  ffmpeg not found and the download is %s — saving it under an .mp4 "
                "name, which the browser may refuse to play",
                source.suffix or "an unknown container",
            )
        shutil.move(str(source), str(destination))
        return True

    # Stream copy first; it is instant. Re-encode only when the container and
    # codecs disagree (a .webm download landing in an .mp4 container).
    attempts = (
        [ffmpeg, "-i", str(source), "-t", str(seconds), "-c", "copy", str(destination), "-y"],
        [ffmpeg, "-i", str(source), "-t", str(seconds), str(destination), "-y"],
    )
    for index, command in enumerate(attempts):
        try:
            completed = subprocess.run(
                command, capture_output=True, timeout=FFMPEG_TIMEOUT_SECONDS, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("  ffmpeg failed to trim (%s)", exc)
            break
        if completed.returncode == 0 and destination.exists():
            return True
        logger.debug(
            "  ffmpeg attempt %d exited %d: %s",
            index + 1, completed.returncode,
            completed.stderr.decode("utf-8", "replace").strip()[-300:],
        )

    # Trimming is a nicety; an untrimmed clip still beats no clip.
    logger.warning("  could not trim — keeping the full download")
    shutil.move(str(source), str(destination))
    return False


def _fingerprint(path: Path) -> str:
    """Hash of the first megabyte — enough to spot two words sharing one video."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            digest.update(handle.read(1024 * 1024))
    except OSError:
        return ""
    return digest.hexdigest()


def _record_download(
    glossary: dict[str, dict], word: str, clip: Path, result: SearchResult
) -> None:
    entry = glossary.get(word.lower())
    if entry is None:
        logger.debug("  %r is not in the glossary — file saved, nothing to update", word)
        return

    relative = clip.relative_to(REPO_ROOT).as_posix()
    entry["clip_downloaded"] = True
    entry["clip_local_path"] = relative
    entry["clip_web_path"] = f"/signs/{clip.name}"
    entry["download_timestamp"] = datetime.now(UTC).isoformat()
    # Provenance, so a signer can check the clip really shows this sign.
    entry["source_url"] = result.url
    entry["source_title"] = result.title
    save_glossary(glossary)


def download_word(
    word: str,
    glossary: dict[str, dict],
    *,
    trim_seconds: int,
    seen_fingerprints: dict[str, str],
) -> WordOutcome:
    """Fetch one word's clip. Returns an outcome; never raises."""
    destination = clip_path_for(word, glossary)

    if destination.exists() and destination.stat().st_size > MIN_FILE_BYTES:
        return WordOutcome(word, "exists", "already exists", destination.stat().st_size)

    if yt_dlp is None:
        return WordOutcome(word, "failed", "yt-dlp is not installed")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_stem = CLIPS_DIR / f".temp_{slugify(word)}"

    try:
        for query_template in SEARCH_QUERIES:
            query = query_template.format(word=word)
            logger.debug("  searching: %s", query)

            results: list[SearchResult] = []
            for attempt in range(1, NETWORK_RETRIES + 1):
                try:
                    results = _search(query)
                    break
                except Exception as exc:  # yt-dlp raises a wide range of types
                    if attempt < NETWORK_RETRIES and _is_transient(exc):
                        logger.warning(
                            "  search failed (attempt %d/%d): %s — retrying in %.0fs",
                            attempt, NETWORK_RETRIES, exc, RETRY_DELAY_SECONDS,
                        )
                        time.sleep(RETRY_DELAY_SECONDS)
                        continue
                    logger.debug("  search error for %r: %s", query, exc)
                    break

            for result in results:
                downloaded: Path | None = None
                for attempt in range(1, NETWORK_RETRIES + 1):
                    try:
                        downloaded = _download_to_temp(result, temp_stem)
                        break
                    except Exception as exc:
                        if attempt < NETWORK_RETRIES and _is_transient(exc):
                            logger.warning(
                                "  download failed (attempt %d/%d): %s — retrying in %.0fs",
                                attempt, NETWORK_RETRIES, exc, RETRY_DELAY_SECONDS,
                            )
                            time.sleep(RETRY_DELAY_SECONDS)
                            continue
                        logger.debug("  download error for %s: %s", result.url, exc)
                        break

                if downloaded is None or not downloaded.exists():
                    continue

                _trim(downloaded, destination, trim_seconds)
                for leftover in temp_stem.parent.glob(temp_stem.name + ".*"):
                    leftover.unlink(missing_ok=True)

                if not destination.exists():
                    continue

                size = destination.stat().st_size
                if size <= MIN_FILE_BYTES:
                    logger.debug("  discarding %s — only %d bytes", destination.name, size)
                    destination.unlink(missing_ok=True)
                    continue

                fingerprint = _fingerprint(destination)
                previous = seen_fingerprints.get(fingerprint)
                if fingerprint and previous and previous != word:
                    logger.warning(
                        "  %r downloaded the same video as %r — likely a bad match, review it",
                        word, previous,
                    )
                elif fingerprint:
                    seen_fingerprints[fingerprint] = word

                _record_download(glossary, word, destination, result)
                return WordOutcome(word, "downloaded", result.title, size, result)

        return WordOutcome(word, "failed", "no video found")

    except Exception as exc:  # a single word must never take the run down
        logger.exception("  unexpected error while fetching %r", word)
        return WordOutcome(word, "failed", f"unexpected error: {exc}")
    finally:
        for leftover in temp_stem.parent.glob(temp_stem.name + ".*"):
            leftover.unlink(missing_ok=True)


# ── Word selection ────────────────────────────────────────────────────────────

def read_priority_words(glossary: dict[str, dict]) -> list[str]:
    if not PRIORITY_WORDS_PATH.exists():
        logger.error("Priority list not found at %s", PRIORITY_WORDS_PATH)
        return []
    words: list[str] = []
    for line in PRIORITY_WORDS_PATH.read_text(encoding="utf-8").splitlines():
        word = line.strip().lower()
        if not word or word.startswith("#"):
            continue
        if word not in glossary:
            logger.warning("Priority word %r is not in the glossary — skipping", word)
            continue
        words.append(word)
    return words


def select_words(args: argparse.Namespace, glossary: dict[str, dict]) -> list[str]:
    if args.word:
        word = args.word.strip().lower()
        if word not in glossary:
            logger.warning("%r is not in the glossary — downloading it anyway", word)
        return [word]

    if args.retry_failed:
        words = [w.lower() for w in read_failed_words()]
        if not words:
            logger.info("Nothing in %s to retry", FAILED_WORDS_PATH)
        return words

    if args.priority_only:
        return read_priority_words(glossary)

    if args.category:
        category = args.category.strip().lower()
        words = [w for w, e in glossary.items() if str(e.get("category", "")).lower() == category]
        if not words:
            available = sorted({str(e.get("category", "?")) for e in glossary.values()})
            logger.error("No words in category %r. Available: %s", category, ", ".join(available))
        return words

    # Whole glossary, most important first, so a partial run is still useful.
    order = {word: index for index, word in enumerate(glossary)}
    return sorted(glossary, key=lambda w: (int(glossary[w].get("priority", 2)), order[w]))


# ── Reporting ─────────────────────────────────────────────────────────────────

def _human_size(num_bytes: float) -> str:
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f}MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.0f}KB"
    return f"{int(num_bytes)}B"


def _human_duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    return f"{minutes}m {secs:02d}s"


def _progress_line(symbols: dict[str, str], index: int, total: int, outcome: WordOutcome) -> str:
    symbol = {
        "downloaded": symbols["ok"],
        "exists": symbols["skip"],
        "failed": symbols["fail"],
        "dry-run": symbols["dry"],
    }[outcome.status]

    if outcome.status == "downloaded":
        detail = f"{_human_size(outcome.size_bytes)} saved"
    elif outcome.status == "exists":
        detail = "already exists"
    elif outcome.status == "dry-run":
        detail = outcome.detail or "would download"
    else:
        detail = outcome.detail or "failed"

    width = len(str(total))
    return f"{symbol} [{index:>{width}}/{total}] {outcome.word:<22} → {detail}"


def print_summary(
    outcomes: list[WordOutcome], glossary: dict[str, dict], elapsed: float, dry_run: bool
) -> None:
    downloaded = [o for o in outcomes if o.status == "downloaded"]
    existed = [o for o in outcomes if o.status == "exists"]
    failed = [o for o in outcomes if o.status == "failed"]
    total_size = sum(o.size_bytes for o in downloaded)

    have_clips = sum(
        1 for word in glossary if clip_path_for(word, glossary).exists()
    )
    coverage = (have_clips / len(glossary) * 100) if glossary else 0.0

    rule = "═" * 34
    logger.info("")
    logger.info(rule)
    logger.info("DOWNLOAD SUMMARY%s", " (dry run)" if dry_run else "")
    logger.info(rule)
    logger.info("Downloaded:      %d", len(downloaded))
    logger.info("Already existed: %d", len(existed))
    logger.info("Failed:          %d", len(failed))
    logger.info("Total time:      %s", _human_duration(elapsed))
    logger.info("Total size:      %.1f MB", total_size / (1024 * 1024))
    logger.info("Coverage:        %.1f%% (%d/%d words have clips)",
                coverage, have_clips, len(glossary))
    logger.info(rule)

    if failed:
        logger.info("Failed words saved to: %s", FAILED_WORDS_PATH)
        for outcome in failed[:20]:
            logger.info("  - %-22s %s", outcome.word, outcome.detail)
        if len(failed) > 20:
            logger.info("  ... and %d more (see the file)", len(failed) - 20)


# ── Entry point ───────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download ISL sign clips from YouTube",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--priority-only", action="store_true",
                           help="only the words in priority_words.txt")
    selection.add_argument("--word", type=str, help="a single word to download")
    selection.add_argument("--category", type=str, help="every word in one glossary category")
    selection.add_argument("--retry-failed", action="store_true",
                           help="retry the words in failed_words.txt")

    parser.add_argument("--dry-run", action="store_true",
                        help="list what would be downloaded, fetch nothing")
    parser.add_argument("--max", type=int, default=None, metavar="N",
                        help="stop after the first N words")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS, metavar="N",
                        help=f"seconds between downloads (default {DEFAULT_DELAY_SECONDS:g})")
    parser.add_argument("--trim-seconds", type=int, default=TRIM_SECONDS, metavar="N",
                        help=f"trim clips to the first N seconds (default {TRIM_SECONDS})")
    parser.add_argument("--verbose", "-v", action="store_true", help="debug logging")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    symbols = setup_logging(args.verbose)

    for directory in (CLIPS_DIR, FAILED_DIR, LOG_DIR):
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error("Could not create %s: %s", directory, exc)
            return 1

    glossary = load_glossary()
    if not glossary:
        return 1

    if yt_dlp is None and not args.dry_run:
        logger.error("yt-dlp is not installed. Install it with: pip install yt-dlp")
        return 1
    if _ffmpeg() is None and not args.dry_run:
        logger.warning(
            "ffmpeg is not on PATH — clips will be saved untrimmed. "
            "Install it for %d-second clips.", args.trim_seconds
        )

    words = select_words(args, glossary)
    if args.max is not None:
        words = words[: max(args.max, 0)]
    if not words:
        logger.info("Nothing to do.")
        return 0

    total = len(words)
    logger.info("Fetching %d word%s into %s", total, "" if total == 1 else "s", CLIPS_DIR)
    logger.info("")

    outcomes: list[WordOutcome] = []
    seen_fingerprints: dict[str, str] = {}
    previously_failed = read_failed_words()
    started = time.monotonic()
    downloads_done = 0

    for index, word in enumerate(words, start=1):
        if args.dry_run:
            destination = clip_path_for(word, glossary)
            status = "exists" if destination.exists() else "dry-run"
            outcome = WordOutcome(
                word, status, f"would save to {destination.relative_to(REPO_ROOT).as_posix()}"
            )
        else:
            outcome = download_word(
                word, glossary,
                trim_seconds=args.trim_seconds,
                seen_fingerprints=seen_fingerprints,
            )

        outcomes.append(outcome)
        logger.info(_progress_line(symbols, index, total, outcome))

        if outcome.status == "downloaded":
            downloads_done += 1
            if downloads_done % BATCH_PAUSE_EVERY == 0 and index < total:
                logger.info("   …pausing %.0fs after %d downloads", BATCH_PAUSE_SECONDS, downloads_done)
                time.sleep(BATCH_PAUSE_SECONDS)
        if outcome.status in {"downloaded", "failed"} and index < total and not args.dry_run:
            time.sleep(max(args.delay, 0.0))

    if not args.dry_run:
        succeeded = {o.word for o in outcomes if o.status in {"downloaded", "exists"}}
        still_failing = [o.word for o in outcomes if o.status == "failed"]
        kept = [w for w in previously_failed if w.lower() not in succeeded]
        write_failed_words(kept + still_failing)

    print_summary(outcomes, glossary, time.monotonic() - started, args.dry_run)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:  # pragma: no cover - interactive
        logger.info("\nInterrupted — progress so far is saved in the glossary.")
        sys.exit(130)
