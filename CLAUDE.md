# The Couch (AirplaneMode app): notes for Claude

A therapist simulator: pick a school of thought (Stoicism, Socialism, more as data files), talk,
get a streamed reply from the shared model, or from the rule-based "offline mind" without it.
FastAPI app in `app.py`, one page in `static/index.html`, schools in `schools/*.json`.

Part of AirplaneMode: the platform repo is `../airplanemode`. Read its `CLAUDE.md` for the
environment notes and `docs/app-contract.md` for the rules. `../airplanemode-darklight` is the
other app built around the shared model.

## Commands

```powershell
docker compose up -d --build         # standalone dev: http://localhost:8774 (offline mind unless LLM_URL is set)
python tests/test_couch.py           # tests (CI runs these before building); .venv has the pins
```

To try the real model: the platform dev stack runs `llm` (Qwen2.5-1.5B) on the `airplanemode`
Docker network. `docker run --rm --network airplanemode -e LLM_URL=http://llm:8080 -p 8774:8000 airplanemode-couch:dev`.

## Files

- `safety.py`: the deterministic crisis check and the fixed replies + resources. Runs on every
  user message **before** anything else; a hit never reaches the model.
- `prompt.py`: prompt building and trimming to `PROMPT_TOKENS` (system prompt always kept, a
  running summary of dropped turns, a per-turn "lens" nudge last so the prefix stays cacheable),
  and output cleaning (`visible` while streaming, `tidy` at the end, `dedupe`).
- `offline.py`: themes, intents, reflections, the no-repeat picker, the fallback summary.
- `schools.py`: loading + validation of school files (the app refuses to start on a bad one).

## Rules

- **Safety first, and fixed.** Never let the model write the crisis reply. When changing
  `safety.py`, add phrases to both POSITIVES and NEGATIVES in the tests. Err towards showing
  resources.
- **Store nothing on the box.** No volume, no message text in logs. The browser holds the
  conversation (localStorage) and sends the last 40 messages; the server is stateless.
- **Every model path has a fallback**: no `LLM_URL`, unreachable, 5xx, no first token within
  `LLM_TIMEOUT`, our slots busy past `QUEUE_WAIT`, or an answer the checks throw out. Failures
  (not bad answers) start a 30 s cooldown.
- **Quotes come from the school files**, short, accurate, public-domain translations, with a
  source; mark your own wording `"paraphrase": true`. The model's quotes are dropped unless they
  match the file; "give me a quote" is answered from the file.
- Reply stream protocol (SSE over POST): `meta`, `delta` {t}, `replace` {text}, `done` {text,
  mode, why, resources}. The page treats `done.text` as final.
- Schools are data. New behaviour that every school needs goes in the schema
  (`schools.validate`) and the README table.
- Page: relative URLs only (a test checks), no external anything, touch targets >= 44px.

## Untested

- Real hardware: speed on the R6S (time to first word with a cold slot, ~800-token prefix),
  and whether `LLM_TIMEOUT` 45 s is right there.
- The page has not been driven in a real phone browser yet (streaming via fetch + ReadableStream).

## Releasing

Push a `vX.Y.Z` tag. CI tests, then publishes `ghcr.io/jessewolcott/airplanemode-couch:X.Y.Z`
(arm64 + amd64). **Ask Jesse before pushing a release tag.** Not released yet.
