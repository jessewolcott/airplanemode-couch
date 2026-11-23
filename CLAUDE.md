# The Couch (AirplaneMode app): notes for Claude

A therapist simulator: pick one of six therapists (the Empath, the Pragmatist, Stoicism, Ho Chi
Minh's ethics, and two playful ones, the Nihilist and the Narcissist; more as data files), talk,
get a streamed reply from the shared model, or from the rule-based "offline mind" without it.
FastAPI app in `app.py`, one page in `static/index.html`, schools in `schools/*.json`.

Part of AirplaneMode: the platform repo is `../airplanemode`. Read its `CLAUDE.md` for the
environment notes and `docs/app-contract.md` for the rules. `../airplanemode-darklight` is the
other app built around the shared model.

## Commands

```powershell
docker compose up -d --build         # standalone dev: http://localhost:8774 (offline mind unless LLM_URL is set)
python tests/test_couch.py           # tests (CI runs these before building); .venv has the pins
node tests/test_format.mjs           # the page's reply formatting (*italic*/**bold**), run from index.html
python evals/persona_eval.py http://127.0.0.1:18080   # the real model: 6 therapists x 4 conversations x 3 (llm/testing-and-release.md)
```

To try the real model: the platform dev stack runs `llm` (Gemma 4 E2B since platform decision 0018) on the `airplanemode`
Docker network. Build under your own tag (the dev stack's own container uses `airplanemode-couch:dev`)
and don't touch the stack's containers: `docker build -t airplanemode-couch:try .` then
`docker run --rm --network airplanemode -e LLM_URL=http://llm:8080 -p 8774:8000 airplanemode-couch:try`.

## Files

- `safety.py`: the deterministic crisis check and the fixed replies + resources. Runs on every
  user message **before** anything else; a hit never reaches the model. Also `low_mood()`, the
  softer signal (hopeless, worthless, "what's the point") that makes every therapist gentler and
  makes the playful ones drop the act (`prompt.gentle_mode`, the school's `gentle` block).
- `prompt.py`: prompt building and trimming to `PROMPT_TOKENS` (system prompt always kept, a
  running summary of dropped turns, a per-turn "lens" nudge last so the prefix stays cacheable),
  and output cleaning (`visible` while streaming, `tidy` at the end, `dedupe`).
- `offline.py`: themes, intents, reflections, the no-repeat picker, the fallback summary.
- `schools.py`: loading + validation of school files (the app refuses to start on a bad one),
  including the optional `voice`, `moves` (one per reply, rotated by `prompt.lens`), `replaces` (old ids -> `ALIASES`), `playful` + `playful_note` +
  `gentle`, and `persona` quotes.

## Rules

- **Safety first, and fixed.** Never let the model write the crisis reply. When changing
  `safety.py`, add phrases to both POSITIVES and NEGATIVES in the tests. Err towards showing
  resources.
- **Store nothing on the box.** No volume, no message text in logs. The browser holds the
  conversation (localStorage) and sends the last 40 messages; the server is stateless.
- **Every model path has a fallback**: no `LLM_URL`, unreachable, 5xx, no first token within
  `LLM_TIMEOUT`, our slots busy past `QUEUE_WAIT`, or an answer the checks throw out. Failures
  (not bad answers, and not a busy queue: that reply alone goes offline) start a 30 s cooldown.
- **Quotes come from the school files**, short, accurate, public-domain translations, with a
  source; mark your own wording `"paraphrase": true`. The model's quotes are dropped unless they
  match the file; "give me a quote" is answered from the file. Only a school with `persona`
  quotes (the Narcissist) may quote itself ("As I always say, ..."); invented lines are only
  ever attributed to the therapist, never to a real person.
- **Playful profiles are safe first.** They drop the act for the rest of the session once
  someone sounds low or was shown crisis resources, and while grief is in the last 3 messages. The Nihilist never says a life or a person doesn't
  matter (`prompt.BLEAK` drops such sentences from any school). The Narcissist never names real
  people and never claims a degree, licence or title. Mai (Ho Chi Minh's ethics) is not Ho Chi
  Minh and stays off politics, governments, parties and war.
- **Renaming a school:** add the old id to the new file's `replaces`; the API and the page map
  saved sessions (socialism -> hochiminh is tested).
- Reply stream protocol (SSE over POST): `delta` {t}, `replace` {text}, `done` {text,
  mode, why, resources, gentle, safety}. The page treats `done.text` as final; `gentle` shows an "out of
  character" chip.
- Schools are data. New behaviour that every school needs goes in the schema
  (`schools.validate`) and the README table.
- Page: relative URLs only (a test checks), no external anything, touch targets >= 44px.
  Replies and session notes render *italic*/**bold** (`inline()` in the page: escape first,
  then add only balanced `<em>`/`<strong>`); safety replies and user text are never formatted.

## Untested

- Real hardware: speed on the R6S (time to first word with a cold slot, ~800-token prefix),
  and whether `LLM_TIMEOUT` 45 s is right there.
- Real phones. The page was driven in a phone-sized desktop browser through the platform's dev
  stack (Caddy + Qwen2.5-1.5B) for 0.1. The six-therapist roster (0.2.0) was tried through the API
  against Qwen2.5-1.5B, then against Gemma 4 E2B (42 scripted conversations): on Gemma the
  playful pair hold character and drop it when they should; the Pragmatist stacked all his
  tools into one reply until he got `moves` (one tool per reply, in turn; `tidy` also keeps
  only the last question). Rechecked with `evals/persona_eval.py` (platform decision 0020): clean; the low lens
  now also asks for no rating scales and a crisis line if serious (Mai still rarely mentions one).

## Releasing

Push a `vX.Y.Z` tag. CI tests, then publishes `ghcr.io/jessewolcott/airplanemode-couch:X.Y.Z`
(arm64 + amd64). **Ask Jesse before pushing a release tag.** Released: 0.1.0; 0.2.0 (six therapists, Robin replaced by Mai, low-mood switch, tuned for
Gemma 4 E2B); 0.2.1 (quote-intent and busy-queue fixes, Gemma stop token); 0.2.2 (home button); 0.2.3 (phone header, *italic*/**bold** in replies); 0.2.4 (low-mood nudge points to help, Gemma 4 turn tokens), pinned in the platform's `compose.yaml`. On a release: bump that pin, and keep the
platform's `portal/apps.json` description and the homepage card in step (homepage: change
English, update all six translations, run `tools/build_i18n.py` and `tools/check_i18n.py` in
`../airplanemode-site`; its CI fails if they don't match).
