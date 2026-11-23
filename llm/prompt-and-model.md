# Prompt building, output cleaning, the model, and the offline mind

## What the model sees (`prompt.build`, `prompt.py:134`)

```
[system]  school system_prompt (or gentle.system_prompt)
          + RULES
          + "The person's first name is X. Use it at most once in a while..."   (if a name)
          + SAFETY_NOTE                                                         (if flagged)
          + LOW_NOTE                                                            (if low)
          + "An example of your tone, written for someone else ..." x 1-3       (if room, not gentle)
[system]  running summary of dropped turns                                      (if any)
[user/assistant ...]  recent turns, newest kept first, at most MAX_TURNS (12)
[system]  the lens: a one-off "Private note, not something the person said ..." nudge
```

- `clean_history` keeps only user/assistant with text and **merges consecutive messages
  from the same side** (joined with `\n`).
- **Budget** (`PROMPT_TOKENS`, default 1600): tokens are estimated as
  `ceil(chars / 3.2) + 6` per message. The lens and a full-size summary are reserved first.
  The tone examples go in only if at least 250 tokens would still be left after them ("the
  conversation matters more than the example"). Then turns are added newest first until the
  room or `MAX_TURNS` runs out. The latest message always goes in, cut to fit (at least 200
  chars) if it alone is too long.
- **Running summary** (`running_summary`, `:57`): for dropped turns, "Earlier in this session
  they talked about <up to 4 themes>. They said: "<first 14 words>"; ..." from the last 3
  dropped user messages, capped at 320 chars. Themes come from `offline.detect_themes`.
- **Why the lens goes last**: the long system prompt is identical turn after turn, so
  llama.cpp's slot cache (`cache_prompt: true`) can reuse it; only the tail changes.
- `build` returns `(messages, info)` with `kept`, `dropped`, `tokens` (estimate), `summary`,
  `gentle`, `examples` (whether they fitted). `info` feeds the log line.
- Why 1600: 4096 context / 2 slots = 2048 per request, minus room for the reply
  (`MAX_TOKENS` 220) and estimation error. `CHARS_PER_TOKEN` 3.2 was chosen on the earlier
  Qwen model. On Gemma 4 E2B (llama.cpp `/tokenize` of the templated first-turn prompt, all six
  schools) it's 4.2-4.4 chars/token: an estimate of 825-1197 was 595-879 real tokens, so a full
  1600-token estimate is ~1200 real. Kept at 3.2 on purpose: room to spare, and short prompts
  are faster on the R6S (platform decision 0020).

### `RULES` (`:17`)

Not therapy; 2-5 short sentences, under 110 words; at most one question, at the end;
specific to what they said; never diagnose, name medication or doses, or claim to be a
professional; on danger/self-harm/abuse/medical, point to emergency services, a crisis line or
a professional; don't write the person's lines; no headings, lists or letter greetings; don't
mention being an AI; never offer to meet or talk later.

### The lens (`lens`, `:94`)

Theme = the first theme found scanning the last 3 user messages newest first, else
`general`. Angle = `reflections[theme].angles[user_turns % len]` (rotates by turn count).

| Case | Nudge |
|---|---|
| gentle (playful, dropped act) | set the act aside; one of `gentle.angles`; "plainly warm and kind ... end with one gentle question ... mention someone they trust or a crisis line if serious" |
| low (or flagged, any school) | "be especially gentle: no challenging, no teaching, no rating scales and no exercises"; the angle "softly"; 2-5 sentences, one gentle question; "If it sounds serious, mention that talking to someone they trust or a crisis line can help" (both added for Gemma 4 E2B, decision 0020: Quinn asked to rate worthlessness 0-10, and no non-playful therapist pointed anywhere on "nobody would notice if I didn't come back") |
| school has `moves` | angle + `voice` + "This reply's move: <moves[(turns-1) % len]>" + "2 to 4 sentences, and only one question" |
| default | angle + `voice` (or default) + "2 to 5 sentences, ending with one question" |

`moves` exists because "a small model told 'use one of these tools' uses all of them"
(Quinn on Gemma stacked scale + exception + miracle + step into one reply).

## Cleaning what the model says

Two entry points share the same rules:
- `visible(raw, ...)` (`:323`) while streaming: returns `(text so far, stop)`. Complete
  sentences that pass the checks, then the unfinished tail **only if** it isn't a risky start
  (`RISKY_STARTS`: "as an ai", "i'm a licensed", "as your therapist", ... or a prefix of one),
  doesn't match `BAD`, and has no opening quote or bracket yet (those wait until complete).
- `tidy(raw, ...)` (`:335`) at the end: the validated final reply, or `""` = unusable.

The pipeline:
1. `_prep` (`:222`): cut at special tokens (`<|...|>`, Gemma's `<|turn>`/`<turn|>`/`<end_of_turn>`, `</s>`, `[INST]`) and at a new line
   starting with a role label (`User:`, `Client:`, `Therapist:`, `Q:`, the person's name...),
   or mid-line `User:/Client:/Human:/Patient:`; strip a leading speaker label (including the
   therapist's name), markdown bold/headings/bullets, part labels ("Brag:", "Practical tip:",
   "Question:"...), a "Dear Sam," salutation. A question that ends a paragraph followed by
   more text ends the reply there (`stop = True`).
2. `split_sentences` on `.!?…` plus closing quotes/brackets.
3. Drop sentences that are `_bad` (`:308`): match `BAD`, match `BLEAK`, start with `(` (an
   aside or leaked note), or contain a quoted span of 5+ words (12+ chars) that isn't a
   substring of one of the school's quotes, unless the school has `persona` quotes and the
   sentence has a `SELF_SAID` marker ("As I always say", "my memoir", ...).
4. `_unique`: drop a sentence already in this reply (2+ words).
5. `_cap`: stop at 150 words on a sentence boundary.
6. (`tidy` only) keep an unfinished tail only if under 8 words came before it (with "…");
   otherwise drop it (ran out of tokens mid-sentence). Then `_one_question`: keep only the
   **last** question. Result must have 3+ words.

`BAD` (`:179`) covers: "As an AI" and "I'm an AI/language model/chatbot"; model and vendor
names (openai, qwen, alibaba cloud, gemma, google deepmind); leaked instructions ("2 to 5
sentences", "ending with one question", "private note", "not something the person said",
"angle that may fit"); "licensed/certified ... therapist/doctor"; "I diagnose"; "you have
depression/PTSD/ADHD/..."; doses (`\d+ mg/ml/mcg`), prescribe/dosage; a list of medication
names including melatonin, SSRIs, antidepressants, sleeping pills.

### `dedupe` (`:373`), after `tidy`, against the session

Drops sentences that:
- the therapist already said earlier (4+ words, normalised), or that appear in the school's
  `examples` replies (a small model parrots them);
- are `_retold`: 8+ words with 80% word overlap with an earlier long sentence (Gemma's
  Narcissist retold the same anecdote);
- `_parrots` the person: 5+ words, first person, 85% of words from the last two user
  messages ("I'm so angry! The desk has a two-hour queue...").

Mid-session it also strips a leading "Hello again, Sam." If anything was dropped and fewer
than 6 words remain, it returns `""` and the offline mind answers with `why: "unusable"` (the
page labels it "simpler reply").

Note: `dedupe` runs only on the final text. The streamed deltas may have shown sentences that
`done.text` then leaves out; the page always replaces the bubble with `done.text`.

## The end-of-session prompt

`summary_messages` (`:418`): system = "You are <therapist>. <closing.style or GENTLE_CLOSING>
Never diagnose, never mention medication, never claim to be a licensed professional. Reply
only with JSON." User message = the transcript as `Person: ...` / `<therapist>: ...` lines,
newest kept first within the budget (minus 140), then the ask: `summary` (2-3 warm sentences
starting "Today you", under 70 words) and `takeaway` (one exercise in the school's style, under
45 words). Sent with `response_format: json_schema` (`SUMMARY_SCHEMA`, both strings required).

`tidy_summary` (`:440`): both fields through `tidy` (without the quote allow-list), strip a
"Takeaway:" label, keep at most 3 summary sentences; `None` if empty or longer than 110 /
80 words.

## Model handling (in `app.py`)

| Situation | What happens | Cooldown? |
|---|---|---|
| `LLM_URL` empty | offline mind, `why: none` | no |
| in cooldown (`down_until`) | offline mind, `why: cooldown` | (already) |
| our semaphore full for `QUEUE_WAIT` (15 s) | offline mind for that reply, `why: busy` | no (busy isn't a failure) |
| connect error / non-200 / bad chunk | offline mind, `why: <class or "HTTP n">` | yes |
| no first word in `LLM_TIMEOUT` (45 s) | offline mind, `why: timeout` | yes |
| silence mid-reply > `LLM_GAP_TIMEOUT` (20 s) | keep what arrived if it passes the checks, else `why: unusable` | no (something arrived) |
| answered, but nothing survived the checks | offline mind, `why: unusable` | no |
| answered fine | mode `model`, `model.ok()` clears any cooldown | - |

Cooldown = `LLM_COOLDOWN` (30 s) of offline mind for everyone (`_Model.failed`). Summary
failures also start it; a summary semaphore timeout doesn't. `MAX_STREAMS` is this app's
share only: The Dark Light and the Guide use the same 2 llama.cpp slots, so a Couch request
can still queue inside llama.cpp, which counts against `LLM_TIMEOUT` (the first-word timer
includes queueing).

Expected speed on the R6S is unmeasured. Decision 0018 estimates ~8-10 s for a Couch reply
on Gemma 4 E2B from other people's RK3588 numbers; CLAUDE.md lists "time to first word with
a cold slot, ~800-token prefix" and whether 45 s is right as untested.

## The offline mind (`offline.py`)

Deterministic per input: the RNG is seeded with `sha256(school id | len(history) | text)`,
so the same request gives the same reply.

- `detect_themes` (`:163`): keyword regexes per theme (`KEYWORDS`), some words counting
  double (`STRONG`: died, funeral, lonely, panic, furious, insomnia, debt...), sorted by score
  then `THEMES` order.
- `detect_intent` (`:176`): first match of `quote` ("quote", "quotation", "what would
  Marcus/Seneca/... say", and "saying(s)"/"quotes" only in a request: "give me a saying",
  "any quotes?", "your favourite saying"), `technique`, `advice` (ignored if the message is over 12
  words, so the theme leads), `who`, `thanks`, `goodbye`, `greeting` (whole message),
  `unsure`; else `short` for 1-2 words with no theme; else `None`.
- `reflect` (`:189`): "I feel X" -> "It sounds like you feel X." with pronoun swaps, cut at
  but/because/so/punctuation, 1-9 words, else nothing.
- `_pick` (`:214`): a random option whose filled text doesn't appear in any earlier assistant
  reply; once all are used, anything but the last reply's.

`reply(school, history, name, low, gentle)` (`:254`):
1. low or gentle: gentle quote request -> non-persona quote + gentle question; low, or gentle
   and not a quote/technique/advice request -> `gentle_reply` (`GENTLE_TALK` for
   thanks/goodbye, else ack-or-mirror + gentle angle + gentle question). Gentle-but-not-low
   technique/advice requests fall through to the normal path.
2. Theme: from this message, else the most recent earlier user message with one, else
   `general`.
3. Small-talk intents -> `small_talk[intent]`.
4. `quote` -> a quote for the theme not used yet + a reflection question. Formatted by
   `quote_line`: `“text” — source.` or `As <source> put it, roughly: text` for paraphrases.
5. `technique` / `advice` -> a technique for the theme: "Here's something to try: <name>
   <how>" + "Would that fit your situation?" (advice on odd turns gets a `small_talk.advice`
   lead instead of the closing question).
6. Otherwise: mirror (75%) or a `GENERIC_ACK`, then the school's angle; on every 3rd turn a
   quote, or from turn 5 on every 4th turn (5, 9, ...) a technique, replaces the angle when
   one fits the theme; then a question. On turns 2 and 7 the name may be prefixed.

`summary` (`:325`): top 3 themes over all user messages, one `closing.summary_lines` (with
`{themes}`) + a farewell, and a technique for the top theme as the takeaway; gentle versions
use `GENTLE_SUMMARY`, `GENTLE_FAREWELL`, `GENTLE_TAKEAWAY`. No user text -> "We didn't get far
today, and that's fine. The couch will be here."
