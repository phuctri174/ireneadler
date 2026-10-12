"""She never abandons an answer unless he really spoke.

Live (Round 6): researching the Queen's Gambit, she stopped mid-sentence, went to
listening, then thinking, and answered "Without a disadvantage, sir." He had said
nothing. Her own voice came back through the speakers as "black can hold on to
it"; the echo check was word-exact ("onto" vs "on to", "can't" vs "can"), and her
early sentences had already been pushed out of the 6 lines it kept. The barge-in
cancelled the answer on the spot, and the same echo then became a turn."""
import asyncio
import time

import numpy as np

from irene.stt import Heard
from irene.voice_data import VoiceData

ANSWER = [
    "Ooh, the Queen's Gambit!",
    "It starts with d4, d5, then c4.",
    "White offers a pawn on c4 to pull Black's pawn away from the centre.",
    "White is about to sacrifice the pawn, but Black can't really hold onto it without falling behind.",
    "So Black usually declines it, with e6 or c6.",
    "The Slav is the c6 line, and it's rock solid.",
    "Accepting it is fine too, as long as Black gives the pawn back.",
    "It's one of the oldest openings still played at the top.",
    "Want the lines on the panel?",
]
AUDIO = np.zeros(16000, np.float32)


class _Speaker:
    def __init__(self):
        self.held = False
        self.stopped = False
        self.gain = 1.0

    def hold(self):
        self.held = True

    def release(self):
        self.held = False

    def stop(self):
        self.stopped = True
        self.held = False


class _Bridge:
    current_state = "speaking"

    def __init__(self):
        self.sent = []

    def send_threadsafe(self, m):
        self.sent.append(m)

    async def state(self, s):
        self.current_state = s


class _Core:
    def __init__(self):
        self.bridge = _Bridge()
        self.speaker = _Speaker()
        self.commands = []
        self.last_react = None
        self._turn = None

    async def on_command(self, message):
        self.commands.append(message)

    async def on_summon_skip(self, _m):
        pass

    async def say(self, *_a, **_k):
        pass


class _Stt:
    """Whisper, told what it will hear."""

    loaded = True

    def __init__(self, text, logprob=-0.3):
        self.heard = Heard(text, logprob, 0.02, 1.4, 60)

    def transcribe(self, *_a, **_k):
        return self.heard

    def confident(self, heard):
        return bool(heard.text.strip()) and heard.avg_logprob >= -0.8 and heard.no_speech_prob <= 0.6


def speaking(tmp_path, first_look, whole=None):
    from irene import voice_loop
    from irene.voice_loop import Voice

    voice_loop.BARGE_LISTEN_S = 0.0
    v = Voice(_Core())
    v.data = VoiceData(tmp_path)
    v.available = True
    v.visible = True
    # the whole answer is queued at once (after grounding), then spoken for a minute
    queued = time.monotonic() - 45.0
    for line in ANSWER:
        v.her_lines.append((queued, line))
    v._on_state("thinking")
    v._spoke_from = queued + 2.0
    v.stt = _Stt(first_look)
    return v, (lambda: setattr(v.stt, "heard", Heard(whole, -0.3, 0.02, 2.0, 80))) if whole else None


def test_her_own_sentence_heard_back_late_in_a_long_answer_is_hers():
    import tempfile

    v, _ = speaking(tempfile.mkdtemp(), "black can hold on to it")
    assert v.is_her("black can hold on to it")
    assert v.is_her("black can't hold on to it without a")
    assert v.not_him(v.stt.heard) == "her own words"


def test_the_incident_she_finishes_her_answer(tmp_path):
    v, _ = speaking(tmp_path, "black can hold on to it")
    asyncio.run(v._check_barge(AUDIO))
    assert not v.core.speaker.held and not v.core.speaker.stopped
    assert v._held_at is None
    # and the same echo, as a whole utterance, is never a turn
    assert asyncio.run(v.on_heard(Heard("black can't hold on to it without a", -0.58, 0.0, 4.8, 245), AUDIO, True)) == "ignored"
    assert v.core.commands == []


def test_noise_or_a_noise_phrase_never_stops_her(tmp_path):
    for heard in ["", "Thank you.", "Hmm.", "Show."]:
        v, _ = speaking(tmp_path, heard)
        asyncio.run(v._check_barge(AUDIO))
        assert v._held_at is None and not v.core.speaker.stopped, heard


def test_maybe_him_pauses_her_and_she_carries_on_when_it_was_not(tmp_path):
    async def go():
        v, _ = speaking(tmp_path, "wait a second please")
        await v._check_barge(AUDIO)
        assert v.core.speaker.held and v._held_at is not None, "paused, nothing cancelled"
        v.stt.heard = Heard("Thank you.", -0.3, 0.02, 2.0, 80)  # the whole of it: a noise phrase
        await v._utterance(AUDIO)
        return v

    v = asyncio.run(go())
    assert not v.core.speaker.held and not v.core.speaker.stopped, "she carries on from where she paused"
    assert v.core.commands == []


def test_a_pause_with_nothing_after_it_times_out_and_she_carries_on(tmp_path):
    from irene import voice_loop

    async def go():
        voice_loop.BARGE_HOLD_S = 0.05
        v, _ = speaking(tmp_path, "wait a second please")
        await v._check_barge(AUDIO)
        assert v.core.speaker.held
        await asyncio.sleep(0.2)
        return v

    try:
        v = asyncio.run(go())
    finally:
        voice_loop.BARGE_HOLD_S = 4.0
    assert not v.core.speaker.held and not v.core.speaker.stopped


def test_him_really_speaking_stops_her_and_is_his_turn(tmp_path):
    async def go():
        v, _ = speaking(tmp_path, "wait stop")
        await v._check_barge(AUDIO)
        v.stt.heard = Heard("Wait, stop. What about the Slav?", -0.25, 0.01, 2.2, 90)
        await v._utterance(AUDIO)
        return v

    v = asyncio.run(go())
    assert v.core.speaker.stopped
    assert v.core.commands == [{"text": "Wait, stop. What about the Slav?", "via": "voice", "_origin": "mic"}]


def test_every_barge_decision_is_logged_with_what_was_heard(tmp_path, caplog):
    import logging

    caplog.set_level(logging.INFO, "irene.voice")
    v, _ = speaking(tmp_path, "black can hold on to it")
    asyncio.run(v._check_barge(AUDIO))
    assert any("black can hold on to it" in r.message and "her own words" in r.message for r in caplog.records)


def test_his_words_after_a_barge_in_are_not_lost_to_the_busy_guard(tmp_path):
    async def go():
        v, _ = speaking(tmp_path, "wait stop")

        async def answering():
            await asyncio.sleep(30)

        v.core._turn = asyncio.ensure_future(answering())
        await asyncio.sleep(0)
        await v._check_barge(AUDIO)
        v.stt.heard = Heard("Stop. Tell me about the Slav instead.", -0.25, 0.01, 2.2, 90)
        await v._utterance(AUDIO)
        return v

    v = asyncio.run(go())
    assert v.core.commands and v.core.commands[0]["text"].startswith("Stop.")


def test_a_voice_from_the_room_that_whisper_is_unsure_of_does_not_stop_her(tmp_path):
    """Live: "That's what the dark bar definitely happens." (-0.76) - not him."""
    v, _ = speaking(tmp_path, "that's what you don't know")
    v.stt.heard = Heard("that's what you don't know", -0.73, 0.0, 1.7, 60)
    asyncio.run(v._check_barge(AUDIO))
    assert v._held_at is None and not v.core.speaker.held


def test_a_japanese_word_whisper_splits_is_still_her_echo():
    """Live: her "Then there's the sakigawa" came back as "Then there's the saki
    gowl" (-0.52) and stopped her explaining the shinai."""
    import tempfile

    v, _ = speaking(tempfile.mkdtemp(), "x")
    v.her_lines.append((time.monotonic(), "Then there's the sakigawa, that's the leather cap at the tip."))
    assert v.is_her("Then there's the saki gowl")
    assert not v.is_her("Stop. Tell me about the tsuba instead.")


def test_an_unsure_first_look_gets_a_second_on_the_newest_audio(tmp_path):
    """Live: his "What are you doing?" over her was first heard mixed with the
    ~0.8 s of her echo before it ("offers upon us keep forward", -1.05) and thrown
    away. A second look at only the newest audio hears him."""
    from irene import voice_loop

    class Endpointer:
        speaking = True

        def audio(self):
            return np.zeros(48000, np.float32)

        def reset(self):
            pass

    class Mic:
        endpointer = Endpointer()
        barge = False

        class guard:
            coupling = 0.3

    looks = [Heard("offers upon us keep forward", -1.05, 0.0, 1.4, 60), Heard("what are you doing", -0.22, 0.0, 1.3, 50)]

    async def go():
        voice_loop.BARGE_SECOND_LOOK_S = 0.0
        v, _ = speaking(tmp_path, "x")
        v.mic = Mic()
        v.stt.transcribe = lambda *_a, **_k: looks.pop(0)
        await v._check_barge(AUDIO)
        return v

    try:
        v = asyncio.run(go())
    finally:
        voice_loop.BARGE_SECOND_LOOK_S = 0.8
    assert v.core.speaker.held and v._held_at is not None, "paused to hear all of him"


def test_her_echo_misheard_past_matching_is_still_hers_but_her_name_always_stops_her(tmp_path):
    """Live: "They're accepting the gambit to fly." (-0.56) while she explained
    accepting the gambit - it stopped her."""
    v, _ = speaking(tmp_path, "x")
    v.her_lines.append((time.monotonic(), "Black can respond by accepting the gambit, or by declining it with e6."))
    assert v.not_him(Heard("They're accepting the gambit to fly.", -0.56, 0.0, 4.9, 80)) == "mostly her words"
    assert v.not_him(Heard("Irene, wait - accepting the gambit is bad?", -0.3, 0.0, 2.0, 80)) == "", "her name: him"
    assert v.not_him(Heard("What are you doing?", -0.2, 0.0, 1.3, 50)) == ""
    assert v.not_him(Heard("Wait, stop. What about the Slav?", -0.25, 0.0, 2.2, 90)) == ""


def test_a_number_she_says_as_words_is_still_her_echo():
    """Live: her "The 8th Dan examination is next to impossible" came back as "The
    eighth day an examination is next to-" (-0.54); the digits never matched the
    words, and she stopped to answer her own sentence."""
    import tempfile

    v, _ = speaking(tempfile.mkdtemp(), "x")
    v.her_lines.append((time.monotonic(), "Passing a high-level Dan examination, especially the 8th Dan examination, requires far more than technical proficiency alone."))
    v.her_lines.append((time.monotonic(), "The 8th Dan examination is next to impossible for most."))
    for heard in ("The eighth day an examination is next to-", "the eighth day in examination", "the eighth day an examination"):
        assert v.is_her(heard), heard
    v.her_lines.append((time.monotonic(), "It began in 1939 and ended in 1945, with 2,500 ships."))
    assert v.is_her("It began in nineteen thirty nine and ended in nineteen forty five")
    assert not v.is_her("Wait, what happened in the eighth one?")
