# How to demo the backend to your mentor (not just "WebSocket connected")

Your mentor's complaint is fair: saying "WebSocket connected" is a *status message*, not proof the backend does anything. Below is what to show, in order, and what to say, so they see real data moving through real code.

---

## 0. What your backend actually does (say this in one breath)

"When the teacher speaks, the browser streams raw audio to our FastAPI backend over a WebSocket. The backend detects speech, transcribes it with Whisper, converts the English sentence into ISL gloss word order, maps each gloss word to a sign clip or fingerspells it, and streams the result back to the browser in real time — all before the sentence is even finished."

That's the demo. Everything below just proves each piece of that sentence.

---

## 1. Start everything (terminal, screen-shared)

```bash
docker compose up -d          # postgres + redis + api
cd apps/web && pnpm dev        # next.js frontend on :3000
```

Say: "Postgres stores sessions, Redis caches gloss translations, the API is FastAPI on port 8000."

Then run, in a second terminal:

```bash
docker compose logs -f api
```

Leave this visible the whole demo — every WS connect/audio frame/disconnect logs here. This alone kills "it's just saying connected" because your mentor will watch log lines appear as you speak.

## 2. Prove the API is real, not a mock (30 seconds)

Open `http://localhost:8000/docs` in the browser. Say: "This is auto-generated from our FastAPI route definitions — every endpoint here is live code, not a stub." Point at `/health`, `/sessions`, `/ws/stream/{session_id}`.

Then run:

```bash
curl http://localhost:8000/health
```

Show the JSON: `{"status": "ok", "database": "ok", "redis": "ok"}`. Say: "This isn't hardcoded — it actually pings Postgres and Redis," and point at `services/api/app/routers/health.py` (11 lines, trivial to show it's a real query: `SELECT 1` and `redis_client.ping()`).

## 3. The demo mentors actually want: watch the frames, not the label

1. Open `http://localhost:3000`, start a classroom session.
2. Open Chrome DevTools → **Network tab → WS filter** → click the `ws/stream/<session-id>` connection → **Messages** sub-tab. Do this *before* granting the mic, so your mentor sees the handshake.
3. Grant mic access. Point at the first frame: `{"type": "connected", "session_id": ...}`.
4. **Say "hello"** — this is the one word with a real recorded sign clip (`data/isl_clips/hello.mp4`), so the avatar will actually play a video, not just fingerspell letters. Guaranteed to work.
5. Watch frames appear live in the Messages panel in this order — narrate each one as it lands:
   - Outgoing (↑) binary frames — raw PCM audio chunks leaving the browser mic
   - `{"type": "partial", "text": "hello", ...}` — live transcript, still being spoken
   - `{"type": "final", "text": "hello", "asr_ms": ...}` — Whisper finished, with real latency numbers
   - `{"type": "gloss", "tokens": ["HELLO"], "gloss_ms": ...}` — English → ISL gloss conversion
   - `{"type": "sign_sequence", "actions": [...], "timing": {...}}` — which sign clip to play, with per-stage timing
6. Point at the avatar panel actually playing the hello clip in sync with the sign_sequence frame.

This is the whole pitch: **the mentor watches JSON with real transcribed text and real millisecond timings flow past, not a static "connected" banner.**

If you want a second guaranteed-working sentence, use short, common words from `packages/glossary/priority_words.txt` (e.g. "thank you", "help", "yes", "no") — these will fingerspell letter-by-letter since only "hello" has a recorded video clip today. That's fine to show too — say explicitly: "fingerspelling is the fallback path when we don't have a recorded clip yet; the pipeline never fails, it degrades gracefully." That line makes you look like you understand the system, not like something's missing.

## 4. Walk the code that just ran (this is the "how backend is working" part)

Open these files, in this order, and point at these specific things:

**`services/api/app/routers/ws.py`** — the WebSocket endpoint itself
- Line ~380, `@router.websocket("/ws/stream/{session_id}")` — this is the function that just accepted your connection.
- Line ~230, `_process_audio()` — buffers incoming audio into 1-second windows (`WINDOW_BYTES`) with a 200ms overlap (`OVERLAP_BYTES`) so words don't get cut at chunk boundaries.
- Line ~298, `is_speech()` — runs Silero VAD first, so silence never gets sent to Whisper (saves compute).
- Line ~331, `services.asr.transcribe_chunk(window)` — this is the actual Whisper call, timed (`asr_ms`).
- Line ~250-290, `finalize()` — after 0.6s of silence (`SILENCE_TIMEOUT`), it finalizes the sentence, converts to gloss, maps to signs, and sends all three messages you just watched in DevTools.

Say: "Every message you saw in the Network tab traces to a specific line here — this isn't a black box."

**`services/api/app/services/gloss.py`** — English → ISL gloss
- Lines 1-15 (module docstring) lay out the fallback chain: Redis cache → spaCy rule engine → GPT-4o-mini → raw uppercase words. Say: "We don't call an LLM for every sentence — the rule engine handles normal grammar, GPT is only a fallback for sentences the rules can't parse, and caching means repeated phrases don't cost anything twice."

**`services/api/app/services/sign_mapper.py`** — gloss word → sign clip or fingerspell
- Docstring at top: says exact word → alias → number → prefix match → fingerspell, "fingerspelling always possible, so mapping never fails."

**`apps/web/src/lib/ws-client.ts`** — the frontend client
- Line ~124, `backoffDelay()` — exponential reconnect (1s, 2s, 4s... capped at 30s).
- Line ~236, `handleClose()` — distinguishes a fatal rejection (bad session id, code 4004) from a recoverable drop, so it doesn't retry something that can never succeed.

## 5. Prove it's tested, not just eyeballed

```bash
cd services/api
pytest tests/unit/test_ws.py -v
```

Say: "This is automated — it's not just 'I ran it once and it worked,' it's covered by tests that run in CI on every commit." Then optionally show `.github/workflows/ci.yml` to prove that.

## 6. If you have 60 more seconds: show the architecture decision

Open `docs/ADR/ADR-002-websocket-over-webrtc.md`. Say: "We didn't default to WebSocket — we evaluated WebRTC too and wrote down why WebSocket wins for our scale (under 30 users per classroom, no peer-to-peer need, needs to work through school firewalls)." Mentors respond well to seeing a *decision*, not just an implementation.

---

## If live audio demo is risky (model not loaded, no quiet room, etc.)

Fallback that still proves the backend, no mic needed:

```bash
cd services/api
python test_ws.py
```

This connects directly to `/ws/stream/{session_id}` with a hardcoded session id and prints the raw `connected` frame the server sends — shows the handshake working from a plain script, independent of the frontend. Combine with `pytest tests/unit/test_ws.py -v` and the `/docs` Swagger walkthrough (steps 2 and 5 above) if the full mic-to-avatar demo isn't safe to run live.

---

## One-line answer if they ask "why WebSocket and not just polling/REST"

"REST would mean the browser asks 'anything new?' every X milliseconds — wasteful and laggy. WebSocket is a single open pipe both sides can push through instantly, which is what live captioning needs."
