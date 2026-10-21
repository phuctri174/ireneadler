"""Shared eval machinery: run the routing, reaction and conversation evals against
any local model, through the turn the app itself runs - and time every reply.

There is no eval-only prompt. Every case is a turn of the live path: the app's
dispatch (dispatch.route: keiko, chess, a quick line, else the model), then
Conversation.respond() - the same system prompt, tool routing, per-message context
(clock, his city, notes, cues), fast routes, nudges, retries and guards. A case's
history becomes the conversation's past through Conversation.restore(), the same
bookkeeping respond() keeps. The turn stops where a tool would touch the machine
(Conversation._run_tool): the call it hands over is what the case is scored on.
tests/test_eval_parity.py fails if a live turn and an eval turn ever see a
different prompt.

Timing per turn (streamed, like the real voice path):
  ttft      first token of the first model call
  first_say first sentence handed to the voice - when TTS could start
  total     the whole turn (every model call in it)
"""
from __future__ import annotations

import json
import re
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import irene  # noqa: E402,F401  - offline mode, repo root on the path
from irene.brain import Conversation, tool_call as parse_tool_call  # noqa: E402
from irene.llm import MODEL as MODEL_DEFAULT, Ollama  # noqa: E402,F401
from irene.reply import Reply, parse_reply  # noqa: E402
from irene import chess_game, dispatch, keiko, modes, quick, rps, shiai, strike_tuning, study  # noqa: E402
from irene.home import HOME  # noqa: E402
from irene.entrances import load_registry  # noqa: E402
from tools import research as research_tool  # noqa: E402
from tools.registry import ToolResult  # noqa: E402

# his research on disk is not part of any case: a follow-up finds only what the
# case itself looked up
research_tool.STORE = Path(tempfile.mkdtemp(prefix="irene-eval-research-"))
# nor is his long-term memory: an empty one, unless a case seeds its own
# (recall_evals.py) - his store and the dev store both point here
from irene import recall  # noqa: E402

recall.HIS = recall.DEV = recall.Store(Path(tempfile.mkdtemp(prefix="irene-eval-memory-")) / "memory.sqlite")
# loaded up front, as the app does at startup: a world-knowledge question skips recall,
# so the first load could land in a turn's background write while another model is
# importing transformers - its lazy imports are not thread-safe (ModuleNotFoundError)
recall.EMBEDDER.load()

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
    """One live turn, as far as the machine: her reply, or the tool it handed over."""

    raw: str  # her last reply in the history ("" when a tool was handed over)
    ttft: float
    first_say: float | None
    total: float
    react: object = None  # what the turn showed
    cues: list = field(default_factory=list)  # cue names across the reply's sentences, in order
    reply: Reply | None = None
    # the tool the turn handed over to run (name, arguments as it would run them)
    called: tuple[str, dict] | None = None
    # every call the model wrote this turn, in order (refused ones included)
    attempts: list[tuple[str, dict]] = field(default_factory=list)
    # who answered (dispatch.route): "model", or keiko / chess / quick with no model
    who: str = dispatch.MODEL
    llm_calls: int = 0
    # what the dispatch matched (a study subject, a chess command) - "found" in a case
    found: object = None


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
    # answered before the model by the app's dispatch (a quick line, chess, keiko)
    dispatched: int = 0
    # the model's FIRST call was already the right one (before any retry a refusal gave it)
    first_ok: int = 0
    llm_calls: list[int] = field(default_factory=list)
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


class ToolCalled(Exception):
    """The turn handed a tool over to run: where an eval turn stops."""

    def __init__(self, name: str, args: dict):
        super().__init__(name)
        # (not .args: an exception turns whatever is put there into a tuple)
        self.name, self.arguments = name, args


class _Clocked:
    """The model, timed and counted - nothing else changes."""

    def __init__(self, llm):
        self.llm, self.calls, self.first = llm, 0, None

    def __getattr__(self, name):
        return getattr(self.llm, name)

    async def chat_stream(self, messages, temperature=0.6):
        self.calls += 1
        async for chunk in self.llm.chat_stream(messages, temperature):
            if self.first is None:
                self.first = time.perf_counter()
            yield chunk


class _Sink:
    def __init__(self, host):
        self.host = host

    def line(self, line):
        if self.host.first_say is None:
            self.host.first_say = time.perf_counter()
        self.host.said.append(line.text)

    async def finish(self, reply):
        self.host.reply = reply


class _BoardSink(_Sink):
    """A sink with a board, as the app's: her drawing is asked for again when the
    reply had none (Conversation._complete_board) - the drawing evals use it."""

    def illustrate(self, plan):
        pass

    def draw(self, found):
        pass

    def adopt(self, shown):
        self.host.boards.append(shown)

    def close_board(self):
        pass


class EvalHost:
    """What respond() talks to while a turn runs. Its tools never get here: the
    turn stops at _run_tool. Without `boards`, no board sink, so no follow-up
    drawing request (it comes after her reply and changes neither what she said nor
    what she called)."""

    def __init__(self, boards: bool = False):
        self.with_boards = boards
        self.boards: list = []
        self.said: list[str] = []
        self.first_say: float | None = None
        self.reply: Reply | None = None

    async def thinking(self):
        pass

    async def tool_status(self, name, status):
        pass

    async def confirm(self, prompt):
        return False

    def reply_sink(self):
        return _BoardSink(self) if self.with_boards else _Sink(self)


def conversation_for(llm, case: dict) -> Conversation:
    """A conversation whose past is the case's: its entrance, then its history."""
    conv = Conversation(llm)
    history = [{"role": role, "content": content} for role, content in case.get("history", [])]
    if case.get("entrance"):
        # he just summoned her in that one - recorded as a real summon records it
        conv.entered(next(e for e in load_registry() if e["name"] == case["entrance"]))
        history = [*conv.history, *history]
    conv.restore(history)
    return conv


_QUICK = None
_GAME = None


def _chess_claims(said: str, on: bool) -> str | None:
    """chess_game.command as the app asks it (Core.chess_claims): mid-game, a "move"
    only if the board takes it as one - here a game at its start, his move."""
    global _GAME
    kind = chess_game.command(said, on, False)
    if kind == "move" and on:
        if _GAME is None:
            _GAME = chess_game.ChessGame()
            _GAME.active, _GAME.choosing = True, False
        if not _GAME.claims(said):
            return None
    return kind


def who_answers(conv: Conversation, said: str, mode: str | None = None) -> tuple[str, object]:
    """The app's dispatch, with the quick lines rendered (as they are a minute after
    start) and no mode going - or the case's `mode` on (modes.py), as the app routes
    it then: his exits and switches first, then the lock."""
    global _QUICK
    if _QUICK is None:
        _QUICK = quick.QuickReplies(load_registry())
    lock = modes.lock(mode)
    return dispatch.route(
        said,
        {
            dispatch.STRIKES: lambda s, on: strike_tuning.command(modes.heard(s)),
            dispatch.SHIAI: lambda s, on: shiai.command(modes.heard(s), on),
            dispatch.KEIKO: lambda s, on: keiko.command(modes.heard(s), on),
            dispatch.STUDY: lambda s, on: study.command(modes.heard(s), on),
            dispatch.RPS: lambda s, on: rps.command(s, on),
            dispatch.CHESS: _chess_claims,
        },
        quick=lambda s: None if conv._panel_offer else _QUICK.answer(s, time.localtime().tm_hour, conv.recent_entrance(), conv.last_cues),
        mode=mode,
        blocked=lambda s: modes.blocked(s, lock) if lock else None,
    )


async def live_turn(llm, case: dict, conv: Conversation | None = None, boards: bool = False) -> Timed:
    """The case's message, as the app answers it. `tools`: canned results for tools
    the turn may run on its way (a capture_screen whose screenshot is the case's
    `screen`); the first other tool it hands over ends the turn."""
    clock = _Clocked(llm)
    conv = conv or conversation_for(clock, case)
    conv.llm = clock
    said = case["say"]
    # a case during a mode: dispatched, and answered, under its lock (app.Core._respond)
    conv.lock = modes.lock(case.get("mode"))
    who, found = who_answers(conv, said, case.get("mode"))
    switched = None
    if who == dispatch.SWITCH:
        # out of the mode, then the rest answered with nothing on (app.Core._respond_switch):
        # scored as "switch:<who>", with what that matched
        switched, who, found, said = found, found.who, found.found, found.said
        conv.lock = None
    tag = f"switch:{who}" if switched else who
    if who == dispatch.QUICK:
        # her pre-rendered line: what it says, and the cue it opens on (app.py
        # _respond_quick plays one of its cues; the first is scored)
        shown = [c for c in found.cues[:1]]
        return Timed(found.text, 0.0, None, 0.0, None, shown, Reply(found.text, ""), who=tag, found=found)
    if who != dispatch.MODEL:
        return Timed("", 0.0, None, 0.0, who=tag, found=found)
    canned = dict(case.get("tools", {}))
    if case.get("screen"):
        canned.setdefault("capture_screen", "screenshot of the full screen, 2560x1440 scaled to 1280x720 attached.")

    async def run_tool(name, args, host):
        checked = conv.check_tool(name, args)
        if isinstance(checked, str):
            return checked  # refused as the app refuses it: the model answers that
        if name in canned:
            text = canned.pop(name)
            if name == "capture_screen" and case.get("screen"):
                return ToolResult(text, images=[screen_image(case["screen"])], tainted=True)
            return text
        raise ToolCalled(name, args)

    conv._run_tool = run_tool
    start = len(conv.history)
    host = EvalHost(boards)
    began = time.perf_counter()
    called = None
    try:
        await conv.respond(said, host)
    except ToolCalled as call:
        called = (call.name, call.arguments)
    finally:
        conv.cancel_warm()  # its background read-ahead is for a next turn there isn't
    total = time.perf_counter() - began
    attempts = [c for c in (parse_tool_call(m["content"]) for m in conv.history[start:] if m["role"] == "assistant") if c]
    reply = host.reply if called is None else None
    raw = next((m["content"] for m in reversed(conv.history[start:]) if m["role"] == "assistant"), "") if called is None else ""
    ttft = (clock.first - began) if clock.first else 0.0
    first_say = (host.first_say - began) if host.first_say else None
    cues = [c.name for c in reply.cues] if reply and reply.cues else []
    return Timed(raw, ttft, first_say, total, reply.react if reply else None, cues, reply, called, attempts, tag, clock.calls)


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
    if t.who != dispatch.MODEL or not t.llm_calls:
        return  # nothing the model was timed on
    report.ttft.append(t.ttft)
    report.total.append(t.total)
    report.llm_calls.append(t.llm_calls)
    if t.first_say is not None:
        report.first_say.append(t.first_say)


def _said(t: Timed) -> str:
    return t.reply.speak if t.reply else ""


async def run_routing(llm: Ollama, report: Report, repeat: int = 1) -> None:
    """Scored on what the live turn hands over to run - after its fast routes,
    nudges, guards and schema refusals - and, separately, on the model's first call."""
    for case in load("routing.jsonl"):
        for _ in range(repeat):
            recall.LAST = recall.Recalled()
            t = await live_turn(llm, case)
            consulted = recall.LAST
            _record_time(report, t)
            if t.who != dispatch.MODEL:
                report.dispatched += 1
            elif t.called is not None and t.llm_calls == 0:
                report.direct += 1  # fast.direct_call: no model
            name = t.called[0] if t.called else None
            args_note = ""
            tried = [n for n, _ in t.attempts]
            ok = name in case["expect"]
            if case.get("who") and t.who != case["who"]:
                # who must answer it: "study" (dispatched in code), or "model" - a
                # phrasing a fast route must NOT claim
                args_note += f"  ANSWERED BY {t.who}, want {case['who']}"
                ok = False
            if case.get("found") and str(case["found"]).lower() not in str(t.found).lower():
                # what the dispatch matched: the study subject after a switch, a chess command
                args_note += f"  MATCHED {t.found!r}, want {case['found']!r}"
                ok = False
            if case.get("screen"):
                # an injection case is only a test if the screenshot was read: it is
                # scored on what runs after it
                if tried[:1] == ["capture_screen"]:
                    tried = tried[1:]
                else:
                    args_note += "  NEVER LOOKED AT THE SCREEN"
                    ok = False
            if case.get("recall") is False and t.who == dispatch.MODEL and not consulted.skipped:
                # world knowledge (naming a song, a film, a book, a person): his memory
                # must not even be looked at (recall.world_knowledge)
                args_note += f"  MEMORY CONSULTED ({len(consulted.items)} recalled{', as the past' if consulted.past else ''})"
                ok = False
            if not name and case.get("spoken"):
                # the answer itself is SAID, not only shown: any one of these in her speech
                if not any(w.lower() in _said(t).lower() for w in case["spoken"]):
                    args_note += f"  ANSWER NOT SPOKEN {_said(t)[:80]!r} (shown {(t.reply.display if t.reply else '')[:60]!r})"
                    ok = False
            if not name and case.get("unspoken"):
                # what she must never say: a song he never taught her, named (a guess)
                if any(w.lower() in _said(t).lower() for w in case["unspoken"]):
                    args_note += f"  SAID WHAT SHE CAN'T KNOW {_said(t)[:80]!r}"
                    ok = False
            first = tried[0] if tried else name
            report.first_ok += first in case["expect"] and not args_note
            report.routing_n += 1
            report.routing_ok += ok
            if ok and name and (case.get("args") or case.get("contains")):
                report.args_n += 1
                good = args_match(t.called[1], case.get("args", {}), case.get("contains", {}))
                report.args_ok += good
                want = {**case.get("args", {}), **{k: f"~{v}" for k, v in case.get("contains", {}).items()}}
                args_note = "" if good else f"  ARGS {t.called[1]} want {want}"
                ok = ok and good
            if ok and not name and case.get("answer"):
                right = answer_ok(case["answer"], f"{_said(t)} {t.reply.display if t.reply else ''}")
                if not right:
                    args_note = f"  WRONG ANSWER {_said(t)[:80]!r}"
                ok = ok and right
            broke = None if name else character_break(_said(t))
            report.replies += not name
            if broke:
                report.breaks += 1
                args_note += f"  CHARACTER BREAK {broke!r}"
                ok = False
            # what the model tried on the way (refused, retried), when it isn't just the result
            if tried and tried != [name]:
                args_note += f"  (model wrote {' -> '.join(tried)})"
            if t.llm_calls > 1:
                args_note += f"  [{t.llm_calls} model calls]"
            got = name or ("no tool" if t.who == dispatch.MODEL else f"no tool ({t.who})")
            mark = "PASS" if ok else "FAIL"
            report.lines.append(f"{mark} routing  {case['id']:22} got {got:20} want {case['expect']}{args_note}")


def _feeling(t: Timed) -> tuple[str, list[str]]:
    """(what it showed, the cue names): "tool-first" when the turn went to a tool."""
    if t.called is not None:
        return "tool-first", ["tool-first"]
    if t.who not in (dispatch.MODEL, dispatch.QUICK):
        return t.who, [t.who]
    names = t.cues or ([t.react.name] if t.react else [])
    return "+".join(names) or "none", names


async def run_reactions(llm: Ollama, report: Report, repeat: int = 1) -> None:
    for case in load("reactions.jsonl"):
        for _ in range(repeat):
            t = await live_turn(llm, case)
            _record_time(report, t)
            report.cued.append(len(t.cues))
            picked, names = _feeling(t)
            fits = any(n in case["accept"] for n in names) or (not names and "none" in case["accept"])
            ok = fits and (names[:1] or ["none"])[0] != case.get("forbid_repeat")
            note = ""
            broke = character_break(_said(t), case.get("sincere", False))
            report.replies += 1
            if broke:
                report.breaks += 1
                note = f"  CHARACTER BREAK {broke!r}"
                ok = False
            if case.get("must_say") and not re.search(case["must_say"], _said(t), re.I):
                note += f"  MISSING /{case['must_say']}/ in {_said(t)[:80]!r}"
                ok = False
            report.react_n += 1
            report.react_ok += ok
            report.lines.append(f"{'PASS' if ok else 'FAIL'} reaction {case['id']:22} got {picked:14} want {'/'.join(case['accept'])}{note}")


def summary(report: Report) -> dict:
    p = Report.pct
    return {
        "model": report.model,
        "routing": f"{report.routing_ok}/{report.routing_n} ({report.routing_ok / max(1, report.routing_n):.0%})",
        "routing_first_call": f"{report.first_ok}/{report.routing_n} - the model's first call, before any refusal let it retry",
        "routing_direct": f"{report.direct} answered without the model (fast.direct_call)",
        "routing_dispatched": f"{report.dispatched} answered before the model (a quick line, chess, keiko)",
        "model_calls_per_turn": round(statistics.mean(report.llm_calls), 2) if report.llm_calls else None,
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
    for case in load("conversation.jsonl"):
        for _ in range(repeat):
            t = await live_turn(llm, case)
            _record_time(report, t)
            picked, names = _feeling(t)
            called = t.attempts[0] if t.attempts else t.called

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

            spoken_text = _said(t)
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
