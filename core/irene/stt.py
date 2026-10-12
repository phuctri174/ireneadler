"""Speech to text: faster-whisper large-v3-turbo on the GPU, loaded on first use.

float16 only - int8 crashes on sm_120 (the RTX 5060 Ti), so any other compute
type is refused rather than tried. The weights are local (config/voice.yaml
stt.model_dir, fetched once at setup); nothing is downloaded at runtime.

His vocabulary (config/vocabulary.yaml) goes in as hotwords, so "Tri" is not
"Tree" and "kote" is not "coat". Every result carries how sure Whisper was, so
a guess can be refused ("sorry, say that again?") instead of acted on.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from tools.localconfig import personal

log = logging.getLogger("irene.stt")

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "voice.yaml"
VOCABULARY = personal("vocabulary.yaml")
SAMPLE_RATE = 16000


def settings() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


# Words Whisper should expect only for a while (a chess game's moves): they go in
# FRONT of the vocabulary - hotwords are cut at 223 tokens from the start, and the
# static list nearly fills that - so his corpus tail is what drops out meanwhile.
_CONTEXT: dict[str, tuple[str, ...]] = {}


def context_terms(name: str, terms: list[str] | tuple[str, ...] | None) -> None:
    """Expect `terms` until called again with None (`name`: who asked, e.g. "chess")."""
    if terms:
        _CONTEXT[name] = tuple(terms)
    else:
        _CONTEXT.pop(name, None)
    log.info("context hotwords %s: %s", name, ", ".join(terms) if terms else "off")


def vocabulary(path: Path = VOCABULARY) -> list[str]:
    """Every term in the vocabulary file, in order, without repeats."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    seen: list[str] = []
    for terms in data.values():
        for term in terms or []:
            if isinstance(term, str) and term.strip() and term not in seen:
                seen.append(term.strip())
    return seen


@dataclass(frozen=True)
class Heard:
    text: str
    # mean log-probability of the words; closer to 0 is surer
    avg_logprob: float
    # Whisper's belief that there was no speech at all
    no_speech_prob: float
    seconds: float
    # how long transcription took
    ms: float

    def confident(self, min_avg_logprob: float, max_no_speech_prob: float) -> bool:
        return bool(self.text.strip()) and self.avg_logprob >= min_avg_logprob and self.no_speech_prob <= max_no_speech_prob

    @property
    def english(self) -> bool:
        return english_like(self.text)

    @property
    def hallucinated(self) -> bool:
        """Whisper's stock inventions on noise ("Thank you.", "Outro Music") - heard
        from his room, live, with nobody talking to her."""
        return hallucination(self.text)


# What Whisper writes when there is only noise, music or a murmur: learned from
# its training captions, never what he said to her. Matched whole, lower case,
# without punctuation.
_HALLUCINATIONS = {
    "thank you", "thank you very much", "thanks for watching", "thanks for watching everyone",
    "thank you for watching", "outro music", "music", "intro music", "you", "bye", "i love you",
    "subtitles by the amara org community", "please subscribe", "applause", "laughter",
    "so", "okay", "oh", "hmm", "i'm not sure what i'm doing",
}


def hallucination(text: str) -> bool:
    words = " ".join(re.findall(r"[a-z']+", (text or "").lower()))
    return words in _HALLUCINATIONS


def english_like(text: str) -> bool:
    """Whether a transcript reads as English. Whisper, told the language is English,
    still writes other people's Vietnamese in the room as Vietnamese; a transcript
    that is mostly accented letters is not him talking to her."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    plain = sum(1 for c in letters if c.isascii())
    return plain / len(letters) >= 0.9


class Transcriber:
    """faster-whisper, loaded lazily and shared: one model for wake phrases, his
    turns and the corpus checks. Thread-safe - calls are serialised."""

    def __init__(self, config: dict | None = None):
        stt = (config or settings())["stt"]
        if stt.get("compute_type", "float16") != "float16":
            raise ValueError("faster-whisper must run float16 on sm_120 - int8 crashes it")
        self.model_dir = ROOT / "core" / stt["model_dir"]
        self.language = stt.get("language", "en")
        self.beam_size = int(stt.get("beam_size", 3))
        self.min_avg_logprob = float(stt.get("min_avg_logprob", -0.85))
        self.max_no_speech_prob = float(stt.get("max_no_speech_prob", 0.6))
        terms = vocabulary()
        self.hotwords = " ".join(terms)
        # a short prompt: a long list of terms gets echoed back on near-silence
        self.prompt = "Hey Irene. Mister Tri."
        self._model = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self):
        with self._lock:
            if self._model is None:
                import torch  # noqa: F401  - its CUDA runtime DLLs are what ctranslate2 loads on Windows
                from faster_whisper import WhisperModel

                started = time.perf_counter()
                self._model = WhisperModel(str(self.model_dir), device="cuda", compute_type="float16", local_files_only=True)
                # the first call pays for CUDA kernels (~10 s): pay it now, not on his first sentence
                list(self._model.transcribe(np.zeros(SAMPLE_RATE // 2, np.float32), language=self.language, beam_size=1)[0])
                log.info("whisper large-v3-turbo float16 ready in %.1fs", time.perf_counter() - started)
            return self._model

    def transcribe(self, audio: np.ndarray, beam_size: int | None = None, prompt: bool = True) -> Heard:
        """16 kHz mono float32 -> what he said."""
        model = self.load()
        started = time.perf_counter()
        with self._lock:
            segments, _info = model.transcribe(
                audio.astype(np.float32),
                language=self.language,
                beam_size=beam_size or self.beam_size,
                hotwords=" ".join([*(w for terms in _CONTEXT.values() for w in terms), self.hotwords]),
                initial_prompt=self.prompt if prompt else None,
                condition_on_previous_text=False,
                vad_filter=False,
                without_timestamps=True,
            )
            segments = list(segments)
        ms = (time.perf_counter() - started) * 1000
        return heard_from(segments, len(audio) / SAMPLE_RATE, ms)

    def confident(self, heard: Heard) -> bool:
        return heard.confident(self.min_avg_logprob, self.max_no_speech_prob)


def heard_from(segments, seconds: float, ms: float) -> Heard:
    """Whisper's segments -> one Heard: the words joined, confidence weighted by
    length, and the no-speech belief of the surest segment."""
    text = " ".join(s.text.strip() for s in segments).strip()
    if not segments:
        return Heard("", -10.0, 1.0, seconds, ms)
    weights = [max(1, len(s.text.split())) for s in segments]
    avg = sum(s.avg_logprob * w for s, w in zip(segments, weights)) / sum(weights)
    return Heard(text, float(avg), float(min(s.no_speech_prob for s in segments)), seconds, ms)
