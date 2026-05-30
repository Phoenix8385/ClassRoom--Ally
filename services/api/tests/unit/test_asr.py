from __future__ import annotations

import struct
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.services.asr import (
    TranscriptResult,
    WhisperService,
    WordTimestamp,
    _load_model,
    _transcribe_sync,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _pcm(n_samples: int = 16000, value: int = 0) -> bytes:
    return struct.pack(f"<{n_samples}h", *([value] * n_samples))


def _mock_model(text: str = "hello world") -> MagicMock:
    w0 = MagicMock(word="hello", start=0.0, end=0.3, probability=0.9)
    w1 = MagicMock(word=" world", start=0.3, end=0.7, probability=0.8)
    seg = MagicMock()
    seg.text = text
    seg.words = [w0, w1]
    model = MagicMock()
    model.transcribe.return_value = (iter([seg]), MagicMock())
    return model


# ── 1. transcribe_chunk returns TranscriptResult ──────────────────────────────

@pytest.mark.asyncio
async def test_transcribe_chunk_returns_transcript_result():
    svc = WhisperService()
    svc._model = _mock_model("hello world")

    result = await svc.transcribe_chunk(_pcm())

    assert isinstance(result, TranscriptResult)
    assert result.text == "hello world"
    assert result.latency_ms >= 0
    assert 0.0 <= result.confidence <= 1.0
    assert len(result.word_timestamps) == 2
    assert isinstance(result.word_timestamps[0], WordTimestamp)


# ── 2. transcribe() backward-compat ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_transcribe_backward_compat_returns_plain_string():
    svc = WhisperService()
    svc._model = _mock_model("test text")

    text = await svc.transcribe(_pcm())

    assert isinstance(text, str)
    assert text == "test text"


# ── 3. CPU fallback ───────────────────────────────────────────────────────────

def test_cpu_fallback_when_cuda_unavailable():
    with patch("torch.cuda.is_available", return_value=False), \
         patch("faster_whisper.WhisperModel") as MockModel:
        MockModel.return_value = MagicMock()
        import app.services.asr as asr_mod
        asr_mod._load_model()

    MockModel.assert_called_once_with(
        asr_mod._MODEL_NAME, device="cpu", compute_type="int8"
    )


def test_cuda_path_when_cuda_available():
    with patch("torch.cuda.is_available", return_value=True), \
         patch("faster_whisper.WhisperModel") as MockModel:
        MockModel.return_value = MagicMock()
        import app.services.asr as asr_mod
        asr_mod._load_model()

    MockModel.assert_called_once_with(
        asr_mod._MODEL_NAME, device="cuda", compute_type="int8_float16"
    )


# ── 4. Int16 → float32 conversion ────────────────────────────────────────────

def test_int16_conversion_max_maps_to_near_one():
    pcm = struct.pack("<h", 32767)
    arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    assert arr[0] == pytest.approx(32767 / 32768.0, rel=1e-5)


def test_int16_conversion_min_maps_to_neg_one():
    pcm = struct.pack("<h", -32768)
    arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    assert arr[0] == pytest.approx(-1.0, rel=1e-5)


def test_int16_silence_maps_to_all_zeros():
    arr = np.frombuffer(b"\x00\x00" * 16000, dtype=np.int16).astype(np.float32) / 32768.0
    assert np.all(arr == 0.0)


# ── 5. model.transcribe called with required kwargs ───────────────────────────

def test_transcribe_sync_passes_required_kwargs():
    model = _mock_model("x")
    _transcribe_sync(model, _pcm(), 16000)

    model.transcribe.assert_called_once()
    _, kw = model.transcribe.call_args
    assert kw["beam_size"] == 3
    assert kw["condition_on_previous_text"] is False
    assert kw["language"] == "en"
    assert kw["vad_filter"] is False
    assert kw["word_timestamps"] is True


# ── 6. empty segments → confidence 0.0, empty text ───────────────────────────

def test_transcribe_sync_empty_segments_returns_defaults():
    model = MagicMock()
    model.transcribe.return_value = (iter([]), MagicMock())

    result = _transcribe_sync(model, _pcm(), 16000)

    assert result.text == ""
    assert result.confidence == 0.0
    assert result.word_timestamps == []


# ── 7. singleton ──────────────────────────────────────────────────────────────

def test_get_instance_is_idempotent():
    WhisperService._instance = None  # isolate from other tests
    a = WhisperService.get_instance()
    b = WhisperService.get_instance()
    assert a is b
    WhisperService._instance = None  # clean up
