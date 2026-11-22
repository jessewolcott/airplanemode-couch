"""Schools of thought are data: one JSON file each in schools/. Adding one is adding a file.

load() validates every file against SCHEMA-like rules below and refuses to start if one is
broken, so a typo shows up in CI rather than as a blank card on the box.
"""
import json
import re
from pathlib import Path

THEMES = ("work", "family", "relationships", "anxiety", "sleep", "travel",
          "loneliness", "anger", "grief", "money")
ALL_THEMES = THEMES + ("general",)
SMALL_TALK = ("greeting", "thanks", "goodbye", "unsure", "who", "advice", "short")
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
COLOUR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# field -> type (and minimum count / length where it matters)
REQUIRED = {
    "id": str, "name": str, "therapist": str, "tagline": str, "description": str,
    "accent": str, "accent2": str, "avatar": str, "system_prompt": str,
    "examples": list, "opening_lines": list, "handoff_lines": list, "techniques": list, "quotes": list,
    "reflections": dict, "small_talk": dict, "closing": dict,
}


class SchoolError(ValueError):
    pass


def _strings(value, where, minimum=1):
    if not isinstance(value, list) or len(value) < minimum:
        raise SchoolError(f"{where}: needs a list of at least {minimum}")
    for s in value:
        if not isinstance(s, str) or not s.strip():
            raise SchoolError(f"{where}: every entry must be non-empty text")
        if len(s) > 400:
            raise SchoolError(f"{where}: keep entries under 400 characters: {s[:40]}...")


def validate(d, filename_id=None):
    """Raise SchoolError if the school dict is incomplete or malformed."""
    for key, kind in REQUIRED.items():
        if key not in d:
            raise SchoolError(f"missing field {key!r}")
        if not isinstance(d[key], kind):
            raise SchoolError(f"{key!r} must be a {kind.__name__}")
        if kind is str and not d[key].strip():
            raise SchoolError(f"{key!r} is empty")
    sid = d["id"]
    if not ID_RE.match(sid):
        raise SchoolError(f"bad id {sid!r}")
    if filename_id is not None and sid != filename_id:
        raise SchoolError(f"id {sid!r} must match the file name {filename_id!r}")
    for key in ("accent", "accent2"):
        if not COLOUR_RE.match(d[key]):
            raise SchoolError(f"{key} must be a #rrggbb colour")
    av = d["avatar"].strip()
    if not (av.startswith("<svg") and av.endswith("</svg>")):
        raise SchoolError("avatar must be one inline <svg>...</svg>")
    if re.search(r"<script|\bon\w+\s*=|javascript:|href|<foreignObject|url\(\s*['\"]?http", av, re.I):
        raise SchoolError("avatar may not contain scripts, event handlers, links or external URLs")
    if len(av) > 6000:
        raise SchoolError("avatar is too big (keep it under 6 KB)")
    if len(d["system_prompt"]) < 200 or len(d["system_prompt"]) > 1500:
        raise SchoolError("system_prompt should be 200-1500 characters (the model is small and slow)")
    ex = d["examples"]
    if not 1 <= len(ex) <= 3:
        raise SchoolError("examples: 1 to 3 example exchanges (they steer the small model's voice)")
    for e in ex:
        if not isinstance(e, dict) or not all(isinstance(e.get(k), str) and e[k].strip() for k in ("user", "reply")):
            raise SchoolError("each example needs user and reply text")
        if len(e["reply"].split()) > 120:
            raise SchoolError("keep example replies under 120 words: the model copies their length")
    _strings(d["opening_lines"], "opening_lines", 2)
    _strings(d["handoff_lines"], "handoff_lines", 1)

    techs = d["techniques"]
    if len(techs) < 4:
        raise SchoolError("techniques: needs at least 4")
    seen = set()
    for t in techs:
        if not isinstance(t, dict) or not all(isinstance(t.get(k), str) and t[k].strip() for k in ("id", "name", "how")):
            raise SchoolError(f"technique needs id, name and how: {t!r}")
        if t["id"] in seen:
            raise SchoolError(f"duplicate technique id {t['id']}")
        seen.add(t["id"])
        if not isinstance(t.get("themes"), list) or not t["themes"] or set(t["themes"]) - set(ALL_THEMES):
            raise SchoolError(f"technique {t['id']}: themes must be a non-empty list from {ALL_THEMES}")

    quotes = d["quotes"]
    if len(quotes) < 6:
        raise SchoolError("quotes: needs at least 6")
    for q in quotes:
        if not isinstance(q, dict) or not all(isinstance(q.get(k), str) and q[k].strip() for k in ("text", "source")):
            raise SchoolError(f"every quote needs text and a source: {q!r}")
        if len(q["text"]) > 300:
            raise SchoolError(f"keep quotes short: {q['text'][:40]}...")
        if "paraphrase" in q and not isinstance(q["paraphrase"], bool):
            raise SchoolError("quote paraphrase must be true or false")
        if not isinstance(q.get("themes"), list) or not q["themes"] or set(q["themes"]) - set(ALL_THEMES):
            raise SchoolError(f"quote themes must be a non-empty list from {ALL_THEMES}: {q['text'][:40]}")

    refl = d["reflections"]
    for theme in ALL_THEMES:
        r = refl.get(theme)
        if not isinstance(r, dict):
            raise SchoolError(f"reflections: missing theme {theme!r}")
        _strings(r.get("angles"), f"reflections.{theme}.angles", 3)
        _strings(r.get("questions"), f"reflections.{theme}.questions", 3)
        for a in r["angles"]:
            if "?" in a:
                raise SchoolError(f"reflections.{theme}.angles are statements (the question comes separately): {a}")
        for q in r["questions"]:
            if not q.rstrip().endswith("?"):
                raise SchoolError(f"reflections.{theme}.questions should be questions: {q}")
    extra = set(refl) - set(ALL_THEMES)
    if extra:
        raise SchoolError(f"reflections: unknown themes {sorted(extra)}")

    for key in SMALL_TALK:
        _strings(d["small_talk"].get(key), f"small_talk.{key}", 2)

    closing = d["closing"]
    if not isinstance(closing.get("style"), str) or not closing["style"].strip():
        raise SchoolError("closing.style is required")
    _strings(closing.get("summary_lines"), "closing.summary_lines", 2)
    _strings(closing.get("farewells"), "closing.farewells", 2)
    if not all("{themes}" in s for s in closing["summary_lines"]):
        raise SchoolError("every closing.summary_lines entry needs {themes}")
    if "order" in d and not isinstance(d["order"], int):
        raise SchoolError("order must be a number")
    return d


def load(folder):
    schools = {}
    for path in sorted(Path(folder).glob("*.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            validate(d, path.stem)
        except (ValueError, SchoolError) as e:
            raise SchoolError(f"{path.name}: {e}") from None
        schools[d["id"]] = d
    if not schools:
        raise SchoolError(f"no schools found in {folder}")
    return dict(sorted(schools.items(), key=lambda kv: (kv[1].get("order", 100), kv[0])))


def public(d):
    """What the page needs to show a school (no prompts, no offline material)."""
    return {k: d[k] for k in ("id", "name", "therapist", "tagline", "description", "accent", "accent2",
                              "avatar", "opening_lines", "handoff_lines")} | {
        "techniques": [{"name": t["name"], "how": t["how"]} for t in d["techniques"]]}


def fill(template, name="", **values):
    """Fill {, name} (", Sam" or nothing), {name}, and any other {key}."""
    name = (name or "").strip()
    out = template.replace("{, name}", f", {name}" if name else "")
    out = out.replace(", {name}", f", {name}" if name else "")
    out = out.replace("{name}", name or "friend")
    for k, v in values.items():
        out = out.replace("{" + k + "}", str(v))
    return out
