"""His name is Tri - "Tree". config/pronunciation.yaml must reach every TTS backend
on every path that makes her speak, not just the one it was written for.

It regressed once: the map was applied in tts.Speaker.prepare() only, and the
cached "Mister Tri!" lead-in (openers.py) went straight to Chatterbox-Turbo, which
said "Mister Try". Each test below records exactly what text an engine was given.
"""
import re
from pathlib import Path

import numpy as np
import pytest

from irene import entrances, openers
from irene import voice as voice_mod
from irene.greeting import NAME
from irene.pronounce import load_rules
from irene.tts import Speaker

ROOT = Path(__file__).resolve().parents[2]
MAP = __import__("tools.localconfig", fromlist=["personal"]).personal("pronunciation.yaml")
IRENE = ROOT / "core" / "irene"


class Recorder(voice_mod.Engine):
    """A stand-in engine that says nothing and remembers everything it was given."""

    def __init__(self):
        self.heard: list[str] = []

    def synth(self, text, speed=1.0):
        self.heard.append(text)
        yield np.full(2400, 0.1, np.float32)


class FakeTurbo(Recorder):
    name = "turbo"
    tags = True


class FakeKokoro(Recorder):
    name = "kokoro"
    tags = False


def make_voice(monkeypatch, backend: str):
    monkeypatch.setattr(voice_mod, "TurboEngine", FakeTurbo)
    monkeypatch.setattr(voice_mod, "KokoroEngine", FakeKokoro)
    v = voice_mod.Voice(backend)
    assert v.name == backend
    return v


# what each backend must be given for "Tri", straight from the map
EXPECTED = {
    "turbo": "Tree",  # Chatterbox-Turbo reads no phonemes: the respelling
    "kokoro": "[Tri](/tɹˈi/)",  # Kokoro: its inline phoneme override
}
BACKENDS = sorted(EXPECTED)


def says_tri_right(heard: list[str], backend: str) -> bool:
    text = " ".join(heard)
    return EXPECTED[backend] in text and not re.search(r"(?<![\w\[])Tri(?![\w\]])", text)


@pytest.mark.parametrize("backend", BACKENDS)
def test_the_engine_wrapper_applies_the_map(monkeypatch, backend):
    v = make_voice(monkeypatch, backend)
    v.all("Good morning, Mister Tri.")
    assert says_tri_right(v.engine.heard, backend), v.engine.heard


@pytest.mark.parametrize("backend", BACKENDS)
def test_live_speech_through_the_speaker(monkeypatch, backend):
    v = make_voice(monkeypatch, backend)
    speaker = Speaker.__new__(Speaker)  # no audio device: just the text path
    speaker.voice = v
    speaker.synthesize(f"Good evening, {NAME}, how can I help?")
    assert says_tri_right(v.engine.heard, backend), v.engine.heard


@pytest.mark.parametrize("backend", BACKENDS)
def test_the_cached_lead_ins(monkeypatch, tmp_path, backend):
    # the regression: "Mister Tri!" rendered once, straight to the engine
    assert "Mister Tri!" in openers.OPENERS
    v = make_voice(monkeypatch, backend)
    monkeypatch.setattr(openers, "ASSETS", tmp_path)
    openers.load_or_render(v)
    named = [t for t in v.engine.heard if "Mister" in t]
    assert named and says_tri_right(named, backend), named


@pytest.mark.parametrize("backend", BACKENDS)
def test_entrance_lines(monkeypatch, tmp_path, backend):
    v = make_voice(monkeypatch, backend)
    monkeypatch.setattr(entrances, "ASSETS", tmp_path)
    entry = {"name": "chess", "line": "Your move, Mister Tri.", "ms": 4500, "voice_at": 1.0, "doing": "x", "sfx": []}
    entrances.load_or_render(v, entry)
    assert says_tri_right(v.engine.heard, backend), v.engine.heard


def test_turbo_failing_mid_sentence_hands_kokoro_its_own_form(monkeypatch):
    class BrokenTurbo(FakeTurbo):
        def synth(self, text, speed=1.0):
            raise RuntimeError("CUDA out of memory")

    monkeypatch.setattr(voice_mod, "TurboEngine", BrokenTurbo)
    monkeypatch.setattr(voice_mod, "KokoroEngine", FakeKokoro)
    v = voice_mod.Voice("turbo")
    v.all("Mister Tri!")
    assert v.engine.name == "kokoro" and says_tri_right(v.engine.heard, "kokoro"), v.engine.heard


def test_a_map_change_re_renders_only_the_lines_it_touches(monkeypatch, tmp_path):
    v = make_voice(monkeypatch, "turbo")
    named = {"name": "chess", "line": "Your move, Mister Tri.", "ms": 4500}
    plain = {"name": "kendo", "line": "Oh! Hi, sir!", "ms": 4600}
    assert entrances.key_of(named, "turbo", v.spoken(named["line"])) != entrances.key_of(named, "turbo")
    assert entrances.key_of(plain, "turbo", v.spoken(plain["line"])) == entrances.key_of(plain, "turbo")
    before = openers._cache_key(v)
    tweaked = tmp_path / "pronunciation.yaml"
    tweaked.write_text("Tri:\n  say: Treee\n", encoding="utf-8")
    v._rules = {True: load_rules(tweaked, True), False: load_rules(tweaked, False)}
    assert openers._cache_key(v) != before, "a changed map must re-render the cached lead-ins"


def test_nothing_else_talks_to_an_engine_directly():
    """Everything speaks through voice.Voice, where the map is applied. The one
    exception is the summon clip (summon_fx), a fixed line with no mapped word."""
    direct = re.compile(r"\.engine\.synth\(|\bsynth_one\(|\bTurboEngine\(|\bKokoroEngine\(|\.pipeline\(")
    offenders = []
    for path in IRENE.glob("*.py"):
        if path.name in ("voice.py", "summon_fx.py", "summon.py"):
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if direct.search(line) and not line.lstrip().startswith("#"):
                offenders.append(f"{path.name}:{n}: {line.strip()}")
    assert not offenders, "these reach a TTS engine without the pronunciation map:\n" + "\n".join(offenders)
    from irene import summon_fx

    mapped = [str(w) for w in __import__("yaml").safe_load(MAP.read_text(encoding="utf-8"))]
    fixed = " ".join([summon_fx.PART1, summon_fx.PART2A, summon_fx.PART2B])
    assert not any(re.search(rf"\b{re.escape(w)}\b", fixed) for w in mapped), "the summon line now needs the map too"
