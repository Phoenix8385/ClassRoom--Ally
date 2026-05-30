# ADR 003 — faster-whisper large-v3-turbo INT8 Locally over OpenAI Whisper API

## Status: Accepted

## Context

Classroom Ally transcribes teacher speech in real time and delivers captions and ISL sign cues to students. Transcription quality, latency, cost, and data privacy are all first-order concerns in a school deployment.

Two approaches were evaluated:

1. **OpenAI Whisper API** — send audio chunks to `api.openai.com/v1/audio/transcriptions`, receive text back.
2. **Local faster-whisper** — run the `large-v3-turbo` model locally on the school server or teacher's workstation using CTranslate2's INT8 quantisation.

The target deployment hardware includes machines with **NVIDIA RTX 4050 or RTX 4060** GPUs, which are common in mid-range developer and student laptops in the target market.

## Decision

Use **faster-whisper `large-v3-turbo` with INT8 quantisation**, running locally on GPU (CUDA) or CPU fallback. The transcription service runs as a sidecar process (Python, exposed via HTTP or direct IPC) alongside the Next.js application server.

`large-v3-turbo` is selected over `large-v3` because it offers near-identical word error rate with significantly lower inference time, and over smaller models (medium, small) because accuracy on accented Indian English and code-switching (English/Hindi/regional languages) is substantially better.

INT8 quantisation is used to fit the model within the VRAM budget of the RTX 4050 (6 GB) while maintaining acceptable WER.

## Rationale

**Latency**
- API round-trips add 200–800 ms of network overhead per chunk. For 2–3 second audio windows, this pushes total latency to 1–1.5 s, which causes visible caption lag and sign cue delay.
- Local inference on RTX 4050/4060 with `large-v3-turbo` INT8 achieves ~300–500 ms per chunk including audio preprocessing, keeping end-to-end latency under 700 ms — acceptable for live captioning.

**Cost**
- OpenAI Whisper API pricing at launch was $0.006/minute. A 6-hour school day across 30 classrooms accumulates ~$1,080/day or ~$200,000/year for a mid-sized school district. This is prohibitive for an open-source educational tool targeting under-resourced schools.
- Local inference has zero marginal cost per minute after hardware is provisioned.

**Offline capability**
- Schools in Tier 2/3 Indian cities frequently experience internet outages. A dependency on an external API makes the entire accessibility feature unavailable during outages — exactly when a self-hosted fallback would matter most.
- Local faster-whisper continues functioning with no internet connectivity.

**Data privacy**
- Student and teacher audio leaving the school network and being processed by a third-party API creates FERPA/DPDP Act compliance concerns. Local processing keeps all audio within the school's infrastructure.

**Hardware availability**
- RTX 4050 and 4060 are present in the target deployment environment. INT8 quantisation fits `large-v3-turbo` in 4–5 GB VRAM, within the 6 GB limit of the RTX 4050.
- CPU fallback (faster-whisper supports this) allows the system to run on machines without a discrete GPU, at higher latency (~2–4 s per chunk).

## Alternatives Rejected

| Alternative | Reason Rejected |
|---|---|
| **OpenAI Whisper API** | High recurring cost, 200–800 ms added network latency, no offline operation, third-party audio data processing raises privacy concerns. |
| **faster-whisper `large-v3` (FP16 / no quantisation)** | Requires ~10 GB VRAM; exceeds RTX 4050 budget. FP16 on RTX 4060 (8 GB) is feasible but removes the 4050 support tier. INT8 `large-v3-turbo` achieves comparable WER within the 6 GB envelope. |
| **faster-whisper `medium` or `small`** | Lower WER on standard English, but noticeably worse on Indian-accented English, code-switching, and low-SNR classroom audio. Accessibility quality would degrade for the primary user population. |
| **Vosk (offline, lightweight)** | WER significantly higher than Whisper large-v3-turbo on Indian English. Not suitable for real-time captioning where accuracy is an accessibility requirement. |
| **AssemblyAI / Deepgram real-time ASR API** | Same objections as OpenAI API (cost, latency, offline, privacy) plus less control over Indian English fine-tuning. |
| **Azure Cognitive Services Speech** | On-premises container option exists but is expensive to license, complex to deploy, and offers no accuracy advantage over faster-whisper for this use case. |

## Consequences

**Positive**
- Zero marginal cost per transcription minute — sustainable for free/open-source deployment in schools.
- Fully offline — captions and ISL cues continue functioning during internet outages.
- All audio remains on-premises; no third-party data processing required.
- End-to-end latency budget met on RTX 4050/4060 hardware.
- Model weights can be cached locally; no API key management or rate limit handling.

**Negative**
- Requires a GPU or a reasonably powerful CPU on the deployment machine. Very low-spec hardware (Raspberry Pi, old i3) will have 4+ second latency, degrading the live captioning experience.
- The school or administrator must handle model download (~1.5 GB for INT8 `large-v3-turbo`) and Python/CUDA environment setup. This is a higher deployment burden than a pure API integration.
- Model updates (e.g., a hypothetical `large-v4`) require manual upgrade steps, unlike an API where the provider silently upgrades.
- If the deployment machine lacks a CUDA-capable GPU, inference falls back to CPU with higher latency. This must be clearly communicated in deployment documentation.
