# Demo runbook — showing the backend actually working

Two scripts, both verified working on this machine.

| Script | Needs | Risk | Shows |
| --- | --- | --- | --- |
| `pipeline_demo.py` | Redis only | **none** — instant | English → ISL gloss → sign clips |
| `stream_demo.py` | Redis + Postgres + API | low — takes ~30 s | the whole pipeline, audio in / signs out |

Run `pipeline_demo.py` first. It is instant, it never fails, and it is the part
that shows actual intelligence. Keep `stream_demo.py` for the finish.

---

## Before the mentor arrives (10 minutes)

```bash
# 1. Postgres + Redis
docker compose up -d postgres redis
docker ps                       # both must say (healthy)

# 2. Start the API — leave this terminal open and visible
cd services/api
venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# 3. In a second terminal, prove it is alive
curl http://localhost:8000/health
# {"status":"ok","database":"ok","redis":"ok"}

# 4. Warm the Whisper model up ONCE so the demo is not slow
cd ../..
services/api/venv/Scripts/python demo/stream_demo.py --tail 12
```

Step 4 matters. The very first run downloads and loads the model (~15 s). Do it
before the mentor is watching, not during.

If the audio file is missing, regenerate it with Windows text-to-speech:

```powershell
powershell -File demo/make_audio.ps1
```

---

## The demo, in order

### 1 — "The backend is a real service, here is its API" (30 s)

Open **http://localhost:8000/docs** in a browser.

> "This is auto-generated from our code by FastAPI. Every endpoint you see is
> live. Let me call them."

Click **GET /health** → Try it out → Execute. Show `database: ok, redis: ok`.

> "That one call proves the API is up, PostgreSQL is connected, and Redis is
> connected."

### 2 — "It knows Indian Sign Language" (3 min) ← **spend the most time here**

```bash
services/api/venv/Scripts/python demo/pipeline_demo.py
```

Nine sentences convert instantly. Then make it undeniable — **ask the mentor for
a sentence**:

```bash
services/api/venv/Scripts/python demo/pipeline_demo.py --interactive
```

Type whatever they say. Sentences that always land well:

| Type this | Output | Point to make |
| --- | --- | --- |
| `I am not going to class today` | `I CLASS GO NOT TODAY` | object before verb, negation after verb |
| `Where is the library?` | `LIBRARY WHERE` | question word moves to the end |
| `Open your books to page five` | `BOOK OPEN PAGE 5` | "five" → digit, "page" fingerspelled |
| `My name is <mentor's name>` | `MY NAME <NAME>` | their own name spelled letter by letter |
| `How many students are in the class?` | `STUDENT CLASS HOW MANY` | "how many" travels together |

> "This is not a lookup table. spaCy parses the sentence, finds the subject,
> object and verb, and our rules rebuild it in ISL word order. That is why it
> works on a sentence you just invented."

The fingerspelling line is the one to dwell on:

> "There is no ISL sign for your name, so we spell it — p-r-a-v-e-e-n — exactly
> like a human interpreter does. That is why our coverage is never zero. Every
> word can always be shown."

### 3 — "And it does all that from live speech" (1 min)

```bash
services/api/venv/Scripts/python demo/stream_demo.py
```

Narrate while it scrolls:

> "Audio is streaming over a WebSocket in 100 ms chunks, exactly like the
> microphone would send it.
>
> `partial` lines — that's live captioning while the person is still speaking.
>
> `FINAL TEXT` — 0.6 seconds of silence, so the sentence is complete.
>
> `ISL GLOSS` — grammar converted.
>
> `SIGN ACTIONS` — the video clips the avatar will play, with timings.
>
> And every message carries the backend's own measured latency."

### 4 — "And it is tested" (30 s)

```bash
cd services/api && venv/Scripts/python -m pytest tests -q
# 148 passed, 1 skipped
```

> "148 automated tests. They include failure tests — we deliberately break Redis,
> break spaCy, break the LLM, and assert the pipeline still returns something.
> GitHub Actions runs all of this plus linting and type-checking on every commit."

---

## Code to open, if they ask "show me the code"

Open these four in the editor. Nothing else.

| File | Jump to | Say |
| --- | --- | --- |
| `services/api/app/routers/ws.py` | line 230 `_process_audio` | "the whole pipeline in one function: buffer → VAD → ASR → gloss → signs" |
| `services/api/app/services/gloss.py` | line 347 `_apply_isl_rules` | "the ISL grammar rules — subject, object, verb, then negation, then WH-words" |
| `services/api/app/services/sign_mapper.py` | line 222 `_resolve` | "five lookup strategies, fingerspelling as the guaranteed fallback" |
| `services/api/app/services/asr.py` | line 60 `_load_model` | "GPU if available, CPU if not, so it runs anywhere" |

Two details worth pointing out unprompted — they show engineering judgement:

- `ws.py:158` `_enqueue_frame` — "when the queue fills we drop the **oldest**
  audio, not the newest. Falling behind is better than going stale."
- `gloss.py:510` `convert` — "four fallback layers, and this function can never
  raise. A live classroom cannot stop."

---

## Questions they will ask

**"Why does the transcript have small mistakes?"**
> We are running Whisper `base` on CPU because this laptop has no CUDA build of
> PyTorch. The architecture supports `large-v3-turbo` on GPU — it is one
> environment variable, `WHISPER_MODEL`. Accuracy is a hardware question, not a
> design question; the pipeline is identical either way.

**"Why not have AI generate the sign videos directly?"**
> The best published score on the standard ISL dataset is 1.47 BLEU-4 — close to
> unintelligible. Showing a Deaf student wrong signs is worse than showing none.
> So we use real recorded ISL clips and fingerspell anything we lack. It is
> written up in `docs/ADR/ADR-001`.

**"Why WebSocket and not a normal REST API?"**
> REST is request-reply. We need to push captions and sign cues to the student
> continuously without being asked. `docs/ADR/ADR-002`.

**"How many of the 300 words have real video?"**
> One so far — `hello`. The mapping layer is complete and tested against all 300
> entries; downloading clips from ISLRTC is the next phase, and the scripts for
> it are already written in `packages/glossary/scripts/`.

**"What happens if Redis or the OpenAI API goes down?"**
> Nothing breaks. Redis is only a cache — a miss just means we compute it. The
> LLM is only a fallback for sentences the rules cannot parse. We have tests that
> deliberately kill each one.

---

## Do not do these

- Do **not** open a browser tab and say "WebSocket connected". That is what got
  you sent away. Show the *messages flowing*, not the connection state.
- Do **not** run `docker compose up` for the `api` service — there is no
  Dockerfile yet, it will fail. Use `uvicorn` directly, as above.
- Do **not** run `stream_demo.py` cold in front of them. Warm it up first.
