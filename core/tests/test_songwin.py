"""The song-win bit: his lines exactly, only after she named a song he taught her and he
confirmed it, the 2 s hold real, every line through the pronunciation chokepoint."""
import asyncio

import numpy as np
import pytest

from irene import recall, skit, songwin
from irene.brain import Conversation
from tests.test_brain import FakeLLM
from tests.test_pronunciation_everywhere import EXPECTED, make_voice
from tests.test_taught import ASKED, TAUGHT, BoardHost


def test_his_words_exactly():
    assert [line.text for line in songwin.LINES] == ["Haha, GG fucking easy Mr Tri", "Oh really?", "FUGGING EASY"]
    assert [line.cue for line in songwin.LINES] == ["smug", "caughtOffGuard", "arrogant"]
    # the hold is his 2 s, in the config he tunes
    assert songwin.pace().hold_ms == 2000


def test_the_pace_is_read_from_config(tmp_path):
    path = tmp_path / "songwin.yaml"
    path.write_text("speed_fugging: 0.6\nbeat_after_really_ms: 900\nhold_ms: lots\nspeed_gloat: 5\n", encoding="utf-8")
    p = songwin.pace(path)
    assert (p.speed_fugging, p.beat_after_really_ms) == (0.6, 900)
    # what isn't a number, or is out of range, keeps the default
    assert (p.hold_ms, p.speed_gloat) == (2000, songwin.Pace().speed_gloat)
    assert songwin.pace(tmp_path / "missing.yaml") == songwin.Pace()
    # every key in the shipped file is one the bit reads
    import yaml
    shipped = yaml.safe_load(songwin.CONFIG.read_text(encoding="utf-8"))
    assert set(shipped) == {f.name for f in __import__("dataclasses").fields(songwin.Pace)}


def test_what_counts_as_yes_and_as_an_objection():
    for yes in ("Yes, it's correct", "yes it's correct.", "Correct!", "Yep, that's the one", "You got it, Irene", "That's right", "yes"):
        assert songwin.confirms(yes), yes
    for other in ("No, it's not", "Not quite", "Yes, play it on YouTube", "That's wrong", "Close, but no", "Who sings it?", ""):
        assert not songwin.confirms(other), other
    for no in ("Hey, don't say that.", "Don't say that!", "Hey, language!", "Watch your mouth", "That's rude", "Don't swear"):
        assert songwin.objects(no), no
    for other in ("Haha nice", "Play it", "What else do you know about it?", "Okay"):
        assert not songwin.objects(other), other


def test_only_after_she_named_his_song_and_only_his_next_message():
    bit = songwin.SongWin()
    assert bit.heard("Yes, it's correct", None) is None  # she named nothing: never
    assert bit.heard("Yes, it's correct", "Blue") == "gloat"
    assert bit.heard("Hey, don't say that", None) == "fugging"
    assert bit.heard("Hey, don't say that", None) is None  # over
    # no objection: she carries on, and the bit is over
    assert bit.heard("Yes, it's correct", "Blue") == "gloat"
    assert bit.heard("What else is on the album?", None) is None
    assert bit.heard("Hey, don't say that", None) is None


def _voiced(n: float) -> np.ndarray:
    return (0.3 * np.sin(np.arange(int(n * skit.SR)) / 9)).astype(np.float32)


def test_every_gap_is_exact_and_the_faces_ride_the_clip():
    p = songwin.Pace(beat_before_gloat_ms=650, beat_before_really_ms=150, beat_after_really_ms=600, hold_ms=2000, beat_before_fugging_ms=400)
    edge = np.zeros(int(0.03 * skit.SR), np.float32)
    really = np.concatenate([edge, _voiced(0.6), edge])
    fugging = np.concatenate([edge, _voiced(0.9), edge])
    clip, (first, second) = songwin.held(really, fugging, p)
    # the 3 s after "Oh really?" start at its LAST sample (its whole tail), not inside it
    start = int(round(0.15 * skit.SR))
    assert first == start / skit.SR and np.array_equal(clip[start:start + len(really)], really)
    after = start + len(really)
    gap = int(round(3.0 * skit.SR))
    assert not clip[after:after + gap].any() and second == (after + gap) / skit.SR
    assert np.array_equal(clip[after + gap:], fugging)
    gloat = np.concatenate([edge, _voiced(1.0), edge])
    clip, (at,) = songwin.gloat_clip(gloat, p)
    assert at == 0.65 and not clip[: int(0.65 * skit.SR)].any() and np.array_equal(clip[int(0.65 * skit.SR):], gloat)


@pytest.mark.parametrize("backend", sorted(EXPECTED))
def test_rendered_through_the_pronunciation_chokepoint(monkeypatch, tmp_path, backend):
    v = make_voice(monkeypatch, backend)
    # (a take on Turbo is one synth_one call, from a fixed seed)
    monkeypatch.setattr(type(v.engine), "synth_one", lambda self, text, temperature=0.8, seed=1: (self.heard.append(text), np.full(2400, 0.1, np.float32))[1], raising=False)
    monkeypatch.setattr(skit, "CACHE", tmp_path)
    monkeypatch.setattr(skit.render_line, "__defaults__", (tmp_path,))
    bit = songwin.SongWin()
    bit.load_or_render(v)
    assert bit.ready and bit.engine == backend
    gloat = next(h for h in v.engine.heard if "GG" in h)
    assert EXPECTED[backend] in gloat and "Tri " not in f"{gloat} ", gloat


@pytest.mark.skipif(not recall.MODEL_DIR.exists(), reason="bge-small-en-v1.5 not installed")
def test_a_taught_answer_that_names_it_arms_the_bit(tmp_path, monkeypatch):
    store = recall.Store(tmp_path / "memory.sqlite", recall.Embedder())
    monkeypatch.setattr(recall, "HIS", store)
    monkeypatch.setattr(recall, "DEV", store)
    store.add("fact", TAUGHT, session="taught")
    conv = Conversation(FakeLLM([
        "<speak><cue>proud</cue>It's “Blue” by yung kai, Mister Tri. Moonlight and waves. You keep coming back to it.</speak>",
        "<speak><cue>happy</cue>Glad you like it.</speak>",
    ]))
    asyncio.run(conv.respond(ASKED, BoardHost()))
    assert conv.named == "Blue"
    # any reply after it closes the window
    asyncio.run(conv.respond("tell me a joke", BoardHost()))
    assert conv.named is None
    store.close()


def test_slowed_keeps_the_onset_and_stretches_the_rest():
    edge = np.zeros(int(0.03 * skit.SR), np.float32)
    line = np.concatenate([edge, _voiced(1.0), edge])
    out = songwin.slowed(line, 0.7)
    lead = skit.silences(line)[0]  # (20 ms frames)
    keep = int((lead + songwin.ONSET_KEEP_MS) * skit.SR / 1000) - int(0.01 * skit.SR)
    assert np.array_equal(out[:keep], line[:keep])  # the first word's onset, untouched
    assert abs(len(out) / skit.SR - (0.15 + (len(line) / skit.SR - 0.15) / 0.7)) < 0.05
    assert songwin.slowed(line, 1.0) is not None and len(songwin.slowed(line, 1.0)) == len(line)
