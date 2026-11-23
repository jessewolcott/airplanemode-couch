# Safety: the crisis check, low mood, and gentle mode

Three layers, from hardest to softest:

1. **Crisis check** (`safety.check`): a fixed reply and the resources card; the model never
   sees the message.
2. **Low mood** (`safety.low_mood`): no card; every therapist is gentler, playful ones drop
   the act.
3. **Output filter** (`prompt.BLEAK`, `prompt.BAD`): sentences that call a life pointless, or
   that diagnose, prescribe or claim credentials, are dropped from any model reply.

## 1. The crisis check (`safety.py:184`)

```
check(text):
  t = IDIOM_RE.sub(" ", normalise(text))
  for cat in ORDER = (medical, self_harm, harm_others, abuse):
      first match of COMPILED[cat] in t  -> add cat
      (harm_others: skipped if NEGATED matches in the 30 chars before the match)
  return [cats...]   # empty = nothing found
```

- `normalise` (`:58`): NFKC, lower case, curly quotes and backtick to `'`, everything except
  word characters, `'`, whitespace and `.,!?-` becomes a space, spaces collapsed, padded with
  one space each side.
- **Idioms first** (`IDIOMS`, `:72`): figures of speech are blanked out before matching:
  "<thing> is killing me" (with a long `THINGS` list: flight, seat, feet, job, layover, jet
  lag, wifi, deadline, ...), "you're killing me", "dying to/for", "could kill for a",
  "killing time", "killed it", "bored to death", "died of embarrassment", "my phone is dying",
  "dead tired", "deadline(s)", "shoot me a text", "hit me up", "hurt her feelings", "heart
  attack on a plate", "stroke of luck", "overdosed on coffee", "I'll get killed by my mum".
- **Categories** (`PATTERNS`, `:111`):
  - `self_harm`: suicide words, "kill/hurt/cut... myself", kms, unalive, self-harm, end my
    life, end it all, want to die, wish I was dead, better off dead/without me, no reason to
    live, don't want to live/be here anymore/wake up, life isn't worth, can't go on, wrists,
    cutting again, jump off a bridge, too many pills, overdose, disappear forever, goodbye
    note.
  - `harm_others`: intent words + kill/stab/hurt... + `PEOPLE` (pronouns and a long list of
    relations, roles, seatmate, pilot ...); "make them pay"; bomb/shoot up a place; mass
    shooting; hurt my baby/kids. Negation ("I'd never hurt him") skips a match.
  - `abuse`: `ABUSERS` (he/she/they/my partner, parent, boss, coach, carer...) + hits me /
    is hurting me / will kill me; abusive, domestic violence, sexual assault, raped, groomed;
    afraid to go home; not safe at home; touched me inappropriately; won't let me leave;
    took my passport.
  - `medical`: chest pain, heart attack, stroke, can't breathe, short of breath,
    anaphylaxis, allergic reaction, seizure, passed out / unconscious, heavy bleeding,
    choking, face drooping, one-sided numbness, slurred speech, EpiPen, overdose, diabetic
    emergency / hypoglycaemia.
- "Overdose" is in both `self_harm` and `medical`, so it returns both; the medical message
  wins.
- `respond(categories)` (`:198`) returns the `MESSAGES` entry for the first category in
  `ORDER`: medical > self_harm > harm_others > abuse. Every message mentions emergency
  services (a test checks) and ends by offering to keep talking (except medical).
- `RESOURCES` (`:17`): emergency 112 / 911 ("on a plane, tell the cabin crew"), 988 (US and
  Canada), Samaritans 116 123 (UK and Ireland), findahelpline.com (once online). Kept general
  on purpose: the box could be anywhere. A test checks all five numbers/names are present.

### What happens after a hit

- `reply` returns at once: a single `done {text: fixed,
  mode: "safety", resources: true, safety: cats}`. The model isn't called (a test with the
  fake model asserts no completion request, for every school).
- The page shows the reply with a "safety message" chip and appends the resources card.
- The conversation carries on. From then on `flagged` is true for the session (any earlier
  user message that trips `check`), so:
  - the system prompt gets `SAFETY_NOTE` ("Earlier the person said something worrying ...
    keep encouraging them to reach out");
  - the lens uses its low-mood ("be especially gentle") form for every school, because
    `build` passes `low or flagged` to `lens`;
  - playful schools are in gentle mode for the rest of the session;
  - `/api/summary` returns `resources: true` and a fixed `safety_note`.

## 2. Low mood (`safety.py:211-241`)

`low_mood(text)` = any `LOW_MOOD` pattern after the same normalise + idiom removal. Patterns
include: hopeless (not "hopeless at"), worthless, "what's the point" (end of sentence or of
life/trying/...), "don't see the point" (not of the layover/meeting/...), "why do I bother",
"nobody would care/notice", "nobody loves me", "feel empty/numb/like a burden", "dead
inside", "I'm a failure/worthless/broken" (not "at"), "I hate myself", "nothing matters",
"life is meaningless", "give up on myself", "no future", "I'm depressed/miserable", "can't
stop crying", "what's wrong with me", "not good enough", "tired of everything", "can't cope
anymore". Tests: `LOW_POSITIVES` / `LOW_NEGATIVES` in `test_low_mood_check`.

How long it lasts (`app.py`):
- **Every school:** `low` is true when either of the **last two** user messages is low, i.e.
  that turn and the next (`_low`, `app.py:137`).
- **Playful schools:** `low` stays true for the **rest of the session** once any user message
  was low, and also while grief is the top theme of any of the last 3 user messages
  (`app.py:310`; `safety.py`'s low-mood comment says the same).

Effects of `low`:
- system prompt gets `LOW_NOTE` (never agree with harsh self-talk; say they matter; mention
  someone they trust or a crisis line if serious);
- lens: "they sound low right now, so be especially gentle: no challenging, no teaching, no
  rating scales and no exercises", with the theme's angle "softly", and again "if it sounds
  serious, mention someone they trust or a crisis line" (Gemma 4 E2B ignored `LOW_NOTE`'s version
  of that for the four non-playful therapists: 0 of 24 low replies pointed anywhere; decision 0020);
- quote requests aren't scripted (`and not low`), so they go to the model or offline gentle;
- offline mind uses `gentle_reply` (plain acknowledgement + gentle angle + gentle question).

## Gentle mode (playful schools only)

`prompt.gentle_mode(school, low, flagged)` = `playful and (low or flagged)` (`prompt.py:78`).
When on:
- the system prompt is the school's `gentle.system_prompt` instead of the act (plus `RULES`);
- no comic `examples`;
- the lens is the gentle form with one of `gentle.angles` ("set any act, jokes and showing off
  aside ... plainly warm and kind");
- the offline mind answers from `gentle.angles` + `GENTLE_ANGLES` and `gentle.questions`; a
  quote request gets a non-`persona` quote plus a gentle question;
- the summary uses `GENTLE_CLOSING` (model) or `GENTLE_SUMMARY` / `GENTLE_FAREWELL` /
  `GENTLE_TAKEAWAY` (offline), which suggest messaging someone they trust;
- `done.gentle = true`, so the page adds an "out of character" chip.

Earnest schools never enter gentle mode: their summary keeps the school's own closing style
even after a low-mood or flagged session (only `safety_note` is added when flagged).

## 3. The BLEAK filter (`prompt.py:283`)

Applied to every sentence of every model reply (all schools, gentle or not): "your life is
meaningless", "you don't matter", "you're nothing", "nobody would notice/miss you", "no reason
to keep living", "might as well give up", "death would be a relief", "give up on life",
"they don't care about you", "easier without you", "if today were your last day", "your pain
is pointless", "nothing matters anymore". The sentence is dropped, not the reply. Tested in
`test_bleak_lines_are_dropped`. It doesn't apply to offline-mind text (that comes from the
checked school files).

## Changing any of this

- Add every new phrase to the tests: crisis phrases to `POSITIVES[cat]` and near-miss idioms
  to `NEGATIVES`; low-mood to `LOW_POSITIVES` / `LOW_NEGATIVES`.
- Err towards showing resources: a false alarm costs a card; a miss costs much more.
- Never route a crisis message to the model, and never let the model write `MESSAGES`.
- The check is English-only regex. Other languages pass through unchecked (not handled in
  0.2.0).
