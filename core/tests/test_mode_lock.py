"""The mode lock (irene/modes.py): while chess, shiai, study mode, keiko, rock-paper-
scissors, a strike calibration or a lecture capture is on, it owns the display until
he ends it. Filming, 2026-10-18: he trash-talked mid-game ("You can even play
Sicilian?") and she replaced the board with a drawing.

Every blocked tool is attempted during every mode, the way it would really come -
the model writing the call - through the app's real turn (Core.on_command) and the
real Bridge, with what reached the HUD recorded at the socket: the tool never runs,
she brushes it off, and nothing that repaints the display was sent."""
from __future__ import annotations

import asyncio
import json
import types

import pytest

from irene import dispatch, modes
from irene.brain import Conversation
from tools import REGISTRY

MODES = list(modes.MODES)
BLOCKED_TOOLS = sorted(t for t in REGISTRY if t not in modes.QUIET_TOOLS)
# tools whose args the schema needs, so the call is one the app would accept
ARGS = {
    "research": {"question": "black holes"}, "read_page_text": {"url": "https://example.com"}, "open_url": {"url": "https://example.com"},
    "open_in_my_browser": {"url": "https://example.com"}, "youtube_play": {"query": "lofi"}, "youtube_search": {"query": "lofi"},
    "show_panel": {"what": "last research"}, "perform": {"sequence": "surprise"},
}


class Socket:
    """The HUD end of the socket: every message core sent it."""

    def __init__(self):
        self.sent: list[dict] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    def repaints(self) -> list[dict]:
        return [m for m in self.sent if m.get("type") in modes.REPAINTS or (m.get("type") == "tool" and m.get("cue"))
                or (m.get("type") == "reply" and m.get("display"))]

    def said(self) -> list[str]:
        return [m["text"] for m in self.sent if m.get("type") == "transcript" and m.get("role") == "irene"]


class Model:
    """The model, writing the same reply every call; counts its calls."""

    def __init__(self, reply: str):
        self.reply, self.calls, self.last, self.parked = reply, 0, {}, False

    async def chat_stream(self, messages, temperature=0.6):
        self.calls += 1
        for k in range(0, len(self.reply), 12):
            yield self.reply[k:k + 12]

    async def chat(self, messages, temperature=0.6, **_):
        return ""

    def __getattr__(self, name):
        async def nothing(*_a, **_k):
            return None

        return nothing


def _core(mode: str, monkeypatch):
    from irene import app as app_module
    from irene.bridge import Bridge

    core = app_module.Core()
    core.bridge = Bridge()
    socket = Socket()
    core.bridge._clients.add(socket)
    core.speaker = None
    # the mode on, as its own code leaves it
    if mode == "strikes":
        core._calibrating = []
    elif mode == "lecture":
        core.lectures = types.SimpleNamespace(active=True, note_turn=lambda: None)
    else:
        getattr(core, mode).active = True
    if mode == "chess":
        monkeypatch.setattr(core.chess, "board_spec", lambda: {"template": "chessboard", "fen": "start"})
    ran: list[str] = []

    async def never(self, name, args, host):
        ran.append(name)
        raise AssertionError(f"{name} ran during {mode}")

    monkeypatch.setattr(Conversation, "_run_tool", never)
    return core, socket, ran


def _turn(core, text: str, reply: str) -> Model:
    model = Model(reply)
    core.conversation.llm = model

    async def run():
        await core.on_command({"text": text, "via": "voice", "_origin": "script"})
        if core._turn is not None:
            await asyncio.wait_for(core._turn, 10)

    asyncio.run(run())
    return model


def test_every_mode_has_a_lock_and_its_brush_off():
    for mode in MODES:
        lock = modes.lock(mode)
        assert lock is not None and lock.mode == mode
        assert modes.BRUSH_OFF[mode] and modes.BRUSH_OFF_CUES[mode]
    assert modes.lock(None) is None


@pytest.mark.parametrize("mode", MODES)
def test_the_model_is_offered_only_the_quiet_tools(mode):
    conv = Conversation(None)
    conv.lock = modes.lock(mode)
    offered = set(conv.offered())
    assert offered <= modes.QUIET_TOOLS | modes.OWN_TOOLS.get(mode, frozenset())
    for name in BLOCKED_TOOLS:
        if name in modes.OWN_TOOLS.get(mode, ()):
            continue
        refused = conv.check_tool(name, ARGS.get(name, {}))
        assert isinstance(refused, str) and refused.startswith("error: no tool"), (mode, name)
    # the per-message tools section never names one
    block = conv.context("hmm, interesting").split("## Right now")[0]
    for name in BLOCKED_TOOLS:
        if name not in offered:
            assert f"{name}(" not in block and f"- {name}" not in block, (mode, name)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("tool", BLOCKED_TOOLS)
def test_every_blocked_tool_during_every_mode_is_brushed_off_and_the_display_unchanged(mode, tool, monkeypatch):
    if tool in modes.OWN_TOOLS.get(mode, ()):
        pytest.skip("the mode's own exit")
    core, socket, ran = _core(mode, monkeypatch)
    call = json.dumps({"name": tool, "arguments": ARGS.get(tool, {})})
    _turn(core, "hmm, what do you think about that", f"<tool_call>{call}</tool_call>")
    assert ran == []
    assert socket.repaints() == [], socket.repaints()
    said = " ".join(socket.said())
    assert any(line in said for line in modes.BRUSH_OFF[mode]), said


@pytest.mark.parametrize("mode", MODES)
def test_trash_talk_is_answered_and_her_drawing_is_never_shown(mode, monkeypatch):
    """The filmed failure: talk about an opening, mid-game - she answers, in words."""
    core, socket, ran = _core(mode, monkeypatch)
    reply = ('<speak><cue>smug</cue>Can I play the Sicilian? Watch me.</speak>'
             '<display>The Sicilian: 1.e4 c5</display>'
             '<draw>{"template": "chessboard", "moves": "e4 c5"}</draw>')
    model = _turn(core, "You can even play Sicilian?", reply)
    assert model.calls >= 1, "trash talk goes to the model"
    assert ran == []
    assert socket.repaints() == []
    assert "Watch me" in " ".join(socket.said())


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("said", [
    "Research black holes", "look up suriage waza", "search tenouchi", "Draw me a black hole",
    "Show me the panel", "Turn the screens off",
])
def test_an_explicit_request_is_brushed_off_in_code(mode, said, monkeypatch):
    core, socket, ran = _core(mode, monkeypatch)
    model = _turn(core, said, "<speak>should never be asked</speak>")
    assert model.calls == 0, "decided in code, never by the model"
    assert ran == [] and socket.repaints() == []
    assert any(line in " ".join(socket.said()) for line in modes.BRUSH_OFF[mode])


def test_the_mode_keeps_its_own_commands():
    """dispatch.route: with chess on, a move is chess's; shiai's yame is shiai's."""
    claims = {dispatch.CHESS: lambda s, on: "move" if on else None}
    assert dispatch.route("e4", claims, mode="chess")[0] == dispatch.CHESS
    assert dispatch.route("yame", {dispatch.SHIAI: lambda s, on: "stop" if on else None}, mode="shiai")[0] == dispatch.SHIAI
    # nothing on: unchanged
    assert dispatch.route("let's play chess", {dispatch.CHESS: lambda s, on: "start"})[0] == dispatch.CHESS


def test_a_quiet_command_still_works_mid_game():
    lock = modes.lock("chess")
    assert modes.blocked("What time is it?", lock) is None
    assert modes.blocked("Set a timer for 10 minutes", lock) is None
    assert modes.blocked("You can even play Sicilian?", lock) is None
    assert modes.blocked("research the Sicilian", lock) == "research"
    assert modes.blocked("draw me a cat", lock) == "draw"


def test_the_mode_own_messages_are_never_caught_by_the_gate():
    """The gate is the locked TURN's: the chess game redrawing its own board, outside
    one, goes through."""
    assert modes.gate({"type": "draw", "value": {"template": "chessboard"}}) is not None
    token = modes.HOLD.set("chess")
    try:
        assert modes.gate({"type": "draw", "value": {}}) is None
        assert modes.gate({"type": "panel", "value": {}}) is None
        assert modes.gate({"type": "reaction", "value": "smug"}) == {"type": "reaction", "value": "smug"}
        assert modes.gate({"type": "reply", "display": "x", "speak": "y"})["display"] == ""
    finally:
        modes.HOLD.reset(token)


def test_brush_off_never_repeats_itself_twice_running():
    b = modes.BrushOff()
    for mode in MODES:
        last = None
        for _ in range(12):
            line, cue = b(mode)
            assert line != last
            last = line
