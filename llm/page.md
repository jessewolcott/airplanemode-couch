# The page: `static/index.html`

One file: CSS (`:10-164`), markup (`:167-211`), vanilla JS (`:213-563`). No framework, no
external fonts or scripts, no build step. Dark only (`color-scheme: dark`). All URLs are
relative (`api/schools`, `api/reply`, `icon.svg`, `../` for the AirplaneMode home button), which
`test_page_and_health` enforces (it also checks the `a.am-home` link and that the brand points at
`./`): no `"/api/`, no `src`/`href` starting with `http:`, `//` or
`/x`, and no `http://`/`https://` anywhere.

## Header and leaving

The header is shared by both screens: the brand (couch icon + "The Couch"; icon only in the chat
below 520 px), then in the chat the therapist (`#who`) and the session menu button, and always,
at the right end, the AirplaneMode home button `a.am-home#amHome` (`href="../"`, house icon,
44 px, accent focus ring; platform app contract item 10).

- The **brand** goes to the app's own start screen (`href="./"`, the click is handled in JS:
  `showStart()` with the current therapist pre-selected). The conversation is kept: the start
  screen then shows "Back to your conversation with <therapist>" (`#resume` -> `showChat()`).
  If a reply is streaming it asks first and aborts it.
- The **home button** just leaves, because the session is in localStorage and boot resumes it.
  `leaveOk()` asks first only when something would be lost: a reply still arriving (`busy`), or a
  conversation with user messages when localStorage doesn't work (`storageWorks()` probe).
- The header has no `z-index` of its own so the home button (`z-index: 11`) stays above an open
  sheet and its backdrop (9/10) and can be used while a sheet is up.

## Screens

- **Start** (`#start`, `showStart`, `:250`): hero, optional first-name input (`maxlength 30`,
  remembered in `couch.name`), the therapist cards (avatar, name, therapist, tagline,
  description, *Playful* pill + `playful_note`), a "Sit down with <therapist>" button, and a
  "Need real help?" link. Choosing a card sets `--a`/`--a2` to the school's accents.
- **Chat** (`#chat`, `showChat`, `:292`): header with avatar, "Therapist · School", a status
  dot + label; the message log; composer (textarea `maxLength` from `api/schools`' `max_chars`, 1500, Enter sends only on
  devices with hover, i.e. not phones); a disclaimer line with a "Real help" link.
- **Sheets** (bottom sheets, `sheet()`, `:449`): the session menu, switch therapist, real
  help. Escape or a tap on the backdrop closes them.

## The session (`localStorage`)

Key `couch.session.v1` holds `S = {school, name, messages: [...], offlineNoted, started}`.
Message kinds stored locally:

| role | fields | sent to the server? |
|---|---|---|
| `user` | `content` | yes |
| `assistant` | `content, school, mode, gentle` | yes (role + content only) |
| `note` | `content, kind?` (`handoff`) | no |
| `resources` | - | no |
| `summary` | `school, summary, takeaway, resources, safety_note` | no |

`payload()` (`:355`) sends the last 40 user/assistant messages as `{role, content}`. The
server never sees notes, cards or summaries. `store()`/`recall()` swallow storage errors;
without storage the session simply isn't kept across reloads.

Starting a session pushes a random `opening_lines` entry (filled with the name) as an
assistant message with mode `script`, which is then sent back as context on the first reply.
Starting a new one over a conversation with user messages asks for confirmation.

## Sending a message (`send`, `:357`)

1. `busy = true`; append the user message; add a temporary row with a typing indicator.
2. After 7 s with nothing shown: "The on-board model is slow; <therapist> is thinking…".
3. `fetch("api/reply", {method: "POST", headers: {"X-Couch": "1"}})`, read the body with a
   `ReadableStream` reader, split on blank lines, parse `event:`/`data:`:
   `delta` appends to `shown`, `replace` sets it, `done` is kept (other events are ignored). Each
   change redraws the bubble (paragraphs on blank lines, a blinking caret).
4. Non-2xx: the JSON `detail` becomes the error text. If nothing was shown: an error with
   "Try again" (removes the user message and resends). If some text was shown before an
   error, the page keeps what it has (falls through with `done = null`, mode `model`).
5. On completion the temp row is replaced by a saved assistant message with
   `text = done.text` (the server's final, cleaned text). Mode chips:
   `offline` -> "offline mind", `why: unusable` -> stored as mode `simple` -> "simpler reply",
   `safety` -> "safety message" (amber bubble), `gentle` -> "out of character". `model` and
   `script` get no chip.
6. The first offline (not unusable) reply of a session adds a note: "Offline mind: the
   on-board model isn't available, so I'm using simpler responses." (`offlineNoted`).
7. `done.resources` appends the resources card.
8. Status label: an offline (not unusable) reply calls `recheckStatus()`, which asks
   `api/status` at once and then every 30 s (up to six checks) while the chat is open and the
   state isn't `ready` or `none`, so the label recovers when the model comes back. A model
   reply flips it to ready.

Only one request at a time (`busy`). The `AbortController` is only used by "Forget".

## Status

`checkStatus()` (`:309`) calls `api/status` once per `showChat()` (start, switch, boot), and
`recheckStatus()` repeats it after an offline reply (see above). No other polling. Labels: `ready` -> "On-board model" (green dot); `loading` -> "Model warming up ·
offline mind for now"; anything else -> "Offline mind" (amber dot).

## Session menu (`:461`)

- **End session** (`endSession`, `:498`): needs at least one user message; shows "<therapist>
  is writing your session notes…", POSTs `api/summary`, appends a `summary` card ("Session
  notes from <therapist>", the summary, a "Try this" box with the takeaway, the safety note
  if `resources`, buttons Export and New session). On error: a note "Couldn't write the
  notes just now." The session can carry on afterwards.
- **Switch therapist** (`switchTo`, `:489`): sets `S.school`, appends a handoff note
  ("<next> takes over from <prev>") and a `handoff_lines` entry with `{prev}` filled. The
  history is kept and sent to the new therapist; earlier replies keep their own avatar
  (`m.school`).
- **Export as text** (`exportText`, `:518`): a `.txt` download `the-couch-YYYY-MM-DD.txt`
  with a header, each line as "Name: text", notes in brackets, resources and session notes.
- **Real help**: the resources card (labels + details from `api/schools`, plus the
  disclaimer) in a sheet.
- **Forget this conversation** (`forget`, `:537`): confirm, abort any request, clear the
  session, back to the start screen. The remembered first name (`couch.name`) is kept.

## Boot

1. `GET api/schools` -> `SCHOOLS`, `RES`, `DISC`, `ALIAS`. Failure: replaces `main` with
   "Couldn't load The Couch. Check you're on the hotspot and reload."
2. Recall the session; map `S.school` and each message's `school` through `ALIAS` (renamed
   schools keep working).
3. Unknown school or broken shape -> drop the session. A session with user messages resumes in
   the chat; one without (only the opening line) goes back to the start screen with that
   therapist pre-selected.

## Rendering and safety of HTML

- `esc()` escapes all text from the server and the user; `paras()` turns blank-line-separated
  text into `<p>` with `<br>`.
- School avatars are inserted as raw SVG; `schools.validate` (no scripts, handlers, links,
  external URLs, < 6 KB) is what keeps that safe.
- User messages render with `white-space: pre-wrap`; assistant ones as paragraphs.

## Layout notes

- Touch targets are at least 44 px (`.iconbtn`, `.send`, `.btn.small`, `.fine button`,
  `.disc button` (the disclaimer's "Real help", `min-height`/`min-width` 44 px), menu items
  52 px).
- `100dvh`, `env(safe-area-inset-*)`, `interactive-widget=resizes-content` for the phone
  keyboard; content column `min(100%, 720px)`; cards two-up from 620 px.
- `prefers-reduced-motion` turns off animations.
- Tried only in a phone-sized desktop browser (dev stack), not on real phones.
