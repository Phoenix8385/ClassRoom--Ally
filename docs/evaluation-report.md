# Gloss Engine Evaluation Report

_Generated 2026-08-16 16:52 UTC_

- **Corpus:** `C:\Users\Praveen Jawali\Desktop\major_project\ClassRoom--Ally\data\isltranslate\test.json`
- **Sentences tested:** 20
- **LLM fallback:** enabled

## Scores

| Metric | Value |
|---|---|
| Exact match | 75.0% |
| Token accuracy (recall) | 100.0% |
| Token precision | 98.8% |
| Avg tokens — ours | 3.1 |
| Avg tokens — reference | 3.1 |
| Rows without a reference gloss | 0 |

Token accuracy is multiset overlap against the reference, so a system that
emits extra tokens is not penalised by it — read it alongside precision.

## Top mistakes

| Kind | Token | Count |
|---|---|---|
| Added by us | `NEED` | 1 |

## Worst-scoring examples

| English | Reference | Ours |
|---|---|---|
| We need to finish the homework | `WE HOMEWORK FINISH` | `WE HOMEWORK FINISH NEED` |
| Good morning students | `GOOD MORNING STUDENT` | `GOOD MORNING STUDENT` |
| What is your name? | `YOUR NAME WHAT` | `YOUR NAME WHAT` |
| I am not going to class today | `I CLASS GO NOT TODAY` | `I CLASS GO NOT TODAY` |
| Please sit down | `SIT DOWN` | `SIT DOWN` |
| The teacher explained the lesson | `TEACHER LESSON EXPLAIN` | `TEACHER LESSON EXPLAIN` |
| I want water | `I WATER WANT` | `I WATER WANT` |
| Are you hungry? | `YOU HUNGRY` | `YOU HUNGRY` |
| She did not eat the apple | `SHE APPLE EAT NOT` | `SHE APPLE EAT NOT` |
| Where is the library? | `LIBRARY WHERE` | `LIBRARY WHERE` |
| I do not understand | `I UNDERSTAND NOT` | `I UNDERSTAND NOT` |
| Open your books | `BOOK OPEN` | `BOOK OPEN` |
| The exam is tomorrow | `EXAM TOMORROW` | `EXAM TOMORROW` |
| He is not coming to school | `HE SCHOOL COME NOT` | `HE SCHOOL COME NOT` |
| How many students are in the class? | `CLASS STUDENT HOW MANY` | `STUDENT CLASS HOW MANY` |
