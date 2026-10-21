# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Mode entry, in code, before anything else sees the words.

Modes are a closed set - study mode, shiai, chess, rock-paper-scissors, keiko, the
strike calibration, lecture capture - and entering one is never a judgement call.
So the app asks this first (dispatch.route, with `heard()` applied): a mode command
is claimed here, deterministically, and neither the fast path nor the model ever
sees it. Anything that is not one falls through to them unchanged. Lecture capture
is matched the same way in fast.direct_call (code, before the model).

Whisper mishears some of the mode words, the same way every time, and the
hotword budget is full (223 tokens). So the mishearings are rewritten back - but
only where a mode command stands ("let's do CI"), never elsewhere in a sentence -
and the per-mode patterns then match as usual. Every alias is one Whisper produced
for his voice, logged or re-decoded from his saved turns (core/voice_data/turns):

  shiai   "CI", "Xi'an", "xi-ai", "Si An", "Sii"     2026-10-18, five turns
  Sicilian "La Sicilia", "Gaula Sicilian"            2026-10-18 ("go learn Sicilian")
  strikes "stripe", "strike", "Mindstrike"           2026-10-18 ("calibrate my strikes")

Add a new one when the logs show it; keep each anchored to its command.
"""
from __future__ import annotations

import contextvars
import logging
import re
from dataclasses import dataclass

log = logging.getLogger("irene.modes")

# things he says before the command that are not part of it: "Yes, let's do shiai"
# ("hey": live, Whisper often keeps the "hey" of "hey Irene" and drops her name -
# "Hey learn Sicilian please" fell through to chat, 2026-10-18)
_PREFACE = re.compile(r"^\W*(?:(?:yes|yeah|yep|ok(?:ay)?|alright|right|so|well|come\s+on|now|hey|please)\b[\s,.!]*)+", re.I)

_SHIAI_HEARD = r"(?:ci|c\.i\.|xi'?\s?an|xi-?ai|si\s?an|si+|shi\s?ai|shia|shiai)"
# (pattern, replacement) in order; each only where the mode command stands
ALIASES: tuple[tuple[re.Pattern, str], ...] = tuple(
    (re.compile(p, re.I), r)
    for p, r in (
        # "let's do CI", "start a Xi'an", "time for si an", "wanna do CI?"
        (r"\b((?:let'?s|let\s+us|wanna|want\s+to|shall\s+we|can\s+we|time\s+(?:for|to)|start|begin)\s+(?:do\s+|have\s+)?(?:a\s+)?)" + _SHIAI_HEARD + r"(?=\W|$)", r"\1shiai"),
        # "CI time", "CI with me"
        (r"^(\W*(?:(?:hey\s+)?irene\W+)?)" + _SHIAI_HEARD + r"(\s+(?:time|with\s+me))\b", r"\1shiai\2"),
        # "Go La Sicilia", "Gaula Sicilian": "go learn the Sicilian"
        (r"^(\W*(?:(?:hey\s+)?irene\W+)?)(?:go\s+la|gaula|go\s+lan?)\s+sicili(?:a|an)\b", r"\1go learn the Sicilian"),
        # "calibrate my stripe", "calibrate Mindstrike": "calibrate my strikes"
        (r"\b(calibrat\w*)\s+(?:my\s*|mine\s*|mind\s*)(?:stripes?|strikes?)\b", r"\1 my strikes"),
    )
)


def heard(text: str) -> str:
    """His words with the known mishearings of mode commands put back, and anything
    said before the command ("yes, ...") set aside - for mode matching only."""
    said = (text or "").strip()
    said = _PREFACE.sub("", said) or said
    for pattern, repl in ALIASES:
        said = pattern.sub(repl, said)
    return said


# ---- his orders: out of a mode, and out of one into another -------------------------
#
# The lock below stops HER wandering off; it never stops HIM. So before it, in code:
#   an exit     "cancel", "quit this", "stop the match", "forget the chess",
#               "never mind the game" - the mode on ends (its own goodbye)
#   a compound  "cancel the chess match then learn tenouchi" - the mode on ends and
#               the rest is routed as if nothing were on (study mode on tenouchi)
#   a switch    another mode's start said outright ("let's do shiai" mid-chess) -
#               dispatch.route ends this one and starts that one
# Whatever names a mode ("the chess", "the match", "studying", "the lecture") ends the
# mode that is on: he wants out, whichever word he used for it.

_EXIT_VERB = (r"(?:cancel|stop|end|quit|abandon|drop|leave|exit|finish|scrap|ditch|skip|forget(?:\s+about)?|never\s*mind|"
              r"enough(?:\s+(?:of|with))?|no\s+more|i'?m\s+done\s+with|we'?re\s+done\s+with)")
_MODE_NOUN = (r"(?:(?:the|this|that|our|my|your)\s+)?(?:(?:chess\s+)?(?:match|game|bout)|chess|shiai|kendo(?:\s+(?:match|bout|practice))?|"
              r"keiko|practice|sparring|studying|study(?:\s+mode)?|(?:the\s+)?books?|reading|lecture(?:\s+capture)?|listening|"
              r"capture|recording|notes|rock\s+paper\s+scissors|rps|calibration|calibrating)")
_LEAD = r"^\W*(?:(?:hey\s+|okay\s+|ok\s+)?irene\W+)?(?:(?:okay|ok|alright|right|actually|wait|no|nah)\W+)*(?:(?:let'?s|please|just)\s+)?"
# study mode's own: "put the book down"
_PUT_DOWN = r"put\s+(?:the\s+|your\s+|that\s+)?(?:books?|notes)\s+(?:down|away)"
# the whole of what he said is the exit
_EXIT_ALONE = re.compile(
    _LEAD + r"(?:" + _EXIT_VERB + r"(?:\s+(?:" + _MODE_NOUN + r"|it|this|that))?"
    r"|" + _PUT_DOWN + r"|i'?m\s+done|we'?re\s+done)(?:\s+(?:now|please|irene|then))*\W*$",
    re.I,
)
# an exit, then something else: "cancel the chess match then learn tenouchi"
_THEN = r"(?:\s*[,.;!]+\s*|\s+)(?:and\s+)?(?:then\s+|instead\s+|now\s+|so\s+)?(?:,\s*)?"
_EXIT_NAMED_THEN = re.compile(_LEAD + r"(?:" + _EXIT_VERB + r"\s+" + _MODE_NOUN + r"|" + _PUT_DOWN + r")" + _THEN + r"(?P<rest>\S.*)$", re.I)
# a bare verb ("stop and ...", "cancel, ...") is an exit only when what follows is a mode
_EXIT_BARE_THEN = re.compile(_LEAD + r"(?:(?:quit|cancel|stop|end|forget|drop|scrap)\s+(?:it|this|that)|" + _EXIT_VERB + r")" + _THEN + r"(?P<rest>\S.*)$", re.I)

# rock-paper-scissors is named, not ordered, in plenty of trash talk ("I'd beat you at
# rock paper scissors too"): out of another mode, only an order to play it starts it
_RPS_ORDER = re.compile(
    r"^\W*(?:(?:hey\s+)?irene\W+)?(?:(?:let'?s|let\s+us|wanna|want\s+to|shall\s+we|can\s+we|could\s+we|how\s+about|time\s+for|start|"
    r"begin|play|i\s+want\s+to|do\s+you\s+want\s+to)\s+)+(?:play\s+|do\s+)?(?:a\s+(?:game|round)\s+of\s+|some\s+)?(?:rock|rps\b)",
    re.I,
)


@dataclass(frozen=True)
class Order:
    """His order to leave the mode on: `rest` is what he said after it, if anything,
    to be routed once the mode is off - and `named` whether the exit named a mode."""

    rest: str | None
    named: bool = False


def order(text: str, mode: str | None) -> Order | None:
    """His words as an exit from the mode on: Order(None) for an exit on its own,
    Order(rest) for an exit followed by something else, None for neither. Without a
    mode on there is nothing to leave."""
    if not mode:
        return None
    said = (text or "").strip()
    if _EXIT_ALONE.search(said):
        return Order(None)
    m = _EXIT_NAMED_THEN.search(said)
    if m:
        return Order(m.group("rest").strip(), named=True)
    m = _EXIT_BARE_THEN.search(said)
    if m:
        return Order(m.group("rest").strip())
    return None


def may_switch(who: str, said: str) -> bool:
    """May this other mode's claim start it out of the mode on? Every mode's start
    is an order already (anchored to the start of what he said) - but rock-paper-
    scissors is matched anywhere, so out of another mode it must be asked for."""
    return who != "rps" or bool(_RPS_ORDER.search(said))


def starts_lecture(said: str) -> bool:
    """Is this his order to start a lecture capture (fast.direct_call's lecture_start)?"""
    from . import fast
    from .brain import parse_tool_call

    call = fast.direct_call((said or "").strip())
    parsed = parse_tool_call(call) if call is not None else None
    return bool(parsed and parsed[0] == "lecture_start")


# ---- the mode lock -----------------------------------------------------------------
#
# While a mode is on - chess, shiai, study mode, keiko, rock-paper-scissors, a strike
# calibration, lecture capture - it owns the display until he ends it. He can still
# talk to her (trash talk, in character), and the mode's own commands and its exit
# are its own code's (dispatch.route claims them first). Nothing else may repaint.
#
# Enforced in three places, none of them an instruction the model could be talked
# out of:
#   1. what the model can call: only the tools that change nothing on screen
#      (Lock.tools) are offered or run - the rest do not exist for that turn, the
#      way screen observation has no tool at all; a call to one is answered with
#      the brush-off, never run (brain.Conversation)
#   2. the turn has no board: no plan, and a <draw> she writes is dropped (brain)
#   3. a locked turn's messages: anything that would repaint (HOLD below, checked
#      in Bridge.send) is dropped before it reaches the HUD
# And an explicit request for what is blocked - another mode, "research X", "draw
# me X", the panel, a lecture capture - gets a short in-character brush-off, in
# code (blocked(), app.Core._respond_blocked), not silence.

# who can hold the display, in the order a mode is looked for (only one is ever on)
MODES = ("strikes", "shiai", "keiko", "study", "rps", "chess", "lecture")

# tools that change nothing on screen: allowed to the model while a mode is on
QUIET_TOOLS = frozenset({
    "get_time", "set_timer", "change_volume", "set_volume", "mute",
    "media_play_pause", "media_next", "media_previous", "system_status",
})
# each mode's own tools (its exit, where the model is how it is reached)
OWN_TOOLS: dict[str, frozenset[str]] = {"lecture": frozenset({"lecture_stop", "lecture_ask"})}

# HUD messages that change what is on screen (her board, the panel, a scene over her).
# Not the dashboard's live readout (CPU, timers): a timer set mid-game still shows.
REPAINTS = frozenset({"draw", "board_term", "panel", "activity", "entrance", "summon", "show_url"})

# the mode that owns the display for the turn being run (None: not locked). Set on
# the turn's task only (app.Core._locked_task), so the mode's own handlers - a chess
# move redrawing its board - are never caught by it.
HOLD: contextvars.ContextVar[str | None] = contextvars.ContextVar("irene_mode_hold", default=None)


@dataclass(frozen=True)
class Lock:
    mode: str
    tools: frozenset[str]

    def allows(self, tool: str) -> bool:
        return tool in self.tools


def lock(mode: str | None) -> Lock | None:
    """The lock for this active mode, or None."""
    if not mode:
        return None
    return Lock(mode, QUIET_TOOLS | OWN_TOOLS.get(mode, frozenset()))


def held() -> str | None:
    """The mode holding the display for the turn running now (HOLD), or None."""
    return HOLD.get()


def gate(message: dict) -> dict | None:
    """A HUD message as a locked turn may send it: a repaint dropped (None), a tool's
    prop scene taken off its status, a reply's display text off the screen."""
    mode = HOLD.get()
    if mode is None:
        return message
    kind = message.get("type")
    if kind in REPAINTS:
        log.warning("mode lock (%s): dropped a %r message from a locked turn", mode, kind)
        return None
    if kind == "tool" and message.get("cue"):
        return {**message, "cue": None}
    if kind == "reply" and message.get("display"):
        return {**message, "display": ""}
    return message


# what he asks for that the lock refuses, by the tool it would take
_KIND = {
    "research": "research", "read_page_text": "research", "youtube_search": "research", "daily_briefing": "research",
    "show_panel": "panel", "save_panel_pdf": "panel", "open_dashboard_item": "panel", "clear_research": "panel",
    "lecture_start": "lecture", "lecture_stop": "lecture", "lecture_summary": "lecture", "lecture_research": "lecture", "lecture_ask": "lecture",
    "perform": "show", "capture_screen": "screen", "screens_off": "screen", "enable_screens_off": "screen",
}


def blocked(text: str, active: Lock) -> str | None:
    """What an EXPLICIT request for something the lock refuses is ("research", "draw",
    "panel", "lecture", ...), or None - talk, trash talk, a question, a quiet command:
    the model answers it, with only the quiet tools. Inferred lookups (an opening
    named in a question, a price) are not requests: those go to the model too, which
    has no research to reach for."""
    from . import board, fast
    from .brain import parse_tool_call

    said = (text or "").strip()
    call = fast.direct_call(said)
    if call is not None:
        parsed = parse_tool_call(call)
        name = parsed[0] if parsed else None
        if name and not active.allows(name):
            if name != "research" or fast._research(said) is not None:
                return _KIND.get(name, "other")
    if board.wanted(said):
        return "draw"
    return None


# every line says WHY: a mode is on, and which - a refusal must never pass for a bug
BRUSH_OFF: dict[str, tuple[str, ...]] = {
    "chess": ("Not now - we're in the middle of a chess game. Your move.", "We're mid-game in chess - after the game. Your move.",
              "Can't, we're playing chess right now. Say stop the game first."),
    "shiai": ("Not now - we're in the middle of a bout. Kamae!", "We're mid-shiai - points first. Say stop the match to end it.",
              "Can't, we're in a bout right now. Kamae!"),
    "keiko": ("Not now - we're in the middle of keiko. Kamae!", "We're practising right now - say stop keiko first."),
    "study": ("Not now - I'm in study mode, head in the book. Say stop studying first.",
              "Can't, I'm studying right now. Ask me when I'm done."),
    "rps": ("Not now - we're in the middle of rock-paper-scissors. Finish it first.",
            "We're mid-game in rock-paper-scissors - say quit the game to end it."),
    "strikes": ("Not now - I'm measuring your strikes. Three swings first.", "Can't, I'm calibrating your strikes - swing, then ask."),
    "lecture": ("Not now - I'm capturing a lecture. Say stop listening first.",
                "Can't, I'm listening to the lecture right now. Ask me when it's over."),
}
# her face for it: during study mode and the dojo only expressions (a gesture's hands
# would draw over the book or the bogu); over the chess board only the face shows
BRUSH_OFF_CUES: dict[str, tuple[str, ...]] = {
    "chess": ("smug", "wink", "focused"),
    "shiai": ("firedUp", "smug", "focused"),
    "keiko": ("firedUp", "focused"),
    "study": ("indignant", "focused", "sulking"),
    "rps": ("notNow", "smug", "wink"),
    "strikes": ("notNow", "focused"),
    "lecture": ("notNow", "takeNotes", "focused"),
}


class BrushOff:
    """Her line for a blocked request: the mode's own, never the same twice running."""

    def __init__(self, rng=None) -> None:
        import random

        self.rng = rng or random.Random()
        self._last: dict[str, str] = {}
        self._last_cue: str | None = None

    def __call__(self, mode: str) -> tuple[str, str]:
        lines = BRUSH_OFF.get(mode, BRUSH_OFF["chess"])
        line = self.rng.choice([x for x in lines if x != self._last.get(mode)] or list(lines))
        self._last[mode] = line
        cues = BRUSH_OFF_CUES.get(mode, ("smug",))
        cue = self.rng.choice([c for c in cues if c != self._last_cue] or list(cues))
        self._last_cue = cue
        return line, cue


_DOING = {
    "chess": "a chess game with him", "shiai": "a shiai with him (a kendo match, first to two)",
    "keiko": "keiko with him (kendo practice)", "study": "study mode (you are studying, head in the book)",
    "rps": "a game of rock-paper-scissors with him", "strikes": "measuring his strikes",
    "lecture": "a lecture capture (you are listening to a lecture playing on his PC)",
}


def lock_section(active: Lock) -> str:
    """The per-message line that says what is going on. Only a help: the lock itself
    is the tools that exist for the turn and the display gate, not these words."""
    return (f"## Right now\nYou are in the middle of {_DOING.get(active.mode, active.mode)}. It owns the screen until he ends it. "
            "Talk with him all you like - tease him back, in character - but in words only: no drawing, nothing looked up, nothing shown.")


# ---- no mode can get stuck ----------------------------------------------------------
#
# The mode guard (app.Core._mode_guard) ends any mode with nothing happening in it for
# this long - on top of each mode's own timeout, so even one whose own watchdog died
# clears. Chess and a lecture capture had no timeout of their own.
IDLE_LIMIT_S = {"strikes": 60.0, "shiai": 180.0, "keiko": 180.0, "rps": 120.0, "study": 660.0, "chess": 1200.0, "lecture": 1800.0}
# what the mode is called, on screen (the dashboard header) and when she ends it
SHOWN = {"strikes": "Strike calibration", "shiai": "Shiai", "keiko": "Keiko", "rps": "Rock-paper-scissors", "study": "Study",
         "chess": "Chess", "lecture": "Lecture capture"}
