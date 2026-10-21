"""Between a point's call and "Hajime!" nothing counts - SUPPRESSED in code, not just
not shown. Every kind of event the HUD sends - his strikes, footwork, a block - is
fired through the app's real handlers (Core.on_*) during the dead window, and the
score, the HUD's score messages and the point calls must not move until hajime. Then
a strike counts again. And through the same handlers: one swing is one strike."""
from __future__ import annotations

import asyncio
import random
import time

from irene import shiai
from tests.test_mode_lock import Socket


class Dice(random.Random):
    def __init__(self, pick: str = "take") -> None:
        super().__init__(0)
        self.pick = pick

    def choices(self, population, weights=None, k=1):
        return [self.pick] if self.pick in population else [population[0]]

    def uniform(self, a, b):
        return 1e6  # her attacks never come: only his events are under test


def _core(monkeypatch, pick: str = "take"):
    from irene import app as app_module
    from irene.bridge import Bridge

    core = app_module.Core()
    core.bridge = Bridge()
    socket = Socket()
    core.bridge._clients.add(socket)
    core.speaker = None
    core.shiai = shiai.Shiai(rng=Dice(pick))
    core.shiai.start()
    core.shiai.hajime()
    return core, socket


def _scores(socket: Socket) -> list[tuple[int, int]]:
    return [(m["you"], m["her"]) for m in socket.sent if m.get("type") == "shiai" and m.get("action") == "score"]


STRIKE = {"type": "strike_event", "wrist": "left", "peak": 30.0, "stopMs": 60}
EVENTS = [STRIKE, {"type": "strike_event", "wrist": "right", "peak": 14.0, "stopMs": 62},
          {"type": "shiai_move", "move": "block", "height": -1.0, "rest": 1.4},
          {"type": "shiai_move", "move": "retreat"}, {"type": "shiai_move", "move": "advance"}]


def _fire(core, m: dict):
    m = {**m, "_origin": "hud"}
    return {"strike_event": core.on_strike_event, "shiai_move": core.on_shiai_move}[m["type"]](m)


def test_nothing_counts_between_the_call_and_hajime(monkeypatch):
    monkeypatch.setattr(shiai, "beat", lambda path=None: {"startCountdownS": 0.0, "pauseS": 1.0, "resetAfterS": 0.3})
    core, socket = _core(monkeypatch)

    async def run():
        await _fire(core, STRIKE)
        assert (core.shiai.you, core.shiai.her) == (1, 0) and core.shiai.paused
        beat = core._turn
        fired = 0
        while not beat.done():
            for m in EVENTS:
                await _fire(core, m)
                fired += 1
            await asyncio.sleep(0.05)
            assert core._turn is beat
            if not beat.done():
                assert (core.shiai.you, core.shiai.her) == (1, 0), "an event counted inside the dead window"
        await beat
        return fired

    assert asyncio.run(run()) >= 50
    assert (core.shiai.you, core.shiai.her) == (1, 0) and _scores(socket) == [(1, 0)]
    kinds = [m.get("action") for m in socket.sent if m.get("type") == "keiko"]
    assert kinds.index("reset") < kinds.index("countdown") < kinds.index("hajime"), kinds

    async def after():
        await asyncio.sleep(shiai.STRIKE_GAP_S)
        await _fire(core, STRIKE)
        if core._turn:
            await core._turn

    asyncio.run(after())
    assert (core.shiai.you, core.shiai.her) == (2, 0)


def test_the_pause_runs_from_the_call_to_hajime(monkeypatch):
    monkeypatch.setattr(shiai, "beat", lambda path=None: {"startCountdownS": 0.0, "pauseS": 0.8, "resetAfterS": 0.2})
    core, socket = _core(monkeypatch)

    async def run():
        t = time.monotonic()
        await _fire(core, STRIKE)
        await core._turn
        return time.monotonic() - t

    took = asyncio.run(run())
    assert 0.8 - 0.03 <= took < 3.0, took  # (Windows timers can wake ~15 ms early)


def test_one_swing_through_the_handlers_is_one_answer(monkeypatch):
    """A swing that reaches core as three strike events over 1.4 s (live, in bogu) is
    answered once."""
    core, socket = _core(monkeypatch, pick="parry")

    async def run():
        for gap in (0.0, 0.55, 0.8):
            await asyncio.sleep(gap)
            await _fire(core, STRIKE)
        if core._turn:
            await core._turn

    asyncio.run(run())
    answers = [m for m in socket.sent if m.get("type") == "keiko" and m.get("action") in ("block", "dodge", "ippon")]
    assert len(answers) == 1, answers
