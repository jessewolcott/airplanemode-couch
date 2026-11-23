# Gotchas and how to extend

## Gotchas and quirks (as the code stands)

Backend:
- **Quote requests are matched narrowly.** `offline.INTENTS` "quote" matches `quote`/
  `quotation`, "what would X say", and `saying(s)`/`quotes` only in a request ("give me a
  saying", "tell me a saying", "any quotes?", "your favourite saying"). "My boss keeps saying
  I'm lazy" reaches the model (tested both ways). A request phrased some other way falls
  through to the model, whose invented quotes are dropped anyway.
- **A full queue is not a failure.** Waiting longer than `QUEUE_WAIT` for this app's semaphore
  sends that one reply to the offline mind (`why = "busy"`) without starting the cooldown;
  the summary endpoint behaves the same.
- **`MAX_STREAMS` is per app, not per model.** The Dark Light and the Guide share llama.cpp's 2
  slots; time spent queued inside llama.cpp counts against `LLM_TIMEOUT`.
- **Flagged is sticky, low is short (except for playful schools).** Any earlier message that
  tripped the crisis check keeps `SAFETY_NOTE` and the gentle lens on for every school for the
  rest of the session the browser sends (40 messages). Low mood lasts two user turns for
  earnest schools, the whole session for playful ones.
- **Earnest schools have no gentle summary.** After a low or flagged session their notes use
  the school's own `closing.style` / summary lines; only a fixed `safety_note` is added when
  flagged. Only the playful pair switch to plain, kind notes (the README says so).
- **Streamed text can differ from the final text.** `dedupe` and `_one_question` run only on
  the final reply. The page replaces the bubble with `done.text`, so a sentence can vanish at
  the end. If you add a client that keeps deltas, it will show text the server rejected.
- **Old history goes away silently.** The page sends 40 messages, `build` keeps at most 12
  that fit the budget and summarises up to 3 of the dropped user messages in 320 chars.
- **Merged turns.** `clean_history` joins consecutive same-role messages, so a switch
  (assistant handoff line right after an assistant reply) arrives as one assistant message.
- **Token estimate is a guess** (`len / 3.2 + 6`), tuned on the earlier Qwen model; not
  re-measured on Gemma 4 E2B. If prompts overflow the slot, llama.cpp behaviour decides what
  happens (not tested).
- `BAD` blocks the words "qwen" and "gemma" in replies. The stop string is Gemma's
  `<end_of_turn>`; remaining Qwen mentions are history (what was seen on Qwen2.5-1.5B).
- **Summary has looser input checks**: no last-message-must-be-user rule and no 1500-char
  limit (only Pydantic's 4000 per message). An empty history returns the offline "We didn't get
  far today" summary.
- **The offline mind is deterministic**: same school, history length and text -> same reply.
  A "Try again" after an error resends the same thing and gets the same offline answer.
- **Names**: anything not matching `NAME_RE` is dropped silently (no error), so "Sam2" or
  "Dr. Who:" means no name in the prompt.
- **Single worker only.** Several uvicorn workers would each have their own semaphore and
  cooldown. Don't add `--workers`.
- The crisis check is English regex; it errs towards false alarms on purpose.

Page:
- **Relative-URL test is strict**: no `"/api/` string anywhere in the HTML, no `src`/`href`
  that starts with `http:`, `//` or `/x`, and no `http://`/`https://` at all (including in
  comments).
- **The textarea limit comes from the server** (`max_chars` in `api/schools`, set as
  `maxLength` at boot), so it matches the 413 check.
- **Status is re-checked after an offline reply**: at once, then every 30 s for up to six
  checks while the chat is open and the state isn't `ready`/`none`. Otherwise it updates on
  chat open/switch and when a model reply arrives.
- **Avatars are raw HTML.** Loosening `schools.validate`'s avatar checks is an XSS hole.
- Enter sends only on devices with hover; on phones Enter is a newline and the button sends.
- Storage failures are swallowed: no session survives a reload then.

Platform:
- `handle_path /couch/*` strips the prefix: the app's routes are rooted at `/`.
- The app has `profiles: ["llm"]` in the platform compose file: it isn't running at all on the
  GL.iNet profile, and the admin hides it there (decision 0017). The offline mind is still
  needed on the R6S for when the model is loading, busy or down.

## How to extend

### Add or change a school
See `schools.md`. Data only; update `ALL_IDS` in the tests and the README table.

### Add a field every school needs
Put the rule in `schools.validate` / `_optional`, use it in `prompt.py` and/or `offline.py`,
add it to all six files, document it in the README "Adding a school" table, and add a
schema test (a broken variant must raise `SchoolError`).

### Change the safety check
Edit `PATTERNS`/`IDIOMS`/`LOW_MOOD` in `safety.py`; add phrases to `POSITIVES` and
`NEGATIVES` (and `LOW_POSITIVES`/`LOW_NEGATIVES`). Keep `MESSAGES` fixed text; keep `ORDER`
most urgent first. Never send a crisis message to the model.

### Change a model behaviour
- Tone or structure per turn: `prompt.lens` (or a school's `voice`/`moves`).
- Global rules: `prompt.RULES` (every reply's system prompt; keep it short, the model is
  small and the prefix is cached).
- New output filter: add a regex to `BAD` or `BLEAK`, or a step in `_prep`/`tidy`/`dedupe`.
  Remember `visible` must stay consistent with `tidy` (a sentence shown while streaming and
  then dropped causes a `replace`). Add a test in the "cleaning model output" group.
- Sampling: `llm_stream` body (`temperature`, `top_p`, `repeat_penalty`, `stop`).

### Add an endpoint
Put it in `app.py`; call `_guard(request)` on anything that POSTs; resolve schools via
`_school()`; raise `HTTPException(status, "Human sentence.")` (the page shows `detail`). Never
log message text. Use a relative URL in the page and add a test (name it with a fake-model
prefix if it calls the model).

### New env var
Read it at the top of `app.py`, document it in `app.yaml` `env:` and the README settings
table, and set it in the platform `compose.yaml` only if the box needs a non-default.

### Before shipping
`python tests/test_couch.py` passes; try it in the platform dev stack with the model at phone
size; retake `docs/screenshots/` if the UI changed; mark anything not verified on hardware or
real phones as *untested*; ask before pushing a `v*` tag.
