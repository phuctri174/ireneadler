"""Skit mode (irene/skit.py): scripted scenes from config/skits/*.json, for filming.

Lines are said exactly as written, his turns are only waited for (never parsed),
and the pauses between her lines are the silence the file asks for."""
import asyncio
import json
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from irene import react as cues
from irene import skit as S
from irene.listen import BLOCK, Endpointer

ROOT = Path(__file__).resolve().parents[2]
ENTRANCES = {e["name"] for e in json.loads((ROOT / "config" / "entrances.json").read_text(encoding="utf-8"))["entrances"]}


def parse(beats, **extra):
    return S.parse({"beats": beats, **extra}, "t", Path("t.json"), ENTRANCES)


def test_first_dance_is_the_scene_he_wrote_word_for_word():
    skit = S.load("first_dance", ENTRANCES)
    assert skit.name == "first_dance"
    assert [b.who for b in skit.beats] == [
        "wait_for_me", "summon", "irene", "wait_for_me", "irene", "working", "wait_for_me", "irene", "wait_for_me", "irene", "irene",
    ]
    lines = [b.line for b in skit.beats if b.who == "irene"]
    assert lines == [
        "What's up, Mister Tri?",
        "I'm so sorry, Mister Tri. Let me redo it for you.",
        "Anyway... although you hate me, I still don't hate you the way she does, Mister Tri.",
        "Nevermind, I'll take that back.",
        "...even though I was telling the truth.",
    ]
    _, sorry, anyway, back, truth = (b for b in skit.beats if b.who == "irene")
    assert sorry.cues == ["sobbing"] and sorry.sound == "wail"
    # beat 6: her working state, then she waits for his apology
    working, apology = skit.beats[5], skit.beats[6]
    assert working.working and working.hold_ms == 2500 and apology.who == "wait_for_me"
    # the 2 s comes AFTER the whole "Nevermind, I'll take that back." - none inside it
    assert back.cues == ["peeking"] and back.pause_after_ms == 2000 and back.max_gap_ms <= 450
    assert truth.cues == ["smug"] and truth.pause_after_ms == 2500
    # sincere, not playful: the harmless angel face, and a low (flat) Turbo temperature
    assert anyway.cues == ["innocent"] and anyway.temperature < 0.8
    # not rushed: every line a little slower, the end - from "Nevermind" - slowest,
    # and all of them steady (no line at Turbo's default 0.8)
    mine = [b for b in skit.beats if b.who == "irene"]
    assert all(b.speed < 1 and b.temperature <= 0.6 for b in mine)
    assert back.speed == truth.speed == min(b.speed for b in mine)
    assert skit.start_hidden
    summon = skit.beats[1]
    # her full introduction: the boot and her song, then the entrance - the
    # Victorian one when he wakes her with "Irene Adler"
    assert summon.entrance in ENTRANCES and summon.boot and summon.music and summon.adler == "victorian"
    assert skit.beats[0].wake


def test_every_shipped_skit_loads_and_never_shows_one_cue_twice_running():
    for path in S.files():
        skit = S.load(path.stem, ENTRANCES)
        mine = [b for b in skit.beats if b.who == "irene"]
        assert all(b.cues for b in mine), f"{path.name}: every line carries a cue"
        for a, b in zip(mine, mine[1:]):
            assert a.cues[-1] != b.cues[0], f"{path.name}: {a.cues[-1]} twice running"


def test_the_prop_is_her_research_on_paper_never_on_the_panel():
    content = S.prop("first_dance")
    assert content["title"] == "First Dance in Kendo — A Beginner's Guide" and content["blocks"]
    # a skit can't put anything on her panel
    with pytest.raises(S.SkitError, match="unknown panel"):
        parse([{"who": "summon", "panel": "first_dance"}])
    kinds = {b["kind"] for b in content["blocks"]}
    assert {"heading", "text", "quote", "image"} <= kinds
    # nothing on it is fetched: its picture is embedded
    assert all(b["src"].startswith("data:image/") for b in content["blocks"] if b["kind"] == "image")


@pytest.mark.parametrize("beat, error", [
    ({"who": "her", "line": "x"}, "who must be"),
    ({"who": "irene", "line": "Hi."}, "at least one cue"),
    ({"who": "irene", "line": "Hi.", "cue": "nope"}, "cue 'nope'"),
    ({"who": "irene", "line": "Hi.", "cue": "folder"}, "cue 'folder'"),
    ({"who": "irene", "line": "Hi.", "cue": "happy", "pause_afer_ms": 2000}, "unknown pause_afer_ms"),
    ({"who": "irene", "line": "Hi.", "cue": "happy", "pause_after_ms": -1}, "milliseconds"),
    ({"who": "irene", "line": "Hi.", "cue": "happy", "sound": "kazoo"}, "sound 'kazoo'"),
    ({"who": "irene", "line": "Hi.", "cue": "happy", "working": "happy"}, "not a prop"),
    ({"who": "summon", "entrance": "moonwalk"}, "no entrance"),
    ({"who": "wait_for_me", "silence_ms": 100}, "mid-word"),
])
def test_a_broken_beat_says_which_and_why(beat, error):
    with pytest.raises(S.SkitError, match=error):
        parse([{"who": "wait_for_me"}, beat])


def test_the_newest_file_is_the_one_the_hotkey_plays(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "SKITS", tmp_path)
    for name, at in (("old", 1000), ("new", 2000)):
        (tmp_path / f"{name}.json").write_text('{"beats": [{"who": "wait_for_me"}]}', encoding="utf-8")
        import os

        os.utime(tmp_path / f"{name}.json", (at, at))
    assert S.find(None).stem == "new" and S.find("old").stem == "old"
    with pytest.raises(S.SkitError):
        S.find("../config/cues")


def test_his_turn_ends_on_the_beats_silence_and_may_run_long():
    ep = Endpointer()
    ep.fixed_wait_s, ep.max_utterance_s = 1.5, 120.0
    voiced, quiet = np.full(BLOCK, 0.1, np.float32), np.zeros(BLOCK, np.float32)
    events = [e for _ in range(20) for e in ep.feed(voiced, 0.9)]
    # a 1.2 s breath mid-rant does not end it (the conversation's would at 0.9 s)
    events += [e for _ in range(int(1.2 / (BLOCK / 16000))) for e in ep.feed(quiet, 0.0)]
    events += [e for _ in range(1100) for e in ep.feed(voiced, 0.9)]  # 35 s of rant
    assert not [e for e in events if e.kind == "end"]
    ends = [e for _ in range(60) for e in ep.feed(quiet, 0.0) if e.kind == "end"]
    assert len(ends) == 1


def test_a_cue_list_is_her_face_and_her_body():
    timeline = S.cue_messages(["happy", "wave"])
    assert (0.0, {"type": "emotion", "value": "happy"}) in timeline
    assert (0.0, {"type": "reaction", "value": "wave", "big": True}) in timeline


# ---- the run, against a fake core -------------------------------------------------


class Bridge:
    def __init__(self):
        self.sent: list[tuple[float, dict]] = []
        self.hud_connected = False
        self.current_state = "listening"

    async def send(self, m):
        self.sent.append((time.perf_counter(), m))

    def send_threadsafe(self, m):
        self.sent.append((time.perf_counter(), m))

    async def state(self, v):
        self.current_state = v
        await self.send({"type": "state", "value": v})

    async def emotion(self, v):
        await self.send({"type": "emotion", "value": v})

    async def panel(self, v):
        await self.send({"type": "panel", "value": v})

    async def transcript(self, role, text):
        await self.send({"type": "transcript", "role": role, "text": text})


class Speaker:
    """Plays at once; done when the clip's length has passed, like the real one."""

    def __init__(self):
        self.played: list[tuple[float, float]] = []
        self.voice = type("V", (), {"name": "fake"})()

    def play(self, audio, levels, marks=(), done=None):
        start = time.perf_counter()
        for _, fn in marks:
            fn()
        seconds = len(audio) / 24000

        def finish():
            time.sleep(seconds)
            self.played.append((start, time.perf_counter()))
            done and done(True)

        threading.Thread(target=finish, daemon=True).start()
        return start

    def stop(self):
        pass


class Core:
    def __init__(self):
        self.bridge = Bridge()
        self.speaker = Speaker()
        self.muted = False
        self.dark = False
        self._turn = None
        self._sounds = {}
        self._progress_at = 0.0
        self.last_react = None
        self.entrances = []
        self.voice = type("Voice", (), {"mic": None, "heard_her": lambda self, t: None})()
        self.summons = 0

    async def on_summon_skip(self, _m):
        pass

    async def exit_dark(self, why):
        pass


def run_skit(core, beats, heard_after: dict[int, float] | None = None):
    """Play `beats`; his voice "finishes" `heard_after[n]` s into wait beat n."""
    skit = parse(beats)
    runner = S.Skits(core)
    core.skit = runner

    async def go():
        runner.task = asyncio.create_task(runner._run(skit))
        seen = 0
        while not runner.task.done():
            await asyncio.sleep(0.005)
            if runner.waiting:
                seen += 1
                await asyncio.sleep((heard_after or {}).get(seen, 0.05))
                assert runner.heard(0.1) is False  # a cough is not his turn
                assert runner.heard(2.0) is True
        await runner.task

    asyncio.run(go())
    return runner


def test_lines_play_in_order_with_exactly_the_silences_asked(monkeypatch):
    monkeypatch.setattr(S, "render_line", lambda voice, beat: np.zeros(int(0.2 * 24000), np.float32))
    core = Core()
    runner = run_skit(core, [
        {"who": "wait_for_me"},
        {"who": "irene", "line": "One.", "cue": "happy", "pause_after_ms": 300, "working": "folder"},
        {"who": "irene", "line": "Two.", "cue": "innocent", "pause_after_ms": 200},
        {"who": "irene", "line": "Three.", "cue": "smug", "pause_after_ms": 100},
    ])
    said = [m["text"] for _, m in core.bridge.sent if m["type"] == "transcript"]
    assert said == ["One.", "Two.", "Three."]
    assert [w for w, _ in runner.gaps] == [300, 200]
    for wanted, got in runner.gaps:
        assert abs(got - wanted) < 40, runner.gaps
    # the working state fills the first pause with her prop - and nothing else is said
    tools = [m for _, m in core.bridge.sent if m["type"] == "tool"]
    assert tools[0] == {"type": "tool", "name": "skit", "status": "running", "cue": "folder"}
    faces = [m["value"] for _, m in core.bridge.sent if m["type"] == "emotion"]
    assert faces == ["happy", "innocent", "smug", "neutral"]
    # the smug face holds for the last beat's pause before she settles
    smug_at = next(t for t, m in core.bridge.sent if m.get("value") == "smug")
    neutral_at = next(t for t, m in core.bridge.sent if m.get("value") == "neutral")
    assert neutral_at - smug_at >= 0.2 + 0.1 - 0.02
    assert core.last_react == "smug"
    assert core.bridge.sent[-1][1] == {"type": "state", "value": "listening"}


def test_she_waits_for_him_however_long_he_talks(monkeypatch):
    monkeypatch.setattr(S, "render_line", lambda voice, beat: np.zeros(2400, np.float32))
    core = Core()
    t0 = time.perf_counter()
    run_skit(core, [{"who": "wait_for_me"}, {"who": "irene", "line": "Hi.", "cue": "happy"}], heard_after={1: 0.4})
    line_at = next(t for t, m in core.bridge.sent if m["type"] == "transcript")
    assert line_at - t0 >= 0.4


def test_an_abort_stops_the_take_and_she_settles(monkeypatch):
    monkeypatch.setattr(S, "render_line", lambda voice, beat: np.zeros(2400, np.float32))
    core = Core()
    runner = S.Skits(core)

    async def go():
        runner.task = asyncio.create_task(runner._run(parse([{"who": "wait_for_me"}, {"who": "irene", "line": "Never said.", "cue": "happy"}])))
        await asyncio.sleep(0.05)
        assert runner.waiting
        await runner.abort("test")
        assert not runner.active and runner.heard(2.0) is False

    asyncio.run(go())
    said = [m for _, m in core.bridge.sent if m["type"] == "transcript"]
    assert not said
    assert {"type": "skit", "phase": "end", "name": "t", "completed": False} in [m for _, m in core.bridge.sent]


def test_a_skit_takes_his_voice_from_the_conversation():
    """Mid-skit, the end of his speech goes to the skit - never transcribed, never a
    wake phrase or a command."""
    from irene.listen import Event
    from irene.voice_loop import Voice

    got = []

    class Skit:
        active = True
        wants_words = False

        def heard(self, seconds, said=None):
            got.append(seconds)
            return True

    v = object.__new__(Voice)
    v.core = type("C", (), {"skit": Skit(), "bridge": None})()
    v.visible = False
    v.verifier = None
    v.stt = None  # would raise if anything tried to transcribe
    asyncio.run(v._handle(Event("end", audio=np.zeros(32000, np.float32), generation=1)))
    asyncio.run(v._handle(Event("check", audio=np.zeros(16000, np.float32), generation=1)))
    asyncio.run(v._handle(Event("peek", audio=np.zeros(16000, np.float32), generation=1)))
    assert got == [2.0]


def test_new_expressions_are_in_the_pool():
    for name in ("sobbing", "innocent", "peeking", "smug"):
        assert cues.BY_NAME[name]["kind"] == "expression"


def test_the_summon_blocks_until_her_whole_intro_is_over(monkeypatch):
    """Nothing in the skit - least of all her first line - starts until the boot
    and the entrance have finished and she is listening; no greeting plays."""
    monkeypatch.setattr(S, "render_line", lambda voice, beat: np.zeros(2400, np.float32))
    core = Core()
    core.entrances = [{"name": "domain_expansion", "line": "DOMAIN EXPANSION"}]
    core.picker = type("P", (), {"last": None})()
    stages = []

    async def boot_only(scored):
        stages.append(("boot start", time.perf_counter()))
        await asyncio.sleep(0.3)
        stages.append(("boot end", time.perf_counter()))

    async def play_summon(line):
        await asyncio.sleep(0.2)
        stages.append(("entrance end", time.perf_counter()))

    core._boot_only = boot_only
    core.play_summon = play_summon
    core._music_start = lambda: False
    run_skit(core, [
        {"who": "wait_for_me"},
        {"who": "summon", "entrance": "domain_expansion", "boot": True},
        {"who": "irene", "line": "What's up?", "cue": "happy"},
    ])
    first_line = next(t for t, m in core.bridge.sent if m["type"] == "transcript")
    assert [n for n, _ in stages] == ["boot start", "boot end", "entrance end"]
    assert first_line > stages[-1][1]
    said = [m["text"] for _, m in core.bridge.sent if m["type"] == "transcript"]
    assert said == ["What's up?"]  # no greeting


def _speech(*parts):
    """Audio of `parts`: ("say", ms) is a tone, ("quiet", ms) silence."""
    out = []
    for kind, ms in parts:
        n = int(24 * ms)
        out.append(0.3 * np.sin(np.arange(n) * 0.2).astype(np.float32) if kind == "say" else np.zeros(n, np.float32))
    return np.concatenate(out)


def test_a_take_with_a_long_silence_inside_is_rendered_again_and_trimmed(tmp_path):
    """Live: 2 s between "Nevermind" and "I'll take that back", inside one rendering.
    A take like that is rendered again with another seed; the words are trimmed of
    the silence around them, so the pause after a line is the file's."""
    takes = {1: _speech(("quiet", 300), ("say", 500), ("quiet", 2000), ("say", 900), ("quiet", 450)),
             1001: _speech(("quiet", 300), ("say", 500), ("quiet", 120), ("say", 900), ("quiet", 450))}
    seeds = []

    class Voice:
        name = "turbo"

        def spoken(self, text):
            return text

        def take(self, text, speed=1.0, temperature=0.8, seed=1):
            seeds.append(seed)
            return takes[seed]

    beat = parse([{"who": "irene", "line": "Nevermind, I'll take that back.", "cue": "peeking"}]).beats[0]
    audio = S.render_line(Voice(), beat, cache=tmp_path)
    assert seeds == [1, 1001]
    lead, tail, inside, _ = S.silences(audio)
    assert inside < 200 and lead <= S.EDGE_MS and tail <= S.EDGE_MS
    assert abs(len(audio) / 24000 - (0.5 + 0.12 + 0.9 + 2 * S.EDGE_MS / 1000)) < 0.05
    # kept: the next take reads it from the cache, nothing rendered again
    S.render_line(Voice(), beat, cache=tmp_path)
    assert seeds == [1, 1001]


def test_the_working_beat_waits_for_him_however_long_he_apologises(monkeypatch):
    monkeypatch.setattr(S, "render_line", lambda voice, beat: np.zeros(2400, np.float32))
    core = Core()
    t0 = time.perf_counter()
    run_skit(core, [
        {"who": "wait_for_me"},
        {"who": "irene", "line": "Sorry.", "cue": "sobbing"},
        {"who": "working", "prop": "folder", "hold_ms": 300},
        {"who": "wait_for_me"},
        {"who": "irene", "line": "Anyway.", "cue": "innocent"},
    ], heard_after={2: 0.6})
    tools = [(t, m) for t, m in core.bridge.sent if m["type"] == "tool"]
    running = next(t for t, m in tools if m["status"] == "running" and m["cue"] == "folder")
    done = next(t for t, m in tools if m["status"] == "done" and t > running)
    anyway = next(t for t, m in core.bridge.sent if m.get("text") == "Anyway.")
    # working from the hold through his whole apology, gone as she speaks again
    assert done - running >= 0.3 + 0.6 - 0.05 and anyway >= done


def test_his_apology_inside_the_working_hold_still_counts(monkeypatch):
    """He finishes apologising before the 2.5 s hold is over: that turn is kept for
    the wait after it - she never sits waiting for an apology he already made."""
    monkeypatch.setattr(S, "render_line", lambda voice, beat: np.zeros(2400, np.float32))
    core = Core()
    skit = parse([
        {"who": "working", "prop": "folder", "hold_ms": 300},
        {"who": "wait_for_me"},
        {"who": "irene", "line": "Anyway.", "cue": "innocent"},
    ])
    runner = S.Skits(core)

    async def go():
        runner.task = asyncio.create_task(runner._run(skit))
        await asyncio.sleep(0.1)
        assert runner.heard(2.0) is True  # inside the hold
        await asyncio.wait_for(runner.task, 3.0)

    asyncio.run(go())
    assert any(m.get("text") == "Anyway." for _, m in core.bridge.sent)


def _wake_skit(said: str):
    """first_dance's opening - a wake beat, the summon - woken with `said`.
    Returns (the entrance played, whether the music started, the runner)."""
    core = Core()
    core.entrances = [{"name": "domain_expansion", "line": "DOMAIN EXPANSION"}, {"name": "victorian", "line": "Charmed."}]
    core.entrance_clips = {"victorian": "the victorian clip"}
    core.picker = type("P", (), {"last": None})()
    played, music = [], []

    async def boot_only(scored):
        await asyncio.sleep(0.01)

    async def play_summon(line):
        played.append("domain_expansion")

    async def play_entrance(clip, line):
        played.append(clip)

    core._boot_only, core.play_summon, core.play_entrance = boot_only, play_summon, play_entrance
    core._music_start = lambda: music.append(True) or False
    skit = parse([{"who": "wait_for_me", "wake": True}, {"who": "summon", "entrance": "domain_expansion", "boot": True, "music": True}])
    runner = S.Skits(core)

    async def go():
        runner.task = asyncio.create_task(runner._run(skit))
        await asyncio.sleep(0.05)
        # anything that isn't a wake phrase leaves her waiting
        assert runner.heard(2.0, "okay let's start filming") is False and runner.waiting
        assert runner.heard(2.0, None) is False
        assert runner.heard(1.5, said) is True
        await asyncio.wait_for(runner.task, 3.0)

    asyncio.run(go())
    return played, bool(music), runner


def test_irene_adler_wakes_her_with_the_irene_adler_scene():
    played, music, runner = _wake_skit("Irene Adler.")
    assert played == ["the victorian clip"] and music and runner.wake_phrase == "adler"


def test_hey_irene_wakes_her_with_the_domain_expansion():
    played, music, runner = _wake_skit("Hey Irene!")
    assert played == ["domain_expansion"] and music and runner.wake_phrase == "hey"


def test_a_slower_line_is_her_voice_at_the_same_pitch():
    from irene.stretch import stretch

    sr = 24000
    t = np.arange(int(0.8 * sr)) / sr
    # a voice-like tone: 210 Hz with harmonics
    voice = sum(np.sin(2 * np.pi * 210 * k * t) / k for k in range(1, 6)).astype(np.float32) * 0.2
    slow = stretch(voice, 0.85)
    assert abs(len(slow) / len(voice) - 1 / 0.85) < 0.01
    spectrum = np.abs(np.fft.rfft(slow[2000:-2000]))
    peak = np.fft.rfftfreq(len(slow) - 4000, 1 / sr)[np.argmax(spectrum)]
    assert abs(peak - 210) < 5
    assert stretch(voice, 1.0) is not None and len(stretch(voice, 1.0)) == len(voice)
