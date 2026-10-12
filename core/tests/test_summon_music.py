"""The music under a voice summon: the Speaker's bed mixes under her voice with its
own ramps, survives play()/stop(), fades out; the config and the track load."""
from collections import deque
import threading

import numpy as np

from irene import music
from irene.tts import SAMPLE_RATE, Speaker


def bare_speaker() -> Speaker:
    """A Speaker with just the state the mixer needs (no audio device)."""
    s = Speaker.__new__(Speaker)
    s._lock = threading.Lock()
    s._fifo = deque()
    s._bed = None
    s._bed_at = 0
    s._bed_gain = s._bed_target = s._bed_step = 0.0
    return s


def test_the_bed_ramps_in_and_mixes_under_what_she_plays():
    s = bare_speaker()
    s.bed(np.ones(SAMPLE_RATE, np.float32), level=0.5, ramp_s=0.1)
    out = np.zeros(SAMPLE_RATE // 5, np.float32)
    s._mix_bed(out)
    # ramps from silence up to the level over 0.1 s, then holds it
    assert out[0] < 0.01 and abs(out[int(0.05 * SAMPLE_RATE)] - 0.25) < 0.02
    assert np.allclose(out[int(0.11 * SAMPLE_RATE):], 0.5, atol=1e-3)
    # added to what is already in the block (her voice), not replacing it
    voice = np.full(100, 0.2, np.float32)
    s._mix_bed(voice)
    assert np.allclose(voice, 0.7, atol=1e-3)


def test_the_bed_drops_for_the_silence_and_fades_out_to_nothing():
    s = bare_speaker()
    s.bed(np.ones(SAMPLE_RATE * 3, np.float32), level=0.4, ramp_s=0)
    s.bed_to(0.02, 0.15)
    out = np.zeros(int(0.2 * SAMPLE_RATE), np.float32)
    s._mix_bed(out)
    assert abs(out[-1] - 0.02) < 1e-3
    s.bed_to(0.0, 0.5)
    for _ in range(4):
        s._mix_bed(np.zeros(int(0.2 * SAMPLE_RATE), np.float32))
    assert not s.bed_playing, "faded all the way out: the bed is done"


def test_her_voice_queue_never_touches_the_bed():
    s = bare_speaker()
    s.bed(np.ones(SAMPLE_RATE, np.float32), level=0.3)
    s._generation = 0
    s._marks = []
    s.held = False
    Speaker.stop(s)
    assert s.bed_playing


def test_the_config_and_the_track():
    cfg = music.settings()
    assert cfg.start_s == 10.0 and 0 < cfg.level <= 1 and cfg.fade_out_s > 1
    missing = music.Track(music.Settings(True, music.Path("C:/no/such.mp3"), 10, 5, 0.3, 0.5, 4))
    missing._load()
    assert missing.audio is None
    if cfg.file.is_file():
        audio = music.decode(cfg.file, cfg.start_s, 2.0)
        assert len(audio) == 2 * SAMPLE_RATE and 0.99 <= float(np.max(np.abs(audio))) <= 1.0001
