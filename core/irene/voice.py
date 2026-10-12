"""Irene's voice engines, behind one interface: text in, 24 kHz float32 audio out.

  turbo   Chatterbox-Turbo (Resemble AI, MIT), cloned from her af_bella reference
          clip (core/assets/voice/af_bella_ref.wav). Expressive, understands
          [laugh] [sigh] [gasp] [chuckle] in the text. Doesn't stream: a sentence
          is synthesised whole, so speech is fed to it in short chunks.
  kokoro  Kokoro-82M, voice af_bella: the fallback. Loaded only if Turbo can't
          load, or when Turbo runs out of memory mid-conversation (then it stays).

Both are in-process, sharing one CUDA context with nothing else.

config/pronunciation.yaml is applied HERE, to everything any engine is ever asked
to say - live replies, the cached lead-ins, entrance lines, anything rendered
later - in the form the engine that will actually speak it understands: Kokoro
gets its phoneme override, Turbo (no phonemes) the respelling. It used to be
applied only in tts.Speaker.prepare(), so text that reached an engine any other
way (the "Mister Tri!" lead-in, rendered once and cached) was said "Try".
"""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Iterator

import numpy as np
from tools.localconfig import personal

log = logging.getLogger("irene.voice")

SAMPLE_RATE = 24000
KOKORO_VOICE = "af_bella"
REFERENCE = Path(__file__).resolve().parents[1] / "assets" / "voice" / "af_bella_ref.wav"
PRONUNCIATION = personal("pronunciation.yaml")
# the nonverbal tags Turbo performs; everything else only ever sees them stripped
TAGS = ("laugh", "sigh", "gasp", "chuckle")
_TAG = re.compile(r"\s*\[(?:" + "|".join(TAGS) + r")\]\s*", re.I)


def strip_tags(text: str) -> str:
    """Text without [laugh]-style tags - for display, and for Kokoro."""
    return re.sub(r"\s{2,}", " ", _TAG.sub(" ", text)).strip()


class Engine:
    name = "engine"
    #: whether it understands [laugh]-style tags
    tags = False
    #: whether `speed` changes anything
    speeds = False

    def synth(self, text: str, speed: float = 1.0) -> Iterator[np.ndarray]:
        raise NotImplementedError


class KokoroEngine(Engine):
    name = "kokoro"
    speeds = True

    def __init__(self) -> None:
        from kokoro import KPipeline

        self.pipeline = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
        for _ in self.pipeline("Ready.", voice=KOKORO_VOICE):
            pass

    def synth(self, text: str, speed: float = 1.0) -> Iterator[np.ndarray]:
        for _, _, audio in self.pipeline(strip_tags(text), voice=KOKORO_VOICE, speed=speed):
            yield np.asarray(audio, dtype=np.float32)


class TurboEngine(Engine):
    name = "turbo"
    tags = True

    def __init__(self, reference: Path = REFERENCE) -> None:
        from chatterbox.tts_turbo import ChatterboxTurboTTS

        self.model = ChatterboxTurboTTS.from_pretrained(device="cuda")
        # its loudness normalisation hands the tokenizer float64 (a crash on torch
        # 2.11); the reference clip is already level, so clone without it
        self.model.prepare_conditionals(str(reference), norm_loudness=False)
        self._lock = threading.Lock()
        self.synth_one("Ready.")  # CUDA kernels, before anyone is waiting

    def synth_one(self, text: str, temperature: float = 0.8, seed: int | None = None) -> np.ndarray:
        import torch

        with self._lock, torch.inference_mode():
            if seed is not None:
                # a skit's take (skit.py): the same delivery every time it renders
                torch.manual_seed(seed)
            wav = self.model.generate(text, temperature=temperature)
        return wav.squeeze().float().cpu().numpy()

    def synth(self, text: str, speed: float = 1.0) -> Iterator[np.ndarray]:
        text = text.strip()
        # a tag on its own is a sound, not a sentence: Turbo needs words around it
        if not strip_tags(text):
            text = f"{text} Hm."
        yield self.synth_one(text)


class Voice:
    """The live engine, falling back to Kokoro once and for good if Turbo fails."""

    def __init__(self, prefer: str = "turbo", pronunciation: Path = PRONUNCIATION) -> None:
        from . import pronounce

        # phoneme overrides for engines that read them (Kokoro), respellings for the rest
        self._rules = {True: pronounce.load_rules(pronunciation, phonemes=True), False: pronounce.load_rules(pronunciation, phonemes=False)}
        self.fallback: KokoroEngine | None = None
        self.engine: Engine
        if prefer == "turbo":
            try:
                self.engine = TurboEngine()
                log.info("voice: chatterbox-turbo, cloned from %s", REFERENCE.name)
                return
            except Exception as error:  # missing package, no GPU memory, a bad file
                log.error("chatterbox-turbo failed to load (%s: %s); falling back to kokoro", type(error).__name__, error)
        self.engine = self._kokoro()

    def _kokoro(self) -> KokoroEngine:
        if self.fallback is None:
            self.fallback = KokoroEngine()
            log.info("voice: kokoro %s", KOKORO_VOICE)
        return self.fallback

    @property
    def name(self) -> str:
        return self.engine.name

    def spoken(self, text: str, engine: "Engine | None" = None) -> str:
        """`text` as `engine` (the live one by default) must be given it, with his
        pronunciation map applied: phonemes for Kokoro, respellings for Turbo."""
        from . import pronounce

        engine = engine or self.engine
        return pronounce.apply(text, self._rules[not engine.tags])

    def synth(self, text: str, speed: float = 1.0) -> Iterator[np.ndarray]:
        from .levels import level_speech

        try:
            # every sentence at the same loudness (levels.py): quiet and loud lines sit together
            for chunk in self.engine.synth(self.spoken(text), speed):
                yield level_speech(chunk)
        except Exception as error:
            if self.engine.name == "kokoro":
                raise
            # out of GPU memory (gemma grew, an image call) or any other failure:
            # Kokoro from here on - she keeps talking
            log.error("chatterbox-turbo failed mid-speech (%s: %s); switching to kokoro", type(error).__name__, error)
            try:
                import torch

                torch.cuda.empty_cache()
            except Exception:
                pass
            self.engine = self._kokoro()
            yield from self.engine.synth(self.spoken(text), speed)

    def all(self, text: str, speed: float = 1.0) -> np.ndarray:
        chunks = list(self.synth(text, speed))
        return np.concatenate(chunks) if chunks else np.zeros(0, np.float32)

    def take(self, text: str, speed: float = 1.0, temperature: float = 0.8, seed: int = 1) -> np.ndarray:
        """One whole line, exactly these words, as a skit plays it (skit.py): Turbo
        at `temperature` (lower is flatter, steadier) from a fixed `seed`, so a take
        renders the same every time; Kokoro at `speed` (Turbo has no speed)."""
        from .levels import level_speech

        if isinstance(self.engine, TurboEngine):
            text = self.spoken(text).strip()
            return level_speech(self.engine.synth_one(text if strip_tags(text) else f"{text} Hm.", temperature, seed))
        return self.all(text, speed)
