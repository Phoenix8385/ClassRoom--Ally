from __future__ import annotations

import asyncio
import io
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import soundfile as sf

from app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_MODEL_SIZE = settings.WHISPER_MODEL

# Loaded when the configured checkpoint is not one this faster-whisper build
# knows about — an unrecognised name otherwise takes the whole pipeline down at
# the first window of audio, which is a bad way to discover a version mismatch.
_FALLBACK_MODEL_SIZE = "base"

# Silero VAD is a JIT model with a fixed input width: it accepts exactly
# 512 samples at 16 kHz (256 at 8 kHz) and raises on anything else.
_VAD_FRAME_SAMPLES: dict[int, int] = {8000: 256, 16000: 512}


@dataclass(frozen=True)
class WordTimestamp:
    word: str
    start: float
    end: float
    probability: float


@dataclass
class TranscriptResult:
    text: str
    segments: list
    confidence: float
    latency_ms: int
    word_timestamps: list[WordTimestamp] = field(default_factory=list)


# ── Shared audio conversion ───────────────────────────────────────────────────

def pcm16_to_float32(audio_bytes: bytes) -> np.ndarray:
    """Decode raw little-endian PCM Int16 to float32 in [-1.0, 1.0).

    Divides by 32768 (not 32767) so that Int16 min maps to exactly -1.0, which
    is the convention both Whisper and Silero were trained against.
    """
    # A partial sample at the tail would make frombuffer raise; drop it.
    usable = len(audio_bytes) - (len(audio_bytes) % 2)
    if usable <= 0:
        return np.empty(0, dtype=np.float32)
    return np.frombuffer(audio_bytes, dtype=np.int16, count=usable // 2).astype(
        np.float32
    ) / 32768.0


# ── Whisper ───────────────────────────────────────────────────────────────────

def _load_model(model_size: str = DEFAULT_MODEL_SIZE) -> tuple[Any, str]:
    """Return (model, device). Tries CUDA int8_float16, falls back to CPU int8."""
    import faster_whisper
    from faster_whisper import WhisperModel

    try:
        import torch

        if torch.cuda.is_available():
            model = WhisperModel(model_size, device="cuda", compute_type="int8_float16")
            logger.info(
                "WhisperModel '%s' loaded on device=cuda compute_type=int8_float16",
                model_size,
            )
            return model, "cuda"
        logger.info("CUDA not available — loading Whisper on CPU")
    except Exception as exc:
        # Covers both a missing torch and a CUDA/cuDNN init failure inside
        # WhisperModel itself; either way CPU is the usable path.
        logger.warning("CUDA unavailable (%s) — falling back to CPU", exc)

    try:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
    except ValueError:
        # faster-whisper only accepts checkpoint names its own build knows;
        # "large-v3-turbo", for instance, arrived in 1.1.0. Without this the
        # mismatch surfaces as a dead audio pipeline on the first window.
        if model_size == _FALLBACK_MODEL_SIZE:
            raise
        logger.exception(
            "Whisper checkpoint %r is not available in faster-whisper %s — "
            "loading %r instead. Set WHISPER_MODEL to a supported name.",
            model_size,
            getattr(faster_whisper, "__version__", "?"),
            _FALLBACK_MODEL_SIZE,
        )
        model = WhisperModel(_FALLBACK_MODEL_SIZE, device="cpu", compute_type="int8")
        logger.info(
            "WhisperModel '%s' loaded on device=cpu compute_type=int8",
            _FALLBACK_MODEL_SIZE,
        )
        return model, "cpu"

    logger.info("WhisperModel '%s' loaded on device=cpu compute_type=int8", model_size)
    return model, "cpu"


def _confidence_from(segments: list, probs: list[float]) -> float:
    """Mean word probability, falling back to exp(avg_logprob) per segment."""
    if probs:
        return float(np.mean(probs))
    logprobs = [
        s.avg_logprob
        for s in segments
        if isinstance(getattr(s, "avg_logprob", None), int | float)
    ]
    if logprobs:
        return float(np.exp(np.mean(logprobs)))
    return 0.0


def _transcribe_sync(model: Any, audio_bytes: bytes, sample_rate: int) -> TranscriptResult:
    """Blocking transcription — always called on a worker thread."""
    t0 = time.monotonic()

    audio_f32 = pcm16_to_float32(audio_bytes)
    if audio_f32.size == 0:
        return TranscriptResult(text="", segments=[], confidence=0.0, latency_ms=0)

    # Whisper reads from a file-like object; keep the WAV entirely in memory.
    buf = io.BytesIO()
    sf.write(buf, audio_f32, sample_rate, format="WAV", subtype="FLOAT")
    buf.seek(0)

    segments_iter, _info = model.transcribe(
        buf,
        beam_size=3,
        condition_on_previous_text=False,
        language="en",
        vad_filter=False,
        word_timestamps=True,
    )
    # faster-whisper yields lazily; force the work here, inside the executor.
    segments = list(segments_iter)

    text = " ".join(seg.text.strip() for seg in segments).strip()

    word_ts: list[WordTimestamp] = []
    probs: list[float] = []
    for seg in segments:
        for w in seg.words or []:
            word_ts.append(
                WordTimestamp(
                    word=w.word, start=w.start, end=w.end, probability=w.probability
                )
            )
            probs.append(w.probability)

    return TranscriptResult(
        text=text,
        segments=segments,
        confidence=_confidence_from(segments, probs),
        latency_ms=int((time.monotonic() - t0) * 1000),
        word_timestamps=word_ts,
    )


class WhisperService:
    """Lazily-loaded faster-whisper wrapper, serialised onto one worker thread."""

    _instance: WhisperService | None = None
    _class_lock: threading.Lock = threading.Lock()

    def __init__(self, model_size: str = DEFAULT_MODEL_SIZE) -> None:
        self.model_size = model_size
        self.device: str | None = None
        self._model: Any = None
        self._model_lock = threading.Lock()
        # max_workers=1: a CTranslate2 model is not safe to drive from several
        # threads at once, so concurrent callers queue instead of racing.
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="whisper"
        )

    @classmethod
    def get_instance(cls, model_size: str = DEFAULT_MODEL_SIZE) -> WhisperService:
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = cls(model_size)
        return cls._instance

    def _ensure_model(self) -> None:
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    self._model, self.device = _load_model(self.model_size)

    async def transcribe_chunk(
        self,
        audio_bytes: bytes,
        sample_rate: int = 16000,
    ) -> TranscriptResult:
        self._ensure_model()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            _transcribe_sync,
            self._model,
            audio_bytes,
            sample_rate,
        )

    async def transcribe(self, audio_bytes: bytes) -> str:
        """Backward-compatible wrapper; returns plain transcript text."""
        result = await self.transcribe_chunk(audio_bytes)
        return result.text

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)


# ── Silero VAD ────────────────────────────────────────────────────────────────

def _speech_probability_sync(
    model: Any, audio_bytes: bytes, sample_rate: int
) -> float:
    """Peak per-frame speech probability across the buffer.

    Silero only accepts one fixed-width frame at a time, so a 1 s window is fed
    through as ~31 frames. We take the peak rather than the mean: the caller
    wants to know whether the window contains *any* speech worth transcribing,
    and a mean would let a short word drown in surrounding silence.
    """
    frame_len = _VAD_FRAME_SAMPLES.get(sample_rate)
    if frame_len is None:
        raise ValueError(
            f"Silero VAD supports {sorted(_VAD_FRAME_SAMPLES)} Hz, got {sample_rate}"
        )

    import torch

    audio = pcm16_to_float32(audio_bytes)
    if audio.size == 0:
        return 0.0

    n_frames, remainder = divmod(audio.size, frame_len)
    if n_frames == 0:
        audio = np.pad(audio, (0, frame_len - audio.size))
        n_frames = 1
    elif remainder:
        # Ignore the ragged tail; at 16 kHz it is under 32 ms.
        audio = audio[: n_frames * frame_len]

    # The model is an LSTM: clear carry-over so each call is independent.
    reset_states = getattr(model, "reset_states", None)
    if callable(reset_states):
        reset_states()

    peak = 0.0
    with torch.no_grad():
        for i in range(n_frames):
            frame = torch.from_numpy(audio[i * frame_len : (i + 1) * frame_len])
            peak = max(peak, float(model(frame, sample_rate).item()))
            if peak >= 1.0:
                break
    return peak


class SileroVAD:
    """Voice-activity gate used to skip silent windows before hitting Whisper."""

    _instance: SileroVAD | None = None
    _class_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._model: Any = None
        self._model_lock = threading.Lock()
        # Single worker: the model carries LSTM state between frames.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vad")

    @classmethod
    def get_instance(cls) -> SileroVAD:
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _ensure_model(self) -> None:
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    from silero_vad import load_silero_vad

                    self._model = load_silero_vad()
                    logger.info("SileroVAD model loaded")

    async def speech_probability(
        self,
        audio_bytes: bytes,
        sample_rate: int = 16000,
    ) -> float:
        self._ensure_model()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            _speech_probability_sync,
            self._model,
            audio_bytes,
            sample_rate,
        )

    async def is_speech(
        self,
        audio_bytes: bytes,
        sample_rate: int = 16000,
        threshold: float = 0.5,
    ) -> bool:
        return await self.speech_probability(audio_bytes, sample_rate) >= threshold

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)
