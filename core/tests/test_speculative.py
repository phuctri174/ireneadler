"""The speculative start: she answers from the first look at his words (0.3 s into
his silence) instead of waiting out the end-of-speech tail - and takes it back
if he was not finished, or the full transcript says something else."""
import asyncio
import random

import numpy as np

from irene import entrances
from irene.listen import BLOCK, Endpointer
from irene.quick import QuickReplies
from irene.stt import Heard
from irene.voice_data import VoiceData


def feed(ep, voiced_s, silent_s):
    events = []
    for _ in range(int(voiced_s / 0.032)):
        events += ep.feed(np.full(BLOCK, 0.1, np.float32), 0.9)
    for _ in range(int(silent_s / 0.032)):
        events += ep.feed(np.zeros(BLOCK, np.float32), 0.0)
    return events


def test_an_early_verdict_ends_the_utterance_at_the_next_silent_block():
    ep = Endpointer(max_silence_s=3.0, min_silence_s=0.9, check_after_s=0.3)
    events = feed(ep, 1.0, 0.32)
    check = next(e for e in events if e.kind == "check")
    ep.verdict(True, check.generation, now=True)
    after = feed(ep, 0, 0.064)
    assert any(e.kind == "end" for e in after), "ends now, not 0.6 s later"


def test_speech_before_that_block_cancels_it():
    ep = Endpointer(max_silence_s=3.0, min_silence_s=0.9, check_after_s=0.3)
    events = feed(ep, 1.0, 0.32)
    ep.verdict(True, next(e for e in events if e.kind == "check").generation, now=True)
    resumed = feed(ep, 0.3, 0.5)
    assert not any(e.kind == "end" for e in resumed), "he went on: still his turn"


class FakeBridge:
    current_state = "listening"

    def __init__(self):
        self.sent = []
        self.state_listeners = []

    def send_threadsafe(self, m):
        self.sent.append(m)

    async def send(self, m):
        self.sent.append(m)


class FakeCore:
    def __init__(self):
        self.bridge = FakeBridge()
        self.commands, self.said, self.retracted = [], [], 0
        self.last_react = None
        self.quick = QuickReplies(entrances.load_registry(), random.Random(1))

    async def on_command(self, message):
        self.commands.append(message)

    async def say(self, text, react=None):
        self.said.append(text)

    async def retract_turn(self, settle=True, why=""):
        self.retracted += 1


class FakeEndpointer:
    def __init__(self, speaking=True):
        self.speaking = speaking

    def audio(self):
        return np.zeros(24000, np.float32)

    def reset(self):
        self.speaking = False


class FakeMic:
    def __init__(self, speaking=True):
        self.endpointer = FakeEndpointer(speaking)


def _checks(monkeypatch, v, his: bool, words: str):
    """The check after her early answer, made instant: whose voice, and what it said."""
    from irene import voice_loop

    monkeypatch.setattr(voice_loop, "CONTINUE_CHECK_S", 0.0)
    monkeypatch.setattr(voice_loop, "CARRY_FLUSH_S", 0.05)

    async def not_his(*_a):
        return not his

    v.not_his_voice = not_his
    v.stt.transcribe = lambda *_a, **_k: heard(words)
    v.stt._model = object()


def voice(tmp_path):
    from irene.voice_loop import Voice

    v = Voice(FakeCore())
    v.data = VoiceData(tmp_path)
    return v


def heard(text):
    return Heard(text, -0.2, 0.02, 1.5, 180)


def test_a_command_starts_on_the_first_look_and_the_full_transcript_confirms_it(tmp_path):
    v = voice(tmp_path)
    asyncio.run(v._answer_early(heard("What's the weather in Da Lat?"), None, np.zeros(16000, np.float32), True, final=heard("What's the weather in Da Lat?")))
    assert v.core.commands == [{"text": "What's the weather in Da Lat?", "via": "voice", "_origin": "mic"}]


def test_a_different_full_transcript_starts_the_turn_over(tmp_path):
    v = voice(tmp_path)
    asyncio.run(v._answer_early(heard("What's the weather in the lot?"), None, np.zeros(16000, np.float32), True, final=heard("What's the weather in Da Lat?")))
    assert [c["text"] for c in v.core.commands] == ["What's the weather in the lot?", "What's the weather in Da Lat?"]
    assert v.core.commands[1]["retract"] is True
    # only one voice turn is kept: the words he really said
    assert len(list(tmp_path.rglob("*.json"))) == 1


def test_small_talk_is_answered_on_the_first_look_with_no_second_pass(tmp_path):
    v = voice(tmp_path)

    def boom(*_a, **_k):
        raise AssertionError("small talk needs no second transcription")

    v.stt.transcribe = boom
    asyncio.run(v._answer_early(heard("Thanks, Irene!"), None, np.zeros(16000, np.float32), True))
    assert v.core.commands == [{"text": "Thanks, Irene!", "via": "voice", "_origin": "mic"}]


def test_if_he_goes_on_talking_the_early_answer_goes_and_the_halves_are_joined(tmp_path, monkeypatch):
    from irene.listen import Event

    v = voice(tmp_path)
    v.wake_for(30)
    v.mic = FakeMic(speaking=True)
    _checks(monkeypatch, v, his=True, words="what the weather is like")

    async def run():
        await v._answer_early(heard("Can you tell me."), None, np.zeros(16000, np.float32), True, final=heard("Can you tell me."))
        await v._handle(Event("speech", generation=2))
        await asyncio.sleep(0.02)  # the check: his voice, his words -> dropped
        assert v.core.retracted == 1
        v.stt.transcribe = lambda *_a, **_k: heard("what the weather is like tomorrow?")
        await v._utterance(np.zeros(16000, np.float32), generation=2)

    asyncio.run(run())
    assert v.core.commands[-1]["text"] == "Can you tell me. what the weather is like tomorrow?"


def test_her_own_sound_after_her_early_answer_never_cuts_it(tmp_path, monkeypatch):
    """Round 11, live: 0.8 s into her answer to "What are you doing?", her own sound
    and voice leaking past the echo canceller raised a "speech" event; she was cut
    after two words and answered both of his questions at once a turn later."""
    from irene.listen import Event

    v = voice(tmp_path)
    v.wake_for(30)
    v.mic = FakeMic(speaking=True)
    _checks(monkeypatch, v, his=False, words="Men-uchi! Did you see it")

    async def run():
        await v._answer_early(heard("What are you doing?"), None, np.zeros(16000, np.float32), True, final=heard("What are you doing?"))
        await v._handle(Event("speech", generation=2))
        await asyncio.sleep(0.02)

    asyncio.run(run())
    assert v.core.retracted == 0, "not his voice: she carries on"
    assert v._carry is None


def test_a_dropped_early_answer_is_never_left_waiting_for_his_next_turn(tmp_path, monkeypatch):
    """Even when the drop was right to start with (his voice, a word or two), and
    then nothing of his follows: his first words are answered on their own."""
    from irene.listen import Event

    v = voice(tmp_path)
    v.wake_for(30)
    v.mic = FakeMic(speaking=True)
    _checks(monkeypatch, v, his=True, words="um so")

    async def run():
        await v._answer_early(heard("What are you doing?"), None, np.zeros(16000, np.float32), True, final=heard("What are you doing?"))
        n = len(v.core.commands)
        await v._handle(Event("speech", generation=2))
        await asyncio.sleep(0.02)
        assert v.core.retracted == 1
        v.mic.endpointer.speaking = False  # he stopped; no utterance of his ends
        await asyncio.sleep(0.15)
        return n

    n = asyncio.run(run())
    assert [c["text"] for c in v.core.commands[n:]] == ["What are you doing?"]
    assert v._carry is None


def test_long_after_she_answered_his_next_words_are_a_new_turn(tmp_path, monkeypatch):
    from irene import voice_loop
    from irene.listen import Event

    v = voice(tmp_path)
    asyncio.run(v._answer_early(heard("Thanks, Irene!"), None, np.zeros(16000, np.float32), True))
    clock = voice_loop.time.monotonic() + voice_loop.MERGE_S + 1
    monkeypatch.setattr(voice_loop.time, "monotonic", lambda: clock)
    asyncio.run(v._handle(Event("speech", generation=3)))
    assert v.core.retracted == 0


def test_words_carried_from_a_dev_replay_stay_sandboxed(tmp_path, monkeypatch):
    """Round 11, live: the carried words were re-sent as "mic" - a replayed "Can you
    turn on the screen for me?" escaped the sandbox and really switched his monitors
    off. Anything re-sent keeps the origin of the words it carries."""
    from irene.listen import Event

    v = voice(tmp_path)
    v.wake_for(30)
    v.mic = FakeMic(speaking=True)
    v.mic._replaying = True
    _checks(monkeypatch, v, his=True, words="for me")

    async def run():
        await v._answer_early(heard("Can you turn on the screen for me?"), None, np.zeros(16000, np.float32), True,
                              final=heard("Can you turn on the screen for me?"))
        n = len(v.core.commands)
        v.mic._replaying = False  # the replay is over by the time the carry is re-sent
        await v._handle(Event("speech", generation=2))
        await asyncio.sleep(0.02)
        v.mic.endpointer.speaking = False
        await asyncio.sleep(0.15)
        return n

    n = asyncio.run(run())
    assert v.core.commands[n - 1]["_origin"] == "replay"
    resent = v.core.commands[n:]
    assert resent and all(c["_origin"] == "replay" for c in resent), resent
