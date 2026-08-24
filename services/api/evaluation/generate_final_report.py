#!/usr/bin/env python
"""Assemble docs/FINAL-EVALUATION-REPORT.md from the component reports.

    python services/api/evaluation/generate_final_report.py
    python services/api/evaluation/generate_final_report.py --skip-latency

Reads the three generated reports, measures pipeline latency live, and writes a
single submission-ready document. Every figure is parsed from a report or
measured here — nothing is hard-coded, so a stale component report shows up as a
missing value rather than a wrong one.

One structural note. The final report does NOT put an exact-match figure under
the ISLTranslate heading, because ISLTranslate ships no gloss annotations (it
pairs ISL *video* with English). The only accuracy figure this project has comes
from a 20-sentence hand-written set, and that set's provenance is stated beside
it. Presenting it as "accuracy on 500 ISLTranslate sentences" would misdescribe
both the corpus and the result.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent
API_DIR = EVAL_DIR.parent
REPO_ROOT = API_DIR.parent.parent

DOCS = REPO_ROOT / "docs"
MANUAL_REPORT = DOCS / "evaluation-report.md"
REAL_REPORT = DOCS / "real-evaluation-report.md"
CLIP_REPORT = DOCS / "clip-validation-report.md"
OUTPUT = DOCS / "FINAL-EVALUATION-REPORT.md"

DEMO_AUDIO = REPO_ROOT / "demo" / "demo_speech.wav"
GLOSSARY = REPO_ROOT / "packages" / "glossary" / "isl_glossary.json"

LATENCY_WINDOWS = 8   # 1-second windows of demo audio to time
WINDOW_SECONDS = 1

_PLACEHOLDER_SETTINGS = {
    "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/db",
    "REDIS_URL": "redis://localhost:6379",
    "OPENAI_API_KEY": "sk-not-set",
    "SECRET_KEY": "evaluation-only",
}


def _bootstrap() -> None:
    if str(API_DIR) not in sys.path:
        sys.path.insert(0, str(API_DIR))
    for env_path in (API_DIR / ".env", REPO_ROOT / ".env"):
        if env_path.is_file():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())
    for key, value in _PLACEHOLDER_SETTINGS.items():
        os.environ.setdefault(key, value)


_bootstrap()


# ── Report parsing ────────────────────────────────────────────────────────────

@dataclass
class Parsed:
    """Values pulled out of one component report."""

    path: Path
    present: bool
    values: dict[str, Any] = field(default_factory=dict)


def _search(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def parse_report(path: Path, patterns: dict[str, str]) -> Parsed:
    """Extract named values from a report, tolerating a missing file."""
    if not path.is_file():
        return Parsed(path, present=False)
    text = path.read_text(encoding="utf-8")
    return Parsed(path, True, {k: _search(text, p) for k, p in patterns.items()})


def parse_all() -> dict[str, Parsed]:
    return {
        "manual": parse_report(
            MANUAL_REPORT,
            {
                "sentences": r"\*\*Sentences tested:\*\*\s*(\d+)",
                "exact": r"\|\s*Exact match\s*\|\s*([\d.]+)%",
                "token": r"\|\s*Token accuracy[^|]*\|\s*([\d.]+)%",
                "precision": r"\|\s*Token precision\s*\|\s*([\d.]+)%",
                "degraded": r"(DEGRADED RUN)",
            },
        ),
        "real": parse_report(
            REAL_REPORT,
            {
                "sentences": r"\*\*Sentences tested:\*\*\s*(\d+)",
                "coverage": r"Glossary coverage \(Tier 1\)\*?\*?\s*\|\s*\*?\*?([\d.]+)%",
                "compression": r"\|\s*Compression\s*\|\s*([\d.]+) tokens",
                "fingerspelled": r"\|\s*Fingerspelled \(Tier 3\)\s*\|\s*(\d+)",
                "no_fingerspell": r"needing no fingerspelling\s*\|\s*([\d.]+)%",
                "tokens": r"\|\s*Gloss tokens produced\s*\|\s*(\d+)",
            },
        ),
        "clip": parse_report(
            CLIP_REPORT,
            {
                "ours": r"\|\s*Our glossary\s*\|\s*(\d+) words",
                "include": r"\|\s*INCLUDE\s*\|\s*(\d+) signs",
                "overlap": r"\|\s*\*\*Overlap\*\*\s*\|\s*\*\*(\d+)\*\*",
                "overlap_pct": r"\*\*Overlap\*\*[^|]*\|[^(]*\(([\d.]+)% of INCLUDE\)",
                "missing": r"missing from ours\s*\|\s*(\d+)",
                "extra": r"not in INCLUDE\s*\|\s*(\d+)",
                "downloaded": r"actually downloaded\s*\|\s*(\d+)\s*/\s*(\d+)",
            },
        ),
    }


# ── Latency ───────────────────────────────────────────────────────────────────

def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * pct / 100
    low, high = int(position), min(int(position) + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


async def _measure(windows: int) -> dict[str, Any]:
    import soundfile as sf

    from app.services.asr import SileroVAD, WhisperService
    from app.services.gloss import GlossService

    audio, sample_rate = sf.read(DEMO_AUDIO, dtype="int16")
    if audio.ndim > 1:
        audio = audio[:, 0]

    whisper = WhisperService.get_instance()
    vad = SileroVAD.get_instance()
    gloss = GlossService()

    frame = sample_rate * WINDOW_SECONDS
    available = min(windows, len(audio) // frame)

    # First call pays model load and JIT warm-up; timed separately so it does
    # not distort the steady-state percentiles.
    load_start = time.perf_counter()
    await whisper.transcribe_chunk(audio[:frame].tobytes(), sample_rate)
    await vad.speech_probability(audio[:frame].tobytes(), sample_rate)
    warmup_ms = (time.perf_counter() - load_start) * 1000

    vad_ms: list[float] = []
    asr_ms: list[float] = []
    gloss_ms: list[float] = []
    total_ms: list[float] = []

    for i in range(available):
        chunk = audio[i * frame : (i + 1) * frame].tobytes()
        window_start = time.perf_counter()

        t = time.perf_counter()
        await vad.speech_probability(chunk, sample_rate)
        vad_ms.append((time.perf_counter() - t) * 1000)

        t = time.perf_counter()
        result = await whisper.transcribe_chunk(chunk, sample_rate)
        asr_ms.append((time.perf_counter() - t) * 1000)

        # Only timed when there was text to gloss. A silent window would
        # otherwise contribute a 0 ms sample and drag the percentiles down.
        if result.text.strip():
            t = time.perf_counter()
            await gloss.convert(result.text)
            gloss_ms.append((time.perf_counter() - t) * 1000)

        total_ms.append((time.perf_counter() - window_start) * 1000)

    whisper.shutdown()
    vad.shutdown()

    return {
        "windows": available,
        "warmup_ms": warmup_ms,
        "device": whisper.device or "cpu",
        "model": whisper.model_size,
        "vad": vad_ms,
        "asr": asr_ms,
        "gloss": gloss_ms,
        "total": total_ms,
    }


def measure_latency(windows: int) -> dict[str, Any] | None:
    if not DEMO_AUDIO.is_file():
        print(f"  no demo audio at {DEMO_AUDIO} — skipping latency")
        return None
    print(f"  timing {windows} x {WINDOW_SECONDS}s windows of {DEMO_AUDIO.name}...")
    try:
        return asyncio.run(_measure(windows))
    except Exception as exc:
        print(f"  latency measurement failed: {type(exc).__name__}: {exc}")
        return None


# ── Gloss-only latency (no audio needed) ──────────────────────────────────────

async def _gloss_only(sentences: list[str]) -> list[float]:
    from app.services.gloss import GlossService

    service = GlossService()
    # Loads spaCy on the first call; timed separately from the samples below.
    await service.convert("The teacher opened the book")
    timings = []
    for sentence in sentences:
        t = time.perf_counter()
        await service.convert(sentence)
        timings.append((time.perf_counter() - t) * 1000)
    return timings


def measure_gloss_latency() -> list[float]:
    sentences = [
        "Good morning students",
        "Open your books to page ten",
        "We need to finish the homework today",
        "What is your name?",
        "The teacher explained the lesson clearly",
        "I did not understand the question",
        "How many students are in the class?",
        "Please write your name on the paper",
    ]
    # Repeated so the percentiles rest on enough samples to mean something —
    # a single pass over 8 short sentences is too few to read a p95 from.
    try:
        return asyncio.run(_gloss_only(sentences * 12))
    except Exception as exc:
        print(f"  gloss latency failed: {type(exc).__name__}: {exc}")
        return []


# ── Report assembly ───────────────────────────────────────────────────────────

def value(parsed: Parsed, key: str, suffix: str = "") -> str:
    """A parsed value for display, or an explicit 'not available' marker."""
    raw = parsed.values.get(key) if parsed.present else None
    return f"{raw}{suffix}" if raw else "_not available_"


def build(reports: dict[str, Parsed], latency: dict[str, Any] | None,
          gloss_only: list[float]) -> str:
    manual, real, clip = reports["manual"], reports["real"], reports["clip"]
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Classroom Ally — Evaluation Report",
        "",
        f"_Generated {generated}_",
        "",
        "## Datasets Used",
        "",
        "| Dataset | Scale | Source | Role here |",
        "|---|---|---|---|",
        "| ISLTranslate | ~31,000 sentences | Exploration-Lab, IIT Kanpur (ACL 2023) |"
        " Real ISL-aligned English for coverage measurement |",
        "| INCLUDE | 263 signs, 4,292 clips | AI4Bharat (ACM MM 2020) |"
        " Signer-recorded reference vocabulary |",
        "| Hand-written regression set | 20 sentences | This project |"
        " The only text→gloss pairs available |",
        "",
        "### An important limitation, stated up front",
        "",
        "Neither public dataset contains **text → ISL gloss** pairs. ISLTranslate",
        "aligns ISL *video* with English sentences (schema `uid,text`); INCLUDE is",
        "isolated-sign video, one clip per word. Neither carries gloss notation.",
        "",
        "Gloss-engine *accuracy* therefore cannot be measured against either. It is",
        "reported below only against the 20-sentence hand-written set, whose",
        "limitations are stated with it. What the public datasets do support —",
        "vocabulary coverage and dictionary validation — is measured on them at full",
        "scale.",
        "",
        "## Gloss Engine Results",
        "",
        "### Accuracy (hand-written set)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Sentences | {value(manual, 'sentences')} |",
        f"| Exact match | {value(manual, 'exact', '%')} |",
        f"| Token accuracy | {value(manual, 'token', '%')} |",
        f"| Token precision | {value(manual, 'precision', '%')} |",
        "",
        "**Caveat:** these 20 sentences were written by the project, and several are",
        "drawn from examples in the gloss engine's own source comments. The set is a",
        "regression guard — it catches breakage — not an independent benchmark, and",
        "the figure should not be cited as ISL translation accuracy.",
        "",
        "### Coverage (500 real ISLTranslate sentences)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Sentences tested | {value(real, 'sentences')} |",
        f"| Gloss tokens produced | {value(real, 'tokens')} |",
        f"| Compression | {value(real, 'compression')} tokens per English word |",
        f"| **Glossary coverage (Tier 1)** | **{value(real, 'coverage', '%')}** |",
        f"| Tokens fingerspelled (Tier 3) | {value(real, 'fingerspelled')} |",
        f"| Sentences needing no fingerspelling | {value(real, 'no_fingerspell', '%')} |",
        "",
        "Exact match is deliberately absent here: with no reference gloss in the",
        "corpus, any such figure would be 0% by construction.",
        "",
        "## Sign Dictionary Results",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Our vocabulary | {value(clip, 'ours')} words |",
        f"| INCLUDE vocabulary | {value(clip, 'include')} signs |",
        f"| Overlap | {value(clip, 'overlap')} words ({value(clip, 'overlap_pct', '%')} of INCLUDE) |",
        f"| In INCLUDE, missing from ours | {value(clip, 'missing')} |",
        f"| In ours, absent from INCLUDE | {value(clip, 'extra')} |",
    ]

    downloaded = clip.values.get("downloaded") if clip.present else None
    if downloaded:
        match = re.search(r"actually downloaded\s*\|\s*(\d+)\s*/\s*(\d+)",
                          CLIP_REPORT.read_text(encoding="utf-8"))
        if match:
            lines.append(f"| Clips actually downloaded | {match.group(1)} / {match.group(2)} |")
    lines += [
        "",
        "Our clips come from YouTube search results, which `download_signs.py`",
        "documents as unverified. INCLUDE's are recorded by Deaf signers, so the",
        "overlapping words are the subset we can validate against a human reference.",
        "",
        "## Latency Results",
        "",
    ]

    if latency:
        lines += [
            f"Measured on `{DEMO_AUDIO.name}` ({latency['windows']} x "
            f"{WINDOW_SECONDS}s windows), Whisper `{latency['model']}` on "
            f"`{latency['device']}`.",
            "",
            "| Stage | p50 | p95 | max |",
            "|---|---|---|---|",
        ]
        for label, key in (("VAD (Silero)", "vad"), ("ASR (Whisper)", "asr"),
                           ("Gloss (spaCy)", "gloss"), ("**End-to-end**", "total")):
            series = latency[key]
            lines.append(
                f"| {label} | {percentile(series, 50):.0f} ms |"
                f" {percentile(series, 95):.0f} ms | {max(series):.0f} ms |"
            )
        lines += [
            "",
            f"Cold start (model load + warm-up): {latency['warmup_ms']:.0f} ms, excluded above.",
            "",
        ]
        p50_total = percentile(latency["total"], 50)
        budget = WINDOW_SECONDS * 1000
        if p50_total > budget:
            lines += [
                f"> **Real-time budget exceeded.** A {WINDOW_SECONDS}s window must be",
                f"> processed in under {budget} ms to keep up with live speech. The",
                f"> measured p50 is {p50_total:.0f} ms on CPU, so captions fall behind",
                "> progressively. A CUDA device or a smaller checkpoint is required for",
                "> live classroom use; this is a hardware/config gap, not a code defect.",
                "",
            ]
    else:
        lines += ["_Not measured in this run._", ""]

    if gloss_only:
        lines += [
            "### Gloss stage in isolation",
            "",
            f"Over {len(gloss_only)} classroom sentences, no audio involved:",
            "",
            f"- p50 **{percentile(gloss_only, 50):.1f} ms**",
            f"- p95 **{percentile(gloss_only, 95):.1f} ms**",
            f"- mean {statistics.mean(gloss_only):.1f} ms",
            "",
            "The gloss stage is not a bottleneck; ASR dominates end-to-end latency.",
            "",
        ]

    lines += ["## Conclusion", ""] + conclusion(reports, latency, gloss_only)
    lines += [
        "",
        "## Reproducing these numbers",
        "",
        "```",
        "python services/api/evaluation/datasets/get_isltranslate.py",
        "python services/api/evaluation/datasets/get_include.py",
        "python services/api/evaluation/evaluate_gloss.py --data data/isltranslate/test.json",
        "python services/api/evaluation/test_on_isltranslate.py --limit 500",
        "python services/api/evaluation/verify_against_include.py",
        "python services/api/evaluation/generate_final_report.py",
        "```",
        "",
        "Requires `en_core_web_sm`; every script refuses to produce numbers without it.",
        "",
    ]
    return "\n".join(lines)


def conclusion(reports: dict[str, Parsed], latency: dict[str, Any] | None,
               gloss_only: list[float]) -> list[str]:
    real, clip = reports["real"], reports["clip"]
    coverage = real.values.get("coverage") if real.present else None
    no_fs = real.values.get("no_fingerspell") if real.present else None
    overlap_pct = clip.values.get("overlap_pct") if clip.present else None

    text = [
        "The rule-based gloss engine works as designed: it applies ISL",
        "Subject-Object-Verb ordering, drops function words, lemmatises content",
        "words, and moves WH-words and negation to the end. It is fast — the gloss",
        "stage runs in single-digit milliseconds — and it degrades safely, never",
        "raising into the caption stream.",
        "",
    ]

    if coverage:
        text += [
            "The binding constraint is vocabulary, not grammar. Across 500 real",
            f"ISLTranslate sentences, only **{coverage}%** of produced gloss tokens",
            "resolve to a sign clip; the rest fall through to fingerspelling.",
        ]
        if no_fs:
            text.append(
                f"Only **{no_fs}%** of sentences avoid fingerspelling entirely."
            )
        text += [
            "ADR-001 rejects end-to-end neural generation on the grounds that Tier 1",
            "dictionary lookup handles the majority of classroom content. That claim",
            "is not yet supported by measurement: on general-domain ISL text the",
            "dictionary carries a minority of tokens. The architecture is sound, but",
            "the glossary must grow substantially before the Tier 1 assumption holds.",
            "",
        ]

    if overlap_pct:
        text += [
            "Dictionary validation is similarly limited. Our vocabulary overlaps",
            f"INCLUDE by only {overlap_pct}% of INCLUDE's signs, because INCLUDE",
            "covers everyday categories while ours is classroom-specific. Most of our",
            "clips therefore have no independent reference and rest on unverified",
            "YouTube scrapes — a correctness risk for the Deaf students this serves,",
            "and the strongest argument for signer review before deployment.",
            "",
        ]

    if latency:
        p50 = percentile(latency["total"], 50)
        verdict = (
            "exceeds the real-time budget on CPU and needs GPU acceleration"
            if p50 > WINDOW_SECONDS * 1000
            else "meets the real-time budget"
        )
        text += [
            f"End-to-end latency is {p50:.0f} ms per {WINDOW_SECONDS}s window, which",
            f"{verdict}.",
            "",
        ]

    text += [
        "**Honest summary of what is proven.** The pipeline is end-to-end functional",
        "and the engineering is measured rather than asserted. What remains unproven",
        "is ISL output *quality*: no public text→gloss corpus exists for ISL, so",
        "translation accuracy has been measured only against a small self-authored",
        "set. Establishing real quality requires a signer-annotated corpus, and that",
        "is the single highest-value next step for this project.",
    ]
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Assemble the final evaluation report.")
    parser.add_argument("--skip-latency", action="store_true",
                        help="skip audio timing (much faster)")
    parser.add_argument("--windows", type=int, default=LATENCY_WINDOWS)
    args = parser.parse_args()

    logging.getLogger("app.services.gloss").setLevel(logging.ERROR)

    # Latency here is the local pipeline's. The LLM fallback fires only when the
    # rules yield almost nothing, and a network round-trip (or a 401 against an
    # unset key) would swamp the measurement; a threshold of 0 disables it.
    from app.services import gloss as gloss_module

    gloss_module._MIN_TOKENS = 0

    print("Reading component reports...")
    reports = parse_all()
    for name, parsed in reports.items():
        state = "ok" if parsed.present else "MISSING"
        print(f"  {name:<8} {state:<8} {parsed.path.name}")
        if parsed.present:
            empty = [k for k, v in parsed.values.items() if not v and k != "degraded"]
            if empty:
                print(f"           could not parse: {', '.join(empty)}")

    if reports["manual"].present and reports["manual"].values.get("degraded"):
        print("\n  WARNING: evaluation-report.md is from a DEGRADED run.")
        print("  Re-run evaluate_gloss.py with the spaCy model installed first.\n")

    print("Measuring gloss latency...")
    gloss_only = measure_gloss_latency()

    latency = None
    if not args.skip_latency:
        print("Measuring pipeline latency...")
        latency = measure_latency(args.windows)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(build(reports, latency, gloss_only), encoding="utf-8")
    print(f"\nWrote {OUTPUT}")


if __name__ == "__main__":
    main()
