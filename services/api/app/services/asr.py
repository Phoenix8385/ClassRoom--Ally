from __future__ import annotations

import asyncio
import io
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

_MODEL_NAME = "large-v3-turbo"


@dataclass
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


def _load_model():
    from faster_whisper import WhisperModel
    try:
        import torch
        if torch.cuda.is_available():
            model = WhisperModel(_MODEL_NAME, device="cuda", compute_type="int8_float16")
            logger.info("WhisperModel loaded on device=cuda compute_type=int8_float16")
            return model
    except Exception as exc:
        logger.warning("CUDA unavailable (%s), falling back to CPU", exc)

    model = WhisperModel(_MODEL_NAME, device="cpu", compute_type="int8")
    logger.info("WhisperModel loaded on device=cpu compute_type=int8")
    return model


def _transcribe_sync(model, audio_bytes: bytes, sample_rate: int) -> TranscriptResult:
    t0 = time.monotonic()

    audio_f32 = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
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
    segments = list(segments_iter)

    latency_ms = int((time.monotonic() - t0) * 1000)
    text = " ".join(seg.text.strip() for seg in segments).strip()

    word_ts: list[WordTimestamp] = []
    probs: list[float] = []
    for seg in segments:
        for w in seg.words or []:
            word_ts.append(WordTimestamp(word=w.word, start=w.start, end=w.end, probability=w.probability))
            probs.append(w.probability)

    confidence = float(np.mean(probs)) if probs else 0.0

    return TranscriptResult(
        text=text,
        segments=segments,
        confidence=confidence,
        latency_ms=latency_ms,
        word_timestamps=word_ts,
    )


def _is_speech_sync(model, audio_bytes: bytes, sample_rate: int, threshold: float) -> bool:
    import torch
    audio_f32 = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    tensor = torch.from_numpy(audio_f32)
    with torch.no_grad():
        prob = model(tensor, sample_rate).item()
    return prob >= threshold


class WhisperService:
    _instance: Optional[WhisperService] = None
    _class_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._model = None
        self._model_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> WhisperService:
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _ensure_model(self) -> None:
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    self._model = _load_model()

    async def transcribe_chunk(
        self,
        audio_bytes: bytes,
        sample_rate: int = 16000,
    ) -> TranscriptResult:
        self._ensure_model()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            _transcribe_sync,
            self._model,
            audio_bytes,
            sample_rate,
        )

    async def transcribe(self, audio_bytes: bytes) -> str:
        """Backward-compatible wrapper; returns plain transcript text."""
        result = await self.transcribe_chunk(audio_bytes)
        return result.text


class SileroVAD:
    _instance: Optional[SileroVAD] = None
    _class_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._model = None
        self._model_lock = threading.Lock()

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

    async def is_speech(
        self,
        audio_bytes: bytes,
        sample_rate: int = 16000,
        threshold: float = 0.5,
    ) -> bool:
        self._ensure_model()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            _is_speech_sync,
            self._model,
            audio_bytes,
            sample_rate,
            threshold,
        )
