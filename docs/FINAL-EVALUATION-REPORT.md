# Classroom Ally — Evaluation Report

_Generated 2026-08-16 17:58 UTC_

## Datasets Used

| Dataset | Scale | Source | Role here |
|---|---|---|---|
| ISLTranslate | ~31,000 sentences | Exploration-Lab, IIT Kanpur (ACL 2023) | Real ISL-aligned English for coverage measurement |
| INCLUDE | 263 signs, 4,292 clips | AI4Bharat (ACM MM 2020) | Signer-recorded reference vocabulary |
| Hand-written regression set | 20 sentences | This project | The only text→gloss pairs available |

### An important limitation, stated up front

Neither public dataset contains **text → ISL gloss** pairs. ISLTranslate
aligns ISL *video* with English sentences (schema `uid,text`); INCLUDE is
isolated-sign video, one clip per word. Neither carries gloss notation.

Gloss-engine *accuracy* therefore cannot be measured against either. It is
reported below only against the 20-sentence hand-written set, whose
limitations are stated with it. What the public datasets do support —
vocabulary coverage and dictionary validation — is measured on them at full
scale.

## Gloss Engine Results

### Accuracy (hand-written set)

| Metric | Value |
|---|---|
| Sentences | 20 |
| Exact match | 80.0% |
| Token accuracy | 100.0% |
| Token precision | 100.0% |

**Caveat:** these 20 sentences were written by the project, and several are
drawn from examples in the gloss engine's own source comments. The set is a
regression guard — it catches breakage — not an independent benchmark, and
the figure should not be cited as ISL translation accuracy.

### Coverage (500 real ISLTranslate sentences)

| Metric | Value |
|---|---|
| Sentences tested | 500 |
| Gloss tokens produced | 2162 |
| Compression | 0.63 tokens per English word |
| **Glossary coverage (Tier 1)** | **41.2%** |
| Tokens fingerspelled (Tier 3) | 1271 |
| Sentences needing no fingerspelling | 7.0% |

Exact match is deliberately absent here: with no reference gloss in the
corpus, any such figure would be 0% by construction.

## Sign Dictionary Results

| Metric | Value |
|---|---|
| Our vocabulary | 300 words |
| INCLUDE vocabulary | 263 signs |
| Overlap | 74 words (28.1% of INCLUDE) |
| In INCLUDE, missing from ours | 189 |
| In ours, absent from INCLUDE | 226 |
| Clips actually downloaded | 50 / 300 |

Our clips come from YouTube search results, which `download_signs.py`
documents as unverified. INCLUDE's are recorded by Deaf signers, so the
overlapping words are the subset we can validate against a human reference.

## Latency Results

Measured on `demo_speech.wav` (12 x 1s windows), Whisper `base` on `cpu`.

| Stage | p50 | p95 | max |
|---|---|---|---|
| VAD (Silero) | 16 ms | 20 ms | 21 ms |
| ASR (Whisper) | 824 ms | 1378 ms | 1972 ms |
| Gloss (spaCy) | 5 ms | 6 ms | 6 ms |
| **End-to-end** | 840 ms | 1399 ms | 1995 ms |

Cold start (model load + warm-up): 2485 ms, excluded above.

### Gloss stage in isolation

Over 96 classroom sentences, no audio involved:

- p50 **5.4 ms**
- p95 **7.8 ms**
- mean 5.4 ms

The gloss stage is not a bottleneck; ASR dominates end-to-end latency.

## Conclusion

The rule-based gloss engine works as designed: it applies ISL
Subject-Object-Verb ordering, drops function words, lemmatises content
words, and moves WH-words and negation to the end. It is fast — the gloss
stage runs in single-digit milliseconds — and it degrades safely, never
raising into the caption stream.

The binding constraint is vocabulary, not grammar. Across 500 real
ISLTranslate sentences, only **41.2%** of produced gloss tokens
resolve to a sign clip; the rest fall through to fingerspelling.
Only **7.0%** of sentences avoid fingerspelling entirely.
ADR-001 rejects end-to-end neural generation on the grounds that Tier 1
dictionary lookup handles the majority of classroom content. That claim
is not yet supported by measurement: on general-domain ISL text the
dictionary carries a minority of tokens. The architecture is sound, but
the glossary must grow substantially before the Tier 1 assumption holds.

Dictionary validation is similarly limited. Our vocabulary overlaps
INCLUDE by only 28.1% of INCLUDE's signs, because INCLUDE
covers everyday categories while ours is classroom-specific. Most of our
clips therefore have no independent reference and rest on unverified
YouTube scrapes — a correctness risk for the Deaf students this serves,
and the strongest argument for signer review before deployment.

End-to-end latency is 840 ms per 1s window, which
meets the real-time budget.

**Honest summary of what is proven.** The pipeline is end-to-end functional
and the engineering is measured rather than asserted. What remains unproven
is ISL output *quality*: no public text→gloss corpus exists for ISL, so
translation accuracy has been measured only against a small self-authored
set. Establishing real quality requires a signer-annotated corpus, and that
is the single highest-value next step for this project.

## Reproducing these numbers

```
python services/api/evaluation/datasets/get_isltranslate.py
python services/api/evaluation/datasets/get_include.py
python services/api/evaluation/evaluate_gloss.py --data data/isltranslate/test.json
python services/api/evaluation/test_on_isltranslate.py --limit 500
python services/api/evaluation/verify_against_include.py
python services/api/evaluation/generate_final_report.py
```

Requires `en_core_web_sm`; every script refuses to produce numbers without it.
