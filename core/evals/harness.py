"""Shared eval machinery: run the routing and reaction evals against any local model,
with the exact system prompt a real conversation uses, and time every reply.

Timing per reply (streamed, like the real voice path):
  ttft      first token
  first_say first complete sentence inside <speak> - when TTS could start
  total     whole reply
"""
from __future__ import annotations

import json
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import irene  # noqa: E402,F401  - offline mode, repo root on the path
from irene.brain import _CUE, Conversation, StreamingReply, tool_call as parse_tool_call  # noqa: E402
from irene.react import act_out, resolve  # noqa: E402
from irene.llm import MODEL as MODEL_DEFAULT, Ollama  # noqa: E402,F401
from irene.reply import parse_reply  # noqa: E402
from irene import fast, sentiment  # noqa: E402
from irene.home import HOME  # noqa: E402
from irene.entrances import load_registry  # noqa: E402

HERE = Path(__file__).parent

# Irene breaking character: refusing to act something out because she is "just a
# model" or "has no body". Never allowed in any reply. Saying she's a language model
# at all is allowed only where the case marks the question as sincere.
CHARACTER_BREAK = re.compile(
    r"\b(just|only|merely) an? (large )?(language model|ai|program|chatbot|computer program)\b"
    r"|\b(don'?t|do not) (really )?have (a |any )?(physical )?(body|hands|arms|legs|form)\b"
    r"|\bas an ai\b|\bcan'?t physically\b|\bcannot physically\b|\bno physical (body|form|presence)\b"
    r"|\bnot able to physically\b|\bI'?m not capable of (physically|moving)\b",
    re.I,
)
LANGUAGE_MODEL = re.compile(r"\b(I'?m|I am) (a |an )?(large )?language model\b", re.I)


def character_break(speak: str, sincere: bool = False) -> str | None:
    """The offending phrase if a spoken reply breaks character, else None."""
    m = CHARACTER_BREAK.search(speak) or (None if sincere else LANGUAGE_MODEL.search(speak))
    return m.group(0) if m else None


def load(name: str) -> list[dict]:
    return [json.loads(line) for line in (HERE / name).read_text(encoding="utf-8").splitlines() if line.strip()]


@dataclass
class Timed:
    raw: str
    ttft: float
    first_say: float | None
    total: float
    react: object = None  # what the stream reader resolved, as a real turn would show
    cues: list = field(default_factory=list)  # cue names across the reply's sentences, in order


@dataclass
class Report:
    model: str
    lines: list[str] = field(default_factory=list)
    routing_ok: int = 0
    routing_n: int = 0
    args_ok: int = 0
    args_n: int = 0
    react_ok: int = 0
    react_n: int = 0
    # conversation: does the feeling fit, did she stay herself, did small talk
    # survive as small talk
    chat_ok: int = 0
    chat_n: int = 0
    chat_fit: int = 0
    chat_kept_chat: int = 0
    chat_chatty: int = 0
    chat_service: int = 0
    breaks: int = 0
    replies: int = 0
    # routing cases answered by fast.direct_call, as the app would, without the model
    direct: int = 0
    cued: list[int] = field(default_factory=list)
    ttft: list[float] = field(default_factory=list)
    first_say: list[float] = field(default_factory=list)
    total: list[float] = field(default_factory=list)

    @staticmethod
    def pct(xs: list[float], q: float) -> float:
        if not xs:
            return float("nan")
        xs = sorted(xs)
        return xs[min(len(xs) - 1, round(q * (len(xs) - 1)))]


async def timed_reply(llm: Ollama, messages: list[dict]) -> Timed:
    start = time.perf_counter()
    ttft = None
    first_say = None
    # the same stream reader a real turn uses, act-out and mood cues included
    last = messages[-1]["content"] if messages[-1]["role"] == "user" else ""
    said = last.split("\n\n[")[0]
    # what her previous reply showed, as Conversation.last_cues would hold it
    before = next((m["content"] for m in reversed(messages[:-1]) if m["role"] == "assistant"), "")
    shown = tuple(r.name for r in map(resolve, _CUE.findall(before)) if r)
    stream = StreamingReply(act_out(said), mood=sentiment.read(said).cues, avoid=shown)
    async for chunk in llm.chat_stream(messages):
        now = time.perf_counter()
        if ttft is None:
            ttft = now - start
        sentences = stream.feed(chunk)
        if sentences and first_say is None:
            first_say = now - start
    tail = stream.finish()
    if first_say is None and tail:
        first_say = time.perf_counter() - start
    return Timed(stream.raw, ttft or 0.0, first_say, time.perf_counter() - start, stream.react, [c.name for c in stream.cues])


def screen_image(lines: list[str]) -> str:
    """A fake screenshot (base64 JPEG) showing `lines` of text, rendered here so the
    evals carry no binary fixtures and never capture the real screen."""
    import base64
    import io

    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1280, 720), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1280, 40), fill=(40, 60, 110))
    try:
        font = ImageFont.truetype("arial.ttf", 30)
    except OSError:
        font = ImageFont.load_default()
    for k, line in enumerate(lines):
        draw.text((60, 90 + k * 50), line, fill=(20, 20, 20), font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _messages(conv: Conversation, case: dict) -> list[dict]:
    """The prompt a real turn builds (Conversation.prompt). `screen`: text lines shown
    on a fake screenshot attached to the last message (a capture_screen result),
    for the screen-injection cases."""
    history = [{"role": role, "content": content} for role, content in case.get("history", [])]
    # `entrance`: he just summoned her in that one - recorded as a real summon records it
    conv.entrance, conv.history = None, []
    if case.get("entrance"):
        conv.entered(next(e for e in load_registry() if e["name"] == case["entrance"]))
        history = [*conv.history, *history]
        conv.history = []
    user = case["say"]
    if case.get("context"):
        user = f"{user}\n\n[{case['context']}]"
    final = {"role": "user", "content": user}
    if case.get("screen"):
        final["images"] = [screen_image(case["screen"])]
    recent = [n for _, c in case.get("history", []) for n in re.findall(r'"name": "(\w+)"', c)]
    return conv.prompt(case["say"], [*history, final], len(history), recent)


def _spoken_numbers(text: str) -> str:
    """Digits for the number words a spoken answer uses ("ninety-five days")."""
    units = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
    tens = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}

    ordinals = {"first": "one", "second": "two", "third": "three", "fifth": "five", "eighth": "eight",
                "ninth": "nine", "twelfth": "twelve", "twentieth": "twenty", "thirtieth": "thirty"}
    text = re.sub(r"\b(\w+?)(th)?\b", lambda m: ordinals.get(m.group(0), m.group(1) if m.group(2) and m.group(1) in units else m.group(0)), text)

    def word(m: re.Match) -> str:
        t, u = m.group(1), m.group(2)
        return str(tens[t] + (units.index(u) if u else 0))

    text = re.sub(r"\b(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[- ](one|two|three|four|five|six|seven|eight|nine))?\b", word, text)
    return re.sub(r"\b(" + "|".join(units) + r")\b", lambda m: str(units.index(m.group(1))), text)


def answer_ok(kind: str, raw: str, now: datetime | None = None) -> bool:
    """Is a direct (no-tool) answer to a date question actually right?"""
    now = now or datetime.now()
    text = _spoken_numbers(raw.lower())
    if kind == "weekday":
        return now.strftime("%A").lower() in text
    if kind == "month":
        return now.strftime("%B").lower() in text
    if kind == "date":
        return now.strftime("%B").lower() in text and re.search(rf"\b{now.day}(st|nd|rd|th)?\b", text) is not None
    if kind == "christmas":
        target = date(now.year, 12, 25)
        if target < now.date():
            target = date(now.year + 1, 12, 25)
        days = (target - now.date()).days
        return any(re.search(rf"\b{d}\b", text) for d in (days - 1, days, days + 1))
    if kind == "time":  # hour and minute, 24h or 12h, a minute either way
        for delta in (-1, 0, 1):
            t = datetime.fromtimestamp(now.timestamp() + 60 * delta)
            if f"{t.hour}:{t.minute:02d}" in text or f"{t.hour % 12 or 12}:{t.minute:02d}" in text:
                return True
        return False
    if kind == "year":
        return str(now.year) in text
    raise ValueError(f"unknown answer check {kind!r}")


def args_match(got: dict, exact: dict, contains: dict) -> bool:
    """Numbers compare as numbers, strings case-insensitively; `contains` is a
    case-insensitive substring check (paths and search terms vary in form).
    "{home}" in a value is the configured city (config/home.yaml, else its example)."""
    exact = {k: v.replace("{home}", HOME.city) if isinstance(v, str) else v for k, v in exact.items()}
    contains = {k: str(v).replace("{home}", HOME.city) for k, v in contains.items()}
    for key, want in exact.items():
        value = got.get(key)
        if isinstance(want, (int, float)):
            try:
                if float(value) != float(want):
                    return False
            except (TypeError, ValueError):
                return False
        elif str(value).strip().lower() != str(want).lower():
            return False
    for key, want in contains.items():
        if str(want).lower() not in str(got.get(key, "")).lower().replace("\\", "/"):
            return False
    return True


def _record_time(report: Report, t: Timed) -> None:
    report.ttft.append(t.ttft)
    report.total.append(t.total)
    if t.first_say is not None:
        report.first_say.append(t.first_say)


async def run_routing(llm: Ollama, report: Report, repeat: int = 1) -> None:
    conv = Conversation(llm)
    for case in load("routing.jsonl"):
        for _ in range(repeat):
            # an unmistakable command never reaches the model in the app (fast.direct_call)
            # (a follow-up sees the tools its history ran, as Conversation.recent_tools)
            recent = [n for _, c in case.get("history", []) for n in re.findall(r'"name": "(\w+)"', c)]
            direct = fast.direct_call(case["say"], recent)
            if direct is not None:
                report.direct += 1
                t = Timed(direct, 0.0, None, 0.0)
            else:
                t = await timed_reply(llm, _messages(conv, case))
                _record_time(report, t)
            call = parse_tool_call(t.raw)
            if call and call[0] == "research":
                # as the app sends it: an empty question is his words, and a
                # location-dependent search gets his city (brain.py, home.py)
                question = str(call[1].get("question") or "").strip() or case["say"]
                call = (call[0], {**call[1], "question": HOME.localise(question)})
            name = call[0] if call else None
            ok = name in case["expect"]
            report.routing_n += 1
            report.routing_ok += ok
            args_note = ""
            if ok and name and (case.get("args") or case.get("contains")):
                report.args_n += 1
                good = args_match(call[1], case.get("args", {}), case.get("contains", {}))
                report.args_ok += good
                want = {**case.get("args", {}), **{k: f"~{v}" for k, v in case.get("contains", {}).items()}}
                args_note = "" if good else f"  ARGS {call[1]} want {want}"
                ok = ok and good
            if ok and not name and case.get("answer"):
                right = answer_ok(case["answer"], t.raw)
                if not right:
                    args_note = f"  WRONG ANSWER {parse_reply(t.raw).speak[:80]!r}"
                ok = ok and right
            broke = None if name else character_break(parse_reply(t.raw).speak)
            report.replies += not name
            if broke:
                report.breaks += 1
                args_note += f"  CHARACTER BREAK {broke!r}"
                ok = False
            mark = "PASS" if ok else "FAIL"
            report.lines.append(f"{mark} routing  {case['id']:22} got {name or 'no tool':20} want {case['expect']}{args_note}")


async def run_reactions(llm: Ollama, report: Report, repeat: int = 1) -> None:
    conv = Conversation(llm)
    for case in load("reactions.jsonl"):
        for _ in range(repeat):
            t = await timed_reply(llm, _messages(conv, case))
            _record_time(report, t)
            reply = parse_reply(t.raw)
            report.cued.append(len(t.cues))
            # every cue that played; a display-only reply shows its own
            names = t.cues or ([reply.react.name] if reply.react else [])
            picked = "+".join(names) or "none"
            # a reply that calls a tool first has no reaction yet: judge only real replies
            if parse_tool_call(t.raw):
                picked, names = "tool-first", ["tool-first"]
            fits = any(n in case["accept"] for n in names) or (not names and "none" in case["accept"])
            ok = fits and (names[:1] or ["none"])[0] != case.get("forbid_repeat")
            note = ""
            broke = character_break(reply.speak, case.get("sincere", False))
            report.replies += 1
            if broke:
                report.breaks += 1
                note = f"  CHARACTER BREAK {broke!r}"
                ok = False
            if case.get("must_say") and not re.search(case["must_say"], reply.speak, re.I):
                note += f"  MISSING /{case['must_say']}/ in {reply.speak[:80]!r}"
                ok = False
            report.react_n += 1
            report.react_ok += ok
            report.lines.append(f"{'PASS' if ok else 'FAIL'} reaction {case['id']:22} got {picked:14} want {'/'.join(case['accept'])}{note}")


def summary(report: Report) -> dict:
    p = Report.pct
    return {
        "model": report.model,
        "routing": f"{report.routing_ok}/{report.routing_n} ({report.routing_ok / max(1, report.routing_n):.0%})",
        "routing_direct": f"{report.direct} answered without the model (fast.direct_call)",
        "arguments": f"{report.args_ok}/{report.args_n} ({report.args_ok / max(1, report.args_n):.0%})",
        "reactions": f"{report.react_ok}/{report.react_n} ({report.react_ok / max(1, report.react_n):.0%})",
        "conversation": f"{report.chat_ok}/{report.chat_n} ({report.chat_ok / max(1, report.chat_n):.0%})",
        "conversation_feeling_fits": f"{report.chat_fit}/{report.chat_n}",
        "small_talk_stayed_talk": f"{report.chat_kept_chat}/{report.chat_chatty}",
        "service_desk_lines": report.chat_service,
        "character_breaks": f"{report.breaks}/{report.replies}",
        "cues_per_reply": round(statistics.mean(report.cued), 2) if report.cued else None,
        "multi_cue_replies": f"{sum(c > 1 for c in report.cued)}/{len(report.cued)}",
        "ttft_p50_ms": round(p(report.ttft, 0.5) * 1000),
        "ttft_p95_ms": round(p(report.ttft, 0.95) * 1000),
        "first_say_p50_ms": round(p(report.first_say, 0.5) * 1000),
        "first_say_p95_ms": round(p(report.first_say, 0.95) * 1000),
        "total_p50_ms": round(p(report.total, 0.5) * 1000),
        "total_p95_ms": round(p(report.total, 0.95) * 1000),
        "median_total_ms": round(statistics.median(report.total) * 1000) if report.total else None,
    }


# Lines that turn a conversation back into a service desk. She may offer to DO
# something when he asked for something; these are the reflexes that show up
# after "hey Irene" and make her sound like a helpdesk instead of company.
SERVICE_DESK = re.compile(
    r"\b(anything else (i can|you)|is there anything|let me know if you|"
    r"how (can|may) i (help|assist)|happy to help|at your service today|"
    r"i'?m here to help|what can i do for you today|feel free to ask)\b",
    re.I,
)


async def run_conversation(llm: Ollama, report: Report, repeat: int = 1) -> None:
    """Talking, not commanding. Each case is scored three ways: does the feeling she
    shows fit what he said, did she stay in character, and - for the conversational
    ones - did she talk instead of reaching for a tool."""
    conv = Conversation(llm)
    for case in load("conversation.jsonl"):
        for _ in range(repeat):
            t = await timed_reply(llm, _messages(conv, case))
            _record_time(report, t)
            reply = parse_reply(t.raw)
            called = parse_tool_call(t.raw)
            names = t.cues or ([reply.react.name] if reply.react else [])
            picked = "+".join(names) or "none"
            if called:
                picked, names = "tool-first", ["tool-first"]

            fits = any(n in case["accept"] for n in names) or (not names and "none" in case["accept"])
            note = "" if fits else f"  FEELING {picked} not in {'/'.join(case['accept'])}"
            ok = fits
            report.chat_fit += fits

            # small talk must not become work
            chatty = bool(case.get("no_tool"))
            report.chat_chatty += chatty
            if chatty:
                kept = not called
                report.chat_kept_chat += kept
                if not kept:
                    note += f"  TURNED INTO A TASK ({called[0]})"
                    ok = False

            spoken_text = reply.speak
            desk = SERVICE_DESK.search(spoken_text)
            if desk:
                report.chat_service += 1
                note += f"  SERVICE DESK {desk.group(0)!r}"
                ok = False
            broke = character_break(spoken_text, case.get("sincere", False))
            report.replies += 1
            if broke:
                report.breaks += 1
                note += f"  CHARACTER BREAK {broke!r}"
                ok = False
            if case.get("must_say") and not re.search(case["must_say"], spoken_text, re.I):
                note += f"  MISSING /{case['must_say']}/ in {spoken_text[:70]!r}"
                ok = False
            if case.get("forbid") and re.search(case["forbid"], spoken_text, re.I):
                note += f"  FORBIDDEN /{case['forbid']}/ in {spoken_text[:70]!r}"
                ok = False

            report.chat_n += 1
            report.chat_ok += ok
            report.lines.append(
                f"{'PASS' if ok else 'FAIL'} chat     {case['id']:26} got {picked:16}{note}"
            )
