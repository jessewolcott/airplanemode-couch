# Testing, dev setups and releasing

## Tests (`tests/test_couch.py`)

A plain script, no pytest: `python tests/test_couch.py` (from the repo root; `.venv` has the
pins). 69 tests as of 0.2.3, all passing on 2026-11-22. Also `node tests/test_format.mjs` (8 tests: the reply formatter, including every partial stage of streamed replies), run in CI. It prints `ok`/`FAIL` per test and
exits 1 on any failure.

How it works:
- Sets `LLM_URL=""` before importing `app`, adds the repo root to `sys.path`.
- Runs every `test_*` function in file order inside one `TestClient(couch.app)` (`c`).
- Before each test: `couch.LLM_URL` is `http://fake-llm` if the test name starts with
  `test_stream`, `test_model`, `test_quote_requests`, `test_stall`, `test_safety_never`,
  `test_earlier`, `test_status_with` or `test_summary_from`; otherwise `""`. Timeouts
  (`LLM_TIMEOUT`, `GAP_TIMEOUT`, `QUEUE_WAIT`) are set to 1 s, `couch.client` is replaced by an
  `httpx.AsyncClient` over `httpx.MockTransport(fake_llm)`, and the cooldown is cleared.
- **Naming matters**: a new model-path test must start with one of those prefixes or it runs
  with no model.
- `fake_llm` imitates llama.cpp: `/health` (status from `FAKE["health"]`), non-200 via
  `FAKE["status"]`, non-streaming JSON for summaries (`FAKE["json"]`), and SSE chunks from
  `FAKE["pieces"]` with optional `first_delay` and `stall_after`. `use_fake(**kw)` resets
  `FAKE`, `CALLS` (every request path + body) and the model state.
- `events(r)` parses an SSE response into `[(event, data)]`; `chat(...)` posts a reply.

What's covered (by group):
- **Safety**: `POSITIVES` per category and `NEGATIVES` (idioms); fixed messages and
  priority; resource numbers. Low mood: `LOW_POSITIVES` / `LOW_NEGATIVES`, and idioms aren't
  low.
- **School files**: every file valid; the schema rejects broken variants; `public()` hides
  prompts; `fill`; playful/persona/moves/replaces schema rules.
- **Prompt**: budget kept and system prompt always in; short history kept whole; a giant
  message truncated but kept; role merging; lens uses the theme's angle; moves in turn;
  safety note when flagged; low-mood prompt swap; examples fit the default budget.
- **Output cleaning**: boilerplate, role-play, medical claims, length cap, fragments,
  invented quotes, risky starts held back, one question, dedupe, retold anecdotes, BLEAK,
  self-quotes only for persona schools, small-model habits.
- **Offline mind**: theme detection, every school x every theme, intents, quote intent only
  for real requests ("my boss keeps saying ..." is not one), no immediate repeats, summary.
- **API without a model**: page + health + relative URLs, schools endpoint (exact id order
  and playful flags, `max_chars` matches the server and the page uses it), status `none`, guards (403/404/400/413/422), offline reply, fixed safety
  reply, bad names, offline summary.
- **Streaming against the fake**: deltas equal final text, request body (stream,
  cache_prompt, max_tokens, system first, lens last), boilerplate never shown, role-play cut,
  timeout -> fallback + cooldown, busy queue -> fallback without cooldown, error -> fallback, stall keeps what arrived, crisis never
  reaches the model (every school), earlier flag reaches the prompt, status with model,
  summary from model and fallback, quote requests from the file, "saying" in a normal
  sentence reaches the model, renamed school.
- **Playful profiles**: gentle mode offline for every theme, carries over a short follow-up,
  stays on for the session, grief is never a joke (and Stoicism doesn't go gentle on grief),
  stays out of character after a crisis (and the summary is the gentle one), gentle quote
  requests avoid persona quotes, the Narcissist may quote himself.

Tests share module state and run in order; a test that leaves the cooldown or `FAKE` set
can affect the next one (the loop resets the cooldown and client, `use_fake` resets the rest).

## Dev setups

- **Standalone** (`compose.yaml`, project name `couch-dev`): `docker compose up -d --build`
  -> http://localhost:8774. `LLM_URL` defaults to empty, so it's the offline mind unless you
  set it. VS Code tasks: "Standalone: up/down", "Tests: The Couch".
- **With the real model** (from CLAUDE.md): the platform dev stack runs `llm` (Gemma 4 E2B)
  on the `airplanemode` Docker network. Build under your own tag and leave the stack's
  containers alone:
  `docker build -t airplanemode-couch:try .` then
  `docker run --rm --network airplanemode -e LLM_URL=http://llm:8080 -p 8774:8000 airplanemode-couch:try`.
- **Platform dev stack** (`../airplanemode`): `docker compose -f compose.yaml -f
  compose.dev.yaml up -d --build` builds this repo as `airplanemode-couch:dev`; the app is at
  http://localhost:8080/couch/ behind Caddy. The `llm` profile must be on for the model and
  for the app itself (it has `profiles: ["llm"]`).
- Locally Python 3.10 works for the tests (CI and the image use 3.12).

## Image

`Dockerfile`: `python:3.12-slim`, `pip install -r requirements.txt` (fastapi 0.115.6,
uvicorn 0.34.0, httpx 0.28.1), `COPY . .`, unprivileged user `couch` (uid 10001), port 8000,
single uvicorn worker. `.dockerignore` drops `.git`, `.github`, `.vscode`, `.venv`, `tests`,
`__pycache__`, `*.md` (root only), `compose.yaml`, `docs`, `llm/`. About 35 MB in use under the
64 MB limit (README).

## CI (`.github/workflows/image.yml`)

On push to `main`, `v*` tags and pull requests: checkout, Python 3.12, install requirements,
run the tests, then QEMU + buildx and build `linux/arm64,linux/amd64`. Pushes to GHCR (not on
PRs): `ghcr.io/jessewolcott/airplanemode-couch:main` for main, `:X.Y.Z` for tag `vX.Y.Z`.

## Releasing

1. Tests green; check the page in the platform dev stack at `/couch/` (with the model) and at
   phone size; retake `docs/screenshots/` if the UI changed.
2. **Ask Jesse before pushing a `v*` tag** (it publishes the image).
3. Push `vX.Y.Z`; CI publishes the image.
4. In `../airplanemode`: bump the pin in `compose.yaml` (`couch:` service), keep
   `portal/apps.json`'s description and the homepage card (`../airplanemode-site`, generated
   from apps.json) in step.
5. Update the "Released" line in this repo's `CLAUDE.md`.

Released: 0.1.0 (Stoicism + Socialism), 0.2.0 (six therapists, Robin replaced by Mai,
low-mood switch, tuned for Gemma 4 E2B, `moves`), 0.2.1 (quote-intent and busy-queue fixes,
Gemma stop token), 0.2.2 (home button).

## Untested (keep marking it)

- **Real hardware**: speed on the R6S (time to first word with a cold slot and a ~800-token
  prefix; whether `LLM_TIMEOUT` 45 s is right). Platform `docs/testing.md` has the on-device
  checklist item "replies stream with the R6S model (note seconds to first word)".
- **Real phones**: only a phone-sized desktop browser so far. For 0.1 through the dev stack
  with Qwen2.5-1.5B; the 0.2.0 roster through the API against Qwen2.5-1.5B and then Gemma 4
  E2B (42 scripted conversations).
- Non-English input against the safety check (not designed for it).
