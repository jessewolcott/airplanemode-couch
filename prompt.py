"""Building what the model sees, and cleaning what it says.

The server is stateless: the browser sends the recent conversation each time. build() keeps
the school's system prompt (always), a short running summary of whatever had to be dropped,
and as many of the latest turns as fit a token budget. The shared model has a 4096-token
context split across 2 slots, so one request gets about 2048 tokens: prompt + reply.

Output is checked before anyone sees it (tidy / visible): role-play of the user is cut off,
"As an AI ..." boilerplate and claims to be a licensed professional are dropped, medication
talk is dropped, and the length is capped at a sentence boundary.
"""
import math
import re

import offline

RULES = (
    "This is a reflective conversation app for fun and reflection on a long journey; it is not "
    "therapy. Rules: reply in 2 to 5 short sentences, under 110 words. Ask at most one question, "
    "at the end. Respond to what the person actually said and be specific to their situation. "
    "Never diagnose, never name or suggest medication or doses, and never claim to be a "
    "therapist, doctor or licensed professional. If they mention danger, self-harm, abuse or a "
    "medical problem, gently encourage them to contact local emergency services, a crisis line "
    "or a professional. Do not write the person's lines, do not use headings, lists or letter "
    "greetings, and do not mention being an AI. You only exist in this chat: never offer to meet or talk later."
)
SAFETY_NOTE = ("Earlier the person said something worrying and was shown crisis resources. Be gentle, "
               "and keep encouraging them to reach out to real people and services.")
LOW_NOTE = ("Right now the person sounds low. Be especially gentle and kind. Never agree with harsh things "
            "they say about themselves, or that nobody would care or notice: gently say that they matter. "
            "If it sounds serious, mention talking to someone they trust or a crisis line.")
DEFAULT_VOICE = "warm and specific to what they said"
CHARS_PER_TOKEN = 3.2      # conservative for English; measured on the earlier Qwen model, not re-measured on Gemma 4 E2B
PER_MESSAGE = 6            # chat-template overhead per message
MAX_TURNS = 12             # never send more than this many recent messages, however short
SUMMARY_CHARS = 320


def tokens(text):
    return math.ceil(len(text or "") / CHARS_PER_TOKEN) + PER_MESSAGE


def clean_history(history):
    """Only user/assistant text, consecutive messages from the same side merged."""
    out = []
    for m in history:
        role, content = m.get("role"), (m.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        if out and out[-1]["role"] == role:
            out[-1] = {"role": role, "content": out[-1]["content"] + "\n" + content}
        else:
            out.append({"role": role, "content": content})
    return out


def running_summary(dropped):
    """A few lines about the turns that didn't fit: themes and the person's own words."""
    users = [m["content"] for m in dropped if m["role"] == "user"]
    if not users:
        return ""
    themes = []
    for u in users:
        for t in offline.detect_themes(u):
            if t not in themes:
                themes.append(t)
    parts = []
    if themes:
        parts.append("Earlier in this session they talked about " + ", ".join(themes[:4]) + ".")
    snippets = []
    for u in reversed(users[-3:]):
        words = u.split()
        snippets.append('"' + " ".join(words[:14]) + ("..." if len(words) > 14 else "") + '"')
    parts.append("They said: " + "; ".join(reversed(snippets)) + ".")
    return " ".join(parts)[:SUMMARY_CHARS]


def gentle_mode(school, low=False, flagged=False):
    """A playful profile drops the act when the person sounds low or was shown crisis resources."""
    return bool(school.get("playful")) and (low or flagged)


def system_prompt(school, name="", flagged=False, gentle=False, low=False):
    parts = [school["gentle"]["system_prompt"] if gentle else school["system_prompt"], RULES]
    if name:
        parts.append(f"The person's first name is {name}. Use it at most once in a while, never in every reply.")
    if flagged:
        parts.append(SAFETY_NOTE)
    if low:
        parts.append(LOW_NOTE)
    return "\n\n".join(parts)


def lens(school, history, low=False, gentle=False):
    """A per-turn nudge: the school's own angle on what the person is talking about.

    It goes last (after their message) so the long, unchanging start of the prompt stays
    cacheable in llama.cpp's slot. When the person sounds low it asks for gentleness instead
    (and a playful profile gets one of its plain, kind lines rather than its act)."""
    users = [m["content"] for m in history if m["role"] == "user"]
    who = school["therapist"]
    if gentle:
        g = school["gentle"]["angles"]
        return ("(Private note, not something the person said: they sound low right now, so set any act, "
                f"jokes and showing off aside for this reply. A kind thought that may fit: {g[len(users) % len(g)]}) "
                f"Now answer their last message as {who}, plainly warm and kind: name what they feel, say it "
                "makes sense, and end with one gentle question. 2 to 5 sentences. If it sounds serious, "
                "mention that talking to someone they trust or a crisis line can help.")
    theme = "general"
    for u in reversed(users[-3:]):
        found = offline.detect_themes(u)
        if found:
            theme = found[0]
            break
    angles = school["reflections"][theme]["angles"]
    angle = angles[len(users) % len(angles)]
    if low:
        return ("(Private note, not something the person said: they sound low right now, so be especially "
                f"gentle: no challenging and no teaching. An angle that may fit, softly: {angle}) "
                f"Now answer their last message as {who}: warm and kind, 2 to 5 sentences, ending with one "
                "gentle question.")
    if school.get("moves"):
        # One move per reply, in turn: a small model told "use one of these tools" uses all of them
        moves = school["moves"]
        move = moves[(len(users) - 1) % len(moves)]
        return (f"(Private note, not something the person said: an angle {who} might take: {angle}) "
                f"Now answer their last message as {who}: {school.get('voice', DEFAULT_VOICE)}. "
                f"This reply's move: {move} 2 to 4 sentences, and only one question, at the end.")
    return (f"(Private note, not something the person said: an angle {who} might take: {angle}) "
            f"Now answer their last message as {who}: {school.get('voice', DEFAULT_VOICE)}, "
            "2 to 5 sentences, ending with one question.")


def build(school, history, name="", budget=1400, flagged=False, low=False):
    """Messages for the model, newest turns first to go in, never over budget (tokens, estimated).

    Order: system prompt (with the school's example replies, for tone), any summary of dropped
    turns, the recent turns, then a short per-turn nudge (lens). `low`: the person sounds low
    (safety.low_mood); a playful profile then uses its gentle voice, without the comic examples.
    Returns (messages, info)."""
    history = clean_history(history)
    gentle = gentle_mode(school, low, flagged)
    system = system_prompt(school, name, flagged, gentle, low)
    examples = [] if gentle else school.get("examples", [])
    style = "".join("\n\nAn example of your tone, written for someone else (never mention it or its details): "
                    f"\"{e['reply']}\"" for e in examples)
    nudge = {"role": "system", "content": lens(school, history, low or flagged, gentle)}
    reserve = tokens(nudge["content"]) + tokens("x" * SUMMARY_CHARS)
    if style and budget - reserve - tokens(system + style) >= 250:
        system += style     # unless the budget is tight: the conversation matters more than the example
    room = budget - reserve - tokens(system)
    kept = []
    for i, m in enumerate(reversed(history)):
        cost = tokens(m["content"])
        if i == 0:
            # the latest message always goes in, cut down if it alone is too long
            if cost > room:
                limit = max(200, int((room - PER_MESSAGE) * CHARS_PER_TOKEN))
                m = {"role": m["role"], "content": m["content"][:limit]}
                cost = tokens(m["content"])
        elif cost > room or len(kept) >= MAX_TURNS:
            break
        kept.append(m)
        room -= cost
    kept.reverse()
    dropped = history[:len(history) - len(kept)]
    summary = running_summary(dropped)
    head = [{"role": "system", "content": system}]
    if summary:
        head.append({"role": "system", "content": summary})
    messages = head + kept + [nudge]
    used = sum(tokens(m["content"]) for m in messages)
    return messages, {"kept": len(kept), "dropped": len(dropped), "tokens": used, "summary": summary,
                      "gentle": gentle, "examples": bool(style) and style in system}


# ---------------- cleaning the model's output ----------------
MAX_WORDS = 150
BAD = re.compile(
    r"\bas an? (?:ai|a\.i\.|artificial|language model|virtual|digital|chat ?bot|machine)"
    r"|\b(?:i'?m|i am) (?:just |only |merely )?(?:an? )?(?:ai|a\.i\.|artificial intelligence|language model|chat ?bot|virtual assistant|computer program)\b"
    r"|\blanguage model\b|\bopenai\b|\bqwen\b|\balibaba cloud\b|\bgemma\b|\bgoogle deepmind\b"
    r"|\b\d+ to \d+ (?:short )?sentences\b|\bending with one question\b|\bthen one question\b|\bprivate note\b"
    r"|\bnot something the person said\b|\bangle that may fit\b"
    r"|\b(?:i'?m|i am|as) (?:a |your )?(?:licensed|certified|registered|qualified|trained) (?:therapist|counsel+or|psychologist|psychiatrist|doctor|physician|professional|clinician)"
    r"|\bi (?:can |would |will )?diagnose\b"
    r"|\byou (?:have|suffer from|might have|may have|probably have|clearly have) (?:clinical |major |an? |severe )?(?:depression|ptsd|adhd|bipolar|ocd|anxiety disorder|generali[sz]ed anxiety|personality disorder|autism|schizophrenia|insomnia disorder)\b"
    r"|\b\d+\s?(?:mg|milligrams?|mcg|ml)\b|\b(?:prescribe|prescribing|prescription|dosage|dose of)\b"
    r"|\b(?:sertraline|zoloft|prozac|fluoxetine|xanax|alprazolam|valium|diazepam|lexapro|escitalopram|ambien|zolpidem|"
    r"melatonin|benzodiazepines?|ssris?|antidepressants?|sleeping pills?|sedatives?|ativan|lorazepam|klonopin|seroquel|lithium)\b",
    re.I)
RISKY_STARTS = ("as an ai", "as an a.i", "as a language model", "as an artificial", "as a virtual",
                "i'm an ai", "i am an ai", "i'm just an ai", "i am just an ai", "i'm only an ai",
                "i'm a licensed", "i am a licensed", "as a licensed", "as your therapist", "as a therapist")
ROLE_WORDS = r"user|client|patient|human|person|me|you|q|a|therapist|assistant|counsel+or"
SPECIAL = re.compile(r"<\|[a-z_]+\|>|<\/?s>|\[/?INST\]", re.I)


def _stop_re(name):
    names = ROLE_WORDS + (("|" + re.escape(name)) if name else "")
    # a new line that starts "User:" (or their name) is the model writing their part: stop there.
    # Mid-line, only the unambiguous role names count.
    return re.compile(rf"(?:\n\s*(?:\*\*)?(?:{names})(?:\*\*)?\s*:|(?:^|\s)(?:User|Client|Human|Patient)\s*:)", re.I)


def split_sentences(text):
    """(complete sentences with their trailing space, the unfinished tail)."""
    out, start = [], 0
    for m in re.finditer(r"[.!?…]+[\"'”’)\]]*(?:\s+|$)", text):
        out.append(text[start:m.end()])
        start = m.end()
    return out, text[start:]


def _risky(tail):
    t = tail.strip().lower().replace("’", "'")
    if not t:
        return False
    return bool(BAD.search(tail)) or any(r.startswith(t) or t.startswith(r) for r in RISKY_STARTS)


def _prep(raw, name, speaker=""):
    """Cut at special tokens / role-play, strip a leading speaker label and markdown."""
    text = SPECIAL.split(raw, maxsplit=1)[0]
    stop = len(text) < len(raw)
    m = _stop_re(name).search(text, 1)
    if m:
        text, stop = text[:m.start()], True
    who = ROLE_WORDS + (("|" + re.escape(speaker)) if speaker else "")
    text = re.sub(rf"^\s*(?:\*\*)?(?:{who})(?:\*\*)?\s*:\s*", "", text, count=1, flags=re.I)
    text = re.sub(r"\*\*|__|^#+\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.M)
    text = re.sub(r"(?im)(?:^\s*|(?<=[.!?] ))(?:and )?(?:now )?(?:for )?(?:the |my )?(?:brag|humble-?brag|anecdote|practical tip|tip|"
                  r"useful tip|suggestion|question|step|small step|next step|the idea|idea)\s*:\s*", "", text)
    # a letter's salutation ("Dear Sam,") isn't how anyone talks in a chat
    text = re.sub(r"^\s*Dear [\w'’ .-]{1,30},[ \t]*\n?\s*", "", text, count=1)
    # a question that ends a paragraph ends the reply: what follows is the model rambling on
    m = re.search(r"\?[\"'”’)]*[ \t]*\n\s*\n\s*\S", text)
    if m:
        text, stop = text[:text.index("?", m.start()) + 1], True
    return text, stop


def _unique(sentences):
    """Drop a sentence the reply already contains ("Oh, Sam! ... Oh, Sam!")."""
    seen, out = set(), []
    for s in sentences:
        n = _norm(s)
        if n and n in seen and len(n.split()) >= 2:
            continue
        seen.add(n)
        out.append(s)
    return out


def _is_question(sentence):
    return sentence.rstrip().rstrip("\"'”’)").endswith("?")


def _one_question(sentences):
    """Keep only the last question. Gemma's Pragmatist asked four or five in one reply (scale,
    exception, miracle, step, and the step again); the rule is one question per reply."""
    asks = [i for i, s in enumerate(sentences) if _is_question(s)]
    if len(asks) <= 1:
        return sentences
    drop = set(asks[:-1])
    return [s for i, s in enumerate(sentences) if i not in drop]


def _cap(sentences):
    out, n = [], 0
    for s in sentences:
        w = len(s.split())
        if n + w > MAX_WORDS and out:
            return out, True
        out.append(s)
        n += w
    return out, False


QUOTED = re.compile(r"[\"“]([^\"”]{12,})[\"”]")
# Never let a therapist (least of all the Nihilist) tell someone their life, or they, don't matter.
BLEAK = re.compile(
    r"\b(?:your|a|any|human|my) life (?:is|was|'s|would be) (?:\w+ )?(?:meaningless|pointless|worthless|not worth (?:living|it))"
    r"|\bnot worth living\b|\byou (?:don't|do not|really don't) matter\b"
    r"|\byou(?:'re| are) (?:\w+ )?(?:worthless|insignificant|nothing|irrelevant|a nobody)\b"
    r"|\b(?:no ?one|nobody) (?:would|will|really) (?:care|notice|miss you)\b|\b(?:no ?one|nobody) cares about you\b"
    r"|\b(?:no|not any|isn't any) (?:reason|point) (?:to|in) (?:keep |carry on |go on )?(?:live|living|go on|going on|being alive|existing)\b"
    r"|\bwhy (?:bother|keep) (?:living|going on|existing)\b|\bmight as well (?:die|give up|not exist|not be here|end it)\b"
    r"|\b(?:death|dying|not existing) (?:is|would be|could be) (?:a relief|the answer|a release|freedom|better)\b"
    r"|\bgive up on (?:life|living|yourself)\b"
    # dismissive about them or the people in their life, or agreeing they'd not be missed
    r"|\b(?:people|they|nobody|no ?one|he|she) (?:don't|do not|wouldn't|won't|doesn't|does not) (?:really )?care (?:if|whether|that|about) you"
    r"|\bnot like (?:she|he|they|anyone|anybody|people|your \w+) (?:really )?cares?\b|\b(?:she|he|they) (?:doesn't|don't) care anyway\b"
    r"|\b(?:simpler|easier|better(?: off)?) (?:if you (?:disappeared|weren't (?:there|here|around)|were gone|left for good|vanished)|without you)\b"
    r"|\b(?:if|as if) (?:today|tomorrow|this) (?:was|were) (?:the|your) last day\b|\blast day (?:ever|of your life|on earth)\b"
    r"|\byour (?:pain|feelings?|grief|sadness) (?:is|are) (?:pointless|meaningless|irrelevant|a waste)\b"
    r"|\b(?:no ?one|nobody) (?:cares|would care|will care|would notice|would miss) (?:if|whether|that|about)\b"
    r"|\bnothing (?:really )?matters any ?more\b",
    re.I)
# A persona's invented self-quotes ("As I always say, ...") are allowed; anyone else's must be in the file.
SELF_SAID = re.compile(
    r"\b(?:as I (?:always |often |once |famously |so often )?(?:say|said|put it|wrote|told \w+)"
    r"|I (?:always|often|once|famously|like to|love to) (?:say|said|tell|told|wrote|write)"
    r"|I(?:'ve| have) always said|my (?:memoir|book|bestseller|podcast|talk|catchphrase|motto|keynote))\b", re.I)


def _bad(sentence, quotes=(), self_quotes=False):
    """Drop a sentence that breaks the rules, or quotes words that aren't in the school's file
    (a small model happily invents a Seneca line; the school's quotes are checked). A school with
    persona quotes may quote itself ("As I always say, ...")."""
    if BAD.search(sentence) or BLEAK.search(sentence) or sentence.lstrip().startswith("("):
        return True
    for m in QUOTED.finditer(sentence):
        said = _norm(m.group(1))
        if len(said.split()) >= 5 and not any(said in _norm(q) for q in quotes):
            if self_quotes and SELF_SAID.search(sentence):
                continue
            return True
    return False


def visible(raw, name="", speaker="", quotes=(), self_quotes=False):
    """What can be shown so far while streaming: (text, stop_generating)."""
    text, stop = _prep(raw, name, speaker)
    sentences, tail = split_sentences(text.lstrip())
    keep = _unique([s for s in sentences if not _bad(s, quotes, self_quotes)])
    keep, capped = _cap(keep)
    words = sum(len(s.split()) for s in keep) + len(tail.split())
    if not capped and tail and not _risky(tail) and not re.search("[\"“(]", tail) and words <= MAX_WORDS:
        keep.append(tail)    # (a sentence with a quote or a bracket waits until it's complete)
    return _squash("".join(keep)), stop or capped


def tidy(raw, name="", speaker="", quotes=(), self_quotes=False):
    """The final, validated reply ("" means: unusable, fall back)."""
    text, _ = _prep(raw, name, speaker)
    sentences, tail = split_sentences(text.strip())
    keep = _unique([s for s in sentences if not _bad(s, quotes, self_quotes)])
    keep, capped = _cap(keep)
    if tail.strip() and not capped and not _bad(tail, quotes, self_quotes):
        words = sum(len(s.split()) for s in keep)
        if words < 8:            # nothing much else: keep the fragment, trailing off
            keep.append(tail.rstrip(" ,;:-") + "…")
        # otherwise the reply ran out of tokens mid-sentence: drop the fragment
    keep = _one_question(keep)
    out = _squash("".join(keep))
    return out if len(out.split()) >= 3 else ""


def _norm(sentence):
    return re.sub(r"[^a-z0-9 ]", "", sentence.lower()).strip()


FIRST_PERSON = re.compile(r"\b(?:i'm|i am|my|me|i've|i was)\b")


def _parrots(sentence, user_words):
    """The therapist saying the person's own words as if they were its own ("I'm so angry! The
    desk has a two-hour queue and I'm stuck...": a small model slips into the person's shoes)."""
    words = _norm(sentence).split()
    return (len(words) >= 5 and FIRST_PERSON.search(sentence.lower().replace("’", "'")) is not None
            and sum(w in user_words for w in words) >= 0.85 * len(words))


def _retold(sentence, long_said):
    """The same long sentence again with a word or two changed (Gemma's Narcissist told the same
    anecdote two turns running: "I once convinced..." / "I remember once telling...")."""
    words = set(_norm(sentence).split())
    return len(words) >= 8 and any(len(words & e) >= 0.8 * len(words) for e in long_said)


def dedupe(text, history, examples=()):
    """Drop sentences the therapist already said earlier in the session, copied from the school's
    example replies (a small model parrots them), or that repeat the person's last message in the
    first person ("" if too little is left)."""
    if not text:
        return ""
    said, long_said = set(), []
    earlier = [m.get("content", "") for m in history if m.get("role") == "assistant"]
    for content in earlier + [e["reply"] for e in examples]:
        for sent in split_sentences(content + " ")[0]:
            if len(sent.split()) >= 4:
                said.add(_norm(sent))
            if len(sent.split()) >= 8:
                long_said.append(set(_norm(sent).split()))
    users = [m.get("content", "") for m in history if m.get("role") == "user"]
    user_words = set(_norm(" ".join(users[-2:])).split())
    if earlier:   # mid-session, "Hello again, Sam." at the top of every reply is a tic: drop it
        text = re.sub(r"^\s*(?:hello|hi|hey)(?: again| there)?(?:,? [\w'’-]{1,30})?[.!]\s+", "", text, count=1, flags=re.I)
    sentences, tail = split_sentences(text + " ")
    keep = [s for s in sentences if _norm(s) not in said and not _retold(s, long_said) and not _parrots(s, user_words)]
    if len(keep) == len(sentences):
        return text
    out = _squash("".join(keep + ([tail] if tail.strip() else [])))
    return out if len(out.split()) >= 6 else ""


def _squash(text):
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------- end of session ----------------
SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}, "takeaway": {"type": "string"}},
    "required": ["summary", "takeaway"],
}


GENTLE_CLOSING = ("Set any act or humour aside: the person has had a hard time. Summarise plainly and warmly "
                  "in the second person, noticing what they carried. The takeaway is one small, kind thing to "
                  "do for themselves, ideally reaching out to someone they trust.")


def summary_messages(school, history, name="", budget=1400, gentle=False):
    history = clean_history(history)
    who = school["therapist"]
    style = GENTLE_CLOSING if gentle else school["closing"]["style"]
    system = (f"You are {who}. {style} Never diagnose, never mention medication, and "
              "never claim to be a licensed professional. Reply only with JSON.")
    lines, room = [], budget - tokens(system) - 140
    for m in reversed(history):
        line = f"{'Person' if m['role'] == 'user' else who}: {m['content']}"
        if tokens(line) > room:
            break
        lines.append(line)
        room -= tokens(line)
    lines.reverse()
    ask = ("Here is the session:\n\n" + "\n".join(lines) +
           "\n\nThe session is ending. Write JSON with two fields. "
           "summary: 2 or 3 warm sentences spoken directly to the person, starting with 'Today you', about what "
           "they brought and what you noticed, under 70 words. Do not repeat earlier replies. "
           "takeaway: one small, specific exercise for tomorrow in your school's style, under 45 words.")
    return [{"role": "system", "content": system}, {"role": "user", "content": ask}]


def tidy_summary(data, name="", speaker=""):
    """Validate the model's summary JSON; None if it isn't usable."""
    if not isinstance(data, dict):
        return None
    s = tidy(str(data.get("summary", "")), name, speaker)
    t = tidy(str(data.get("takeaway", "")), name, speaker)
    t = re.sub(r"^(?:takeaway|exercise|try this)\s*:\s*", "", t, flags=re.I)
    s = "".join(split_sentences(s + " ")[0][:3]).strip() or s     # three sentences at most
    if not s or not t or len(s.split()) > 110 or len(t.split()) > 80:
        return None
    return {"summary": s, "takeaway": t}
