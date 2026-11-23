# Schools: the therapist data files

A school is one JSON file in `schools/`, named `<id>.json`. `schools.load()` (`schools.py:190`)
reads every `*.json` in the folder (bundled `schools/`, or `SCHOOLS_DIR`), validates each,
checks aliases, and returns them sorted by `(order, id)` (missing `order` = 100). A broken
file raises `SchoolError("<file>: <reason>")` at import, so the app refuses to start and CI
fails. An empty folder is an error too.

## The six (0.2.0)

| Order | id | Therapist · name | Playful | Notes |
|---|---|---|---|---|
| 1 | `empath` | Mira · The Empath | | Rogers paraphrased; 2 examples, 8 quotes (3 paraphrase) |
| 2 | `pragmatist` | Quinn · The Pragmatist | | Only school with `moves` (6); 2 examples |
| 3 | `stoicism` | Aurelia · Stoicism | | The template to copy; 1 example, 19 quotes; no `voice` |
| 4 | `hochiminh` | Mai · Ho Chi Minh's ethics | | `replaces: ["socialism"]`; all 10 quotes paraphrased |
| 5 | `nihilist` | Nico · The Nihilist | yes | `gentle` block; 5 of 9 quotes paraphrased |
| 6 | `narcissist` | Sterling · The Narcissist | yes | `gentle` block; 8 `persona` quotes + Oscar Wilde |

Earnest ones first, playful last, so someone having a hard time meets a gentle listener first
(README). Robin (Socialism, 0.1) was replaced by Mai; the old id maps to `hochiminh`.

## Required fields (`REQUIRED`, `schools.py:25`, and `validate`)

| Field | Type / rule |
|---|---|
| `id` | `^[a-z][a-z0-9-]{1,30}$`, must equal the file name |
| `name`, `therapist`, `tagline`, `description` | non-empty text |
| `accent`, `accent2` | `#rrggbb` |
| `avatar` | one inline `<svg ...>...</svg>`; no `<script`, `on*=` handlers, `javascript:`, `href`, `<foreignObject`, `url(http`; under 6000 chars. The page injects it as raw HTML, so this check is its XSS guard |
| `system_prompt` | 200-1500 chars |
| `examples` | 1-3 `{user, reply}`; each reply <= 120 words ("the model copies their length") |
| `opening_lines` | >= 2 strings; `{, name}` becomes ", Sam" or nothing |
| `handoff_lines` | >= 1 string; `{prev}` is the previous therapist's name (filled by the page) |
| `techniques` | >= 4 `{id (unique), name, how, themes}`; themes from `ALL_THEMES` |
| `quotes` | >= 6 `{text <= 300 chars, source, themes}`; optional `paraphrase: bool`, `persona: bool` |
| `reflections` | for every theme in `ALL_THEMES` (10 themes + `general`): `angles` (>= 3 statements, no `?`) and `questions` (>= 3, each ending `?`); no unknown themes |
| `small_talk` | `greeting, thanks, goodbye, unsure, who, advice, short`, >= 2 each |
| `closing` | `style` (text for the model's summary), `summary_lines` (>= 2, each containing `{themes}`), `farewells` (>= 2) |

Every list-of-strings entry must be non-empty and under 400 characters (`_strings`). `order`,
if present, must be an int.

## Optional fields (`_optional`, `schools.py:143`)

| Field | Rule | Used by |
|---|---|---|
| `voice` | text <= 300 chars | `prompt.lens`: "Now answer ... as X: <voice>". Default `"warm and specific to what they said"` |
| `moves` | 2-8 texts, each <= 300 chars | `prompt.lens`: one move per reply, `moves[(user_turns - 1) % len]` |
| `replaces` | list of valid ids, not its own | `aliases()`: `{old: id}`; an old id may not be a live school or claimed twice |
| `playful` | bool | Start-screen *Playful* pill; enables gentle mode |
| `playful_note` | required if playful; <= 140 chars | Shown next to the pill |
| `gentle` | required if playful: `system_prompt` 200-1500, `angles` >= 3 (no `?`), `questions` >= 3 (ending `?`) | Replaces the act when the person is low or was flagged |
| quote `persona: true` | `source` must start with the therapist's name; no `paraphrase` flag | Self-quotes allowed by the output filter; skipped in gentle quote replies |

`validate` accepts a `gentle` block on a non-playful school, but nothing uses it there
(`prompt.system_prompt` only swaps it in when `gentle_mode` is true, which needs `playful`).

## What each field feeds

- **Model path** (`prompt.py`): `system_prompt` (or `gentle.system_prompt`), `examples` (as
  "An example of your tone ..." appended to the system prompt, unless gentle or the budget is
  tight), `reflections[theme].angles` (the per-turn lens), `voice`, `moves`,
  `gentle.angles`, `closing.style` (summary), `quotes` (the output filter's allow-list),
  `examples[].reply` (dedupe: copied sentences are dropped), `therapist` (speaker label).
- **Offline mind** (`offline.py`): `reflections` (angles + questions), `small_talk`,
  `techniques`, `quotes`, `closing.summary_lines` / `farewells`, `gentle.angles` /
  `gentle.questions`.
- **Page** (`public()`): card text, colours, avatar, opening/handoff lines, technique names
  (sent but not shown by the page as of 0.2.0).

## Adding a school

1. Copy `schools/stoicism.json` (or `schools/narcissist.json` for a playful one) to
   `schools/<newid>.json`; set `id` to match, pick an `order`.
2. Rewrite everything: persona prompt (the shared `RULES` are appended for you, don't repeat
   them), 1-3 short examples, opening/handoff lines, techniques, quotes, all 11 reflection
   themes, small talk, closing.
3. Quotes: short, accurate, public-domain translations with a source. Your own wording or a
   non-public-domain author: `"paraphrase": true` (shown as "As X put it, roughly: ...").
   Invented lines by the therapist: `"persona": true`, source starting with the therapist's
   name. Never attribute invented lines to a real person.
4. If a small model over-does the persona, add `moves` (one per reply) rather than a longer
   prompt; `voice` sets the nudge's tone.
5. Playful: `playful`, `playful_note`, and a real `gentle` block (plain, kind, no act).
6. Update `ALL_IDS` in `tests/test_couch.py` (`test_schools_endpoint` checks the exact list and
   playful flags), the README therapist table, the platform `portal/apps.json` description
   and the homepage card if the roster is described there.
7. Run `python tests/test_couch.py`: `test_school_files_are_valid`, the every-school offline
   tests and the crisis-for-every-school tests will cover it.

`SCHOOLS_DIR` can load a folder of schools without a new image, but it replaces the bundled
set entirely (it doesn't add to it).

## Renaming a school

Add the old id to the new file's `replaces`. `GET /api/schools` returns `aliases`; the page
rewrites `S.school` and each message's `school` on boot; `_school()` maps old ids on the
server. Tested: `test_model_renamed_school_still_answers`,
`test_renamed_school_offline_and_page`, and the `socialism` summary call in
`test_summary_offline`.

## Templates (`schools.fill`, `schools.py:224`)

`{, name}` -> ", Sam" or ""; `, {name}` -> same; `{name}` -> the name or "friend"; any other
`{key}` from keyword args (`{themes}`, `{prev}`). The page has its own `fill()` with the same
rules (`static/index.html:231`).
