"""The read-aloud voice corpus, recorded in the HUD (Ctrl+Alt+Shift+R).

Same pattern as the gesture captures: a hotkey starts it, Irene guides him by
voice, the HUD shows the sentence big enough to read from a metre away with its
progress ("12 / 200"), a live mic meter and the take ("take 2 of 3"). He reads;
the end of his reading is heard (VAD, and Whisper matching the words to the
sentence, which ends a take quickly instead of after 3 s of silence); the take is
checked, saved, and the next one comes up. No keys - Space redoes the last take,
Escape stops.

A take is refused, with a word from her, when it is too quiet, clipped, too short
or Whisper's transcript is far from the sentence.

core/voice_data/corpus/ (local only):
  <sentence id>/take1.wav take2.wav take3.wav   16 kHz mono, one file per take
  <sentence id>/take1.json ...                  what Whisper heard, level, WER
  sessions.jsonl                                one line per session: when, how many
Progress is the files themselves, so it resumes across sessions and sessions
accumulate. config/corpus.yaml marks every 5th sentence `split: test`: recorded
the same way, never trained on (scripts/voice_wer.py measures on it).
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import soundfile as sf
import yaml

from . import react as cues
from .listen import SAMPLE_RATE, Event
from .wer import wer

if TYPE_CHECKING:
    from .app import Core

log = logging.getLogger("irene.corpus")

ROOT = Path(__file__).resolve().parents[2]
SENTENCES = ROOT / "config" / "corpus.yaml"
DIR = ROOT / "core" / "voice_data" / "corpus"
TAKES = 3
# a take whose transcript is this far from the sentence is read again
MAX_WER = 0.4
# a take is over once Whisper hears the sentence this closely
DONE_WER = 0.2

ENCOURAGE = [
    "Nice.", "Good.", "Lovely.", "Perfect.", "Got it.", "That's the one.", "Great, keep going.",
    "Smooth.", "Clear as a bell.", "Very nice.", "You're good at this.", "On a roll, sir.",
]
MILESTONE = "That's {n} sentences done. {cheer}"
CHEERS = ["Look at you go!", "Halfway to a voice I'll never mishear.", "I can hear you better already.", "Keep it coming!"]


def load_sentences(path: Path = SENTENCES) -> list[dict]:
    items = yaml.safe_load(path.read_text(encoding="utf-8"))["sentences"]
    ids = [s["id"] for s in items]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"{path}: duplicate sentence ids")
    return items


@dataclass(frozen=True)
class Check:
    ok: bool
    reason: str  # "" when ok
    heard: str
    wer: float
    rms: float
    peak: float
    clipped: float


def check_take(audio: np.ndarray, target: str, heard: str) -> Check:
    """Is this take worth keeping? Level, clipping, length, and the words."""
    rms = float(np.sqrt(np.mean(audio * audio))) if len(audio) else 0.0
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    clipped = float(np.mean(np.abs(audio) >= 0.99)) if len(audio) else 0.0
    error = wer(target, heard)
    if len(audio) < 0.5 * SAMPLE_RATE:
        reason = "short"
    elif peak < 0.05 or rms < 0.008:
        reason = "quiet"
    elif clipped > 0.001:
        reason = "clipped"
    elif error > MAX_WER:
        reason = "words"
    else:
        reason = ""
    return Check(not reason, reason, heard, error, rms, peak, clipped)


REDO_LINES = {
    "short": "That was cut short - once more, the whole sentence.",
    "quiet": "That was a bit quiet. Come a little closer and read it again?",
    "clipped": "That one clipped - a touch softer, please.",
    "words": "I heard something a bit different. Read it once more?",
}


class Progress:
    """What has been recorded, read from the files - so it survives anything."""

    def __init__(self, sentences: list[dict], directory: Path = DIR):
        self.sentences = sentences
        self.dir = directory

    def takes(self, sentence_id: str) -> int:
        folder = self.dir / sentence_id
        return sum(1 for k in range(1, TAKES + 1) if (folder / f"take{k}.wav").exists())

    def done(self) -> int:
        return sum(1 for s in self.sentences if self.takes(s["id"]) >= TAKES)

    def next(self) -> tuple[int, dict, int] | None:
        """(index, sentence, take number) of the next take to record, or None."""
        for index, sentence in enumerate(self.sentences):
            have = self.takes(sentence["id"])
            if have < TAKES:
                return index, sentence, have + 1
        return None

    def save(self, sentence: dict, take: int, audio: np.ndarray, check: Check, session: str) -> Path:
        folder = self.dir / sentence["id"]
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"take{take}.wav"
        sf.write(path, audio.astype(np.float32), SAMPLE_RATE, subtype="PCM_16")
        meta = {
            "id": sentence["id"], "take": take, "text": sentence["text"], "split": sentence.get("split", "train"),
            "topic": sentence.get("topic"), "heard": check.heard, "wer": round(check.wer, 3), "rms": round(check.rms, 4),
            "peak": round(check.peak, 3), "seconds": round(len(audio) / SAMPLE_RATE, 2), "session": session,
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        (folder / f"take{take}.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        return path

    def undo_last(self, sentence_id: str) -> int | None:
        """Delete the newest take of a sentence; returns its number."""
        have = self.takes(sentence_id)
        if have == 0:
            return None
        for suffix in ("wav", "json"):
            (self.dir / sentence_id / f"take{have}.{suffix}").unlink(missing_ok=True)
        return have


class Corpus:
    """One recording session at a time, driven by mic events (voice_loop.py routes
    them here while a session is active) and the HUD's keys."""

    def __init__(self, core: "Core", sentences: list[dict] | None = None, directory: Path = DIR):
        self.core = core
        self.sentences = sentences if sentences is not None else load_sentences()
        self.progress = Progress(self.sentences, directory)
        self.active = False
        self.session = ""
        self.recorded = 0
        self.current: tuple[int, dict, int] | None = None
        self._last_saved: str | None = None
        self._busy = False
        self._rng = random.Random()
        self._encouraged: str | None = None

    # ---- HUD -------------------------------------------------------------------

    async def on_message(self, message: dict) -> None:
        action = message.get("action")
        if action == "start":
            await self.start()
        elif action == "redo":
            await self.redo()
        elif action == "stop":
            await self.stop()

    async def _show(self, phase: str, **extra) -> None:
        payload = {"type": "corpus", "phase": phase, "done": self.progress.done(), "total": len(self.sentences)}
        if self.current:
            index, sentence, take = self.current
            payload.update({"index": index + 1, "id": sentence["id"], "text": sentence["text"], "take": take, "takes": TAKES, "split": sentence.get("split", "train")})
        payload.update(extra)
        await self.core.bridge.send(payload)

    async def _say(self, line: str, cue: str | None = None) -> None:
        react = cues.resolve(cue) if cue else cues.fallback(line, avoid=self.core.last_react)
        await self.core.say(line, react=react)

    # ---- the session -----------------------------------------------------------

    async def start(self) -> None:
        if self.active:
            return
        voice = self.core.voice
        if not voice.available:
            await self.core.bridge.send({"type": "corpus", "phase": "no_mic"})
            await self.core.bridge.reaction("noMic")
            return
        self.active = True
        self.session = time.strftime("%Y-%m-%dT%H-%M-%S")
        self.recorded = 0
        self.current = self.progress.next()
        if self.current is None:
            await self._show("complete")
            await self._say("Every sentence is recorded already - three times each. We're done!", "proud")
            self.active = False
            return
        # Whisper checks every take: load it now, while she explains
        asyncio.get_running_loop().run_in_executor(None, voice.stt.load)
        done = self.progress.done()
        await self._show("take")
        if done == 0:
            intro = ("Voice practice! Read each sentence the way you'd normally say it - three times each. "
                     "I'll move on by myself when you finish. Space redoes a take, Escape stops.")
        else:
            intro = f"Welcome back. {done} of {len(self.sentences)} done - let's pick up where we left off."
        await self._say(intro, "excitedBounce" if done == 0 else "happy")
        await self._show("ready")

    async def stop(self, spoken: bool = True) -> None:
        if not self.active:
            return
        self.active = False
        self._log_session()
        await self._show("stopped")
        if spoken:
            await self._say(f"Saved. {self.recorded} takes this time, {self.progress.done()} sentences done in all.", "thumbsUp")

    def _log_session(self) -> None:
        self.progress.dir.mkdir(parents=True, exist_ok=True)
        with (self.progress.dir / "sessions.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"session": self.session, "ended": time.strftime("%Y-%m-%d %H:%M:%S"), "takes": self.recorded, "sentences_done": self.progress.done()}) + "\n")

    async def redo(self) -> None:
        """Space: throw away the last take and record it again."""
        if not self.active:
            return
        voice = self.core.voice
        if voice.mic:
            voice.mic.endpointer.reset()
        if self._last_saved:
            undone = self.progress.undo_last(self._last_saved)
            self._last_saved = None
            self.recorded = max(0, self.recorded - 1)
            log.info("redo: take %s of %s removed", undone, self.current)
        self.current = self.progress.next()
        await self._show("take", note="redo")
        await self._say(self._rng.choice(["Sure, again.", "Once more.", "Again - take your time."]), "thumbsUp")
        await self._show("ready")

    async def on_event(self, event: Event) -> None:
        """Mic events while a session is active."""
        if not self.active or self.current is None:
            return
        voice = self.core.voice
        if event.kind == "speech":
            await self._show("recording")
        elif event.kind == "silence":
            await self._show("recording", remainingMs=round(event.remaining * 1000), totalMs=round(event.total * 1000))
        elif event.kind == "check" and event.audio is not None and voice.stt.loaded:
            target = self.current[1]["text"]
            heard = await asyncio.get_running_loop().run_in_executor(None, lambda: voice.stt.transcribe(event.audio, beam_size=1, prompt=False))
            if voice.mic:
                voice.mic.endpointer.verdict(wer(target, heard.text) <= DONE_WER, event.generation)
        elif event.kind == "end" and event.audio is not None and not self._busy:
            self._busy = True
            try:
                await self._take(event.audio)
            finally:
                self._busy = False

    async def _take(self, audio: np.ndarray) -> None:
        voice = self.core.voice
        index, sentence, take = self.current  # type: ignore[misc]
        await self._show("checking")
        heard = await asyncio.get_running_loop().run_in_executor(None, lambda: voice.stt.transcribe(audio, prompt=False))
        check = check_take(audio, sentence["text"], heard.text)
        log.info("corpus %s take %d: %s (wer %.2f, heard %r)", sentence["id"], take, check.reason or "ok", check.wer, heard.text)
        if not check.ok:
            await self._show("redo", reason=check.reason, heard=heard.text)
            await self._say(REDO_LINES[check.reason], "sheepish" if check.reason == "words" else "concerned")
            await self._show("ready")
            return
        self.progress.save(sentence, take, audio, check, self.session)
        self._last_saved = sentence["id"]
        self.recorded += 1
        await self._show("saved", heard=heard.text)
        self.current = self.progress.next()
        if self.current is None:
            self.active = False
            self._log_session()
            await self._show("complete")
            await self._say("That's all of them - every sentence, three times. Thank you, sir!", "excitedBounce")
            return
        finished_sentence = take == TAKES
        done = self.progress.done()
        await self._show("take")
        if finished_sentence and done % 25 == 0:
            await self._say(MILESTONE.format(n=done, cheer=self._rng.choice(CHEERS)), "starryEyed")
        elif finished_sentence and self._rng.random() < 0.5:
            line = self._rng.choice([e for e in ENCOURAGE if e != self._encouraged])
            self._encouraged = line
            await self._say(line, self._rng.choice(["happy", "thumbsUp", "proud", "wink", "peace", "headTilt"]))
        await self._show("ready")
