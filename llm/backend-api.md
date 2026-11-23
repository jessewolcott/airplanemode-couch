# Backend: `app.py` and the API

All paths are relative to the app root (the platform serves it at `/couch/`). State-changing
calls (`POST`) need the header `X-Couch: 1` (`_guard`, `app.py:116`), else 403
`"Missing X-Couch header."`. It blocks cross-site form posts; it isn't authentication. There
are no accounts and no admin features.

## Endpoints

| Method + path | Line | What it does |
|---|---|---|
| `GET /health` | 254 | `{"ok": true}` |
| `GET /` | 259 | `static/index.html`, `Cache-Control: no-cache` |
| `GET /icon.svg` | 264 | `static/icon.svg` |
| `GET /api/schools` | 269 | `{schools: [public(s)...], aliases, resources, disclaimer, max_chars}` |
| `GET /api/status` | 275 | `{model: bool, state}` |
| `POST /api/reply` | 292 | `text/event-stream` (see below) |
| `POST /api/summary` | 332 | JSON end-of-session notes |

### `GET /api/schools`

- `schools`: `schools.public(d)` for each school in display order: `id, name, therapist,
  tagline, description, accent, accent2, avatar, opening_lines, handoff_lines, playful,
  playful_note`. No techniques (the page never used them), system prompt, examples, quotes,
  reflections or gentle block (a test checks `system_prompt` never appears).
- `aliases`: `{old id: new id}`, today `{"socialism": "hochiminh"}`.
- `resources`: `safety.RESOURCES` (four `{label, detail}` entries).
- `disclaimer`: `DISCLAIMER` (`app.py:65`), shown on the resources card.
- `max_chars`: `MAX_USER_CHARS` (1500); the page uses it as the textarea's `maxLength`.

### `GET /api/status`

- No `LLM_URL` -> `{"model": false, "state": "none"}`.
- In cooldown -> `{"model": false, "state": "busy"}`.
- Otherwise `GET {LLM_URL}/health` (3 s timeout), cached 15 s in `model.health`:
  200 -> `ready`, 503 -> `loading`, anything else / error -> `offline`.
- Only the page's header label uses it; `reply` doesn't consult it.

### `POST /api/reply`

Body (`Chat`, `app.py:110`): `{school: str<=40, name: str<=60 = "", messages: [{role:
"user"|"assistant", content: str<=4000}] (<=120)}`.

Checks, in order:
1. header (403), 2. school known after alias mapping (404 `"Unknown therapist."`),
3. `clean_name` (bad names silently become ""), 4. `_history` drops blank messages; empty or
last not `user` -> 400 `"The last message must be yours."`, 5. last message > 1500 chars ->
413. A bad role or over-long field fails Pydantic -> 422.

Then the decision chain (`app.py:303-329`):

| Step | Condition | Result `done.mode` |
|---|---|---|
| 1 | `safety.check(last)` non-empty | `safety`: fixed `safety.respond(cats)`, `resources: true`, extra key `safety: cats` |
| 2 | compute `flagged`, `low`, `gentle` | (see below) |
| 3 | `offline.detect_intent(last) == "quote"` and not `low` | `script`: `offline.reply(...)` (a quote from the file) |
| 4 | `not model.usable()` (no URL or cooldown) | `offline`, `why: "none"` or `"cooldown"` |
| 5 | otherwise | `model_reply()` stream: `model`, or `offline` with a `why` |

- `flagged` = any **earlier** user message (not the current one) trips `safety.check`.
- `low` = `_low(history)` (`app.py:137`): `safety.low_mood` on either of the last two user
  messages.
- Playful school override (`app.py:310-317`): `low = True` if grief is the **top** theme of
  any of the last 3 user messages, or if **any** user message in the history sounds low.
- `gentle` = `prompt.gentle_mode(school, low, flagged)` = playful and (low or flagged).

### The SSE protocol

`_sse(event, data)` writes `event: <name>\ndata: <json>\n\n` (`ensure_ascii=False`).
Headers: `Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no`.

| Event | Data | When |
|---|---|---|
| `delta` | `{t: "more text"}` | Model path: the cleaned text grew by appending |
| `replace` | `{text: "all text so far"}` | Model path: cleaning changed earlier text (a sentence was dropped) |
| `done` | `{text, mode, resources, gentle?, why?, safety?}` | Always last. `text` is the final reply |

`done.mode` is one of `model`, `offline`, `safety`, `script`. `why` is only non-null for
`offline` from the model path: `busy` (no semaphore slot within `QUEUE_WAIT`), `timeout`,
an httpx exception class name (`ConnectError`, `ReadTimeout`, ...), `HTTP 503` etc.
(`LLMError` text), `bad stream chunk`, or `unusable` (the model answered but nothing
survived the checks). The early-return offline path sets `why` to `none` or `cooldown`. The
safety path has no `why`/`gentle` keys; the script path has no `why`.

Non-model replies use `_single()`: a `StreamingResponse` of one pre-built `done` event, so
the page parses every reply the same way. (A `meta` event used to come first; nothing read it,
so it was dropped.)

### `model_reply()` (`app.py:194-243`)

1. `prompt.build(school, history, name, PROMPT_TOKENS, flagged, low)` ->
   `(messages, info)`; `gentle = info["gentle"]`.
2. Wait up to `QUEUE_WAIT` for the per-app semaphore (`MAX_STREAMS`, default 2). Timeout ->
   `why = "busy"`.
3. Stream `llm_stream(messages)` inside `contextlib.aclosing`. For each piece: `raw += piece`,
   `prompt.visible(raw, ...)` gives `(shown, stop)`. If `shown` extends what was sent, emit
   `delta`; otherwise emit `replace`. `stop` (role-play, special token, question ending a
   paragraph, or the 150-word cap) breaks the loop, which closes the HTTP stream.
4. Errors: `asyncio.TimeoutError` -> `why = "timeout"`; `httpx.HTTPError`, `LLMError`,
   `OSError` -> `why` = class name or LLMError text. The semaphore is always released.
5. `final = prompt.dedupe(prompt.tidy(raw, ...), history, school["examples"])`.
6. `final` non-empty -> `model.ok()`, mode `model` (even if a timeout or error cut the stream
   short: what arrived is kept).
   Empty and nothing arrived and `why` set (other than `busy`) -> `model.failed(why)`
   (starts the cooldown).
   Empty but something arrived -> `why = "unusable"`, `model.ok()` (no cooldown).
   Either way the offline mind supplies `final`.
7. One log line, then `done`.

`why = "busy"` (our own semaphore full) is not a failure: that reply goes to the offline
mind, but no cooldown starts, so the next phone still tries the model (tested:
`test_model_busy_queue_falls_back_without_cooldown`).

### `llm_stream()` (`app.py:152-182`)

POST `{LLM_URL}/v1/chat/completions` with `max_tokens MAX_TOKENS, temperature 0.6, top_p 0.9,
repeat_penalty 1.1, cache_prompt true, stream true, stop ["<end_of_turn>", "<turn|>", "<|turn>",
"\nUser:", "\nClient:", "\nHuman:", "\nYou:"]`. Non-200 -> `LLMError("HTTP n")`. Reads lines with
`asyncio.wait_for`: `LLM_TIMEOUT` until the first non-empty content piece, then
`GAP_TIMEOUT` per line. Ignores non-`data:` lines, stops at `[DONE]` or a `finish_reason`,
raises `LLMError("bad stream chunk")` on unparsable JSON. The shared `httpx.AsyncClient`
(`app.py:70`) has `Timeout(LLM_TIMEOUT, connect=5)`; tests replace it.

`<end_of_turn>` is Gemma 3's end-of-turn token (it replaced Qwen's `<|im_end|>` after decision
0018); Gemma 4's template uses `<|turn>role ... <turn|>`, so those two were added (decision 0020). llama.cpp normally stops on the model's own end-of-turn token anyway; the stop string
is a backstop in case it leaks as text. The `\nUser:` etc. strings cut role-play whatever the
model.

### `POST /api/summary` (`app.py:331-366`)

Same body and header. No check that the last message is the user's, and no length check
beyond Pydantic's. `flagged` / `low` look at **all** user messages; `gentle` is playful and
(low or flagged).

- If the model is usable and there is a user message: wait for the semaphore (`QUEUE_WAIT`;
  timeout -> skip the model, **no** cooldown). Then `llm_json(prompt.summary_messages(...),
  MAX_TOKENS, prompt.SUMMARY_SCHEMA)`: non-streaming, `temperature 0.5`, `cache_prompt`,
  `response_format: json_schema`, timeout `LLM_TIMEOUT * 2`. `prompt.tidy_summary` validates;
  `None` (unusable) falls back without a cooldown. Exceptions call `model.failed`.
- Fallback: `offline.summary(school, history, name, gentle)` (its `themes` key is dropped).
- Response: `{summary, takeaway, mode: "model"|"offline", resources: flagged, safety_note}`,
  where `safety_note` is a fixed sentence when flagged, else "".

## Small helpers

- `clean_name` (`app.py:128`): collapse whitespace; must match `NAME_RE` (starts with a
  letter, then letters, spaces, `'`, `-`, `.`; up to 30 chars; Unicode letters OK, so "José"
  passes). "Sam:", digits, HTML and long strings become "".
- `_school` maps aliases first, so an old id works everywhere (`reply`, `summary`).
- `_Model.sem()` creates the semaphore lazily per running loop (`app.py:94`).
