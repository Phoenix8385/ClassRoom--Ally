# Real-Dataset Evaluation — ISLTranslate (IIT Kanpur)

_Generated 2026-08-16 17:47 UTC_

- **Corpus:** `C:\Users\Praveen Jawali\Desktop\major_project\ClassRoom--Ally\data\isltranslate\train.json`
- **Sentences tested:** 500
- **Grammar rules:** active

## Accuracy: not measurable on this corpus

ISLTranslate pairs ISL **video** with English sentences (schema `uid,text`).
It ships no gloss annotations, so there is no reference to score against.
Exact match and token accuracy are therefore **not reported** — computing
them here would yield 0% by construction and would be misread as an engine
result rather than an absent reference.

To get an accuracy number, a signer-annotated gloss corpus is required.

## Measured on the real corpus

| Metric | Value |
|---|---|
| Gloss tokens produced | 2162 |
| Compression | 0.63 tokens per English word |
| **Glossary coverage (Tier 1)** | **41.2%** of tokens have a sign clip |
| Fingerspelled (Tier 3) | 1271 tokens |
| Sentences needing no fingerspelling | 7.0% |
| Empty outputs | 1 |

Glossary coverage is the figure ADR-001 depends on when it claims Tier 1
"handles the majority of classroom content". Note that ISLTranslate is
general-domain (storybook and lesson prose), so this is a lower bound for
classroom vocabulary specifically.

## Most frequent out-of-vocabulary tokens

These fall through to fingerspelling and are the highest-value additions
to the glossary.

| Token | Occurrences |
|---|---|
| `PAGE` | 18 |
| `DASH` | 15 |
| `THAT` | 15 |
| `BLANK` | 14 |
| `THERE` | 13 |
| `HAVE` | 13 |
| `DAY` | 10 |
| `BE` | 10 |
| `THIS` | 9 |
| `PLANT` | 9 |
