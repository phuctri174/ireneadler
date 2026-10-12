"""The freeze: she showed only the mic and stopped responding. Live, a turn waited
forever on a speaker that had stopped playing (the weather turn on 09-27: the
model answered, the turn never ended, no log). Every wait that could hang now
ends, and a watchdog recovers anything else."""
import asyncio
import collections
import threading
import time

import numpy as np


class _Bridge:
    def __init__(self):
        self.sent = []
        self._state = "listening"
        self.state_at = time.monotonic()
        self.connected = True
        self.state_listeners = []

    @property
    def current_state(self):
        return self._state

    async def send(self, m):
        self.sent.append(m)
        if m.get("type") == "state":
            self._state = m["value"]
            self.state_at = time.monotonic()

    async def state(self, v):
        await self.send({"type": "state", "value": v})

    async def emotion(self, v):
        await self.send({"type": "emotion", "value": v})

    def send_threadsafe(self, m):
        self.sent.append(m)


def _core():
    from irene.app import Core

    core = Core()
    core.bridge = _Bridge()
    return core


def test_a_turn_stuck_thinking_is_recovered_after_15_seconds():
    core = _core()

    async def main():
        await core.bridge.state("thinking")
        core._turn = asyncio.create_task(asyncio.sleep(3600))  # waits forever
        assert core.stuck(time.monotonic() + 10) is None
        why = core.stuck(time.monotonic() + 16)
        assert why and "thinking" in why
        await core.recover(why)
        await asyncio.sleep(0)
        assert core._turn.cancelled()
        assert core.bridge.current_state == "listening"
        assert {"type": "voice", "phase": "listening"} in core.bridge.sent

    asyncio.run(main())


def test_research_working_gets_longer_but_not_forever():
    core = _core()

    async def main():
        await core.bridge.state("thinking")
        core._tool_running = "research"
        core._progress_at = time.monotonic()
        assert core.stuck(time.monotonic() + 30) is None
        assert core.stuck(time.monotonic() + 61)

    asyncio.run(main())


def test_speaking_with_nothing_playing_is_a_freeze_but_real_speech_never_is():
    core = _core()

    class Speaker:
        playing_now = True

        def playing(self):
            return self.playing_now

        def stop(self):
            pass

    core.speaker = Speaker()

    async def main():
        await core.bridge.state("speaking")
        t = time.monotonic()
        assert core.stuck(t + 100) is None, "a long answer is not a freeze"
        core.speaker.playing_now = False
        # counted from when she stopped, not from "speaking"
        assert core.stuck(t + 105) is None, "a gap between two sentences is not a freeze"
        assert "nothing playing" in core.stuck(t + 116)

    asyncio.run(main())


def test_a_research_answer_still_being_written_is_never_killed_between_sentences():
    """Live (Round 6): "speaking" at 11:44:56, a sentence played, grounding cut the
    next two while the model kept writing - and at 11:45:12 the watchdog cancelled
    the answer as a freeze. The model's stream is a sign of life."""
    from irene.app import TurnHost

    core = _core()

    class Speaker:
        def playing(self):
            return False

        def stop(self):
            pass

    core.speaker = Speaker()

    async def main():
        await core.bridge.state("speaking")
        host = TurnHost.__new__(TurnHost)
        host.core = core
        await asyncio.sleep(0)
        t = time.monotonic()
        core.bridge.state_at = t - 16
        core._progress_at = t - 16
        assert core.stuck(t) is not None
        host.alive()  # a chunk from the model
        assert core.stuck(time.monotonic()) is None

    asyncio.run(main())


def test_listening_is_never_a_freeze():
    core = _core()
    assert core.stuck(time.monotonic() + 3600) is None


def test_a_speaker_whose_stream_stops_is_reopened_not_waited_on_forever(monkeypatch):
    from irene import tts
    from irene.tts import Speaker

    sp = Speaker.__new__(Speaker)
    sp._fifo = collections.deque([[np.zeros(2400, np.float32), None]])
    sp._lock = threading.Lock()
    sp._generation = 1
    sp.callback_at = time.perf_counter() - 10  # the device stopped calling back
    sp._reopened_at = 0.0
    reopened = []

    def reopen():
        reopened.append(1)
        with sp._lock:
            sp._fifo.clear()  # the new stream plays it out

    sp.reopen = reopen
    sp._stream = type("S", (), {"latency": 0.0})()
    started = time.perf_counter()
    assert sp._drain(1) is True
    assert reopened and time.perf_counter() - started < 1.0


def test_a_hud_that_stops_reading_never_stalls_core(monkeypatch):
    from irene import bridge as bridge_mod
    from irene.bridge import Bridge

    monkeypatch.setattr(bridge_mod, "SEND_TIMEOUT_S", 0.05)

    class Stuck:
        async def send_text(self, _text):
            await asyncio.sleep(3600)

    b = Bridge()
    b._clients.add(Stuck())

    async def main():
        started = time.monotonic()
        await b.state("speaking")
        assert time.monotonic() - started < 1.0
        assert not b.connected, "dropped; it reconnects"

    asyncio.run(main())


def test_the_hud_never_shows_the_mic_while_she_only_hears_wake_phrases(tmp_path):
    from irene.voice_data import VoiceData
    from irene.voice_loop import Voice

    class Core:
        def __init__(self):
            self.bridge = _Bridge()

    v = Voice(Core())
    v.data = VoiceData(tmp_path)
    v.mic = type("Mic", (), {"barge": False, "dump": None})()
    v.awake_until = 0.0  # her follow-up window ran out while she was thinking
    v._on_state("listening")
    assert v.core.bridge.sent[-1] == {"type": "voice", "phase": "asleep"}
    v.wake_for(8)
    v._on_state("listening")
    assert v.core.bridge.sent[-1] == {"type": "voice", "phase": "listening"}


def test_a_model_still_reading_a_long_prompt_is_slow_not_frozen():
    """Live, Round 8: with VRAM short, a research answer's prompt took 15 s before
    its first word and the watchdog killed the turn."""
    from irene.app import WATCHDOG_S, WATCHDOG_SLOW_TOOL_S, Core

    core = Core.__new__(Core)
    core._tool_running = None
    core._prefilling = True
    core._progress_at = 0.0
    core.speaker = None

    class Bridge:
        current_state = "thinking"
        state_at = 0.0

    core.bridge = Bridge()
    assert core.stuck(now=WATCHDOG_S + 5) is None
    assert core.stuck(now=WATCHDOG_SLOW_TOOL_S + 1) is not None, "a real hang still recovers"
    core._prefilling = False
    assert core.stuck(now=WATCHDOG_S + 5) is not None
