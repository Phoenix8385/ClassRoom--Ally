# Gloss Engine Evaluation Report

_Generated 2026-08-16 16:56 UTC_

- **Corpus:** `C:\Users\Praveen Jawali\Desktop\major_project\ClassRoom--Ally\data\isltranslate\test.json`
- **Sentences tested:** 20
- **LLM fallback:** enabled

## Scores

| Metric | Value |
|---|---|
| Exact match | 0.0% |
| Token accuracy (recall) | 88.0% |
| Token precision | 59.8% |
| Avg tokens — ours | 4.6 |
| Avg tokens — reference | 3.1 |
| Rows without a reference gloss | 0 |

Token accuracy is multiset overlap against the reference, so a system that
emits extra tokens is not penalised by it — read it alongside precision.

## Top mistakes

| Kind | Token | Count |
|---|---|---|
| Added by us | `THE` | 7 |
| Added by us | `IS` | 6 |
| Added by us | `TO` | 3 |
| Omitted by us | `STUDENT` | 2 |
| Added by us | `STUDENTS` | 2 |
| Added by us | `PLEASE` | 2 |
| Added by us | `ARE` | 2 |
| Added by us | `DID` | 2 |
| Added by us | `YOUR` | 2 |
| Omitted by us | `GO` | 1 |

## Worst-scoring examples

| English | Reference | Ours |
|---|---|---|
| Open your books | `BOOK OPEN` | `OPEN YOUR BOOKS` |
| The school is closed today | `SCHOOL TODAY CLOSE` | `THE SCHOOL IS CLOSED TODAY` |
| The teacher explained the lesson | `TEACHER LESSON EXPLAIN` | `THE TEACHER EXPLAINED LESSON` |
| Good morning students | `GOOD MORNING STUDENT` | `GOOD MORNING STUDENTS` |
| How many students are in the class? | `CLASS STUDENT HOW MANY` | `HOW MANY STUDENTS ARE IN THE CLASS` |
| He is not coming to school | `HE SCHOOL COME NOT` | `HE IS NOT COMING TO SCHOOL` |
| I am not going to class today | `I CLASS GO NOT TODAY` | `I AM NOT GOING TO CLASS TODAY` |
| I love learning new things | `I THING NEW LEARNING LOVE` | `I LOVE LEARNING NEW THINGS` |
| Where is the library? | `LIBRARY WHERE` | `WHERE IS THE LIBRARY` |
| The exam is tomorrow | `EXAM TOMORROW` | `THE EXAM IS TOMORROW` |
| We need to finish the homework | `WE HOMEWORK FINISH` | `WE NEED TO FINISH THE HOMEWORK` |
| Please write your name | `NAME WRITE` | `PLEASE WRITE YOUR NAME` |
| She is a good teacher | `SHE TEACHER GOOD` | `SHE IS A GOOD TEACHER` |
| Please sit down | `SIT DOWN` | `PLEASE SIT DOWN` |
| Are you hungry? | `YOU HUNGRY` | `ARE YOU HUNGRY` |
