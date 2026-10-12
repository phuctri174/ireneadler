import numpy as np

from irene import voice as voice_mod
from irene.tts import chunks
from irene.voice import Voice, strip_tags


class FakeKokoro(voice_mod.Engine):
    name = "kokoro"

    def synth(self, text, speed=1.0):
        yield np.full(10, 0.5, np.float32)


def test_turbo_that_fails_to_load_falls_back_to_kokoro(monkeypatch):
    def broken():
        raise RuntimeError("CUDA out of memory")

    monkeypatch.setattr(voice_mod, "TurboEngine", broken)
    monkeypatch.setattr(voice_mod, "KokoroEngine", FakeKokoro)
    v = Voice("turbo")
    assert v.name == "kokoro" and len(v.all("Hello.")) == 10


def test_turbo_that_fails_mid_speech_switches_to_kokoro_for_good(monkeypatch):
    class FlakyTurbo(voice_mod.Engine):
        name = "turbo"
        tags = True

        def synth(self, text, speed=1.0):
            raise RuntimeError("CUDA out of memory")
            yield

    monkeypatch.setattr(voice_mod, "TurboEngine", FlakyTurbo)
    monkeypatch.setattr(voice_mod, "KokoroEngine", FakeKokoro)
    v = Voice("turbo")
    assert v.name == "turbo"
    assert len(v.all("Still talking.")) == 10
    assert v.name == "kokoro"


def test_tags_are_stripped_for_display_and_kokoro():
    assert strip_tags("That's brilliant. [laugh] Really.") == "That's brilliant. Really."
    assert strip_tags("[sigh] Oh no.") == "Oh no."


def test_long_sentences_split_at_commas_and_the_first_gives_up_its_opening():
    assert chunks("Ooh, wait, you finished the whole thesis already?", first=True) == ["Ooh,", "wait, you finished the whole thesis already?"]
    assert chunks("Hmm, good one.", first=True) == ["Hmm, good one."]
    long = "Well, I think the best way to handle this, honestly, is to start small and build it up."
    assert all(len(c.split()) <= 11 for c in chunks(long))


class _Turbo:
    name = "turbo"
    tags = True


def _speaker_with_openers():
    from irene import openers
    from irene.tts import Speaker

    s = object.__new__(Speaker)
    s.voice = type("V", (), {"name": "turbo", "engine": _Turbo()})()
    s._rules = {True: [], False: []}
    s.openers = {openers.key(o): np.zeros(10, np.float32) for o in openers.OPENERS}
    s.openers_engine = "turbo"
    s._last_opener = None
    return s


def test_a_cold_first_phrase_gets_a_cached_lead_in_never_the_same_twice():
    s = _speaker_with_openers()
    leads = [s.lead_in("The Eiffel Tower is about 330 metres tall.", "curious") for _ in range(6)]
    assert all(leads) and all(a != b for a, b in zip(leads, leads[1:]))
    # a reply that already opens with a cached take needs none
    assert s.lead_in("Ooh! Great question.", "happy") is None


def test_the_48k_output_is_her_24k_voice_upsampled_without_seams():
    import numpy as np

    from irene.tts import Upsampler

    t = np.arange(24000) / 24000
    tone = (0.3 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    whole = Upsampler()(tone)
    up = Upsampler()
    blocked = np.concatenate([up(tone[i : i + 480]) for i in range(0, len(tone), 480)])
    assert np.allclose(whole, blocked, atol=1e-6), "block edges must not click"
    spectrum = np.abs(np.fft.rfft(blocked[4800:]))
    freqs = np.fft.rfftfreq(len(blocked[4800:]), 1 / 48000)
    assert abs(freqs[np.argmax(spectrum)] - 1000) < 5
    image = spectrum[np.argmin(abs(freqs - 23000))]
    assert image < spectrum.max() * 0.01, "no mirror image at 23 kHz"


def test_the_speaker_callback_feeds_the_taps_at_24k_and_the_device_at_48k():
    import collections
    import threading

    import numpy as np

    from irene.tts import Speaker, Upsampler

    sp = Speaker.__new__(Speaker)
    sp._ratio, sp._upsample = 2, Upsampler()
    sp._fifo = collections.deque([[np.full(2400, 0.2, np.float32), None]])
    sp._lock = threading.Lock()
    sp._pending_first, sp._first_audio, sp._played, sp._latency_samples = True, None, 0, 0
    sp._marks, sp.gain, sp._was_loud, sp.held, sp._callback_failed = [], 1.0, False, False, False
    sp.master_stage = False  # samples must pass through exactly here
    sp._level_at, sp._level_acc = 0.0, []
    tapped, levels = [], []
    sp.taps = [lambda block, at: tapped.append(len(block))]
    sp._on_level = levels.append
    out = np.zeros((960, 1), np.float32)
    for _ in range(3):
        sp._callback(out, 960, None, None)
    assert tapped == [480, 480, 480] and sp._played == 1440
    assert np.abs(out[200:, 0]).mean() > 0.1
    assert len(levels) == 1, "the mouth level still goes out at 20 Hz, not per 20 ms block"


def test_an_answer_can_follow_her_on_it_instead_of_cutting_it_off():
    import collections
    import threading

    import numpy as np

    from irene.tts import Speaker

    sp = Speaker.__new__(Speaker)
    sp._fifo = collections.deque([[np.zeros(12000, np.float32), None]])  # "On it!", half a second
    sp._lock = threading.Lock()
    sp._generation, sp._marks = 1, []
    fired = []
    sp._begin([(0, lambda: fired.append(1))], keep=True)
    assert len(sp._fifo) == 1, "still queued"
    assert sp._marks[0][0] == 12000, "the answer's cue waits for it"
    sp._begin([], keep=False)
    assert not sp._fifo


class _NoVoice:
    """Stands in for voice.Voice: the Speaker's own audio path, no TTS model."""

    name = "turbo"

    def __init__(self, *_a, **_k):
        pass


def _stream_that_calls_back_on_start(fail_wasapi=False):
    """A sounddevice.OutputStream that runs the callback INSIDE start(), as
    PortAudio's thread can before start() even returns - the race that crashed
    every block on the first real launch ('Speaker' has no attribute '_ratio')."""
    import numpy as np

    class Stream:
        latency = 0.04

        def __init__(self, samplerate, blocksize, callback, **_k):
            self.rate, self.block, self.callback = samplerate, blocksize, callback

        def start(self):
            if fail_wasapi and self.rate == 48000:
                raise RuntimeError("WASAPI refused")
            out = np.zeros((self.block, 1), np.float32)
            self.callback(out, self.block, None, None)

        def abort(self):
            pass

        def close(self):
            pass

    return Stream


def test_a_speaker_built_for_real_survives_its_first_callback(monkeypatch):
    from irene import tts

    for fail_wasapi, ratio in ((False, 2), (True, 1)):
        monkeypatch.setattr(tts, "Voice", _NoVoice)
        monkeypatch.setattr(tts.sd, "OutputStream", _stream_that_calls_back_on_start(fail_wasapi))
        sp = tts.Speaker(tts.Path("unused"), lambda _v: None)
        assert not sp._callback_failed, "the callback ran before the Speaker was ready"
        assert sp._ratio == ratio and (sp._upsample is not None) == (ratio == 2)
        sp.reopen()  # the stall path opens a stream the same way
        assert not sp._callback_failed


def test_the_real_output_device_plays_through_the_speaker_callback(monkeypatch):
    """The whole thing on this PC's actual output, at gain 0: constructed, started,
    called back by the device, fed a block of her voice - no exception, ever."""
    import time

    import numpy as np
    import pytest
    import sounddevice as sd

    from irene import tts

    try:
        sd.query_devices(kind="output")
    except Exception:
        pytest.skip("no audio output device")
    monkeypatch.setattr(tts, "Voice", _NoVoice)
    levels = []
    sp = tts.Speaker(tts.Path("unused"), levels.append)
    try:
        sp.gain = 0.0  # timed, not heard
        done = []
        sp.play(np.full(4800, 0.2, np.float32), np.ones(4, np.float32), done=done.append)
        deadline = time.perf_counter() + 3
        while not done and time.perf_counter() < deadline:
            time.sleep(0.02)
        assert done == [True], "the clip never finished playing"
        assert time.perf_counter() - sp.callback_at < 0.5, "the device stopped calling back"
        assert not sp._callback_failed
    finally:
        sp._stream.abort()
        sp._stream.close()


def test_a_held_speaker_pauses_in_place_and_carries_on_from_the_same_sample():
    """A barge-in being checked pauses her; not him, and she goes on mid-word."""
    import collections
    import threading

    import numpy as np

    from irene.tts import Speaker

    sp = Speaker.__new__(Speaker)
    sp._ratio, sp._upsample = 1, None
    sp._fifo = collections.deque([[np.arange(4800, dtype=np.float32) / 4800, None]])
    sp._lock = threading.Lock()
    sp._pending_first, sp._first_audio, sp._played, sp._latency_samples = True, None, 0, 0
    sp._marks, sp.gain, sp._was_loud, sp.held, sp._callback_failed = [], 1.0, False, False, False
    sp.master_stage = False  # samples must pass through exactly here
    sp._level_at, sp._level_acc = 0.0, []
    sp.taps, sp._on_level = [], lambda level: None
    out = np.zeros((480, 1), np.float32)
    sp._callback(out, 480, None, None)
    assert sp._played == 480
    sp.hold()
    for _ in range(5):
        sp._callback(out, 480, None, None)
        assert not out.any(), "held: silence"
    assert sp._played == 480, "nothing used up while held"
    sp.release()
    sp._callback(out, 480, None, None)
    assert abs(out[0, 0] - 480 / 4800) < 1e-6, "carries on from the sample it paused at"
