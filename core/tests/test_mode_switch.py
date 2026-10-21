"""His orders beat the mode lock (irene/modes.py, dispatch.route): filming, 2026-10-18,
"cancel the chess match then learn tenouchi" was refused. The lock is for HER
wandering off - never for him.

  an exit       "cancel", "quit this", "stop the match", "forget the chess", "never
                mind the game": the mode on ends
  a switch      another mode's start, said outright mid-mode
  a compound    an exit then a start, in one breath: out of one, into the other

Every mode into every other, through the app's real turn (Core.on_command); and the
trash talk that names a mode without ordering one still never leaves it."""
from __future__ import annotations

import asyncio

import pytest

from evals import harness
from irene import dispatch, modes
from irene.brain import Conversation
from tests.test_mode_lock import MODES, _core, _turn

# each mode's start as he says it
STARTS = {
    "chess": "Let's play chess!", "shiai": "Irene, let's do shiai", "keiko": "Let's do keiko",
    "study": "Irene, go study the Sicilian", "rps": "Let's play rock paper scissors", "strikes": "Calibrate my strikes",
    "lecture": "Irene, listen to this lecture for me.",
}
# the exit he says before it, per mode he is in
EXITS = {
    "chess": "cancel the chess match", "shiai": "stop the match", "keiko": "quit this", "study": "forget the studying",
    "rps": "never mind the game", "strikes": "cancel the calibration", "lecture": "stop the lecture",
}
ENTRY = {"chess": "_respond_chess", "shiai": "_respond_shiai", "keiko": "_respond_keiko", "study": "_respond_study",
         "rps": "_respond_rps", "strikes": "_respond_strikes", "lecture": "_respond"}


def _record(core, monkeypatch) -> list[tuple]:
    """Every mode ended and every turn entered, in order - nothing really run."""
    seen: list[tuple] = []

    async def end(mode):
        seen.append(("end", mode))

    monkeypatch.setattr(core, "_end_mode", end)
    for name in set(ENTRY.values()):
        async def entry(text, *args, name=name, **_k):
            seen.append((name, text, *args))

        monkeypatch.setattr(core, name, entry)
    return seen


def _cases():
    for mode in MODES:
        for other in sorted(STARTS):
            if other != mode:
                yield mode, other


@pytest.mark.parametrize("mode,other", list(_cases()))
def test_another_mode_said_outright_switches(mode, other, monkeypatch):
    core, socket, ran = _core(mode, monkeypatch)
    seen = _record(core, monkeypatch)
    _turn(core, STARTS[other], "<speak>never</speak>")
    assert seen[0] == ("end", mode), seen
    assert seen[1][0] == ENTRY[other], seen
    assert not any(line in " ".join(socket.said()) for line in modes.BRUSH_OFF[mode])


@pytest.mark.parametrize("mode,other", list(_cases()))
@pytest.mark.parametrize("joint", [" then ", ", ", " and then ", ". "])
def test_an_exit_then_another_mode_in_one_breath(mode, other, joint, monkeypatch):
    core, socket, ran = _core(mode, monkeypatch)
    seen = _record(core, monkeypatch)
    start = STARTS[other]
    _turn(core, f"{EXITS[mode]}{joint}{start[0].lower()}{start[1:]}", "<speak>never</speak>")
    assert seen[0] == ("end", mode), seen
    assert seen[1][0] == ENTRY[other], seen


def test_the_filmed_compound():
    """"Cancel the chess match then learn tenouchi": out of chess, study mode on tenouchi."""
    conv = Conversation(None)
    who, found = harness.who_answers(conv, "Cancel the chess match then learn tenouchi", "chess")
    assert who == dispatch.SWITCH
    assert (found.left, found.who, found.found) == ("chess", "study", ("start", "tenouchi"))


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("said", [
    "Cancel", "cancel.", "Stop the match", "Forget the chess", "Quit this", "Never mind the game", "Okay, quit this.",
    "Irene, cancel the game", "let's stop the game", "enough of this", "I'm done", "No, cancel that",
])
def test_an_exit_on_its_own_ends_the_mode_on(mode, said):
    who, found = harness.who_answers(Conversation(None), said, mode)
    # a mode's own stop command is as good as the generic exit
    assert who == dispatch.EXIT and found == mode or (who == mode), (said, who, found)


@pytest.mark.parametrize("mode", MODES)
def test_an_exit_on_its_own_runs_the_mode_goodbye(mode, monkeypatch):
    core, socket, ran = _core(mode, monkeypatch)
    seen = _record(core, monkeypatch)
    if mode == "lecture":
        async def toggle(*_a):
            seen.append(("lecture toggle",))
        core.lectures.toggle = toggle
    _turn(core, "never mind the game", "<speak>never</speak>")
    if mode == "lecture":
        assert seen == [("lecture toggle",)]
    elif mode == "strikes":
        assert seen == [("end", "strikes")]
    else:
        assert seen and seen[0][0] == ENTRY[mode], seen


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("said", [
    "You can even play Sicilian?", "I'd beat you at rock paper scissors too", "Stop showing off",
    "Cancel the timer", "Stop the music", "Do you even know what tenouchi is?", "You call that a game?",
    "Is that all you've got?", "I learned the Sicilian last year",
])
def test_trash_talk_naming_a_mode_never_leaves_it(mode, said):
    """Her own takeover stays blocked: talk that names a mode is not an order."""
    who, _ = harness.who_answers(Conversation(None), said, mode)
    assert who not in (dispatch.SWITCH, dispatch.EXIT), (said, who)


def test_a_bare_verb_leaves_only_for_another_mode():
    conv = Conversation(None)
    assert harness.who_answers(conv, "Stop and think about it", "chess")[0] != dispatch.SWITCH
    who, found = harness.who_answers(conv, "Stop, let's do shiai", "chess")
    assert who == dispatch.SWITCH and found.who == "shiai"
    # a named exit takes anything after it: the rest is answered with nothing on
    who, found = harness.who_answers(conv, "Stop the game, what time is it?", "chess")
    assert who == dispatch.SWITCH and found.who in (dispatch.MODEL, dispatch.QUICK) and found.said == "what time is it?"


@pytest.mark.parametrize("hotkey,mode", [("shiai", "chess"), ("study", "shiai"), ("shiai", "lecture"), ("study", "rps")])
def test_a_mode_hotkey_clears_whatever_mode_is_on(hotkey, mode, monkeypatch):
    """A mode hotkey always clears the mode on (his spec, 2026-10-18): it ends it and
    starts nothing - pressed again, it starts its own."""
    core, socket, _ = _core(mode, monkeypatch)
    seen = _record(core, monkeypatch)

    async def run():
        await core.on_mode_hotkey({"mode": hotkey})
        await asyncio.wait_for(core._turn, 5)

    asyncio.run(run())
    assert seen and seen[0] == ("end", mode) and all(x[0] != ENTRY[hotkey] for x in seen), seen


def test_the_lecture_hotkey_switches_out_of_a_game(monkeypatch):
    core, socket, _ = _core("chess", monkeypatch)
    seen = _record(core, monkeypatch)

    async def toggle(*_a, **_k):
        seen.append(("lecture toggle",))

    monkeypatch.setattr(type(core.lectures), "toggle", toggle)
    asyncio.run(core.on_lecture({"action": "toggle"}))
    assert seen == [("end", "chess"), ("lecture toggle",)]


def test_a_cancelled_calibration_is_never_left_measuring(monkeypatch):
    from irene import app as app_module

    core = app_module.Core()
    core.speaker = None

    async def nothing(*_a, **_k):
        return None

    monkeypatch.setattr(core, "_study_say", nothing)
    monkeypatch.setattr(core, "_sync_strike_events", nothing)

    async def run():
        task = asyncio.create_task(core._calibrate_strikes())
        await asyncio.sleep(0.05)
        assert core.active_mode() == "strikes"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert core._calibrating is None and core.active_mode() is None


@pytest.mark.parametrize("mode", MODES)
def test_every_brush_off_says_why(mode):
    """A refusal must never pass for a bug: every line names what is going on."""
    why = {"chess": "chess", "shiai": ("bout", "shiai"), "keiko": ("keiko", "practis"), "study": ("study", "studying"),
           "rps": "rock-paper-scissors", "strikes": "strikes", "lecture": "lecture"}[mode]
    for line in modes.BRUSH_OFF[mode]:
        assert any(w in line.lower() for w in ((why,) if isinstance(why, str) else why)), line


@pytest.mark.parametrize("mode", MODES)
def test_the_mode_guard_ends_an_idle_mode_and_shows_the_mode(mode, monkeypatch):
    """No mode can get stuck: one with nothing happening past modes.IDLE_LIMIT_S is
    ended by the guard, and the dashboard always says which mode is on."""
    core, socket, _ = _core(mode, monkeypatch)
    seen = _record(core, monkeypatch)
    pushed = []

    async def push(force=False):
        pushed.append(core.dashboard.state.get("mode"))

    monkeypatch.setattr(core.dashboard, "push", push)
    monkeypatch.setattr(modes, "IDLE_LIMIT_S", {m: 0.5 for m in modes.IDLE_LIMIT_S})
    if mode == "lecture":
        core.lectures.status = lambda: {"words": 5}

    async def said(line, cue=None, sounds=()):
        seen.append(("said", line))

    monkeypatch.setattr(core, "_study_say", said)

    async def run():
        guard = asyncio.create_task(core._mode_guard())
        await asyncio.sleep(2.6)
        guard.cancel()
        if core._turn:
            await core._turn

    asyncio.run(run())
    assert pushed[0] == modes.SHOWN[mode], pushed
    assert ("end", mode) in seen, seen
    assert any(x[0] == "said" and "ended" in x[1] for x in seen), seen
