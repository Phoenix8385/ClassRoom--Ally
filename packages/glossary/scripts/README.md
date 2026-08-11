# Glossary scripts

Tooling for the ISL clip pipeline: fetch sign videos, check they are usable,
publish them to the web app, and measure how much of a lesson we can sign.

All four scripts are standalone — they read `isl_glossary.json` directly and do
**not** import the API, so no `.env`, Postgres or Redis is needed.

```
packages/glossary/
├── isl_glossary.json      300 words — the single source of truth
├── priority_words.txt     the ~50 words to fetch first
└── scripts/
    ├── download_signs.py  YouTube → data/isl_clips/
    ├── verify_clips.py    are the downloaded clips usable?
    ├── sync_clips.py      data/isl_clips/ → apps/web/public/signs/
    └── check_coverage.py  how much of a text can we sign?
```

## Requirements

| Tool | Needed by | Install |
| --- | --- | --- |
| `yt-dlp` | `download_signs.py` | `pip install yt-dlp` (already in the API venv) |
| `ffmpeg` / `ffprobe` | trimming, duration checks | https://ffmpeg.org/download.html, then add to `PATH` |

**ffmpeg is optional but strongly recommended.** Without it clips are saved
untrimmed (full lesson videos, tens of MB instead of ~1 MB), `verify_clips.py`
cannot check durations, and `sync_clips.py` writes a default 4000 ms duration
into the manifest. It is currently **not** on this machine's `PATH`.

Run everything from this directory, with the API venv's Python:

```bash
cd packages/glossary/scripts
../../../services/api/venv/Scripts/python download_signs.py --dry-run   # Windows
../../../services/api/venv/bin/python  download_signs.py --dry-run      # macOS/Linux
```

---

## `download_signs.py`

Searches YouTube for each word and saves the best short result to
`data/isl_clips/{word}.mp4`, trimmed to the first 4 seconds.

Per word it tries four queries in order, stopping at the first that yields a
usable video:

1. `ISLRTC {word} Indian Sign Language`
2. `ISL {word} sign language India`
3. `{word} Indian Sign Language tutorial`
4. `ISLRTC {word}`

Videos longer than 60 s are skipped, downloads land in a `.temp_{word}` file
first, and anything under 10 KB is discarded as a broken download. On success
the glossary entry gets `clip_downloaded: true`, `clip_local_path`,
`clip_web_path`, `download_timestamp`, plus the `source_url` and `source_title`
it came from. The glossary is rewritten atomically after every word, so an
interrupted run keeps everything fetched so far.

```bash
python download_signs.py                      # all 300, priority 1 first
python download_signs.py --priority-only      # just priority_words.txt
python download_signs.py --word "good morning"
python download_signs.py --category greeting
python download_signs.py --retry-failed       # everything in failed_words.txt
python download_signs.py --dry-run --max 10   # show the plan, fetch nothing
python download_signs.py --delay 5            # slower, if YouTube rate-limits
python download_signs.py --verbose            # yt-dlp detail in the log
```

| Flag | Meaning |
| --- | --- |
| `--priority-only` | only words listed in `../priority_words.txt` |
| `--word WORD` | one word (quote multi-word entries) |
| `--category CAT` | every word in a glossary category |
| `--retry-failed` | retry `data/isl_clips/failed/failed_words.txt` |
| `--dry-run` | print what would be fetched; works without yt-dlp |
| `--max N` | stop after N words |
| `--delay N` | seconds between downloads (default 2) |
| `--trim-seconds N` | clip length (default 4) |
| `--verbose` | debug logging |

Rate limiting: 2 s between downloads and a 10 s pause every 20, which keeps
YouTube from throttling a full 300-word run. Logs go to the console and to
`logs/download_signs.log`.

> **Clips are not verified to be correct.** Search picks whatever YouTube ranks
> first — often a full lesson video rather than an isolated sign. Check the
> `source_title` / `source_url` recorded in the glossary, and have a signer
> review the priority clips before they are shown to students. A wrong sign is
> worse than fingerspelling.

## `verify_clips.py`

Checks every `data/isl_clips/*.mp4`: size over 10 KB, a real MP4 container
(`ftyp` header), and a duration between 1 and 10 s via ffprobe. Prints a report
and lists every invalid clip with the reason.

```bash
python verify_clips.py
python verify_clips.py --remove-invalid   # quarantine bad clips, queue re-download
python verify_clips.py --strict           # exit 1 when anything is invalid (CI)
```

`--remove-invalid` moves bad clips into `data/isl_clips/failed/`, adds their
words to `failed_words.txt` and clears `clip_downloaded` in the glossary — so a
following `download_signs.py --retry-failed` picks them straight back up.

## `sync_clips.py`

Copies clips into `apps/web/public/signs/` (only ones that changed) and writes
two files the frontend can fetch:

- `index.json` — total, word list, words by category, last updated, coverage %
- `manifest.json` — per word: `path`, `size_bytes`, `duration_ms`, `category`

```bash
python sync_clips.py
python sync_clips.py --force   # re-copy everything
python sync_clips.py --clean   # delete published clips no longer in data/isl_clips
```

## `check_coverage.py`

Scores a text file against the glossary — how much of a real lesson we could
sign, and which missing words to add next.

```bash
python check_coverage.py --input ncert_sample.txt
python check_coverage.py --input ncert_sample.txt --top 40 --show-covered
python check_coverage.py --input lesson.txt --keep-stop-words
```

Articles and auxiliaries are skipped by default, since the gloss converter drops
them before mapping ever happens.

---

## Full run order

```bash
cd packages/glossary/scripts

python download_signs.py --priority-only   # 1. the ~50 words that matter most
python verify_clips.py                     # 2. did they come down clean?
python sync_clips.py                       # 3. publish to the web app
python download_signs.py --retry-failed    # 4. another pass at the misses
python download_signs.py                   # 5. the remaining 250 words
python verify_clips.py                     # 6. check the full set
python sync_clips.py                       # 7. publish everything
```

Steps 1–3 are enough for a working demo. Expect step 5 to take roughly an hour
for 300 words at the default 2 s delay, and to leave a handful of failures —
uncommon words genuinely have no ISLRTC video.

---

## Common errors

**`yt-dlp is not installed`**
`pip install yt-dlp`, or run with the API venv's Python. `--dry-run` works
without it.

**`ffmpeg is not on PATH — clips will be saved untrimmed`**
Not fatal; clips are full videos until you install ffmpeg. Afterwards, delete
the untrimmed clips and re-run, or re-trim in place.

**`no video found` for a word**
The four queries all came up empty or every candidate was over 60 s. Try
`--word "the word"` after adding a better query, fetch it by hand into
`data/isl_clips/{word}.mp4`, or leave it — the mapper fingerspells anything with
no clip, so nothing breaks.

**Two words download the same video**
Logged as a warning (`likely a bad match, review it`). Usually means the search
fell back to a generic lesson video. Delete the wrong one and re-fetch it.

**`HTTP Error 429: Too Many Requests`**
YouTube is throttling. Raise `--delay` to 5–10 and re-run; already-downloaded
words are skipped, so re-running is cheap.

**`This video is not available` in the log**
Routine — several candidates are tried per word. Only a `❌` line means the word
actually failed.

**Boxes or `?` instead of ✅ in the terminal**
The console is not UTF-8. The scripts fall back to `[ok]` / `[!!]` markers; on
Windows `chcp 65001` restores the icons.

**Clips download but the avatar shows nothing**
Check `apps/web/public/signs/` is populated (`sync_clips.py`) and that the
frontend reads `clip_web_path` (`/signs/hello.mp4`), not `clip_path`, which is a
server-side path.
