"""The summon end to end: which entrance a trigger gets, the greeting after it, and
what she remembers she was doing."""
import asyncio
import random

import pytest

from irene import entrances
from irene.brain import Conversation
from irene.greeting import Greeter
from tests.test_brain import FakeHost, FakeLLM, run


class FakeCore:
    """Just the summon end of Core: which entrance a trigger picks."""

    def __init__(self, seed=5):
        self.entrances = entrances.load_registry()
        self.picker = entrances.Picker(self.entrances, random.Random(seed))
        self.greeter = Greeter(random.Random(seed))
        self.played: list[str] = []
        self.last_entrance = None

    async def on_speak(self, message):
        if message.get("source") == "summon":
            await self.summon_entrance(entrances.DOMAIN if message.get("by") == "sign" else None)

    async def summon_entrance(self, name=None, music=False):
        entry = next((e for e in self.entrances if e["name"] == name), None) if name else self.picker.pick()
        assert entry is not None
        self.last_entrance = entry["name"]
        self.played.append(entry["name"])


def summon(core, by):
    asyncio.run(core.on_speak({"source": "summon", "text": "...", "by": by}))


def test_the_hand_sign_is_always_the_domain_expansion():
    core = FakeCore()
    for _ in range(12):
        summon(core, "sign")
    assert set(core.played) == {entrances.DOMAIN}


def test_the_hotkey_takes_a_random_one_from_the_pool():
    core = FakeCore()
    for _ in range(300):
        summon(core, "hotkey")
    assert len(set(core.played)) > 4, "the hotkey should reach most of the pool"
    assert all(a != b for a, b in zip(core.played, core.played[1:])), "never twice running"


def entry(name):
    return next(e for e in entrances.load_registry() if e["name"] == name)


def sent_to_model(llm, call=-1):
    return "\n".join(m["content"] for m in llm.seen[call])


def test_she_remembers_what_she_was_doing_and_it_reaches_her_context():
    core = FakeCore()
    summon(core, "hotkey")
    pet = entry(core.last_entrance)

    conv = Conversation(FakeLLM(["<speak>I was busy, sir!</speak>"]))
    conv.entered(pet)
    conv.greeted("Good evening, Mister Tri, how can I help?")
    run(conv, "What are you doing, Irene?", FakeHost())
    sent = sent_to_model(conv.llm)
    assert pet["doing"] in sent, "what she was doing has to be in the context she answers from"
    assert pet["scene"] in sent
    assert "Good evening" in sent
    assert "He is asking what you were doing" in sent


def test_it_is_there_even_when_he_talks_over_the_greeting():
    # the greeting was cut off (typing skips the entrance): nothing was greeted, but
    # the entrance was recorded as it started
    conv = Conversation(FakeLLM(["<speak>Is this your card?</speak>"]))
    conv.entered(entry("cards"))
    run(conv, "what are you doing?", FakeHost())
    assert "ace of hearts" in sent_to_model(conv.llm)


def test_it_stays_in_context_every_turn_while_recent_with_varied_lines():
    pet = entry("victorian")
    conv = Conversation(FakeLLM(["<speak>Hi.</speak>"] * 6))
    conv.entered(pet)
    offered = []
    for said in ("hello", "how's your day", "tell me something", "what are you doing?"):
        run(conv, said, FakeHost())
        sent = sent_to_model(conv.llm)
        assert pet["scene"] in sent, f"the entrance must be in context on {said!r}, not just once"
        offered.append({b for b in pet["backstory"] if b in sent})
    assert all(len(o) == 3 for o in offered)
    assert all(a != b for a, b in zip(offered, offered[1:])), "a different few lines each turn"
    assert "He is asking" not in conv.context("hello") and "He is asking" in conv.context("what were you up to?")


def test_it_fades_once_it_is_no_longer_recent():
    from irene.brain import ENTRANCE_RECENT_S

    conv = Conversation(FakeLLM([]))
    conv.entered(entry("kendo"), now=1000.0)
    assert "dojo" in conv.entrance_section("what are you doing", now=1000.0 + ENTRANCE_RECENT_S - 1)
    assert conv.entrance_section("what are you doing", now=1000.0 + ENTRANCE_RECENT_S + 1) == ""


def test_every_entrance_has_a_scene_and_several_backstories():
    for e in entrances.load_registry():
        assert len(e["scene"]) > 40, e["name"]
        assert len(set(e["backstory"])) >= 4, e["name"]


def test_a_new_entrance_starts_a_fresh_conversation_when_the_old_one_went_stale():
    conv = Conversation(FakeLLM([]))
    conv.history = [{"role": "user", "content": "something from an hour ago"}]
    conv.last_active = 0.0  # long expired
    conv.entered(entry("chess"))
    conv.greeted("Hello again.")
    assert len(conv.history) == 2 and "something from an hour ago" not in str(conv.history)
    assert "playing chess" in conv.history[0]["content"] and "Hello again." in conv.history[1]["content"]
    assert conv.entrance.name == "chess"


@pytest.mark.parametrize("hour,band", [(9, "morning"), (15, "afternoon"), (22, "evening")])
def test_the_greeting_after_an_entrance_suits_the_hour(hour, band):
    greeter = Greeter(random.Random(1))
    lines = [greeter.next(hour) for _ in range(30)]
    assert any(band in line.lower() for line in lines), lines


class _Bridge:
    def __init__(self, connected):
        self.connected = self.hud_connected = connected
        self.sent = []

    async def send(self, message):
        self.sent.append(message)


def _voice_core(connected):
    from irene.app import Core

    core = Core()
    core.bridge = _Bridge(connected)
    played = []

    async def summon_entrance(name=None, music=False):
        played.append(name)

    core.summon_entrance = summon_entrance
    return core, played


def test_hey_irene_summons_through_the_hud_like_the_hotkey():
    # the bug: a voice wake played an entrance but never showed a hidden window.
    # Now it asks the HUD to run the hotkey's summon (Rust shows the window), and
    # the summon comes back through on_speak exactly as ctrl+alt+i's does
    core, played = _voice_core(connected=True)

    async def main():
        asking = asyncio.create_task(core.summon_by_voice(adler=False))
        await asyncio.sleep(0.05)
        assert core.bridge.sent == [{"type": "summon_request", "by": "voice"}]
        await core.on_speak({"text": "...", "source": "summon", "by": "voice"})
        await asking

    asyncio.run(main())
    assert played == [None], "one random entrance, from the HUD's round trip - not a second one here"


def test_irene_adler_brings_the_victorian_lady_through_the_same_path():
    core, played = _voice_core(connected=True)

    async def main():
        asking = asyncio.create_task(core.summon_by_voice(adler=True))
        await asyncio.sleep(0.05)
        assert core.bridge.sent[-1] == {"type": "summon_request", "by": "adler"}
        await core.on_speak({"text": "...", "source": "summon", "by": "adler"})
        await asking

    asyncio.run(main())
    assert played == ["victorian"]


def test_with_no_hud_or_no_answer_the_entrance_still_plays():
    core, played = _voice_core(connected=False)
    asyncio.run(core.summon_by_voice(adler=False))
    assert played == [None] and core.bridge.sent == []
    core, played = _voice_core(connected=True)
    asyncio.run(core.summon_by_voice(adler=True, timeout=0.05))
    assert played == ["victorian"]
