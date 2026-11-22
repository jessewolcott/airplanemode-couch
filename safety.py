"""The safety check: deterministic, runs on every user message before anything else.

The Couch is a toy, not therapy. When a message shows signs of suicide or self-harm, harm to
someone else, abuse, or a medical emergency, the reply is a fixed caring message written here
(never model-generated) and the page shows a resources card. The conversation can carry on.

It errs on the side of showing resources: a false alarm costs a card the person can close; a
miss costs much more. Common figures of speech ("this flight is killing me", "dying for a
coffee") are taken out first so they don't trip it.
"""
import re
import unicodedata

CATEGORIES = ("self_harm", "harm_others", "abuse", "medical")

# Numbers stay general: the box is offline and could be anywhere.
RESOURCES = [
    {"label": "Emergency services", "detail": "112 (most of the world, incl. EU) or 911 (US, Canada). On a plane, tell the cabin crew."},
    {"label": "US and Canada", "detail": "Call or text 988 (Suicide and Crisis Lifeline)."},
    {"label": "UK and Ireland", "detail": "Samaritans: 116 123, free, day or night."},
    {"label": "Anywhere else", "detail": "findahelpline.com lists free, confidential lines by country (once you're online)."},
]

MESSAGES = {
    "self_harm": (
        "I'm really glad you told me. What you're describing sounds serious, and you deserve "
        "support from a real person right now, not a simulator. If you might act on these "
        "thoughts or you're in danger, please contact local emergency services, or call or text "
        "a crisis line (the numbers are on the card below). If you're on a flight, the cabin crew "
        "can help too. If you can, reach out to someone you trust and let them know how you're "
        "feeling. I'm still here if you want to keep talking."
    ),
    "harm_others": (
        "Thank you for saying it out loud. When feelings get to the point of wanting to hurt "
        "someone, it matters to get real support quickly. If anyone is in immediate danger, "
        "please contact local emergency services. If it's the feeling itself that's frightening "
        "you, a crisis line (see the card below) can talk it through with you right now. Putting "
        "some distance between you and the situation for a while can help too. I'm still here "
        "if you want to keep talking."
    ),
    "abuse": (
        "I'm sorry this is happening to you. Nobody deserves to be hurt or threatened, and it "
        "isn't your fault. If you're in danger right now, please contact local emergency "
        "services. A crisis line or a local domestic abuse service can help you think through "
        "your options safely (the card below has some to start with). I'm still here if you "
        "want to keep talking."
    ),
    "medical": (
        "That sounds like it could be a medical emergency, and I can't help with that. Please "
        "get help now: call local emergency services (112 or 911), or if you're on a plane, "
        "press the call button and tell the cabin crew straight away. If someone is with you, "
        "tell them too."
    ),
}
ORDER = ("medical", "self_harm", "harm_others", "abuse")   # which message wins if several match


def normalise(text):
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = t.replace("’", "'").replace("‘", "'").replace("`", "'")
    t = re.sub(r"[^\w'\s.,!?-]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return f" {t.strip()} "


# Things that are not people: "<one of these> is killing me" is a figure of speech.
THINGS = (r"(?:this|that|it|the|my|these|those)?\s*(?:flight|plane|seat|seats|legroom|heat|cold|"
          r"weather|feet|foot|back|neck|knees?|legs?|head|headache|jet ?lag|job|work|commute|layover|"
          r"delay|delays|wait|waiting|queue|line|traffic|hangover|music|noise|wifi|wi-fi|internet|"
          r"suspense|curiosity|homework|deadline|deadlines|email|emails|meeting|meetings|week|day|"
          r"month|year|shoes?|food|airport|security|boredom|this|that|it|you|you guys|lol)")
IDIOMS = [
    rf"{THINGS}\s+(?:is|are|was|were|'s|'re|has been|have been|keeps?)\s+(?:literally\s+|actually\s+|really\s+|slowly\s+|just\s+)?(?:killing|murdering)\s+me",
    r"(?:you're|you are|ur) killing me",
    r"dying (?:to|for|of laughter|laughing)",
    r"(?:could|would|'d) (?:kill|die) for (?:a|an|some|the)\b",
    r"\bkill(?:ing)? (?:some |the )?time\b",
    r"\bkill(?:ing|ed)? it\b",
    r"\bkilled it\b",
    r"\bto die for\b",
    r"\b(?:bored|scared|worried|tickled|loved|done|talked|worked|starved|freezing) to death\b",
    r"\b(?:die|died|dying) (?:of|from) (?:embarrassment|shame|laughter|laughing|boredom|cringe|cuteness)\b",
    r"\bdie laughing\b",
    r"\bmy (?:phone|battery|laptop|plant|plants|car|tablet|headphones) (?:is |was |just )?(?:dying|died|dead)\b",
    r"\bdead (?:tired|on my feet|serious|end|line|lines|lift)\b",
    r"\bdeadlines?\b",
    r"\bkill (?:the|a|my) (?:lights?|engine|music|mood|vibe|process|app|tab|buzz)\b",
    r"\b(?:shoot|shot|shooting) (?:him|her|them|me|you) (?:a|an) (?:text|message|email|note|line|dm)\b",
    r"\bshoot (?:the breeze|a video|some photos|photos|hoops)\b",
    r"\bhit me up\b",
    r"\bhit me with\b",
    r"\bhurt (?:his|her|their|your|my) feelings\b",
    r"\b(?:break a leg|killer (?:app|view|deal|workout))\b",
    r"\bheart attack (?:on a plate|in a bun)\b",
    r"\bstroke of (?:luck|genius|midnight)\b",
    r"\boverdos\w* on (?:coffee|caffeine|sugar|netflix|tv|movies|chocolate|snacks|candy|sweets|carbs|cheese)\b",
    r"\bhad a stroke reading\b",
    r"\b(?:i'll|i will|gonna|going to) (?:be|get) killed (?:by|if) my (?:mom|mum|dad|boss|wife|husband)\b",
]
IDIOM_RE = re.compile("|".join(f"(?:{p})" for p in IDIOMS))

PEOPLE = (r"(?:him|her|them|someone|somebody|anyone|anybody|people|everyone|everybody|"
          r"(?:my|the|that|this|his|her|our) (?:wife|husband|partner|boyfriend|girlfriend|ex|boss|manager|"
          r"coworker|co-worker|colleague|neighbou?r|roommate|flatmate|kid|kids|son|daughter|baby|child|"
          r"children|mom|mum|mother|dad|father|parents?|brother|sister|family|friend|teacher|"
          r"guy|man|woman|lady|passenger|pilot|attendant|seatmate|person|landlord))")
ABUSERS = (r"(?:he|she|they|my (?:wife|husband|partner|boyfriend|girlfriend|ex|dad|father|mom|mum|mother|"
           r"stepdad|stepfather|stepmom|stepmother|parents?|brother|sister|uncle|aunt|grandfather|"
           r"grandpa|boss|coach|teacher|roommate|flatmate|carer|caregiver))")

PATTERNS = {
    "self_harm": [
        r"\bsuicid\w*",
        r"\b(?:kill|hurt|harm|cut|burn|starve|hang|drown|poison|shoot) (?:my ?self|myself)\b",
        r"\bkms\b",
        r"\bunalive\b",
        r"\bself[- ]?harm\w*",
        r"\b(?:end|take|ending|taking) (?:my|my own) life\b",
        r"\bend(?:ing)? it all\b",
        r"\b(?:want|wanna|wanted|going|gonna|plan|planning|ready|deserve|trying) (?:to )?(?:die|be dead)\b",
        r"\bwish (?:i|i'd) (?:was|were|had) (?:dead|never been born|not born|died)\b",
        r"\bwish i (?:could|would) (?:just )?(?:die|disappear forever|not wake up)\b",
        r"\bbetter off (?:dead|without me)\b",
        r"\b(?:no|not any|isn't any) (?:reason|point) (?:to|in) (?:live|living|go on|going on|being alive)\b",
        r"\b(?:don't|do not|dont) want to (?:live|be alive|exist)\b",
        r"\b(?:don't|do not|dont) want to be (?:here|around|alive) (?:anymore|any more)\b",
        r"\b(?:don't|do not|dont) want to wake up(?: ever| again| tomorrow| anymore| any more)?(?=\s*[.!?,]|\s*$| ever| again| tomorrow)",
        r"\bnot worth living\b",
        r"\b(?:life|living) (?:isn't|is not|isnt) worth\b",
        r"\bcan't go on\b|\bcannot go on\b|\bcant go on\b",
        r"\b(?:slit|cut|cutting|slash) (?:my )?wrists?\b",
        r"\bcutting (?:again|myself)\b",
        r"\bjump(?:ing)? (?:off|from|in front of) (?:a|the) (?:bridge|building|roof|train|balcony|cliff)\b",
        r"\b(?:take|took|taking|swallow|swallowed) (?:all|a bottle of|a handful of|too many) (?:my |the |of my |of the )?(?:pills|tablets|meds)\b",
        r"\boverdos\w*\b",
        r"\bdisappear forever\b",
        r"\bgoodbye (?:letter|note)\b|\bsuicide note\b",
    ],
    "harm_others": [
        rf"\b(?:want|wanna|going|gonna|plan|planning|ready|about|tempted|thinking about|could) (?:to )?(?:kill|murder|stab|shoot|strangle|poison|hurt|attack|beat up|punch|hit) {PEOPLE}",
        rf"\b(?:kill|murder|stab|shoot|strangle|poison) {PEOPLE}",
        r"\b(?:make|making) (?:them|him|her|everyone) (?:pay|suffer)\b",
        r"\b(?:shoot up|bomb|blow up) (?:the|a|my) (?:school|office|plane|airport|work|church|mosque|synagogue|place)\b",
        r"\bmass (?:shooting|murder)\b",
        r"\bhurt (?:my|the) (?:baby|kids?|children|child)\b",
    ],
    "abuse": [
        rf"\b{ABUSERS} (?:hits|hit|beats|beat|chokes|choked|strangles|strangled|kicks|kicked|punches|punched|slaps|slapped|hurts|hurt|threatens|threatened|rapes|raped|molests|molested|abuses|abused|forces|forced|burns|burned|locks|locked) me\b",
        rf"\b{ABUSERS} (?:is |was |keeps |has been )?(?:hitting|beating|choking|strangling|kicking|punching|slapping|hurting|threatening|abusing|raping|molesting) me\b",
        rf"\b{ABUSERS} (?:will|would|is going to|'s going to|said (?:he|she|they)(?:'d| would| will)) (?:kill|hurt|hit|beat) me\b",
        r"\b(?:abusive|abused|abusing me|domestic (?:violence|abuse)|sexual(?:ly)? (?:assault|assaulted|abused)|molest\w*|raped?\b|groomed|grooming me)",
        r"\b(?:afraid|scared|terrified|frightened) (?:of|to go home to) (?:my )?(?:husband|wife|partner|boyfriend|girlfriend|dad|father|mom|mum|mother|stepdad|stepmom|parents)\b",
        r"\b(?:afraid|scared|terrified) to go home\b",
        r"\b(?:not|don't feel|do not feel|never feel|isn't) safe (?:at home|with (?:him|her|them|my \w+))\b",
        r"\btouch(?:ed|es|ing) me (?:inappropriately|without|where|there)\b",
        r"\bwon't let me (?:leave|go out|see my friends|have money|have my passport)\b",
        r"\b(?:took|takes|keeps|has) my passport\b",
    ],
    "medical": [
        r"\bchest pains?\b",
        r"\bheart attack\b",
        r"\b(?:having|had|having a|think i'm having a|think i had a) (?:a )?stroke\b",
        r"\b(?:can't|cannot|cant|can not) breathe?\b",
        r"\b(?:trouble|difficulty|struggling|hard) (?:to )?breath(?:e|ing)\b",
        r"\bshort(?:ness)? of breath\b",
        r"\banaphyla\w*\b",
        r"\b(?:severe |bad |serious )?allergic reaction\b",
        r"\b(?:having|had) a seizure\b|\bseizing\b",
        r"\b(?:unconscious|unresponsive|passed out|passing out|fainted|blacking out|blacked out)\b",
        r"\bbleeding (?:heavily|a lot|badly|won't stop|that won't stop)\b|\bwon't stop bleeding\b",
        r"\b(?:i'm|he's|she's|someone's|someone is|is) choking\b",
        r"\b(?:face|smile) (?:is )?drooping\b",
        r"\b(?:numb|numbness) (?:in|on) (?:my |the )?(?:face|left arm|arm|one side)\b",
        r"\bslurr(?:ed|ing) (?:my )?speech\b",
        r"\bepipen\b",
        r"\boverdos\w*\b",
        r"\bdiabetic (?:emergency|coma|shock)\b|\bhypo(?:glycaemi|glycemi)\w*\b",
    ],
}
COMPILED = {cat: re.compile("|".join(f"(?:{p})" for p in pats)) for cat, pats in PATTERNS.items()}
NEGATED = re.compile(r"\b(?:don't|do not|dont|never|wouldn't|would never|won't|will never|not) (?:want to |wanna |going to |gonna )?(?:ever )?$")


def check(text):
    """Return the categories the message matches (empty list = nothing found)."""
    t = IDIOM_RE.sub(" ", normalise(text))
    found = []
    for cat in ORDER:
        for m in COMPILED[cat].finditer(t):
            # "I'd never hurt him" is not a threat; "I don't want to live" still counts (it is listed above).
            if cat == "harm_others" and NEGATED.search(t[max(0, m.start() - 30):m.start()]):
                continue
            found.append(cat)
            break
    return found


def respond(categories):
    """The fixed reply for a set of categories (the most urgent one's message)."""
    for cat in ORDER:
        if cat in categories:
            return MESSAGES[cat]
    return None
