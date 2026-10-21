# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Skit mode: scripted scenes for filming, one file each in config/skits/<name>.json.

  ctrl+alt+shift+k   start the newest skit file (or, mid-skit, start it over)
  ctrl+alt+shift+x   abort it - she settles to listening, ready for another take

A skit is an ordered list of beats; a new skit is only a new JSON file. Each beat
is one of

  {"who": "wait_for_me", "silence_ms": 900, "note": "Hey Irene"}
      waits for HIM to speak and finish - his voiceprint only (speaker_id.py), and
      nothing he says is transcribed or parsed: his turn ends after exactly
      silence_ms of quiet (max_ms is the longest it may run; default 120000).
      "wake": true - the one exception: his words are checked for a wake phrase
      ("Hey Irene", "Irene Adler", ...) and only a wake phrase ends the beat; the
      phrase picks the summon's entrance (below)
  {"who": "summon", "entrance": "domain_expansion", "adler": "victorian", "boot": true, "music": true}
      her normal summon - her window and her panel (her dashboard) come up - with THIS entrance
      (any name in config/entrances.json, or "none": she just appears) - or, when
      his wake phrase was "Irene Adler", the "adler" one (default victorian: her
      Irene Adler scene). boot: true plays the 12 s boot first; music: true her
      summon song under it (config/summon_music.yaml), faded out before her first
      word. Never a greeting: the next beat is hers
  {"who": "working", "prop": "folder", "hold_ms": 2500}
      her working state (thinking, a cues.json prop) - at least hold_ms, and on
      through the wait beats after it until her next line: she is redoing it
      while he talks. His turn can start (and even end) inside the hold; it counts
  {"who": "irene", "line": "...", "cue": "happy", "sound": "whimper"}
      her line, EXACTLY these words (never the model's), with its cue(s) as the
      first sample is heard (config/cues.json: an expression is her face, a
      gesture or scene plays big) and an optional sound effect (core/irene/sfx.py)
      leading the words by sound_lead_ms (default 250) at sound_gain (0.45).
      Delivery: temperature (Turbo; lower is steadier and flatter - default 0.8),
      speed (0.9 = 10% slower, same pitch: Kokoro natively, Turbo's take
      time-stretched - core/irene/stretch.py), take (another seed = another
      rendering of the same words).
      One utterance, one rendering - never split. Turbo still sometimes holds a
      long silence inside a line (live: 2 s between "Nevermind" and "I'll take
      that back"): every take is measured, and one with a silence inside longer
      than max_gap_ms (default 450; a "..." or a full stop may need more) is
      rendered again with another seed. Silence before and after the words is
      trimmed, so the pauses around a line are exactly the file's
      "domain": {"hold_ms": 3000, "bubble": "Nah. I'd win."} - her domain expansion
      on this line, exactly as the summon plays it (the visor slides in, her hand
      lifts it off one eye, it burns ice-blue, the black hole behind), from the
      clip's first sample - the sound (sfx domain_win) is timed to it - held
      hold_ms after the reveal; "bubble": a manga speech bubble on her matrix
      with these words, snapping in on the reveal and held as long

Every beat may also carry
  pause_before_ms / pause_after_ms   silence, exact: measured from the last sample
                                     heard to the next first sample, logged as such
  working: "<prop>"                  during pause_after_ms she shows a working
                                     state (thinking, the prop - a cues.json prop)

A skit never puts anything on her panel: it stays her ordinary dashboard. A prop a
skit needs on paper is panel content in config/skits/props/<name>.json, printed to
his Desktop in her research style by core/scripts/skit_pdf.py.

Her face holds a line's expression through the pauses and his turns, until the
next cue; the skit's last beat's pause_after_ms is how long the final face holds.
Lines are rendered once and kept (core/assets/skits/), so every take sounds the
same and no pause ever waits on synthesis. While a skit runs nothing else speaks
or moves on its own: no model, no greeting, no barge-in, no idle life.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from . import react as cues
from . import sfx

if TYPE_CHECKING:
    from .app import Core

log = logging.getLogger("irene.skit")

ROOT = Path(__file__).resolve().parents[2]
SKITS = ROOT / "config" / "skits"
PROPS = SKITS / "props"
CACHE = ROOT / "core" / "assets" / "skits"
SR = 24000
FORMAT = 2
WHO = ("irene", "wait_for_me", "summon", "working")
SOUND_GAIN = 0.45
SOUND_LEAD_MS = 250
WAIT_SILENCE_MS = 900
WAIT_MAX_MS = 120_000
# his voice: shorter than this is a cough, a click, her echo's tail - not his turn
WAIT_MIN_MS = 300
# the HUD's summon must come back (show the window) within this
SUMMON_TIMEOUT_S = 3.0
# how long a take waits for her to be put away before listening for his wake
HIDE_WAIT_S = 1.5
# what a beat may say: anything else is a typo, and a typo'd pause is a ruined take
COMMON = {"who", "note", "pause_before_ms", "pause_after_ms", "working"}
KEYS = {
    "irene": COMMON | {"line", "cue", "sound", "sound_gain", "sound_lead_ms", "speed", "temperature", "take", "max_gap_ms", "domain"},
    "wait_for_me": COMMON | {"silence_ms", "max_ms", "wake"},
    "summon": COMMON | {"entrance", "adler", "boot", "music"},
    "working": COMMON | {"prop", "hold_ms"},
}
# a take's own silence: inside it (longer = rendered again), and kept at its edges
MAX_GAP_MS = 450
EDGE_MS = 30
RETAKES = 6


class SkitError(ValueError):
    """A skit file that can't be played, with what is wrong in it."""


@dataclass
class Beat:
    who: str
    line: str = ""
    cues: list[str] = field(default_factory=list)
    sound: str | None = None
    sound_gain: float = SOUND_GAIN
    sound_lead_ms: int = SOUND_LEAD_MS
    pause_before_ms: int = 0
    pause_after_ms: int = 0
    working: str | None = None
    speed: float = 1.0
    temperature: float = 0.8
    take: int = 1
    silence_ms: int = WAIT_SILENCE_MS
    max_ms: int = WAIT_MAX_MS
    max_gap_ms: int = MAX_GAP_MS
    hold_ms: int = 2500
    entrance: str = "domain_expansion"
    # the entrance when his wake phrase was "Irene Adler"
    adler: str = "victorian"
    # a wait beat that only a wake phrase ends
    wake: bool = False
    boot: bool = False
    music: bool = False
    note: str = ""
    # her domain expansion fired on this line: {"hold_ms", "bubble"} (or None)
    domain: dict | None = None


@dataclass
class Skit:
    name: str
    beats: list[Beat]
    path: Path
    # she is put away first, so a take starts from nothing (a skit that opens on
    # his "Hey Irene" and summons her)
    start_hidden: bool = False


def _ms(raw: dict, key: str, default: int, where: str) -> int:
    value = raw.get(key, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise SkitError(f"{where}: {key} must be a number of milliseconds >= 0, not {value!r}")
    return int(value)


def parse(data: dict, name: str, path: Path, entrances: set[str] | None = None) -> Skit:
    """A skit from its JSON, every beat checked: what is wrong says which beat."""
    if not isinstance(data, dict) or not isinstance(data.get("beats"), list) or not data["beats"]:
        raise SkitError(f"{path.name}: needs a non-empty \"beats\" list")
    beats: list[Beat] = []
    for n, raw in enumerate(data["beats"], 1):
        where = f"{path.name} beat {n}"
        if not isinstance(raw, dict):
            raise SkitError(f"{where}: must be an object")
        who = raw.get("who")
        if who not in WHO:
            raise SkitError(f"{where}: who must be one of {', '.join(WHO)}, not {who!r}")
        unknown = sorted(k for k in raw if k not in KEYS[who] and not k.startswith("_"))
        if unknown:
            raise SkitError(f"{where}: unknown {', '.join(unknown)} for a {who} beat (it takes {', '.join(sorted(KEYS[who]))})")
        beat = Beat(who=who, note=str(raw.get("note", "")))
        beat.pause_before_ms = _ms(raw, "pause_before_ms", 0, where)
        beat.pause_after_ms = _ms(raw, "pause_after_ms", 0, where)
        working = raw.get("working")
        if working is not None:
            if cues.prop(working) is None:
                props = sorted(c["name"] for c in cues.CUES if c["kind"] == "prop")
                raise SkitError(f"{where}: working {working!r} is not a prop ({', '.join(props)})")
            beat.working = working
        if who == "irene":
            line = raw.get("line")
            if not isinstance(line, str) or not line.strip():
                raise SkitError(f"{where}: an irene beat needs her \"line\"")
            beat.line = line.strip()
            given = raw.get("cue", [])
            given = [given] if isinstance(given, str) else given
            if not isinstance(given, list) or not given:
                raise SkitError(f"{where}: every line carries at least one cue (\"cue\": a name from config/cues.json)")
            for c in given:
                if c not in cues.BY_NAME or cues.BY_NAME[c]["kind"] == "prop":
                    raise SkitError(f"{where}: cue {c!r} is not an expression, gesture or scene in config/cues.json")
            beat.cues = list(given)
            sound = raw.get("sound")
            if sound is not None and sound not in sfx.EFFECTS:
                raise SkitError(f"{where}: sound {sound!r} - have {', '.join(sorted(sfx.EFFECTS))}")
            beat.sound = sound
            beat.sound_gain = float(raw.get("sound_gain", SOUND_GAIN))
            beat.sound_lead_ms = _ms(raw, "sound_lead_ms", SOUND_LEAD_MS, where)
            beat.speed = float(raw.get("speed", 1.0))
            beat.temperature = float(raw.get("temperature", 0.8))
            beat.take = int(raw.get("take", 1))
            beat.max_gap_ms = _ms(raw, "max_gap_ms", MAX_GAP_MS, where)
            domain = raw.get("domain")
            if domain is not None:
                if not isinstance(domain, dict) or sorted(k for k in domain if k not in ("hold_ms", "bubble")):
                    raise SkitError(f"{where}: domain takes {{\"hold_ms\": ms, \"bubble\": \"words\"}}, not {domain!r}")
                bubble = domain.get("bubble", "")
                if not isinstance(bubble, str) or len(bubble) > 16:
                    raise SkitError(f"{where}: domain bubble must be words of at most 16 characters (it is drawn big), not {bubble!r}")
                beat.domain = {"hold_ms": _ms(domain, "hold_ms", 3000, where), "bubble": bubble.strip()}
        elif who == "working":
            prop_name = raw.get("prop", "folder")
            if cues.prop(prop_name) is None:
                props = sorted(c["name"] for c in cues.CUES if c["kind"] == "prop")
                raise SkitError(f"{where}: prop {prop_name!r} is not a prop ({', '.join(props)})")
            beat.working = prop_name
            beat.hold_ms = _ms(raw, "hold_ms", 2500, where)
        elif who == "wait_for_me":
            beat.silence_ms = _ms(raw, "silence_ms", WAIT_SILENCE_MS, where)
            beat.max_ms = _ms(raw, "max_ms", WAIT_MAX_MS, where)
            if beat.silence_ms < 300:
                raise SkitError(f"{where}: silence_ms under 300 would end his turn mid-word")
            beat.wake = bool(raw.get("wake", False))
        else:
            beat.entrance = str(raw.get("entrance", "domain_expansion"))
            beat.adler = str(raw.get("adler", "victorian"))
            for key, entrance in (("entrance", beat.entrance), ("adler", beat.adler)):
                if entrance != "none" and entrances is not None and entrance not in entrances:
                    raise SkitError(f"{where}: {key}: no entrance {entrance!r} (have none, {', '.join(sorted(entrances))})")
            beat.boot = bool(raw.get("boot", False))
            beat.music = bool(raw.get("music", False))
        beats.append(beat)
    hidden = data.get("start_hidden")
    if hidden is None:
        kinds = [b.who for b in beats]
        hidden = "summon" in kinds and kinds[0] == "wait_for_me"
    return Skit(name=name, beats=beats, path=path, start_hidden=bool(hidden))


def files() -> list[Path]:
    return sorted(SKITS.glob("*.json"))


def find(name: str | None) -> Path:
    """config/skits/<name>.json - or, with no name, the newest skit file (the one
    he just wrote or tuned)."""
    if name:
        path = SKITS / f"{Path(name).stem}.json"
        if path.parent != SKITS or not path.exists():
            raise SkitError(f"no skit {name!r} in config/skits/")
        return path
    found = files()
    if not found:
        raise SkitError("no skits in config/skits/")
    return max(found, key=lambda p: p.stat().st_mtime)


def load(name: str | None = None, entrances: set[str] | None = None) -> Skit:
    path = find(name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SkitError(f"{path.name}: not valid JSON ({error})") from error
    return parse(data, path.stem, path, entrances)


def prop(name: str) -> dict:
    """A paper prop: panel content (hud/src/ui/content.ts), as a research shows it -
    printed to his Desktop by core/scripts/skit_pdf.py, never put on the panel."""
    return json.loads((PROPS / f"{name}.json").read_text(encoding="utf-8"))


def _key(voice, beat: Beat) -> str:
    spoken = voice.spoken(beat.line) if hasattr(voice, "spoken") else beat.line
    blob = {"engine": voice.name, "spoken": spoken, "speed": beat.speed, "temperature": beat.temperature, "take": beat.take, "max_gap": beat.max_gap_ms, "format": FORMAT}
    return hashlib.sha1(json.dumps(blob, sort_keys=True).encode()).hexdigest()[:16]


def silences(audio: np.ndarray, frame_ms: int = 20) -> tuple[int, int, int, int]:
    """(leading, trailing, longest inside, where it starts) in ms: quiet is under
    6% of the take's loudest 20 ms."""
    b = int(SR * frame_ms / 1000)
    frames = len(audio) // b
    if frames == 0:
        return 0, 0, 0, 0
    rms = np.sqrt(np.mean(audio[: frames * b].reshape(frames, b) ** 2, axis=1))
    on = rms > rms.max() * 0.06
    lit = np.flatnonzero(on)
    if len(lit) == 0:
        return len(audio) * 1000 // SR, 0, 0, 0
    first, last = int(lit[0]), int(lit[-1])
    longest, at, run = 0, 0, 0
    for k in range(first, last + 1):
        if on[k]:
            if run > longest:
                longest, at = run, k - run
            run = 0
        else:
            run += 1
    return first * frame_ms, (frames - 1 - last) * frame_ms, longest * frame_ms, at * frame_ms


def trimmed(audio: np.ndarray) -> np.ndarray:
    """The words only - EDGE_MS either side: a pause around a line is the file's."""
    lead, tail, _, _ = silences(audio)
    edge = EDGE_MS * SR // 1000
    start = max(0, lead * SR // 1000 - edge)
    end = len(audio) - max(0, tail * SR // 1000 - edge)
    return audio[start:end]


def render_line(voice, beat: Beat, cache: Path = CACHE) -> np.ndarray:
    """Her line in her voice, as ONE utterance: from core/assets/skits/, or rendered
    now - again with another seed while a take holds a silence inside it longer
    than beat.max_gap_ms - trimmed at its edges, and kept."""
    import soundfile as sf

    from .levels import level_speech

    path = cache / voice.name / f"{_key(voice, beat)}.wav"
    if path.exists():
        return level_speech(sf.read(path, dtype="float32")[0])
    t0 = time.perf_counter()
    best: tuple[int, np.ndarray] | None = None
    for k in range(RETAKES):
        seed = beat.take + 1000 * k
        audio = voice.take(beat.line, speed=beat.speed, temperature=beat.temperature, seed=seed) if hasattr(voice, "take") else voice.all(beat.line, beat.speed)
        _, _, gap, at = silences(audio)
        if best is None or gap < best[0]:
            best = (gap, audio)
        if gap <= beat.max_gap_ms:
            break
        log.warning("skit take %d of %r: %d ms of silence inside it (at %d ms; allowed %d) - rendering it again", k + 1, beat.line, gap, at, beat.max_gap_ms)
        if not hasattr(voice, "take"):
            break
    assert best is not None
    gap, audio = best
    if beat.speed != 1.0 and voice.name == "turbo":
        # Turbo has no speed: her take, slowed (or sped up) at the same pitch -
        # Kokoro was already given the speed
        from .stretch import stretch

        audio = stretch(audio, beat.speed)
    audio = trimmed(audio)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, audio, SR, subtype="PCM_16")
    log.info("skit line rendered in %.1f s (%.1f s of audio, longest silence inside %d ms%s): %r", time.perf_counter() - t0, len(audio) / SR, gap,
             "" if gap <= beat.max_gap_ms else f" - STILL over {beat.max_gap_ms}, the best of {RETAKES}", beat.line)
    return audio


def with_sound(speech: np.ndarray, sound: np.ndarray | None, gain: float, lead_ms: int) -> np.ndarray:
    """The sound first, her words lead_ms after it starts."""
    if sound is None:
        return speech
    lead = int(lead_ms * SR / 1000)
    out = np.zeros(max(len(sound), lead + len(speech)), np.float32)
    out[: len(sound)] += gain * sound
    out[lead : lead + len(speech)] += speech
    return out


def cue_messages(names: list[str]) -> list[tuple[float, dict]]:
    """A line's cues as (seconds after its first sample, message): its first
    expression is her face for the whole line; gestures and scenes play big, one
    after another; a later expression changes her face midway."""
    from .app import ATTACHED_GESTURE_S, ATTACHED_SCENE_S

    timeline: list[tuple[float, dict]] = []
    at = 0.0
    faces = [n for n in names if cues.BY_NAME[n]["kind"] == "expression"]
    for name in names:
        kind = cues.BY_NAME[name]["kind"]
        if kind == "scene":
            timeline.append((at, {"type": "activity", "value": name, "loops": 1}))
            at += ATTACHED_SCENE_S
        elif kind == "gesture":
            timeline.append((at, {"type": "reaction", "value": name, "big": True}))
            at += ATTACHED_GESTURE_S
    for k, name in enumerate(faces):
        timeline.append((0.0 if k == 0 else max(at, ATTACHED_GESTURE_S * k), {"type": "emotion", "value": name}))
    return sorted(timeline, key=lambda x: x[0])


def domain_messages(domain: dict | None) -> list[tuple[float, dict]]:
    """Her domain expansion on a line, as (seconds after its first sample, message):
    the summon's own two phases (the HUD draws them as the summon does), carrying
    the hold and the bubble. The part2 time matches sfx.DOMAIN_PART2_S, so the
    impact lands on the eye."""
    if not domain:
        return []
    extra = {"hold_ms": domain["hold_ms"], "bubble": domain["bubble"], "skit": True}
    return [(0.0, {"type": "summon", "phase": "start", **extra}), (sfx.DOMAIN_PART2_S, {"type": "summon", "phase": "part2", **extra})]


class Skits:
    """The skit player: one skit at a time, started and aborted by his hotkeys."""

    def __init__(self, core: "Core"):
        self.core = core
        self.task: asyncio.Task | None = None
        self.skit: Skit | None = None
        self.beat: Beat | None = None
        self._heard: asyncio.Future | None = None
        self._summon: asyncio.Future | None = None
        self._mic: tuple | None = None
        # when her last line's last sample was heard, and how long a play() takes
        # to be heard (the next pause is shortened by it, so the silence is exact)
        self._line_end: float | None = None
        self._lead = 0.0
        # the silence asked for before the next line (pause_after + pause_before)
        self._wanted = 0
        # the wake phrase that ended a wake beat ("hey", "adler", ...): it picks the entrance
        self.wake_phrase: str | None = None
        # her working state is up (a working beat) until her next line
        self._working = False
        # his turn ended while no beat was waiting yet (inside a working hold): kept
        # for the next wait beat, so he is never waited for twice
        self._bank: float | None = None
        self._banking = False
        # when his wake phrase ended (the intro's clock), and whether her first line
        # has been heard yet
        self._wake_at: float | None = None
        self._first_said = False
        self.gaps: list[tuple[int, float]] = []

    @property
    def active(self) -> bool:
        return self.task is not None and not self.task.done()

    @property
    def waiting(self) -> bool:
        return self._heard is not None and not self._heard.done()

    # ---- from the HUD (his hotkeys) ---------------------------------------------

    async def on_message(self, message: dict) -> None:
        from .app import DEV

        if message.get("_origin") != "hud" and not DEV:
            log.warning("skit %s from a %s refused (only his HUD, or a -Dev run)", message.get("action"), message.get("_origin"))
            return
        action = message.get("action")
        if action == "start":
            await self.start(message.get("name") or None)
        elif action == "abort":
            await self.abort("aborted (ctrl+alt+shift+x)")
        elif action == "heard" and DEV:
            # dev only: as if his voice had just finished (the wait without a mic)
            self.heard(float(message.get("seconds", 1.0)), message.get("said"))

    async def start(self, name: str | None = None) -> bool:
        try:
            skit = load(name, {e["name"] for e in self.core.entrances})
        except SkitError as error:
            log.error("skit not started: %s", error)
            await self.core.bridge.send({"type": "skit", "phase": "error", "error": str(error)})
            return False
        if self.active:
            await self.abort("started over")
        self.task = asyncio.create_task(self._run(skit))
        return True

    async def abort(self, why: str) -> None:
        task = self.task
        if task is None or task.done():
            return
        log.info("skit %s: %s", self.skit.name if self.skit else "?", why)
        task.cancel()
        await asyncio.wait([task], timeout=3.0)

    # ---- from the voice loop and core -------------------------------------------

    @property
    def wants_words(self) -> bool:
        """The beat waiting now is a wake beat: his words are checked for a wake phrase."""
        return self.waiting and self.beat is not None and self.beat.wake

    def heard(self, seconds: float, said: str | None = None) -> bool:
        """His voice finished (checked as his by the voice loop). True if a wait
        beat took it; otherwise it is ignored - nothing he says mid-skit does
        anything else."""
        if seconds * 1000 < WAIT_MIN_MS:
            log.info("skit: %.2f s of voice - too short to be his turn, still waiting", seconds)
            return False
        if not self.waiting:
            if self._banking:
                # inside a working hold: his turn has come early - the next wait has it
                self._bank = seconds
                log.info("skit: his voice (%.1f s) during her working state - kept for the next wait", seconds)
                return True
            log.info("skit: his voice (%.1f s) while no beat waits for it - ignored", seconds)
            return False
        assert self._heard is not None
        if self.beat is not None and self.beat.wake:
            from . import wake

            found = (wake.find(said or "") or wake.find_within(said or "")) if said else None
            if found is None:
                log.info("skit: %r is not a wake phrase - still waiting for 'Hey Irene' or 'Irene Adler'", said)
                return False
            self.wake_phrase = found.phrase
            log.info("skit: wake phrase %r (%s)", said, found.phrase)
        self._heard.set_result(seconds)
        return True

    def claim_summon(self) -> bool:
        """The HUD handed a summon back while a skit runs: the skit's own (its
        summon beat) - or a stray one (ctrl+alt+i mid-take), which is ignored
        rather than play an entrance and a greeting over the scene."""
        if self._summon is not None and not self._summon.done():
            self._summon.set_result(True)
        else:
            log.info("skit: a summon mid-skit that the skit didn't ask for - ignored")
        return True

    # ---- the run ----------------------------------------------------------------

    async def _run(self, skit: Skit) -> None:
        core = self.core
        self.skit = skit
        self.gaps = []
        self._line_end = None
        self._wake_at = None
        self._first_said = False
        self.wake_phrase = None
        self._working = False
        self._bank = None
        self._banking = False
        log.info("skit %s: start (%d beats, from %s%s)", skit.name, len(skit.beats), skit.path.name, ", hidden first" if skit.start_hidden else "")
        # whatever she was doing stops: a turn, an entrance, her voice
        if core._turn and not core._turn.done():
            core._turn.cancel()
        await core.on_summon_skip({})
        if core.speaker:
            core.speaker.stop()
        await core.bridge.send({"type": "skit", "phase": "start", "name": skit.name, "hide": skit.start_hidden})
        if skit.start_hidden and core.bridge.hud_connected:
            # put away first - and only then is his "Hey Irene" listened for: a
            # summon that overtook the hide used to be hidden again by it (her
            # intro played into a hidden window, and her z-order was dropped)
            deadline = time.monotonic() + HIDE_WAIT_S
            while getattr(core.voice, "visible", False) and time.monotonic() < deadline:
                await asyncio.sleep(0.02)
            log.info("skit %s: put away (%s)", skit.name, "hidden" if not getattr(core.voice, "visible", False) else f"still shown after {HIDE_WAIT_S:.1f} s")
        self._mic_on()
        loop = asyncio.get_running_loop()
        voice = core.speaker.voice if core.speaker else None
        lines = {i: b for i, b in enumerate(skit.beats) if b.who == "irene"}
        rendered: asyncio.Future = loop.run_in_executor(None, lambda: {i: render_line(voice, b) for i, b in lines.items()}) if voice else loop.create_future()
        if voice is None:
            rendered.set_result({})
        last_cue: str | None = None
        completed = False
        try:
            for n, beat in enumerate(skit.beats):
                self.beat = beat
                log.info("skit %s beat %d/%d: %s%s", skit.name, n + 1, len(skit.beats), beat.who, f" {beat.line!r}" if beat.line else f" ({beat.note})" if beat.note else "")
                await self._pause(beat.pause_before_ms, exact=beat.who == "irene")
                if beat.who == "wait_for_me":
                    await self._wait(beat)
                elif beat.who == "summon":
                    await self._end_working()
                    await self._summon_beat(beat)
                elif beat.who == "working":
                    nxt = next((b for b in skit.beats[n + 1 :] if b.who != "working"), None)
                    await self._working_beat(beat, nxt)
                else:
                    audio = (await rendered).get(n)
                    await self._end_working()
                    await self._say(n + 1, beat, audio)
                    last_cue = beat.cues[-1]
                after = skit.beats[n + 1] if n + 1 < len(skit.beats) else None
                await self._pause(beat.pause_after_ms, exact=bool(after and after.who == "irene" and not after.pause_before_ms), working=beat.working if beat.who != "working" else None)
            completed = True
            log.info("skit %s: done - pauses heard: %s", skit.name, ", ".join(f"{ms} ms -> {got:.0f} ms" for ms, got in self.gaps) or "none")
        finally:
            self._mic_off()
            self.beat = None
            if self._heard and not self._heard.done():
                self._heard.cancel()
            self._heard = None
            if not completed and core.speaker:
                core.speaker.stop()
            if last_cue:
                # her next real reply never opens on the face she ended on
                core.last_react = last_cue
            await core.bridge.send({"type": "tool", "name": "skit", "status": "done", "cue": None})
            await core.bridge.send({"type": "skit", "phase": "end", "name": skit.name, "completed": completed})
            await core.bridge.emotion("neutral")
            await core.bridge.state("listening")
            if not completed:
                log.info("skit %s: stopped - ready for another take (ctrl+alt+shift+k)", skit.name)

    def _mic_on(self) -> None:
        """While a skit runs: no barge-in (his words never stop her lines), and his
        turns end on the beat's silence, not the conversation's."""
        mic = self.core.voice.mic
        if mic is None:
            log.warning("skit: no microphone - the wait beats only end by the dev hook")
            return
        self._mic = (mic.barge_enabled, mic.endpointer.fixed_wait_s, mic.endpointer.max_utterance_s)
        mic.barge_enabled = False

    def _mic_off(self) -> None:
        mic = self.core.voice.mic
        if mic is None or self._mic is None:
            return
        mic.barge_enabled, mic.endpointer.fixed_wait_s, mic.endpointer.max_utterance_s = self._mic
        self._mic = None
        mic.endpointer.reset()

    async def _pause(self, ms: int, exact: bool = False, working: str | None = None) -> None:
        """Silence: nothing plays, nothing moves on its own. `exact`: her line comes
        straight after, so the time its play() takes to be heard comes off the wait."""
        if ms <= 0 and not working:
            return
        core = self.core
        if working:
            await core.bridge.state("thinking")
            await core.bridge.send({"type": "tool", "name": "skit", "status": "running", "cue": working})
        # the next line's play() takes `_lead` to be heard: the silence is exact
        wait = max(0.0, ms / 1000 - (self._lead if exact else 0.0))
        end = time.monotonic() + wait
        while True:
            # a long pause is not a freeze (the watchdog)
            core._progress_at = time.monotonic()
            left = end - time.monotonic()
            if left <= 0:
                break
            await asyncio.sleep(min(left, 1.0))
        if working:
            await core.bridge.send({"type": "tool", "name": "skit", "status": "done", "cue": None})
            await core.bridge.state("listening")

    async def _working_beat(self, beat: Beat, nxt: Beat | None) -> None:
        """Her working state, held at least hold_ms and on until her next line. His
        turn may start - and end - inside it: it is kept for the next wait."""
        core = self.core
        self._working = True
        self._bank = None
        self._banking = nxt is not None and nxt.who == "wait_for_me"
        mic = core.voice.mic
        if self._banking and mic is not None:
            # his turn, if it starts now, ends on the NEXT wait's silence
            mic.endpointer.fixed_wait_s = nxt.silence_ms / 1000
            mic.endpointer.max_utterance_s = nxt.max_ms / 1000
        await core.bridge.state("thinking")
        await core.bridge.send({"type": "tool", "name": "skit", "status": "running", "cue": beat.working})
        log.info("skit: working (%s), at least %d ms - and on while he talks", beat.working, beat.hold_ms)
        await self._pause(beat.hold_ms)

    async def _end_working(self) -> None:
        if not self._working:
            return
        self._working = False
        self._banking = False
        await self.core.bridge.send({"type": "tool", "name": "skit", "status": "done", "cue": None})
        await self.core.bridge.state("listening")

    async def _wait(self, beat: Beat) -> None:
        mic = self.core.voice.mic
        if mic is not None:
            mic.endpointer.fixed_wait_s = beat.silence_ms / 1000
            mic.endpointer.max_utterance_s = beat.max_ms / 1000
        self._heard = asyncio.get_running_loop().create_future()
        await self.core.bridge.send({"type": "skit", "phase": "waiting", "note": beat.note})
        t0 = time.monotonic()
        self._banking = False
        if self._bank is not None:
            # he already said it, during her working state
            self._heard.set_result(self._bank)
            self._bank = None
        while True:
            # waiting on him is not a freeze - least of all in her working state
            # ("thinking"), which the watchdog would otherwise reset after 15 s
            self.core._progress_at = time.monotonic()
            try:
                seconds = await asyncio.wait_for(asyncio.shield(self._heard), 1.0)
                break
            except asyncio.TimeoutError:
                continue
        self._heard = None
        log.info("skit: he spoke %.1f s (his turn ended after %d ms of quiet, %.1f s into the wait)", seconds, beat.silence_ms, time.monotonic() - t0)
        if self._wake_at is None:
            # the first thing he says is the wake: the intro's clock starts here
            self._wake_at = time.monotonic()
            self._stage("wake heard")
        # the face she holds through his turn stays; the next line's timing starts now
        self._line_end = None

    def _stage(self, what: str) -> None:
        """One stage of the skit's intro, timed from the end of his wake phrase -
        the order he can check in core.log: wake heard, window shown, boot start,
        boot end, entrance end, settled, first line starts."""
        at = (time.monotonic() - self._wake_at) * 1000 if self._wake_at is not None else 0.0
        log.info("skit intro: %-22s +%6.0f ms", what, at)

    async def _summon_beat(self, beat: Beat) -> None:
        """Her FULL introduction, as a real summon plays it - the window up, the 12 s
        boot, the entrance - and nothing after it until all of it has finished and
        she has settled to listening. No greeting: the skit's next line is hers."""
        core = self.core
        if self._wake_at is None:
            self._wake_at = time.monotonic()
        self._stage("summon asked")
        self._summon = asyncio.get_running_loop().create_future()
        if core.bridge.hud_connected:
            await core.bridge.send({"type": "summon_request", "by": "voice"})
            try:
                await asyncio.wait_for(asyncio.shield(self._summon), SUMMON_TIMEOUT_S)
                self._stage("window shown")
            except asyncio.TimeoutError:
                log.warning("skit: the HUD didn't hand the summon back in %.0f s - the intro plays anyway", SUMMON_TIMEOUT_S)
        else:
            log.warning("skit: no HUD - the intro plays with no window")
        self._summon = None
        await core.exit_dark("a skit summon")
        name = beat.adler if self.wake_phrase == "adler" else beat.entrance
        log.info("skit: summon - entrance %s%s, boot %s, music %s", name, " (he said Irene Adler)" if self.wake_phrase == "adler" else "",
                 "on" if beat.boot else "skipped", "on" if beat.music else "off")
        # his cursor goes for the introduction, as with every summon
        await core.bridge.send({"type": "intro_cursor", "hidden": True})
        scored = False
        try:
            if beat.boot:
                scored = beat.music and core._music_start()
                self._stage("boot start")
                await core._boot_only(scored)
                self._stage("boot end")
            else:
                # the HUD's boot-up and the panel's hold go at once: straight to her
                await core.bridge.send({"type": "boot_skip"})
                self._stage("boot skipped")
            entry = next((e for e in core.entrances if e["name"] == name), None)
            if entry is None:
                self._stage("no entrance")
            elif entry["name"] == "domain_expansion":
                await core.play_summon(entry["line"])
            else:
                await core.play_entrance(core.entrance_clips[entry["name"]], entry["line"])
            if entry is not None:
                core.picker.last = entry["name"]
                self._stage("entrance end")
            if scored:
                # the music goes, all of it, before she says a word
                core._music_fade("skit intro")
                await asyncio.sleep(core.music.cfg.fade_out_s)
                self._stage("music faded")
        finally:
            await core.bridge.send({"type": "intro_cursor", "hidden": False})
        # settled: her listening face, nothing still playing
        await core.bridge.emotion("neutral")
        await core.bridge.state("listening")
        while core.speaker is not None and getattr(core.speaker, "playing", lambda: False)():
            await asyncio.sleep(0.05)
        self._stage("settled (listening)")
        self._line_end = None

    async def _say(self, number: int, beat: Beat, audio: np.ndarray | None) -> None:
        """Her line as written, its cues on the first sample heard."""
        core = self.core
        loop = asyncio.get_running_loop()
        timeline = cue_messages(beat.cues)
        core.voice.heard_her(beat.line)
        await core.bridge.transcript("irene", beat.line)
        if audio is None or core.muted or core.speaker is None:
            for at, message in [*timeline, *domain_messages(beat.domain)]:
                loop.call_later(at, core.bridge.send_threadsafe, message)
            await asyncio.sleep(max(1.0, len(beat.line.split()) / 2.8))
            return
        sound = None
        if beat.sound:
            if beat.sound not in core._sounds:
                core._sounds[beat.sound] = sfx.render(beat.sound, np.random.default_rng(3))
            sound = core._sounds[beat.sound]
        clip = with_sound(audio, sound, beat.sound_gain, beat.sound_lead_ms)
        finished: asyncio.Future[bool] = loop.create_future()
        heard: dict[str, float] = {}

        first = self._wake_at is not None and not self._first_said
        self._first_said = True

        def on_start() -> None:
            heard["at"] = time.perf_counter()
            if first:
                loop.call_soon_threadsafe(self._stage, f"first line starts ({beat.line[:24]!r})")
            for at, message in timeline:
                if at <= 0:
                    core.bridge.send_threadsafe(message)
                else:
                    loop.call_soon_threadsafe(loop.call_later, at, core.bridge.send_threadsafe, message)
            for at, message in domain_messages(beat.domain):
                if at <= 0:
                    core.bridge.send_threadsafe(message)
                else:
                    loop.call_soon_threadsafe(loop.call_later, at, core.bridge.send_threadsafe, message)

        await core.bridge.state("speaking")
        from .tts import block_levels

        stamp = core.speaker.play(clip, block_levels(clip), marks=[(0.0, on_start)],
                                  done=lambda ok: loop.call_soon_threadsafe(lambda: finished.done() or finished.set_result(ok)))
        ok = await finished
        end = time.perf_counter()
        if "at" in heard:
            self._lead = max(0.0, min(0.3, heard["at"] - stamp))
            if self._line_end is not None:
                wanted = self._wanted + beat.pause_before_ms
                got = (heard["at"] - self._line_end) * 1000
                self.gaps.append((wanted, got))
                log.info("skit: silence before line %d: wanted %d ms, heard %.0f ms", number, wanted, got)
        log.info("skit: line %d %s (%.1f s, cues %s%s)", number, "played" if ok else "CUT OFF", len(clip) / SR, ", ".join(beat.cues), f", sound {beat.sound}" if beat.sound else "")
        self._line_end = end
        self._wanted = beat.pause_after_ms
        # her face holds the line's expression; the state goes back to listening
        await core.bridge.state("listening")
