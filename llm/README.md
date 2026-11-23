# The Couch: how it's built (LLM / engineer reference)

Checked-in engineering notes, written from the code (release 0.2.2,
2026-11-22). They stay out of the image: `.dockerignore` lists `llm/`, because its `*.md` line
only matches Markdown files at the repo root. If the code and these notes disagree, the code
wins; fix the notes.

## Overview

The Couch is an AirplaneMode app: a "therapist simulator" for every phone on the travel
router's hotspot, with no internet. You pick one of six therapists, talk, and get a reply
streamed (SSE over POST) from the box's shared llama.cpp model, which is Gemma 4 E2B since
platform decision 0018. Without the model (no `LLM_URL`, unreachable, loading, too busy, or an
answer that the output checks throw out) a rule-based **offline mind** (`offline.py`) answers
from the school's own file. It's a toy for reflection, not therapy, and says so.

Each therapist is a **school**: one JSON data file in `schools/` (prompt, example replies,
quotes, techniques, reflections, small talk, closing lines). Adding one needs no code.
`schools.py` validates every file at start-up, and the app refuses to start on a bad one.

Every user message goes through a **fixed, deterministic safety check** (`safety.py`) before
anything else. A hit gets a fixed caring message and a crisis-line card, never the model. A
softer **low mood** check makes every therapist gentler, and makes the two playful ones (the
Nihilist and the Narcissist) drop their act.

The server is **stateless and stores nothing**: no volume, no message text in logs. The browser
keeps the conversation in `localStorage` and sends the last 40 messages with every request.
Backend: `app.py` (FastAPI, ~370 lines) plus `prompt.py`, `safety.py`, `offline.py` and
`schools.py`. The whole UI is one file, `static/index.html` (~565 lines of HTML/CSS/vanilla JS).
On the box it runs at `/couch/` with a 64 MB limit, only on the R6S (`llm`) profile: it's
hidden on the GL.iNet lite profile (platform decision 0017).

Nothing has been tested on real hardware or real phones yet (see `testing-and-release.md`).

## Files in this folder

| File | What it covers |
|---|---|
| [architecture.md](architecture.md) | The pieces, request flow, how it plugs into the platform, config and constants |
| [backend-api.md](backend-api.md) | `app.py`: every endpoint, request validation, the SSE protocol, the reply decision chain |
| [schools.md](schools.md) | The school file format, validation rules, the six schools, how to add or rename one |
| [safety.md](safety.md) | The crisis check, the low-mood check, gentle mode for playful schools, the BLEAK filter |
| [prompt-and-model.md](prompt-and-model.md) | Prompt building and trimming, output cleaning, model calls, cooldown, the offline mind |
| [page.md](page.md) | `static/index.html`: session storage, streaming, chips, menu, switch, export, boot |
| [testing-and-release.md](testing-and-release.md) | Tests, dev setups, Docker image, CI, releasing, platform wiring, what's untested |
| [gotchas-and-extending.md](gotchas-and-extending.md) | Non-obvious behaviour, known quirks, and how to change things safely |

## Source map

| Path | Role |
|---|---|
| `app.py` | FastAPI app: routes, model streaming, fallback chain |
| `prompt.py` | Building what the model sees; cleaning what it says; end-of-session prompt |
| `safety.py` | Crisis check + fixed replies + resources; `low_mood()` |
| `offline.py` | The offline mind: themes, intents, reflections, no-repeat picker, fallback summary |
| `schools.py` | Loading and validating school files; `public()` view; `fill()` templates; aliases |
| `schools/*.json` | The six therapists (empath, pragmatist, stoicism, hochiminh, nihilist, narcissist) |
| `static/index.html`, `static/icon.svg` | The page and its icon |
| `tests/test_couch.py` | 69 tests, plain script (no pytest), fake llama.cpp via `httpx.MockTransport` |
| `tests/test_format.mjs` | 8 node tests of the page's reply formatter (`inline`/`paras`), in CI |
| `Dockerfile`, `requirements.txt`, `.dockerignore` | Image (python:3.12-slim, user `couch` uid 10001) |
| `compose.yaml` | Standalone dev on port 8774 (offline mind unless `LLM_URL` is set) |
| `app.yaml` | AirplaneMode app manifest |
| `.github/workflows/image.yml` | CI: tests, then multi-arch image to GHCR |
| `CLAUDE.md`, `README.md`, `docs/` | Rules, user-facing description, icon + screenshots |
| `../airplanemode/docs/decisions/0016-games-and-couch.md` | The design decision |
| `../airplanemode/docs/decisions/0017-*.md`, `0018-*.md` | Hidden on GL.iNet; Gemma 4 E2B |

## The rules that must not break (from `CLAUDE.md`)

1. **Safety first, and fixed.** The model never writes the crisis reply. When changing
   `safety.py`, add phrases to both POSITIVES and NEGATIVES in the tests. Err towards showing
   resources.
2. **Store nothing on the box.** No volume, no message text in logs. The browser holds the
   conversation and sends the last 40 messages; the server is stateless.
3. **Every model path has a fallback** (no `LLM_URL`, unreachable, 5xx, no first token within
   `LLM_TIMEOUT`, our slots busy past `QUEUE_WAIT`, an answer the checks throw out). Failures,
   not bad answers and not a busy queue, start a 30 s cooldown.
4. **Quotes come from the school files**, short, accurate, public domain, with a source; own
   wording is marked `"paraphrase": true`. Model quotes not in the file are dropped; "give me a
   quote" is answered from the file. Only a school with `persona` quotes (the Narcissist) may
   quote itself; invented lines are only ever attributed to the therapist.
5. **Playful profiles are safe first.** They drop the act for the rest of the session once
   someone sounds low or was shown crisis resources, and while grief leads one of the last 3
   messages. The Nihilist never says a life or person doesn't matter (`prompt.BLEAK`, applied
   to every school). The Narcissist never names real people or claims credentials. Mai (Ho Chi
   Minh's ethics) is not Ho Chi Minh and stays off politics, governments, parties and war.
6. **Renaming a school:** put the old id in the new file's `replaces`; API and page map saved
   sessions (socialism -> hochiminh is tested).
7. **Reply stream protocol:** `delta {t}`, `replace {text}`, `done {text, mode, why,
   resources, gentle, safety}` (the unused `meta` event was dropped). `done.text` is final; `gentle` shows an "out of character" chip.
8. **Schools are data.** Behaviour every school needs goes in the schema (`schools.validate`)
   and the README table.
9. **Page:** relative URLs only (a test checks), no external anything, touch targets >= 44px.
