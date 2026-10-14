"""Lecture capture: what the PC plays (a lecture, a meeting), written down as it goes.

    loopback (WASAPI, the output device) -> her-voice gate -> Chunker -> queue
        -> Whisper (the SAME model as his mic, transcribe_background) -> transcript.jsonl

A separate pipeline from his microphone, end to end. Nothing here touches the
speaker check (speaker_id.py): the lecturer is not him, and the gate would throw
away the whole lecture. No wake phrases, no echo canceller, no endpointer - his
mic keeps all of those, untouched, running beside it.

  - Off until he starts it (voice, or Ctrl+Alt+Shift+L); never automatic.
  - Transcript text only. Audio lives in memory for one chunk (<= 30 s) and is
    never written anywhere.
  - Every chunk's text is appended to core/data/lectures/<session>/transcript.jsonl
    and flushed to disk (fsync) at once: a crash loses at most the chunk in flight.
  - Her own voice plays through the same speakers: blocks captured while she is
    audible are zeroed (the timeline stays true; her words never become the lecture).
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
import yaml

from . import stt

log = logging.getLogger("irene.lecture")

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "lecture.yaml"
STORE = ROOT / "core" / "data" / "lectures"
RATE = 16000
BLOCK_S = 0.5
# what a looping or invented segment looks like (stt.Segment)
MAX_COMPRESSION = 2.4
NO_SPEECH = 0.6
LOW_LOGPROB = -1.0
PROMPT_CHARS = 200


def settings() -> dict:
    try:
        return yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    except OSError:
        return {}


# ---- cutting the stream into chunks ------------------------------------------------------


@dataclass
class Chunk:
    start_s: float  # from the session's start
    audio: np.ndarray


class Chunker:
    """Blocks in, chunks out: each between min_s and max_s long, cut at the quietest
    moment in that range (a pause between sentences), so no word is cut in half
    when it can be helped. Pure - tested without a sound card."""

    def __init__(self, min_s: float = 18.0, max_s: float = 30.0, rate: int = RATE):
        self.min = int(min_s * rate)
        self.max = int(max_s * rate)
        self.rate = rate
        self._buf: list[np.ndarray] = []
        self._len = 0
        self._start = 0  # samples from the session start to the buffer's first sample

    def feed(self, block: np.ndarray) -> list[Chunk]:
        self._buf.append(block.astype(np.float32))
        self._len += len(block)
        out = []
        while self._len >= self.max:
            audio = np.concatenate(self._buf)
            cut = self._quietest(audio)
            out.append(Chunk(self._start / self.rate, audio[:cut]))
            rest = audio[cut:]
            self._start += cut
            self._buf, self._len = [rest], len(rest)
        return out

    def flush(self) -> Chunk | None:
        if not self._len:
            return None
        audio = np.concatenate(self._buf)
        chunk = Chunk(self._start / self.rate, audio)
        self._start += len(audio)
        self._buf, self._len = [], 0
        return chunk

    def _quietest(self, audio: np.ndarray) -> int:
        """The middle of the quietest 0.3 s between min and max."""
        win = int(0.3 * self.rate)
        hop = int(0.05 * self.rate)
        best, at = None, self.max
        for i in range(self.min, min(self.max, len(audio)) - win + 1, hop):
            e = float(np.mean(audio[i:i + win] ** 2))
            if best is None or e < best:
                best, at = e, i + win // 2
        return at


# ---- what Whisper wrote, cleaned ------------------------------------------------------------


def clean(segments: list[stt.Segment], offset_s: float) -> list[dict]:
    """Whisper's segments -> transcript lines (session time), without its inventions:
    stock captions on noise ("Thank you."), loops (very compressible text) and
    segments it was itself sure were not speech."""
    out = []
    for s in segments:
        text = " ".join(s.text.split())
        if not any(c.isalpha() for c in text) or stt.hallucination(text):
            continue
        if s.compression_ratio > MAX_COMPRESSION:
            continue
        if s.no_speech_prob > NO_SPEECH and s.avg_logprob < LOW_LOGPROB:
            continue
        out.append({"t": round(offset_s + s.start, 1), "end": round(offset_s + s.end, 1), "text": text, "lp": round(s.avg_logprob, 2)})
    return out


def clock(seconds: float) -> str:
    """1234.5 -> "20:34"; past an hour "1:20:34"."""
    s = int(max(0, seconds))
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


# ---- the session on disk -------------------------------------------------------------------


@dataclass
class Session:
    id: str
    dir: Path
    started: float  # epoch seconds
    device: str = ""
    stopped: float | None = None
    words: int = 0
    lines: int = 0
    seconds: float = 0.0  # audio heard so far
    dropped_s: float = 0.0  # audio zeroed because she was speaking
    last_text: str = ""
    # stretches not heard because core was down (a crash, then a resume): [from_s, to_s]
    gaps: list = field(default_factory=list)

    def meta(self) -> dict:
        return {"id": self.id, "started": self.started, "stopped": self.stopped, "device": self.device, "words": self.words,
                "lines": self.lines, "seconds": round(self.seconds, 1), "dropped_s": round(self.dropped_s, 1), "gaps": self.gaps}


class Writer:
    """transcript.jsonl, one line per transcript line, on disk the moment it exists."""

    def __init__(self, session: Session):
        session.dir.mkdir(parents=True, exist_ok=True)
        self.session = session
        self._f = open(session.dir / "transcript.jsonl", "a", encoding="utf-8")
        self.meta()

    def append(self, lines: list[dict]) -> None:
        if not lines:
            return
        for line in lines:
            self._f.write(json.dumps(line, ensure_ascii=False) + "\n")
        self._f.flush()
        os.fsync(self._f.fileno())

    def meta(self) -> None:
        tmp = self.session.dir / "meta.json.tmp"
        tmp.write_text(json.dumps(self.session.meta(), indent=1), encoding="utf-8")
        os.replace(tmp, self.session.dir / "meta.json")

    def close(self) -> None:
        self.meta()
        self._f.close()


def sessions() -> list[Path]:
    """Every saved lecture, oldest first."""
    if not STORE.exists():
        return []
    return sorted(p for p in STORE.iterdir() if (p / "transcript.jsonl").exists())


def load(path: Path) -> tuple[dict, list[dict]]:
    """(meta, transcript lines) of one saved lecture. A torn last line (a crash
    mid-write) is skipped."""
    meta = {}
    try:
        meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    lines = []
    for raw in (path / "transcript.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            lines.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return meta, lines


# ---- the loopback ----------------------------------------------------------------------------


def _speaker(device: str):
    import soundcard as sc

    if not device or device == "default":
        return sc.default_speaker()
    for spk in sc.all_speakers():
        if device.lower() in spk.name.lower():
            return spk
    log.warning("lecture: no output device named like %r - using the default", device)
    return sc.default_speaker()


class LoopbackSource:
    """What the output device plays, 16 kHz mono, in 0.5 s blocks, in its own thread.
    A device that goes away (headphones unplugged) is found again; the gap is filled
    with silence so the timeline still matches the clock."""

    def __init__(self, device: str, on_block: Callable[[np.ndarray, float], None]):
        self.device = device
        self.on_block = on_block
        self.name = ""
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="irene-loopback", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        import soundcard as sc

        block = int(BLOCK_S * RATE)
        lost_since: float | None = None
        while not self._stop.is_set():
            try:
                spk = _speaker(self.device)
                self.name = spk.name
                mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
                if lost_since is not None:
                    gap = min(120.0, time.perf_counter() - lost_since)
                    log.warning("lecture: loopback back on %s after %.1f s - the gap is silence", spk.name, gap)
                    for _ in range(int(gap / BLOCK_S)):
                        self.on_block(np.zeros(block, np.float32), time.perf_counter())
                    lost_since = None
                log.info("lecture: listening to %s (loopback)", spk.name)
                with mic.recorder(samplerate=RATE, channels=2, blocksize=block) as rec:
                    while not self._stop.is_set():
                        data = rec.record(numframes=block)
                        mono = data.mean(axis=1).astype(np.float32) if data.ndim == 2 else data.astype(np.float32)
                        self.on_block(mono, time.perf_counter())
            except Exception as error:  # noqa: BLE001 - a device change: find it again
                if self._stop.is_set():
                    break
                lost_since = lost_since or time.perf_counter()
                log.warning("lecture: loopback lost (%s: %s) - trying again", type(error).__name__, error)
                self._stop.wait(2.0)


# ---- the capture -------------------------------------------------------------------------------


@dataclass
class _HerVoice:
    """When her own playback ends being audible (perf_counter), from the Speaker's tap."""

    tail_s: float = 0.4
    until: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def tap(self, out: np.ndarray, heard_at: float) -> None:
        if out.size and float(np.max(np.abs(out))) > 1e-3:
            with self.lock:
                self.until = max(self.until, heard_at + len(out) / 24000 + self.tail_s)

    def overlaps(self, block_end: float, block_s: float) -> bool:
        with self.lock:
            return block_end - block_s < self.until


# a capture is running: which session (removed on a clean stop). If core dies, the
# next start finds it and picks the same transcript up again (LectureCapture.resume)
ACTIVE = "active.json"
# a session older than this since it last wrote is over, not interrupted
RESUME_WITHIN_S = 30 * 60


class LectureCapture:
    """One capture at a time. start()/stop() from any thread; the loopback and the
    transcription each run in their own thread. `transcriber` is HIS mic's Whisper
    (one model in VRAM, shared through its queue)."""

    def __init__(self, transcriber: Callable[[], stt.Transcriber], on_change: Callable[[], None] | None = None,
                 source_factory: Callable | None = None, store: Path | None = None):
        self._transcriber = transcriber
        self.on_change = on_change or (lambda: None)
        self._source_factory = source_factory or LoopbackSource
        self.store = store or STORE
        self.session: Session | None = None
        self.her = _HerVoice()
        self._chunks: queue.Queue[Chunk | None] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._source = None
        self._chunker: Chunker | None = None
        self._writer: Writer | None = None
        self._lock = threading.Lock()
        self.config: dict = {}

    @property
    def active(self) -> bool:
        return self.session is not None and self.session.stopped is None

    def status(self) -> dict | None:
        s = self.session
        if s is None or s.stopped is not None:
            return None
        return {"started": int(s.started * 1000), "words": s.words, "seconds": round(s.seconds), "device": s.device,
                "backlog": self._chunks.qsize()}

    def start(self, device: str | None = None) -> Session:
        with self._lock:
            if self.active:
                return self.session  # type: ignore[return-value]
            cfg = settings()
            self.config = cfg
            self.her.tail_s = float(cfg.get("her_voice_tail_s", 0.4))
            now = datetime.now()
            sid = now.strftime("%Y-%m-%d_%H%M%S")
            session = Session(sid, self.store / sid, now.timestamp(), device=device or str(cfg.get("device", "default")))
            self._writer = Writer(session)
            self._chunker = Chunker(float(cfg.get("chunk_min_s", 18)), float(cfg.get("chunk_max_s", 30)))
            self.session = session
            self._run(session)
        (self.store / ACTIVE).write_text(json.dumps({"id": sid, "device": session.device}), encoding="utf-8")
        log.info("lecture: capture STARTED - session %s, device %s (transcript only, no audio kept)", sid, session.device)
        self.on_change()
        return session

    def _run(self, session: Session) -> None:
        self._chunks = queue.Queue()
        self._worker = threading.Thread(target=self._transcribe_loop, args=(session, self._writer, self._chunks), name="irene-lecture-stt", daemon=True)
        self._worker.start()
        self._source = self._source_factory(session.device, self._on_block)
        self._source.start()

    def interrupted(self) -> tuple[Session, float] | None:
        """A capture core was running when it died: (its session, how long since it last
        wrote) - or None. A stale one (nothing for RESUME_WITHIN_S) is closed instead."""
        marker = self.store / ACTIVE
        try:
            sid = json.loads(marker.read_text(encoding="utf-8"))["id"]
        except (OSError, ValueError, KeyError):
            return None
        path = self.store / sid
        meta, _lines = load(path) if (path / "transcript.jsonl").exists() else ({}, [])
        if not meta or meta.get("stopped"):
            marker.unlink(missing_ok=True)
            return None
        quiet = time.time() - (path / "meta.json").stat().st_mtime
        session = Session(sid, path, float(meta["started"]), device=meta.get("device", "default"), words=int(meta.get("words", 0)),
                          lines=int(meta.get("lines", 0)), seconds=float(meta.get("seconds", 0)), dropped_s=float(meta.get("dropped_s", 0)),
                          gaps=list(meta.get("gaps") or []), last_text=_lines[-1]["text"] if _lines else "")
        if quiet > RESUME_WITHIN_S:
            session.stopped = (path / "meta.json").stat().st_mtime
            Writer(session).close()
            marker.unlink(missing_ok=True)
            log.warning("lecture: session %s was interrupted %.0f min ago - too long to resume; closed", sid, quiet / 60)
            return None
        return session, quiet

    def resume(self, session: Session) -> Session:
        """Pick an interrupted session up again: the same transcript file, appended to;
        the timeline goes on from wall-clock time and the time core was down is a gap."""
        with self._lock:
            cfg = settings()
            self.config = cfg
            self.her.tail_s = float(cfg.get("her_voice_tail_s", 0.4))
            now_s = time.time() - session.started
            heard_to = session.seconds
            if now_s > heard_to:
                session.gaps.append([round(heard_to, 1), round(now_s, 1)])
            session.seconds = now_s
            self._writer = Writer(session)
            self._chunker = Chunker(float(cfg.get("chunk_min_s", 18)), float(cfg.get("chunk_max_s", 30)))
            self._chunker._start = int(now_s * RATE)
            self.session = session
            self._run(session)
        log.warning("lecture: capture RESUMED - session %s after %.0f s not heard (core restarted)", session.id, now_s - heard_to)
        self.on_change()
        return session

    def stop(self, drain_s: float = 120.0) -> Session | None:
        """Stop listening, transcribe what is still queued (up to drain_s), close the
        session. Returns it (None if nothing was running)."""
        with self._lock:
            if not self.active:
                return None
            session = self.session
            assert session is not None
            source, self._source = self._source, None
        if source is not None:
            source.stop()
        tail = self._chunker.flush() if self._chunker else None
        if tail is not None:
            self._chunks.put(tail)
        self._chunks.put(None)
        if self._worker is not None:
            self._worker.join(timeout=drain_s)
            if self._worker.is_alive():
                log.warning("lecture: transcription still behind after %.0f s - the rest is dropped", drain_s)
        session.stopped = time.time()
        if self._writer is not None:
            self._writer.close()
        (self.store / ACTIVE).unlink(missing_ok=True)
        log.info("lecture: capture STOPPED - %s, %s heard, %d words (%.0f s of her own voice left out)",
                 session.id, clock(session.seconds), session.words, session.dropped_s)
        self.on_change()
        return session

    # the loopback thread
    def _on_block(self, block: np.ndarray, captured_at: float) -> None:
        session, chunker = self.session, self._chunker
        if session is None or chunker is None or session.stopped is not None:
            return
        seconds = len(block) / RATE
        if self.her.overlaps(captured_at, seconds):
            block = np.zeros_like(block)
            session.dropped_s += seconds
        session.seconds += seconds
        for chunk in chunker.feed(block):
            self._chunks.put(chunk)

    # the transcription thread
    def _transcribe_loop(self, session: Session, writer: Writer, chunks: queue.Queue) -> None:
        silence = float(self.config.get("silence_rms", 0.004))
        beam = int(self.config.get("beam_size", 3))
        while True:
            chunk = chunks.get()
            if chunk is None:
                return
            try:
                rms = float(np.sqrt(np.mean(chunk.audio ** 2))) if chunk.audio.size else 0.0
                if rms < silence:
                    writer.meta()  # alive, only quiet: a resume after a crash still knows it was running
                    continue
                started = time.perf_counter()
                segments = self._transcriber().transcribe_background(chunk.audio, prompt=session.last_text[-PROMPT_CHARS:], beam_size=beam)
                lines = clean(segments, chunk.start_s)
                writer.append(lines)
                if lines:
                    session.lines += len(lines)
                    session.words += sum(len(line["text"].split()) for line in lines)
                    session.last_text = lines[-1]["text"]
                writer.meta()
                log.info("lecture: %s +%d words in %.1f s (backlog %d)", clock(chunk.start_s), sum(len(x["text"].split()) for x in lines),
                         time.perf_counter() - started, chunks.qsize())
            except Exception:  # noqa: BLE001 - one bad chunk must not end the lecture
                log.exception("lecture: a chunk at %s failed - skipped", clock(chunk.start_s))
