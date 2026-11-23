# Architecture

## The pieces

```
 phone browser                          AirplaneMode box (Docker)
 ─────────────                          ─────────────────────────
 /couch/ (index.html) ──Caddy──>  couch:8000  (FastAPI, app.py, 64m, no volume)
   │  GET  api/schools, api/status        │
   │  POST api/reply   (SSE back) ──────> │  safety.check ─ hit ─> fixed reply (never the model)
   │  POST api/summary (JSON back)        │  prompt.build ─> POST http://llm:8080/v1/chat/completions
   │                                      │                        (stream: true, cache_prompt)
   │  localStorage: the whole session     │  offline.reply  <── fallback when the model can't answer
```

- **The Couch backend** (`app.py`): validates the request, runs the safety check, decides
  between a fixed reply, a scripted reply (quote requests), the model, or the offline mind,
  and streams the answer as server-sent events.
- **`prompt.py`**: turns (school, recent turns, name, flags) into chat messages within a token
  budget, and cleans the model's output while it streams and at the end.
- **`safety.py`**: regex-only crisis check with fixed replies and resources, plus `low_mood()`.
- **`offline.py`**: the rule-based "offline mind" (ELIZA-like), driven by the school file.
- **`schools.py`**: loads `schools/*.json` (or `SCHOOLS_DIR`) once at import, validates
  them, sorts by `order`, builds the `{old id: new id}` alias map.
- **Shared model** (platform `llm` service): llama.cpp `server-b12602`, Gemma 4 E2B Q4_K_M
  (decision 0018), 2 slots (`-np 2`), 4096 context (`-c 4096`), so about 2048 tokens per
  request including the reply. Reached at `http://llm:8080` on the internal network.
- **Caddy** (platform `Caddyfile`): `redir /couch /couch/` and
  `handle_path /couch/* { reverse_proxy couch:8000 }`. `handle_path` strips the prefix, so the
  app sees `/`, `/api/reply`, etc. That's why the page uses relative URLs (`api/reply`).
  Caddy passes SSE through without extra config (platform `docs/app-contract.md`).

## Request flow: one message

1. The page appends the user's message to its session, shows a typing indicator, and POSTs
   `api/reply` with `{school, name, messages}` (last 40 user/assistant messages) and the
   header `X-Couch: 1`.
2. `reply()` (`app.py:292`) checks the header, resolves the school (through aliases), cleans
   the name, strips empty messages, requires the last one to be the user's and under 1500
   characters.
3. `safety.check(last)`: a hit returns a single `done` (mode `safety`, `safety: cats`) at once with the fixed
   message and `resources: true`.
4. It works out `flagged` (an earlier user message tripped the safety check), `low` (low mood
   in the last two user messages, or, for a playful school, grief or low mood earlier) and
   `gentle` (a playful school dropping its act).
5. A quote request (and not low) is answered from the school file (mode `script`).
6. Model in cooldown or no `LLM_URL`: the offline mind answers (mode `offline`).
7. Otherwise `model_reply()` streams `delta`/`replace` events as cleaned text
   grows, then `done` with the final, validated text, or the offline mind's text if nothing
   usable came back.
8. The page replaces the streaming bubble with `done.text`, saves it, and adds chips (offline
   mind, simpler reply, safety message, out of character) and the resources card if asked.

## How it plugs into the platform

- Platform `compose.yaml` service `couch`: `profiles: ["llm"]` (model app, not on GL.iNet),
  image `ghcr.io/jessewolcott/airplanemode-couch:0.2.2` (pinned), env
  `LLM_URL: ${LLM_URL-http://llm:8080}`, `mem_limit ${COUCH_MEM:-64m}`, `restart:
  unless-stopped`. No volume.
- Platform `compose.dev.yaml` builds `../airplanemode-couch` as `airplanemode-couch:dev`.
- Platform `portal/apps.json` entry `couch`: path `/couch/`, `uses_llm: true` (decision 0017:
  the admin hides it without the `llm` profile), category Entertainment, colour `#b98fd6`,
  icon `/icons/couch.svg`. Platform CI checks image tag, Caddy route and apps.json entry exist.
- `app.yaml` (this repo): id `couch`, port 8000, path `/couch/`, memory 64m,
  `needs: {llm: optional}`, every env var documented (including `LLM_GAP_TIMEOUT`,
  `LLM_COOLDOWN` and `QUEUE_WAIT`).
- The homepage (`../airplanemode-site`) card is generated from `portal/apps.json`.

## Configuration (environment, read once at import in `app.py:53-61`)

| Var | Default | Meaning |
|---|---|---|
| `LLM_URL` | `http://llm:8080` | Shared model (OpenAI-compatible). Empty = offline mind only. Trailing `/` stripped |
| `LLM_TIMEOUT` | `45` | Seconds to the first word (also httpx's read timeout; summary waits 2x this) |
| `LLM_GAP_TIMEOUT` | `20` | Seconds of silence mid-stream before keeping what arrived |
| `MAX_TOKENS` | `220` | Longest model reply (and summary) in tokens |
| `PROMPT_TOKENS` | `1600` | Estimated token budget for the prompt |
| `LLM_COOLDOWN` | `30` | Seconds of offline mind after a model failure |
| `MAX_STREAMS` | `2` | This app's concurrent model requests (an `asyncio.Semaphore`) |
| `QUEUE_WAIT` | `15` | Seconds to wait for one of those; then that reply alone goes offline (no cooldown) |
| `SCHOOLS_DIR` | bundled `schools/` | Load schools from a mounted folder instead |

Standalone `compose.yaml` sets only `LLM_URL: ${LLM_URL-}` (empty by default) and port
`${PORT:-8774}:8000`, `mem_limit: 64m`.

## Constants worth knowing

| Where | Name | Value | Meaning |
|---|---|---|---|
| `app.py:63` | `NAME_RE` | letter first, then letters/space/`'-.`, max 30 | Anything else becomes no name (prompt-injection guard) |
| `app.py:64` | `MAX_USER_CHARS` | 1500 | Last message limit (413). Sent as `max_chars` in `api/schools`; the page sets the textarea's `maxLength` from it |
| `app.py:105-113` | `Msg`/`Chat` | content <= 4000, <= 120 messages, school <= 40, name <= 60 | Pydantic limits (422) |
| `prompt.py:33` | `CHARS_PER_TOKEN` | 3.2 | Token estimate (Qwen-era; Gemma 4 E2B is ~4.3 chars/token, so it over-counts by ~35%) |
| `prompt.py:34` | `PER_MESSAGE` | 6 | Template overhead per message |
| `prompt.py:35` | `MAX_TURNS` | 12 | Most recent messages ever sent |
| `prompt.py:36` | `SUMMARY_CHARS` | 320 | Running summary of dropped turns |
| `prompt.py:178` | `MAX_WORDS` | 150 | Reply cap, on a sentence boundary |
| `schools.py:17` | `THEMES` | 10 themes + `general` | work, family, relationships, anxiety, sleep, travel, loneliness, anger, grief, money |

## Process model

Single uvicorn worker (`CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]`).
The only in-process state is `model` (`_Model`, `app.py:77`): `down_until` (cooldown),
`health` (cached `/health` result, 15 s), and the semaphore (recreated if the event loop
changes, which matters for tests). Several workers would each get their own semaphore and
cooldown, so `MAX_STREAMS` would multiply. FastAPI docs/OpenAPI are off (`app.py:69`).
Logs are one line per reply (school, mode, why, gentle, low, prompt token estimate, kept and
dropped turns, seconds); never message text.
