"""The "offline mind": a rule-based responder for when the model isn't there.

Used when LLM_URL is empty (the GL.iNet profile), the model is unreachable, or it's too busy
to answer in time. It is ELIZA's grandchild: it spots themes (work, family, sleep, ...) and a
few intents (hello, thanks, "what should I do?"), reflects the person's own words back, and
adds the school's angle, a question, sometimes a quote or a technique, all from the school's
JSON file. It never repeats a line it has already used in the session (it reads the earlier
replies the browser sends), until it runs out.
"""
import hashlib
import random
import re

from schools import THEMES, fill

KEYWORDS = {
    "work": r"work|working|job|jobs|boss|career|office|deadline|deadlines|meeting|meetings|colleague|colleagues|"
            r"coworker|coworkers|co-worker|manager|promotion|fired|laid off|layoff|redundan\w*|burnout|burned out|"
            r"burnt out|overtime|project|inbox|emails?|shift|shifts|clients?|resign\w*|quit my|workload|"
            r"interview|employer|staff|team lead|performance review|startup|business",
    "family": r"family|mom|mum|mother|dad|father|parents?|sister|brother|siblings?|kids?|children|child|son|"
              r"daughter|grandma|grandmother|grandpa|grandfather|aunt|uncle|in-laws?|cousins?|stepmom|stepdad|"
              r"baby|toddler|teenager|home life",
    "relationships": r"partner|boyfriend|girlfriend|husband|wife|spouse|marriage|married|divorce\w*|break ?up|"
                     r"broke up|dating|date|ex|relationship|relationships|love|in love|crush|friends?|friendship|"
                     r"cheat\w*|trust|fight with|argument|argue|arguing|wedding|engaged",
    "anxiety": r"anxious|anxiety|worried|worry|worries|worrying|nervous|panic\w*|stress|stressed|stressful|"
               r"scared|afraid|fear|fears|frightened|overwhelm\w*|overthink\w*|dread\w*|tense|on edge|"
               r"uneasy|what if|can't stop thinking|restless|jittery|freaking out",
    "sleep": r"sleep|sleeping|slept|insomnia|tired|exhausted|exhaustion|awake|jet ?lag|nap|naps|fatigue|"
             r"resting|dreams?|nightmares?|bed|bedtime|3 ?am|can't sleep|drowsy|sleepy|knackered",
    "travel": r"flight|flights|fly|flying|plane|airport|layover|delay|delayed|trip|travel\w*|journey|seat|"
              r"passengers?|luggage|baggage|holiday|vacation|abroad|hotel|turbulence|gate|boarding|"
              r"connection|missed my|cabin|landing|takeoff|take off|time zone|road trip|train|visa",
    "loneliness": r"lonely|loneliness|alone|isolated|isolation|no friends|nobody|no one|left out|"
                  r"disconnected|homesick|by myself|on my own|no one understands|invisible|excluded|"
                  r"miss (?:my|home|people|them)|outsider",
    "anger": r"angry|anger|furious|mad at|mad|rage|raging|annoyed|annoying|irritated|irritating|frustrat\w*|"
             r"resent\w*|hate|hated|pissed|livid|snapped|yelled|shouted|unfair|fed up|sick of|"
             r"rude|disrespect\w*",
    "grief": r"grief|grieving|griev\w*|died|passed away|death|funeral|loss|lost my|mourn\w*|bereave\w*|"
             r"widow\w*|miss (?:him|her)|anniversary of|gone forever|cancer|terminal|put down|"
             r"no longer with us|memorial",
    "money": r"money|rent|debt|debts|bills?|broke|afford|salary|wages?|pay|paid|paycheck|payday|loans?|"
             r"mortgage|savings|budget|expensive|cost|costs|bank|credit card|poor|price|prices|"
             r"bankrupt\w*|overdraft|inflation|cost of living|tax|taxes|income|financ\w*",
}
THEME_RE = {t: re.compile(rf"\b(?:{p})\b") for t, p in KEYWORDS.items()}
# words that count double: they say much more about the theme than "work" or "rest" do
STRONG = {
    "grief": re.compile(r"\b(?:died|passed away|funeral|grief|grieving|mourn\w*|bereave\w*)\b"),
    "loneliness": re.compile(r"\b(?:lonely|loneliness|isolated|homesick)\b"),
    "anxiety": re.compile(r"\b(?:anxious|anxiety|panic\w*|overwhelm\w*)\b"),
    "anger": re.compile(r"\b(?:furious|livid|rage|angry)\b"),
    "sleep": re.compile(r"\b(?:insomnia|can't sleep|jet ?lag)\b"),
    "money": re.compile(r"\b(?:debt|rent|afford|broke)\b"),
}

INTENTS = [
    ("quote", re.compile(r"\b(?:quote|quotation|saying|what would (?:marcus|seneca|epictetus|marx|morris) say)\b")),
    ("technique", re.compile(r"\b(?:exercise|technique|practice|practise|tool|tip|tips|something to try)\b")),
    ("advice", re.compile(r"\b(?:what (?:should|do|can) i do|what do you (?:think|suggest|recommend)|any advice|"
                          r"advice|how do i|how can i|help me|what now|what would you do)\b")),
    ("who", re.compile(r"\b(?:who are you|what are you|are you (?:real|human|a bot|an ai|ai|a robot|a therapist)|"
                       r"your name|is this real)\b")),
    ("thanks", re.compile(r"^(?:ok(?:ay)?,? )?(?:thanks|thank you|thx|ty|cheers|that helps|that helped|"
                          r"appreciate it)\b")),
    ("goodbye", re.compile(r"^(?:ok(?:ay)?,? )?(?:bye|goodbye|good night|goodnight|see you|gotta go|i have to go|"
                           r"that's all|talk later|ttyl)\b")),
    ("greeting", re.compile(r"^(?:hi|hello|hey|hiya|howdy|yo|good (?:morning|afternoon|evening)|greetings)\b"
                            r"[\s!.,]*(?:there|again|aurelia|robin)?[\s!.,]*$")),
    ("unsure", re.compile(r"^(?:i )?(?:don't know|dunno|idk|not sure|no idea|i'm not sure|maybe|"
                          r"i guess|hard to say|nothing really|nothing|whatever)\W*$")),
]

GENERIC_ACK = {
    "work": ["Work sounds like it's taking a lot out of you.", "That's a lot to carry from work.",
             "It sounds like work is never far from your mind right now."],
    "family": ["Family can stir up more than almost anything else.", "That sounds like a hard spot with your family.",
               "Family things run deep."],
    "relationships": ["That sounds painful to sit with.", "Relationships can take up so much room in our heads.",
                      "It sounds like this matters to you a lot."],
    "anxiety": ["That sounds like a lot of worry to hold.", "Anxiety is exhausting, especially when it won't switch off.",
                "It makes sense that you're on edge."],
    "sleep": ["Being short on sleep makes everything heavier.", "Tiredness colours everything.",
              "That sounds draining."],
    "travel": ["Travel can be hard on a person.", "Journeys have a way of stirring things up.",
               "Being in between places can feel unsettling."],
    "loneliness": ["Feeling alone is one of the hardest feelings there is.", "That sounds lonely, and I'm glad you said it.",
                   "Thank you for telling me that."],
    "anger": ["It sounds like you're really frustrated.", "That would make a lot of people angry.",
              "I can hear how much that got to you."],
    "grief": ["I'm so sorry.", "That's a real loss, and grief takes its own time.", "I'm sorry you're going through this."],
    "money": ["Money worries can sit on everything else.", "That sounds stressful.",
              "Money pressure is exhausting."],
    "general": ["I hear you.", "Thank you for sharing that.", "That sounds like a lot.", "Mm, I'm with you."],
}

# Reflect the person's words back, with pronouns swapped: "I feel stuck in my job" -> "you feel stuck in your job".
REFLECT_PATTERNS = [
    (re.compile(r"\bi(?: just| really| kind of| kinda| sort of)? (?:feel|felt|am feeling|'m feeling|have been feeling|'ve been feeling) (?:like |that )?(.+)"),
     ["It sounds like you feel {x}.", "So you're feeling {x}.", "You feel {x}."]),
    (re.compile(r"\bi can(?:'t|not| not) (?:seem to |stop )?(.+)"),
     ["It sounds like you can't {x}, and that's hard.", "Not being able to {x} sounds frustrating."]),
    (re.compile(r"\bi (?:want|need|wish|would like|'d like) (?:to )?(.+)"),
     ["You'd like to {x}.", "Part of you wants to {x}."]),
    (re.compile(r"\bi(?:'m| am)(?: so| really| just| very| quite| a bit| a little| kind of| kinda)? (.+)"),
     ["You're {x}.", "So you're {x}."]),
    (re.compile(r"\bi (?:keep|always|never) (.+)"),
     ["It sounds like a pattern: you keep coming back to this.", "That sounds like it happens a lot."]),
]
SWAPS = {"i": "you", "me": "you", "my": "your", "mine": "yours", "myself": "yourself", "am": "are",
         "i'm": "you're", "i've": "you've", "i'll": "you'll", "i'd": "you'd", "was": "were",
         "you": "I", "your": "my", "yours": "mine", "yourself": "myself", "you're": "I'm", "we": "we"}
STOP_AT = re.compile(r"\s(?:but|because|and then|so|although|though|since|when|which|while)\s|[.!?;,]")


def normalise(text):
    t = (text or "").lower().replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", t).strip()


def detect_themes(text):
    """Themes in this text, most prominent first."""
    t = normalise(text)
    scores = {}
    for theme, rx in THEME_RE.items():
        n = len(rx.findall(t))
        if theme in STRONG:
            n += len(STRONG[theme].findall(t))
        if n:
            scores[theme] = n
    return sorted(scores, key=lambda k: (-scores[k], THEMES.index(k)))


def detect_intent(text):
    t = normalise(text)
    for name, rx in INTENTS:
        if rx.search(t):
            # "help me with my boss" is a request, but there's a theme too: let the theme lead
            if name == "advice" and len(t.split()) > 12:
                continue
            return name
    if len(t.split()) <= 2 and not detect_themes(t):
        return "short"
    return None


def reflect(text, rng):
    """A short mirror of what they said, or None when nothing clean can be reflected."""
    t = normalise(text)
    for rx, frames in REFLECT_PATTERNS:
        m = rx.search(t)
        if not m:
            continue
        frag = STOP_AT.split(" " + m.group(1) + " ")[0].strip()
        words = frag.split()
        if not 1 <= len(words) <= 9:
            continue
        frag = " ".join(SWAPS.get(w, w) for w in words)
        frag = re.sub(r"[^\w\s'-]", "", frag).strip()
        if not frag:
            continue
        return rng.choice(frames).replace("{x}", frag)
    return None


def _used_text(history):
    """Earlier replies, normalised: [all of them joined, the most recent one]."""
    replies = [normalise(m.get("content", "")) for m in history if m.get("role") == "assistant"]
    return (" | ".join(replies), replies[-1] if replies else "")


def _pick(options, used, rng, name=""):
    """A random option not used yet in this session; once all are used, any but the last reply's."""
    everything, last = used
    fresh = [o for o in options if normalise(fill(o, name)) not in everything]
    if fresh:
        return rng.choice(fresh)
    return rng.choice([o for o in options if normalise(fill(o, name)) not in last] or options)


def _seed(school_id, history, text):
    h = hashlib.sha256(f"{school_id}|{len(history)}|{text}".encode()).hexdigest()
    return int(h[:12], 16)


def _named(t):
    """A technique's name as the start of a sentence: "Private trouble or public issue?" keeps its "?"."""
    return t["name"] if t["name"][-1] in ".?!" else t["name"] + "."


def quote_line(q):
    if q.get("paraphrase"):
        return f"As {q['source'].replace('after ', '', 1)} put it, roughly: {q['text']}"
    return f"“{q['text']}” — {q['source']}."


def reply(school, history, name=""):
    """A reply to the last user message in history ([{role, content}, ...])."""
    text = history[-1]["content"] if history else ""
    rng = random.Random(_seed(school["id"], history, text))
    used = _used_text(history[:-1])
    turn = sum(1 for m in history if m.get("role") == "user")
    intent = detect_intent(text)
    themes = detect_themes(text)
    if not themes:   # "yes, every day" carries on whatever we were talking about
        for m in reversed(history[:-1]):
            if m.get("role") == "user":
                themes = detect_themes(m.get("content", ""))
                if themes:
                    break
    theme = themes[0] if themes else "general"
    refl = school["reflections"][theme]
    talk = school["small_talk"]

    if intent in ("greeting", "thanks", "goodbye", "who", "unsure") or (intent == "short" and not themes):
        return fill(_pick(talk[intent], used, rng, name), name)

    if intent == "quote":
        pool = [q for q in school["quotes"] if theme in q["themes"]] or school["quotes"]
        fresh = [q for q in pool if normalise(q["text"]) not in used[0]] or [q for q in school["quotes"] if normalise(q["text"]) not in used[0]] or pool
        q = rng.choice(fresh)
        return f"{quote_line(q)}\n\n{_pick(refl['questions'], used, rng)}"

    if intent in ("technique", "advice"):
        pool = [t for t in school["techniques"] if theme in t["themes"]] or school["techniques"]
        fresh = [t for t in pool if normalise(t["how"]) not in used[0]] or pool
        t = rng.choice(fresh)
        lead = fill(_pick(talk["advice"], used, rng, name), name) if intent == "advice" and turn % 2 else ""
        parts = [lead, f"Here's something to try: {_named(t)} {t['how']}", "Would that fit your situation?"]
        if lead:   # the lead already asks a question: keep one question per reply
            parts[-1] = ""
        return " ".join(p for p in parts if p)

    # The usual shape: mirror + the school's angle + one question. Every few turns, a quote or a
    # technique stands in for the angle so it doesn't feel mechanical.
    mirror = reflect(text, rng) if rng.random() < 0.75 else None
    if not mirror:
        mirror = _pick(GENERIC_ACK[theme], used, rng)
    middle = None
    if turn >= 2 and turn % 3 == 0:
        quotes = [q for q in school["quotes"] if theme in q["themes"] and normalise(q["text"]) not in used[0]]
        if quotes:
            middle = quote_line(rng.choice(quotes))
    elif turn >= 4 and turn % 4 == 1:
        techs = [t for t in school["techniques"] if theme in t["themes"] and normalise(t["how"]) not in used[0]]
        if techs:
            t = rng.choice(techs)
            middle = f"One thing that might help: {_named(t)} {t['how']}"
    if middle is None:
        middle = _pick(refl["angles"], used, rng)
    question = _pick(refl["questions"], used, rng)
    out = f"{mirror} {middle} {question}"
    if name and turn in (2, 7) and not out.startswith(name):
        out = f"{name}, {out[0].lower()}{out[1:]}" if not mirror.startswith("I") else out
    return out


def summary(school, history, name=""):
    """End-of-session summary + one takeaway, without the model."""
    user_text = " ".join(m.get("content", "") for m in history if m.get("role") == "user")
    counts = {}
    for m in history:
        if m.get("role") == "user":
            for t in detect_themes(m.get("content", "")):
                counts[t] = counts.get(t, 0) + 1
    themes = sorted(counts, key=lambda k: (-counts[k], THEMES.index(k)))[:3]
    rng = random.Random(_seed(school["id"], history, "summary"))
    if themes:
        listed = themes[0] if len(themes) == 1 else ", ".join(themes[:-1]) + " and " + themes[-1]
        listed = listed.replace("general", "what's on your mind")
    else:
        listed = "what's on your mind"
    line = fill(rng.choice(school["closing"]["summary_lines"]), name, themes=listed)
    farewell = rng.choice(school["closing"]["farewells"])
    top = themes[0] if themes else "general"
    techs = [t for t in school["techniques"] if top in t["themes"]] or \
            [t for t in school["techniques"] if "general" in t["themes"]] or school["techniques"]
    t = rng.choice(techs)
    if not user_text.strip():
        line = "We didn't get far today, and that's fine. The couch will be here."
    return {"summary": f"{line} {farewell}", "takeaway": f"{t['name'].rstrip('?')}: {t['how']}", "themes": themes}
