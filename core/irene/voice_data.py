"""His voice, kept for later training: every voice turn and every correction.

core/voice_data/ (gitignored, never leaves the machine):
  turns/<YYYY-MM-DD>/<id>.wav    16 kHz mono, what the mic heard for the turn
  turns/<YYYY-MM-DD>/<id>.json   what Whisper heard, how sure, what happened
  corrections.jsonl              {id, heard, corrected, how, at}
  corpus/                        the read-aloud corpus (corpus.py)

A correction is what he meant when Whisper got it wrong. Two ways to give one,
both automatic: typing it in the command bar within a minute of the voice turn
(close enough to the transcript to be the same sentence), or saying "no, I said
..." right after.
"""
from __future__ import annotations

import difflib
import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "voice_data"
SAMPLE_RATE = 16000
CORRECTION_WINDOW_S = 60.0
# "no, I said X", "I said X, not Y", "I meant X"
_SPOKEN_FIX = re.compile(r"^\W*(?:no\W+)?(?:i said|i meant|what i said was)\W+(.+?)(?:\W+not\W+.+)?\W*$", re.I)


def similarity(a: str, b: str) -> float:
    words = lambda s: re.findall(r"[a-z0-9']+", s.lower())  # noqa: E731
    return difflib.SequenceMatcher(None, words(a), words(b)).ratio()


@dataclass
class Turn:
    id: str
    heard: str
    at: float


class VoiceData:
    def __init__(self, directory: Path = DIR, enabled: bool = True):
        self.dir = directory
        self.enabled = enabled
        self.last: Turn | None = None

    def save_turn(self, audio: np.ndarray, heard: str, meta: dict) -> str | None:
        """One voice turn: its audio and what was heard. Returns its id."""
        if not self.enabled:
            return None
        stamp = time.localtime()
        folder = self.dir / "turns" / time.strftime("%Y-%m-%d", stamp)
        folder.mkdir(parents=True, exist_ok=True)
        turn_id = time.strftime("%H%M%S", stamp) + "-" + uuid.uuid4().hex[:6]
        sf.write(folder / f"{turn_id}.wav", audio.astype(np.float32), SAMPLE_RATE, subtype="PCM_16")
        record = {"id": turn_id, "heard": heard, "at": time.strftime("%Y-%m-%d %H:%M:%S", stamp), **meta}
        (folder / f"{turn_id}.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
        self.last = Turn(turn_id, heard, time.monotonic())
        return turn_id

    def correction_for(self, text: str, how: str, now: float | None = None) -> str | None:
        """If `text` corrects the last voice turn, store it and return the corrected
        words. how: "typed" (the whole sentence, retyped) or "spoken" ("no, I said X")."""
        last = self.last
        if not self.enabled or last is None or (now or time.monotonic()) - last.at > CORRECTION_WINDOW_S:
            return None
        if how == "spoken":
            m = _SPOKEN_FIX.match(text or "")
            if not m:
                return None
            corrected = m.group(1).strip()
        else:
            corrected = (text or "").strip()
            # the same sentence, retyped with fixes - not a new command, not identical
            if corrected.lower() == last.heard.strip().lower() or similarity(corrected, last.heard) < 0.5:
                return None
        self.dir.mkdir(parents=True, exist_ok=True)
        with (self.dir / "corrections.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"id": last.id, "heard": last.heard, "corrected": corrected, "how": how, "at": time.strftime("%Y-%m-%d %H:%M:%S")}) + "\n")
        self.last = None
        return corrected
