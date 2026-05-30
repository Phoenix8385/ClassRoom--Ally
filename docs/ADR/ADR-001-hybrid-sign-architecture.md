# ADR 001 — Hybrid Sign Architecture (Dictionary + Avatar + Fingerspelling)

## Status: Accepted

## Context

Classroom Ally needs to render Indian Sign Language (ISL) output from text so that Deaf and hard-of-hearing students can receive classroom content in their primary language. Two broad approaches exist:

1. **End-to-end neural generation** — a sequence-to-sequence model that takes text and directly produces a video or skeletal animation of a signer.
2. **Hybrid lookup-and-compose** — combine a curated sign dictionary (ISLRTC), a parametric avatar renderer (MediaPipe-based), and rule-based fingerspelling as a fallback for out-of-vocabulary words.

The state-of-the-art benchmark for ISL generation is the iSign dataset. The best reported BLEU-4 score on iSign is **1.47**, which means neural models produce output that is largely unintelligible or unreliable compared to human-produced ISL. This is a hard floor set by available training data and model maturity as of 2025–2026.

Deploying an end-to-end neural system at this quality level in an educational context would actively harm comprehension for Deaf users — the core constituency of this feature.

## Decision

Adopt a **three-tier hybrid architecture** for ISL rendering:

1. **Tier 1 — ISLRTC Dictionary lookup**: For every input token, attempt a lookup in the official ISLRTC sign dictionary. If a match exists, play the pre-recorded or pre-animated sign clip.
2. **Tier 2 — MediaPipe avatar composition**: For common grammatical structures and signs not in the dictionary, use a MediaPipe-driven parametric avatar that executes pre-defined motion primitives. This enables grammatical markers (head nods, mouthing) and gloss-level composition.
3. **Tier 3 — Fingerspelling fallback**: For proper nouns, technical terms, and any token with no dictionary or avatar match, render letter-by-letter handshape animation using the ISL manual alphabet.

A lightweight NLP pre-processing step (tokenisation + basic gloss mapping) runs before tier selection to improve dictionary hit rate.

## Rationale

- **Reliability at current SOTA**: BLEU-4 of 1.47 is too low for educational use. A student relying on AI-generated ISL with near-random fidelity faces a worse outcome than no sign support at all. Hybrid lookup uses human-validated signs from ISLRTC, guaranteeing correctness for covered vocabulary.
- **ISLRTC coverage**: The ISLRTC dictionary covers the most frequent educational vocabulary. Tier 1 alone handles the majority of classroom content.
- **Graceful degradation**: The three-tier fallback ensures every word receives some representation — either a correct sign, a composed avatar gesture, or a fingerspelled form that a Deaf user can decode.
- **Maintainability**: Dictionary entries and avatar primitives are auditable and correctable by a sign language expert without retraining a model.
- **Future upgrade path**: When neural ISL generation reaches a usable BLEU threshold, Tier 1/2 lookups can be replaced progressively without architectural changes to the rest of the system.

## Alternatives Rejected

| Alternative | Reason Rejected |
|---|---|
| **End-to-end neural ISL generation (e.g., fine-tuned Transformer on iSign)** | BLEU-4 SOTA of 1.47 is not acceptable for educational use. Output is unreliable; deploying it would mislead and underserve Deaf students. Revisit when BLEU-4 > 10 on iSign or a larger ISL corpus. |
| **Pure fingerspelling for all tokens** | Slow to read, fatiguing for fluent signers. Fingerspelling entire lectures is not practical ISL communication. Acceptable only as a last-resort tier. |
| **Third-party sign synthesis API (e.g., SignAll, Knotwords)** | Vendor lock-in, cost at scale, no ISL-specific coverage, data privacy concerns with student audio/text leaving the system. |
| **Pre-recorded human signer video for all content** | Not generalisable to arbitrary classroom text. Would require a human signer in the loop for every lesson, which is the problem Classroom Ally is solving. |

## Consequences

**Positive**
- Every sign rendered from the ISLRTC dictionary is human-validated and linguistically correct.
- System works offline once dictionary and avatar assets are bundled.
- Auditable: educators or sign language experts can inspect and correct the sign mapping table.
- Low computational cost — tier 1 and tier 3 are lookup/animation, not inference.

**Negative**
- Dictionary coverage is finite; out-of-vocabulary rate increases for highly technical or domain-specific content.
- Fingerspelling fallback (Tier 3) is slower to read than native signs — users will notice quality differences between tiers.
- Gloss mapping (text → ISL gloss order) is non-trivial and requires ongoing linguistic maintenance; incorrect gloss order produces grammatically wrong ISL even with correct individual signs.
- No end-to-end learnable improvement — the system does not get better with more usage data unless the dictionary or avatar primitives are manually expanded.
