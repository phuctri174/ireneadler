"""The VRAM spill guard: it suspects a spill from slow prefill or slow first audio,
confirms it with Ollama's /api/ps, reloads the model, and backs off if a reload
doesn't help."""
import asyncio

from irene import vram
from irene.vram import Placement, VramGuard


class FakeLLM:
    model = "gemma3:12b"

    def __init__(self, placements):
        self.placements = list(placements)
        self.calls = []

    async def placement(self):
        self.calls.append("ps")
        return self.placements.pop(0) if len(self.placements) > 1 else self.placements[0]

    async def unload(self):
        self.calls.append("unload")

    async def warm(self):
        self.calls.append("warm")
        return True


def run(coro):
    return asyncio.run(coro)


def guard(llm, now=0.0):
    clock = {"t": now}
    vram.RELOAD_PAUSE_S = 0
    return VramGuard(llm, idle=lambda: True, clock=lambda: clock["t"]), clock


GB = 1024**3


def test_slow_prefill_and_slow_first_audio_raise_a_suspicion_but_normal_ones_do_not():
    g, _ = guard(FakeLLM([Placement(9 * GB, 9 * GB)]))
    g.note_turn(4000, 1800)  # 2222 tok/s: healthy
    g.note_first_audio(900)
    assert g.suspect is None
    g.note_turn(200, 2000)  # a tiny prompt says nothing
    assert g.suspect is None
    g.note_turn(4000, 7000)  # 571 tok/s: the spill signature
    assert "prefill" in g.suspect
    g.suspect = None
    g.note_first_audio(2930)  # the slow greeting he heard
    assert "first audio" in g.suspect


def test_a_spilled_model_is_reloaded_and_the_recovery_confirmed():
    llm = FakeLLM([Placement(9 * GB, 6 * GB), Placement(9 * GB, 9 * GB)])
    g, _ = guard(llm)
    assert run(g.check()) is True
    assert llm.calls == ["ps", "unload", "warm", "ps"]
    assert g.recoveries == 1


def test_a_model_fully_in_vram_is_left_alone_even_when_suspected():
    llm = FakeLLM([Placement(9 * GB, 9 * GB)])
    g, _ = guard(llm)
    g.note_first_audio(3000)
    assert run(g.check()) is False
    assert llm.calls == ["ps"]


def test_a_model_not_loaded_is_loaded():
    llm = FakeLLM([None])
    g, _ = guard(llm)
    assert run(g.check()) is True and llm.calls == ["ps", "warm"]


def test_no_reload_loop_when_vram_is_genuinely_full():
    # the reload does not fix it: back off for GIVE_UP_S, then it may try again
    llm = FakeLLM([Placement(9 * GB, 6 * GB)])
    g, clock = guard(llm)
    run(g.check())
    assert llm.calls.count("unload") == 1
    clock["t"] = vram.GIVE_UP_S - 1
    run(g.check())
    assert llm.calls.count("unload") == 1, "in cooldown: no second reload"
    clock["t"] = vram.GIVE_UP_S + 1
    run(g.check())
    assert llm.calls.count("unload") == 2


def test_it_waits_until_she_is_idle():
    llm = FakeLLM([Placement(9 * GB, 6 * GB), Placement(9 * GB, 9 * GB)])
    busy = {"on": True}
    g = VramGuard(llm, idle=lambda: not busy["on"])

    async def scenario():
        task = asyncio.create_task(g.run())
        g.note_first_audio(3000)
        await asyncio.sleep(0.05)
        assert "unload" not in llm.calls, "never mid-turn"
        busy["on"] = False
        for _ in range(40):
            await asyncio.sleep(0.05)
            if "warm" in llm.calls:
                break
        task.cancel()

    vram.RELOAD_PAUSE_S = 0
    vram.IDLE_POLL_S = 0.02
    run(scenario())
    assert llm.calls[:3] == ["ps", "unload", "warm"]
