from __future__ import annotations

import asyncio
import math
import os
import statistics
import struct
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.services.asr import (
    DEFAULT_MODEL_SIZE,
    SileroVAD,
    TranscriptResult,
    WhisperService,
    WordTimestamp,
    _speech_probability_sync,
    _transcribe_sync,
    pcm16_to_float32,
)

# ── helpers ───────────────────────────────────────────────────────────────────

SAMPLE_RATE = 16000


def _pcm(n_samples: int = SAMPLE_RATE, value: int = 0) -> bytes:
    return struct.pack(f"<{n_samples}h", *([value] * n_samples))


def _tone_pcm(seconds: float = 1.0, freq: float = 220.0, amp: float = 0.4) -> bytes:
    """A sine tone — not speech, but real signal rather than digital silence."""
    t = np.arange(int(SAMPLE_RATE * seconds), dtype=np.float32) / SAMPLE_RATE
    wave = (np.sin(2 * math.pi * freq * t) * amp * 32767).astype(np.int16)
    return wave.tobytes()


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
    assert result.confidence == pytest.approx(0.85)  # mean word probability
    assert len(result.word_timestamps) == 2
    assert isinstance(result.word_timestamps[0], WordTimestamp)


@pytest.mark.asyncio
async def test_transcribe_backward_compat_returns_plain_string():
    svc = WhisperService()
    svc._model = _mock_model("test text")

    text = await svc.transcribe(_pcm())

    assert isinstance(text, str)
    assert text == "test text"


# ── 2. Device selection ───────────────────────────────────────────────────────


def test_cpu_fallback_when_cuda_unavailable():
    with patch("torch.cuda.is_available", return_value=False), \
         patch("faster_whisper.WhisperModel") as MockModel:
        MockModel.return_value = MagicMock()
        import app.services.asr as asr_mod
        _model, device = asr_mod._load_model()

    assert device == "cpu"
    MockModel.assert_called_once_with(
        DEFAULT_MODEL_SIZE, device="cpu", compute_type="int8"
    )


def test_cuda_path_when_cuda_available():
    with patch("torch.cuda.is_available", return_value=True), \
         patch("faster_whisper.WhisperModel") as MockModel:
        MockModel.return_value = MagicMock()
        import app.services.asr as asr_mod
        _model, device = asr_mod._load_model("small")

    assert device == "cuda"
    MockModel.assert_called_once_with(
        "small", device="cuda", compute_type="int8_float16"
    )


def test_cuda_construction_failure_falls_back_to_cpu():
    """A cuDNN/driver error inside WhisperModel must not take the service down."""
    with patch("torch.cuda.is_available", return_value=True), \
         patch("faster_whisper.WhisperModel") as MockModel:
        MockModel.side_effect = [RuntimeError("cuDNN not found"), MagicMock()]
        import app.services.asr as asr_mod
        _model, device = asr_mod._load_model()

    assert device == "cpu"
    assert MockModel.call_args_list[-1].kwargs == {
        "device": "cpu",
        "compute_type": "int8",
    }


# ── 3. Int16 → float32 conversion ────────────────────────────────────────────


def test_pcm16_conversion_endpoints_and_silence():
    assert pcm16_to_float32(struct.pack("<h", 32767))[0] == pytest.approx(
        32767 / 32768.0, rel=1e-5
    )
    assert pcm16_to_float32(struct.pack("<h", -32768))[0] == pytest.approx(-1.0)
    assert np.all(pcm16_to_float32(b"\x00\x00" * SAMPLE_RATE) == 0.0)
    assert pcm16_to_float32(b"").size == 0


def test_pcm16_conversion_drops_ragged_trailing_byte():
    """An odd-length buffer must not raise — the partial sample is discarded."""
    arr = pcm16_to_float32(struct.pack("<h", 1000) + b"\x7f")
    assert arr.size == 1
    assert arr.dtype == np.float32


# ── 4. model.transcribe called with required kwargs ───────────────────────────


def test_transcribe_sync_passes_required_kwargs():
    model = _mock_model("x")
    _transcribe_sync(model, _pcm(), SAMPLE_RATE)

    model.transcribe.assert_called_once()
    _, kw = model.transcribe.call_args
    assert kw["beam_size"] == 3
    assert kw["condition_on_previous_text"] is False
    assert kw["language"] == "en"
    assert kw["vad_filter"] is False
    assert kw["word_timestamps"] is True


def test_transcribe_sync_empty_segments_returns_defaults():
    model = MagicMock()
    model.transcribe.return_value = (iter([]), MagicMock())

    result = _transcribe_sync(model, _pcm(), SAMPLE_RATE)

    assert result.text == ""
    assert result.confidence == 0.0
    assert result.word_timestamps == []


def test_transcribe_sync_empty_audio_skips_the_model():
    model = MagicMock()
    result = _transcribe_sync(model, b"", SAMPLE_RATE)

    assert result.text == ""
    model.transcribe.assert_not_called()


# ── 5. Singleton ──────────────────────────────────────────────────────────────


def test_get_instance_is_idempotent():
    WhisperService._instance = None  # isolate from other tests
    try:
        a = WhisperService.get_instance()
        b = WhisperService.get_instance()
        assert a is b
        assert a.model_size == DEFAULT_MODEL_SIZE
    finally:
        WhisperService._instance = None


# ── 6. Silero VAD — runs against the real bundled model ──────────────────────


def _vad_model():
    from silero_vad import load_silero_vad

    return load_silero_vad()


def test_vad_accepts_a_full_window_and_scores_silence_low():
    """The 512-sample framing is the point: a raw 1 s tensor makes Silero raise."""
    model = _vad_model()

    prob = _speech_probability_sync(model, _pcm(SAMPLE_RATE), SAMPLE_RATE)

    assert 0.0 <= prob <= 1.0
    assert prob < 0.5  # digital silence is not speech


def test_vad_handles_short_and_ragged_buffers():
    model = _vad_model()

    # Shorter than one frame → zero-padded rather than rejected.
    assert 0.0 <= _speech_probability_sync(model, _pcm(100), SAMPLE_RATE) <= 1.0
    # Not a whole number of frames → ragged tail ignored.
    assert 0.0 <= _speech_probability_sync(model, _pcm(700), SAMPLE_RATE) <= 1.0
    assert _speech_probability_sync(model, b"", SAMPLE_RATE) == 0.0


def test_vad_rejects_unsupported_sample_rate():
    with pytest.raises(ValueError, match="8000"):
        _speech_probability_sync(_vad_model(), _pcm(512), 44100)


@pytest.mark.asyncio
async def test_is_speech_applies_threshold():
    vad = SileroVAD()
    vad._model = _vad_model()

    prob = await vad.speech_probability(_pcm(SAMPLE_RATE))

    assert await vad.is_speech(_pcm(SAMPLE_RATE), threshold=0.5) is (prob >= 0.5)
    # A threshold below the observed probability must flip the verdict.
    assert await vad.is_speech(_pcm(SAMPLE_RATE), threshold=0.0) is True


# ── 7. Benchmark ──────────────────────────────────────────────────────────────

WINDOW_SECONDS = 1.0
# The ws pipeline emits one window per 800 ms stride, so a window must transcribe
# in well under real time or the queue backs up and frames get dropped.
RTF_BUDGET = 0.8


def _report(label: str, latencies_ms: list[float], audio_seconds: float) -> None:
    ordered = sorted(latencies_ms)
    p50 = statistics.median(ordered)
    p95 = ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]
    print(
        f"\n[benchmark] {label}: n={len(ordered)} "
        f"p50={p50:.1f}ms p95={p95:.1f}ms max={ordered[-1]:.1f}ms "
        f"rtf(p50)={p50 / 1000 / audio_seconds:.3f}"
    )


@pytest.mark.asyncio
async def test_benchmark_vad_beats_realtime_by_a_wide_margin():
    """The VAD gate only pays off if it is far cheaper than the ASR it skips."""
    vad = SileroVAD()
    vad._model = _vad_model()
    window = _tone_pcm(WINDOW_SECONDS)

    await vad.speech_probability(window)  # warm up the JIT graph

    latencies: list[float] = []
    for _ in range(10):
        t0 = time.perf_counter()
        await vad.speech_probability(window)
        latencies.append((time.perf_counter() - t0) * 1000)

    _report("silero_vad 1s window", latencies, WINDOW_SECONDS)
    p50 = statistics.median(latencies)
    # Generous: on any machine that can host the API this lands nearer 10 ms.
    assert p50 < 100.0, f"VAD p50 {p50:.1f}ms is too slow to be a cheap gate"


@pytest.mark.asyncio
async def test_benchmark_transcription_does_not_block_the_event_loop():
    """A 200 ms model call must not stall the loop — proves run_in_executor.

    Uses a stub model so the assertion is about the threading contract rather
    than about Whisper's speed; the real-weights numbers come from the
    opt-in benchmark below.
    """
    real_model = _mock_model("stub")

    def slow_transcribe(*args, **kwargs):
        time.sleep(0.2)
        return real_model.transcribe(*args, **kwargs)

    model = MagicMock()
    model.transcribe.side_effect = slow_transcribe

    svc = WhisperService()
    svc._model = model

    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    beat = asyncio.create_task(heartbeat())
    t0 = time.perf_counter()
    result = await svc.transcribe_chunk(_pcm())
    elapsed_ms = (time.perf_counter() - t0) * 1000
    beat.cancel()
    await asyncio.gather(beat, return_exceptions=True)

    _report("stub model (200ms sleep)", [elapsed_ms], WINDOW_SECONDS)
    assert result.text == "stub"
    # If transcription ran inline, the heartbeat would never have fired.
    assert ticks >= 5, f"event loop was blocked — only {ticks} ticks in 200ms"


@pytest.mark.skipif(
    os.environ.get("RUN_ASR_BENCHMARK") != "1",
    reason="set RUN_ASR_BENCHMARK=1 to download the weights and benchmark for real",
)
@pytest.mark.asyncio
async def test_benchmark_real_whisper_meets_realtime_budget():
    """End-to-end latency on the actual weights. Opt-in: downloads ~1.5 GB."""
    svc = WhisperService(os.environ.get("ASR_BENCHMARK_MODEL", DEFAULT_MODEL_SIZE))
    window = _tone_pcm(WINDOW_SECONDS)

    warm = await svc.transcribe_chunk(window)  # first call includes model load
    print(f"\n[benchmark] warm-up (incl. load): {warm.latency_ms}ms on {svc.device}")

    latencies: list[float] = []
    for _ in range(5):
        result = await svc.transcribe_chunk(window)
        latencies.append(float(result.latency_ms))

    _report(f"whisper {svc.model_size} on {svc.device}", latencies, WINDOW_SECONDS)
    rtf = statistics.median(latencies) / 1000 / WINDOW_SECONDS
    assert rtf < RTF_BUDGET, (
        f"real-time factor {rtf:.2f} exceeds budget {RTF_BUDGET}; "
        f"the ws pipeline will drop frames on {svc.device}"
    )
