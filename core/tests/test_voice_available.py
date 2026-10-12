"""Voice always works while she is on screen, and "Hey Irene" is heard even inside
other people's talk.

Live, a hotkey summon left her asleep (only a voice summon woke the listener), so
the mic "did nothing" with her right there; and room talk that never paused
swallowed the wake phrase - the end-of-speech check only runs after a pause."""
import asyncio
import time

import numpy as np

from irene import wake
from irene.listen import BLOCK, Endpointer
from irene.stt import Heard
from irene.voice_data import VoiceData


class _Bridge:
    current_state = "listening"

    def __init__(self):
        self.sent = []
        self.state_listeners = []

    def send_threadsafe(self, m):
        self.sent.append(m)

    async def send(self, m):
        self.sent.append(m)


class _Core:
    def __init__(self):
        self.bridge = _Bridge()
        self.commands, self.summons = [], []
        self.last_react = None

    async def on_command(self, message):
        self.commands.append(message)

    async def summon_by_voice(self, adler):
        self.summons.append("adler" if adler else "hey")

    async def say(self, *_a, **_k):
        pass


def voice(tmp_path):
    from irene.voice_loop import Voice

    v = Voice(_Core())
    v.data = VoiceData(tmp_path)
    v.available = True
    return v


def test_visible_she_listens_without_a_wake_word_whatever_summoned_her(tmp_path):
    v = voice(tmp_path)
    assert not v.awake
    v.set_visible(True)  # a hotkey summon: the window shows, nothing else
    assert v.awake and v.core.bridge.sent[-1] == {"type": "voice", "phase": "listening"}
    asyncio.run(v.on_heard(Heard("What time is it?", -0.2, 0.02, 1.0, 50), np.zeros(16000, np.float32), v.awake))
    assert v.core.commands == [{"text": "What time is it?", "via": "voice", "_origin": "mic"}]
    v.awake_until = 0.0  # the follow-up window after that command has run out
    v.set_visible(False)
    assert not v.awake and v.core.bridge.sent[-1] == {"type": "voice", "phase": "asleep"}


def test_goodbye_on_screen_does_not_put_the_mic_to_sleep(tmp_path):
    v = voice(tmp_path)
    v.set_visible(True)
    v.sleep()
    assert v.awake and v.core.bridge.sent[-1]["phase"] == "listening"


def test_long_talk_is_peeked_at_while_it_goes_on():
    ep = Endpointer()
    peeks = []
    for _ in range(int(4.0 / 0.032)):
        peeks += [e for e in ep.feed(np.full(BLOCK, 0.1, np.float32), 0.9) if e.kind == "peek"]
    assert 3 <= len(peeks) <= 4, "one after 1.4 s, then every 0.8 s"
    assert all(len(p.audio) <= int(2.7 * 16000) for p in peeks), "only the last few seconds"


def test_a_wake_phrase_is_found_inside_other_talk():
    assert wake.find_within("so then he said we should hey Irene go").phrase == "hey"
    assert wake.find_within("blah blah Irene Adler").phrase == "adler"
    assert wake.find_within("I met Irene yesterday at the shop") is None, "the bare name never wakes her"


def test_the_peek_summons_her_out_of_ongoing_talk(tmp_path):
    from irene.listen import Event

    v = voice(tmp_path)
    v.stt._model = object()
    v.stt.transcribe = lambda *_a, **_k: Heard("and the price was fine hey Irene", -0.3, 0.02, 2.6, 120)

    class Mic:
        endpointer = Endpointer()

    v.mic = Mic()
    v.mic.endpointer.generation = 7
    asyncio.run(v._peek(Event("peek", audio=np.zeros(16000, np.float32), generation=7)))
    assert v.core.summons == ["hey"]
    assert not v.mic.endpointer.speaking, "the room's utterance is dropped"


def test_a_dead_microphone_is_reopened(tmp_path, monkeypatch):
    v = voice(tmp_path)

    class DeadMic:
        last_block_age = 5.0
        stopped = False

        def stop(self):
            self.stopped = True

    dead = DeadMic()
    v.mic = dead
    opened = []
    v._open_mic = lambda: opened.append(1) or False
    v.core.corpus = type("C", (), {"active": False})()
    v.core.speaker = None

    async def main():
        task = asyncio.ensure_future(v._watch())
        await asyncio.sleep(0.7)
        task.cancel()

    asyncio.run(main())
    assert dead.stopped and opened, "reopened, not left deaf"
    assert {"type": "voice", "phase": "off"} in v.core.bridge.sent


def test_room_talk_never_interrupts_her_work_but_her_name_does(tmp_path):
    v = voice(tmp_path)
    v.set_visible(True)

    class Running:
        def done(self):
            return False

    v.core._turn = Running()  # she is researching
    heard = Heard("Look into it. Let me look out.", -0.3, 0.02, 2.0, 100)
    assert asyncio.run(v.on_heard(heard, np.zeros(16000, np.float32), v.awake)) == "ignored"
    assert v.core.commands == []
    assert asyncio.run(v.on_heard(Heard("Irene, stop that.", -0.2, 0.02, 1.0, 80), np.zeros(16000, np.float32), v.awake)) == "command"
    v.core._turn = None  # idle and on screen: plain speech is for her again
    assert asyncio.run(v.on_heard(Heard("What time is it?", -0.2, 0.02, 1.0, 80), np.zeros(16000, np.float32), v.awake)) == "command"


def test_look_into_it_is_not_a_research_command():
    from irene.fast import direct_call

    assert direct_call("Look into it. Let me look out.") is None
    assert direct_call("Look into the new Zelda release date") is not None


def test_his_short_question_is_not_taken_for_her_echo(tmp_path):
    v = voice(tmp_path)
    v.heard_her("What a question! You are doing great, and what I was doing is chess.")
    assert not v.is_her("What are you doing?"), "same words, not her sentence"
    v.heard_her("Irene Adler. Charmed, I'm sure.")
    assert v.is_her("charmed I'm sure") and v.is_her("Irene Adler, charmed, I'm sure.")
