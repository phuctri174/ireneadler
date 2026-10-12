"""Is it him? A voiceprint check on every utterance before it can become a turn.

ECAPA-TDNN speaker embeddings (SpeechBrain spkrec-ecapa-voxceleb, vendored in
core/models/ecapa-voxceleb - never fetched at runtime). His voiceprint is the mean
embedding of his corpus recordings (core/voice_data/corpus/*/take*.wav, the
training split only - the held-out sentences stay untouched), cached in
core/data/voiceprint.npz and rebuilt when the corpus grows.

Songs, videos, people in the room and her own voice through the speakers all score
far below him: nothing under the threshold ever reaches Whisper's words, the
barge-in check or the LLM. This is the primary defence; the text echo match in
voice_loop.py stays only as a second line.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import numpy as np

log = logging.getLogger("irene.speaker")

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "core" / "models" / "ecapa-voxceleb"
CORPUS = ROOT / "core" / "voice_data" / "corpus"
PRINT = ROOT / "core" / "data" / "voiceprint.npz"
EMBEDDINGS = ROOT / "core" / "data" / "voice_embeddings.npz"
TURNS = ROOT / "core" / "voice_data" / "turns"
# a live turn the corpus print scores this high is his (enrols the live print)
LIVE_SEED = 0.5
SAMPLE_RATE = 16000
# shorter than this, an embedding is noise: scored on what there is, but a very
# short clip (a cough, "yes") is judged by the newest longer clip around it
MIN_S = 0.5


def corpus_takes(split: str | None = "train") -> list[Path]:
    """His recorded takes - the training split by default (config/corpus.yaml)."""
    from irene.corpus import load_sentences

    wanted = {s["id"] for s in load_sentences() if split is None or s.get("split", "train") == split}
    return sorted(p for p in CORPUS.glob("*/take*.wav") if p.parent.name in wanted)


class Verifier:
    """Load lazily, embed, score against his voiceprint. Thread-safe."""

    def __init__(self, threshold: float = 0.45, device: str | None = None):
        self.threshold = float(threshold)
        self.device = device
        self._model = None
        self._print: np.ndarray | None = None
        self._live: np.ndarray | None = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return (MODEL_DIR / "embedding_model.ckpt").exists()

    @property
    def enrolled(self) -> bool:
        return self._print is not None

    def load(self):
        with self._lock:
            if self._model is None:
                os.environ.setdefault("HF_HUB_OFFLINE", "1")
                import torch
                from speechbrain.inference.speaker import EncoderClassifier

                device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
                started = time.perf_counter()
                # the vendored hyperparams name the hub repo: point them at the local copy
                self._model = EncoderClassifier.from_hparams(
                    source=str(MODEL_DIR), savedir=str(MODEL_DIR), run_opts={"device": device},
                    overrides={"pretrained_path": MODEL_DIR.as_posix()},
                )
                log.info("speaker model (ECAPA) ready on %s in %.1fs", device, time.perf_counter() - started)
            return self._model

    def embed(self, audio: np.ndarray) -> np.ndarray:
        """16 kHz mono float32 -> a unit-length 192-d embedding."""
        import torch

        model = self.load()
        wav = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32)).unsqueeze(0)
        with self._lock, torch.inference_mode():
            e = model.encode_batch(wav.to(model.device)).squeeze().float().cpu().numpy()
        return e / (np.linalg.norm(e) + 1e-9)

    def enrol(self, takes: list[Path] | None = None, force: bool = False) -> int:
        """His voiceprints (cached; rebuilt when the recordings change): one from his
        corpus takes, close to the mic; one from his live turns - the mic across the
        room, through the echo canceller, which his corpus never sounds like (his
        live "Hey Irene" scored 0.2-0.5 against the corpus alone, his takes 0.55+).
        A live turn joins only if the corpus print is already sure it is him."""
        takes = corpus_takes() if takes is None else takes
        if not takes:
            log.warning("speaker check: no corpus recordings to enrol from - every voice passes")
            return 0
        turns = sorted(TURNS.glob("*/*.wav"))
        stamp = f"{len(takes)}:{max(p.stat().st_mtime for p in takes):.0f}:{len(turns)}"
        if not force and PRINT.exists():
            cached = np.load(PRINT, allow_pickle=False)
            if str(cached["stamp"]) == stamp:
                self._print, self._live = cached["print"], cached["live"]
                log.info("speaker check: his voiceprints from %d takes (cached)", len(takes))
                return len(takes)
        started = time.perf_counter()
        corpus = self._embed_all(takes)
        self._print = _unit(corpus.mean(axis=0))
        self._live = np.zeros_like(self._print)
        live = self._embed_all(turns) if turns else np.zeros((0, len(self._print)))
        if len(live):
            mine = live @ self._print >= LIVE_SEED
            if mine.sum() >= 5:
                self._live = _unit(live[mine].mean(axis=0))
                # once more with the live print: his far-from-the-mic turns join it
                mine = np.maximum(live @ self._print, live @ self._live) >= LIVE_SEED
                self._live = _unit(live[mine].mean(axis=0))
            log.info("speaker check: %d of %d live turns are his", int(mine.sum()), len(live))
        PRINT.parent.mkdir(parents=True, exist_ok=True)
        np.savez(PRINT, print=self._print, live=self._live, stamp=np.array(stamp))
        log.info("speaker check: enrolled his voiceprints from %d takes in %.1fs", len(corpus), time.perf_counter() - started)
        return len(corpus)

    def _embed_all(self, paths: list[Path]) -> np.ndarray:
        import soundfile as sf

        # every clip is embedded once, ever (a new turn each launch must not mean
        # re-reading hundreds of them)
        cache: dict[str, np.ndarray] = {}
        if EMBEDDINGS.exists():
            stored = np.load(EMBEDDINGS, allow_pickle=False)
            cache = dict(zip(stored["names"].tolist(), stored["embeddings"]))
        out, added = [], 0
        for path in paths:
            key = f"{path.relative_to(ROOT).as_posix()}:{path.stat().st_size}"
            if key not in cache:
                audio, rate = sf.read(path, dtype="float32", always_2d=True)
                audio = audio.mean(axis=1)
                if rate != SAMPLE_RATE:
                    audio = _resample(audio, rate)
                if len(audio) < MIN_S * SAMPLE_RATE:
                    continue
                cache[key] = self.embed(audio)
                added += 1
            out.append(cache[key])
        if added:
            EMBEDDINGS.parent.mkdir(parents=True, exist_ok=True)
            np.savez(EMBEDDINGS, names=np.array(list(cache)), embeddings=np.array(list(cache.values())))
        return np.array(out)

    def similarity(self, e: np.ndarray) -> float:
        return float(max(e @ self._print, e @ self._live))

    def score(self, audio: np.ndarray) -> float:
        """Cosine similarity to his voiceprints (1.0 = him exactly). The best of the
        whole clip and its newest 2 s: a barge-in clip starts with her echo."""
        if self._print is None:
            return 1.0
        scores = [self.similarity(self.embed(audio))]
        if len(audio) > 3 * SAMPLE_RATE:
            scores.append(self.similarity(self.embed(audio[-2 * SAMPLE_RATE:])))
        return max(scores)

    def is_him(self, audio: np.ndarray) -> tuple[bool, float]:
        if self._print is None or audio is None or len(audio) == 0:
            return True, 1.0
        s = self.score(audio)
        return s >= self.threshold, s


def _unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-9)


def _resample(audio: np.ndarray, rate: int) -> np.ndarray:
    n = int(round(len(audio) * SAMPLE_RATE / rate))
    return np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
