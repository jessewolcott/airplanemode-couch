"""The Couch: a therapist simulator with a choice of philosophies, on the shared local model.

A toy for reflection on a long flight, not therapy. The server keeps nothing: the browser holds
the conversation (localStorage) and sends the recent turns with each message. Nothing a person
types is stored or logged on the box.

Every user message goes through a deterministic safety check first (safety.py). If it trips,
the reply is a fixed caring message plus crisis resources, never the model. Below that threshold,
a "low mood" check (hopeless, worthless, empty) makes every therapist gentler for the turn, and
the playful profiles (Narcissist, Nihilist) drop their act for the rest of the session. Otherwise the model
answers in the chosen school's voice, streamed as it's written. If there's no model (LLM_URL
empty, unreachable, loading or too busy), the "offline mind" (offline.py) answers instead.

API (relative to the app's root; the platform serves it at /couch/):
  GET  api/schools      the therapists (public parts of schools/*.json), crisis resources, the
                        disclaimer, max_chars (longest message), and aliases {old id: new id}
                        for renamed schools (socialism -> hochiminh)
  GET  api/status       is the model there? {"model": bool, "state": ...}
  POST api/reply        {school, name, messages:[{role, content}]} -> text/event-stream:
                          event: delta   {"t": "more text"}          (model, as it streams)
                          event: replace {"text": "all text so far"} (a correction while streaming)
                          event: done    {"text": final, "mode": "model"|"offline"|"safety"|"script", "resources": bool,
                                          "why": why the offline mind answered (none/busy/timeout/unusable/...),
                                          "gentle": a playful profile dropped its act for this reply}
  POST api/summary      {school, name, messages} -> {summary, takeaway, mode, resources}
Changes need the header "X-Couch: 1" (blocks cross-site form posts).
"""
import asyncio
import contextlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import List

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

import offline
import prompt
import safety
from schools import aliases as school_aliases, load as load_schools, public

log = logging.getLogger("couch")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

HERE = Path(__file__).parent
LLM_URL = os.getenv("LLM_URL", "http://llm:8080").strip().rstrip("/")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "45"))       # seconds to the first word (includes queueing)
GAP_TIMEOUT = float(os.getenv("LLM_GAP_TIMEOUT", "20"))   # seconds between words once it's talking
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "220"))
PROMPT_TOKENS = int(os.getenv("PROMPT_TOKENS", "1600"))   # 4096 ctx / 2 slots = 2048 per request, minus the reply
COOLDOWN = float(os.getenv("LLM_COOLDOWN", "30"))         # after a failure, use the offline mind this long
MAX_STREAMS = int(os.getenv("MAX_STREAMS", "2"))          # this app's share of the model's slots
QUEUE_WAIT = float(os.getenv("QUEUE_WAIT", "15"))         # wait for one of our slots before going offline
SCHOOLS = load_schools(os.getenv("SCHOOLS_DIR", str(HERE / "schools")))   # refuses to start if one is broken
ALIASES = school_aliases(SCHOOLS)     # old ids a saved browser session may still send
NAME_RE = re.compile(r"^[^\W\d_](?:[^\W\d_]|[ '\-.]){0,29}$")
MAX_USER_CHARS = 1500
DISCLAIMER = ("The Couch is a simulator for reflection and fun, not a therapist, and nothing here is "
              "medical or professional advice. If you're struggling or in danger, contact local "
              "emergency services or a crisis line.")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
client = httpx.AsyncClient(timeout=httpx.Timeout(LLM_TIMEOUT, connect=5))   # tests replace this


class LLMError(Exception):
    pass


class _Model:
    """What we know about the shared model: when it last failed, and our share of its slots."""
    def __init__(self):
        self.down_until = 0.0
        self.health = (0.0, None)   # (checked at, state)
        self._sem, self._loop = None, None

    def usable(self):
        return bool(LLM_URL) and time.monotonic() >= self.down_until

    def failed(self, why):
        self.down_until = time.monotonic() + COOLDOWN
        log.info("model unavailable (%s): offline mind for %ss", why, COOLDOWN)

    def ok(self):
        self.down_until = 0.0

    def sem(self):
        loop = asyncio.get_running_loop()
        if self._sem is None or self._loop is not loop:
            self._sem, self._loop = asyncio.Semaphore(MAX_STREAMS), loop
        return self._sem


model = _Model()


# ---------------- requests ----------------
class Msg(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=4000)


class Chat(BaseModel):
    school: str = Field(max_length=40)
    name: str = Field("", max_length=60)
    messages: List[Msg] = Field(max_length=120)


def _guard(request: Request):
    if request.headers.get("x-couch") != "1":
        raise HTTPException(403, "Missing X-Couch header.")


def _school(sid):
    s = SCHOOLS.get(ALIASES.get(sid, sid))
    if not s:
        raise HTTPException(404, "Unknown therapist.")
    return s


def clean_name(name):
    name = re.sub(r"\s+", " ", (name or "").strip())
    return name if NAME_RE.match(name) else ""


def _history(body):
    return [{"role": m.role, "content": m.content.strip()} for m in body.messages if m.content.strip()]


def _low(history):
    """The person sounds low: in their last message or the one before it, so the act doesn't
    snap back right after someone said they feel worthless."""
    users = [m["content"] for m in history if m["role"] == "user"]
    return any(safety.low_mood(u) for u in users[-2:])


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}


# ---------------- the model ----------------
async def llm_stream(messages):
    """Yield the reply's text pieces as llama.cpp streams them. Raises LLMError / timeouts."""
    body = {"messages": messages, "max_tokens": MAX_TOKENS, "temperature": 0.6, "top_p": 0.9,
            "repeat_penalty": 1.1, "cache_prompt": True, "stream": True,
            "stop": ["<end_of_turn>", "<turn|>", "<|turn>", "\nUser:", "\nClient:", "\nHuman:", "\nYou:"]}
    async with client.stream("POST", f"{LLM_URL}/v1/chat/completions", json=body) as r:
        if r.status_code != 200:
            raise LLMError(f"HTTP {r.status_code}")
        lines = r.aiter_lines()
        first = True
        while True:
            try:
                line = await asyncio.wait_for(lines.__anext__(), LLM_TIMEOUT if first else GAP_TIMEOUT)
            except StopAsyncIteration:
                return
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                choice = json.loads(data)["choices"][0]
            except (ValueError, KeyError, IndexError, TypeError):
                raise LLMError("bad stream chunk") from None
            piece = (choice.get("delta") or {}).get("content") or ""
            if piece:
                first = False
                yield piece
            if choice.get("finish_reason"):
                return


async def llm_json(messages, max_tokens, schema):
    body = {"messages": messages, "max_tokens": max_tokens, "temperature": 0.5, "cache_prompt": True,
            "response_format": {"type": "json_schema", "json_schema": {"name": "summary", "schema": schema}}}
    r = await asyncio.wait_for(client.post(f"{LLM_URL}/v1/chat/completions", json=body), LLM_TIMEOUT * 2)
    if r.status_code != 200:
        raise LLMError(f"HTTP {r.status_code}")
    return json.loads(r.json()["choices"][0]["message"]["content"])


async def model_reply(school, history, name, flagged, low=False):
    """The SSE stream for a model reply, falling back to the offline mind if the model fails."""
    speaker = school["therapist"]
    quotes = [q["text"] for q in school["quotes"]]
    self_quotes = any(q.get("persona") for q in school["quotes"])
    messages, info = prompt.build(school, history, name, PROMPT_TOKENS, flagged, low)
    gentle = info["gentle"]
    raw, sent, why, started = "", "", None, time.monotonic()
    sem = model.sem()
    try:
        await asyncio.wait_for(sem.acquire(), QUEUE_WAIT)
    except asyncio.TimeoutError:
        why = "busy"
    if why is None:
        try:
            async with contextlib.aclosing(llm_stream(messages)) as pieces:
                async for piece in pieces:
                    raw += piece
                    shown, stop = prompt.visible(raw, name, speaker, quotes, self_quotes)
                    if shown != sent:
                        if shown.startswith(sent):
                            yield _sse("delta", {"t": shown[len(sent):]})
                        else:
                            yield _sse("replace", {"text": shown})
                        sent = shown
                    if stop:
                        break
        except asyncio.TimeoutError:
            why = "timeout"
        except (httpx.HTTPError, LLMError, OSError) as e:
            why = type(e).__name__ if not isinstance(e, LLMError) else str(e)
        finally:
            sem.release()
    final = prompt.dedupe(prompt.tidy(raw, name, speaker, quotes, self_quotes), history, school["examples"])
    if final:
        model.ok()
        mode = "model"
    else:
        if why and not raw and why != "busy":
            model.failed(why)     # a busy queue isn't a failure: only this reply goes offline
        elif raw:
            why = "unusable"      # the model answered, but nothing it said survived the checks
            model.ok()
        final, mode = offline.reply(school, history, name, low, gentle), "offline"
    log.info("reply school=%s mode=%s why=%s gentle=%s low=%s prompt~%s tok kept=%s dropped=%s %.1fs",
             school["id"], mode, why, gentle, low, info["tokens"], info["kept"], info["dropped"],
             time.monotonic() - started)
    yield _sse("done", {"text": final, "mode": mode, "why": why if mode == "offline" else None, "resources": False,
                        "gentle": gentle})


def _single(events):
    async def gen():
        for e in events:
            yield e
    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


# ---------------- routes ----------------
@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/icon.svg")
def icon():
    return FileResponse(HERE / "static" / "icon.svg", media_type="image/svg+xml")


@app.get("/api/schools")
def schools():
    return {"schools": [public(s) for s in SCHOOLS.values()], "aliases": ALIASES, "resources": safety.RESOURCES,
            "disclaimer": DISCLAIMER, "max_chars": MAX_USER_CHARS}


@app.get("/api/status")
async def status():
    if not LLM_URL:
        return {"model": False, "state": "none"}
    if not model.usable():
        return {"model": False, "state": "busy"}
    checked, state = model.health
    if time.monotonic() - checked > 15 or state is None:
        try:
            r = await asyncio.wait_for(client.get(f"{LLM_URL}/health"), 3)
            state = "ready" if r.status_code == 200 else ("loading" if r.status_code == 503 else "offline")
        except (httpx.HTTPError, asyncio.TimeoutError, OSError):
            state = "offline"
        model.health = (time.monotonic(), state)
    return {"model": state == "ready", "state": state}


@app.post("/api/reply")
async def reply(body: Chat, request: Request):
    _guard(request)
    school = _school(body.school)
    name = clean_name(body.name)
    history = _history(body)
    if not history or history[-1]["role"] != "user":
        raise HTTPException(400, "The last message must be yours.")
    last = history[-1]["content"]
    if len(last) > MAX_USER_CHARS:
        raise HTTPException(413, f"Keep a message under {MAX_USER_CHARS} characters.")

    cats = safety.check(last)
    if cats:   # fixed words, never the model's
        log.info("reply school=%s mode=safety", school["id"])
        return _single([_sse("done", {"text": safety.respond(cats), "mode": "safety",
                                      "resources": True, "safety": cats})])
    flagged = any(safety.check(m["content"]) for m in history[:-1] if m["role"] == "user")
    low = _low(history)
    users = [m["content"] for m in history if m["role"] == "user"]
    if school.get("playful") and (any("grief" in offline.detect_themes(u)[:1] for u in users[-3:])
                                  or any(safety.low_mood(u) for u in users)):
        # No comedy act over a bereavement, and once someone has sounded low the act stays off for
        # the rest of the session: a small model's nihilist (seen on the earlier Qwen2.5-1.5B) slipped
        # back into "I'm not important in the grand scheme" the turn after "nobody would care if I
        # disappeared".
        low = True
    gentle = prompt.gentle_mode(school, low, flagged)
    if offline.detect_intent(last) == "quote" and not low:
        # quotes come from the school file (checked, with sources), never from the model's memory
        return _single([_sse("done", {"text": offline.reply(school, history, name, low, gentle), "mode": "script",
                                      "resources": False, "gentle": gentle})])
    if not model.usable():
        return _single([_sse("done", {"text": offline.reply(school, history, name, low, gentle), "mode": "offline",
                                      "why": "none" if not LLM_URL else "cooldown", "resources": False,
                                      "gentle": gentle})])
    return StreamingResponse(model_reply(school, history, name, flagged, low),
                             media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/summary")
async def summary(body: Chat, request: Request):
    _guard(request)
    school = _school(body.school)
    name = clean_name(body.name)
    history = _history(body)
    flagged = any(safety.check(m["content"]) for m in history if m["role"] == "user")
    low = any(safety.low_mood(m["content"]) for m in history if m["role"] == "user")
    gentle = prompt.gentle_mode(school, low, flagged)
    result, mode = None, "offline"
    if model.usable() and any(m["role"] == "user" for m in history):
        sem = model.sem()
        try:
            await asyncio.wait_for(sem.acquire(), QUEUE_WAIT)
        except asyncio.TimeoutError:
            sem = None
        if sem:
            try:
                data = await llm_json(prompt.summary_messages(school, history, name, PROMPT_TOKENS, gentle),
                                      MAX_TOKENS, prompt.SUMMARY_SCHEMA)
                result = prompt.tidy_summary(data, name, school["therapist"])
                model.ok()
            except asyncio.TimeoutError:
                model.failed("timeout")
            except (httpx.HTTPError, LLMError, OSError, ValueError, KeyError, IndexError, TypeError) as e:
                model.failed(type(e).__name__)
            finally:
                sem.release()
        if result:
            mode = "model"
    if not result:
        fb = offline.summary(school, history, name, gentle)
        result = {"summary": fb["summary"], "takeaway": fb["takeaway"]}
    return {**result, "mode": mode, "resources": flagged,
            "safety_note": ("If any of what we talked about feels like too much to carry, please reach "
                            "out to someone you trust or a crisis line.") if flagged else ""}
