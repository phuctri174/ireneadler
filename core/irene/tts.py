# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Her voice (voice.py: Chatterbox-Turbo, Kokoro as the fallback) with streaming
playback and a ~20 Hz RMS level for the HUD mouth.

Text is split into sentences - and, for Turbo, which synthesises a whole chunk at a
time, long sentences into their comma phrases - and each chunk is synthesised while
the previous one plays, so first audio arrives after one short chunk. The output
stream runs in callback mode and measures RMS on exactly the block the device is
about to play, so the level tracks what is heard rather than what was queued.

Pre-rendered clips (the summon line) go through the same stream with their own
mouth levels and sample-accurate marks, fired as the marked sample is heard. A
streamed sentence can carry its own mark too - her face changes as that sentence
starts, not when it was written.
"""
from __future__ import annotations

import bisect
import collections
import logging
import random
import queue
import re
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np
import sounddevice as sd

from . import openers
from .voice import SAMPLE_RATE as VOICE_RATE, Voice, strip_tags

from .levels import master as master_level
log = logging.getLogger("irene.tts")

SAMPLE_RATE = VOICE_RATE
BLOCK = SAMPLE_RATE // 20  # 50 ms -> level at 20 Hz
VOICE = "af_bella"
# an output stream silent this long (no callbacks) while audio waits is reopened
STALL_S = 3.0
# Turbo chunks: a sentence longer than this many words is spoken as its comma phrases
CHUNK_WORDS = 11
_COMMA = re.compile(r"(?<=[,;:])\s+")
# speech RMS that should read as a fully open mouth
FULL_SCALE_RMS = 0.12
# a cue's sound effect under her voice: peak level, and how far it leads the words
SFX_LEVEL = 0.1
SFX_LEAD_S = 0.06

_SENTENCES = re.compile(r"(?<=[.!?…])\s+")
_WORD = re.compile(r"[A-Za-z][A-Za-z']*")

LevelCallback = Callable[[float], None]
Done = Callable[[bool], None]


def unshout(sentence: str) -> str:
    """A sentence written entirely in capitals is shouting, not a string of acronyms.

    misaki spells all-caps words letter by letter ("IRENE" -> I-R-E-N-E); title-case
    them so they are read as words. Mixed-case sentences keep acronyms as written.
    """
    words = _WORD.findall(sentence)
    if len(words) < 2 or not all(w.isupper() for w in words if len(w) > 1):
        return emphasis(sentence)
    return _WORD.sub(lambda m: m.group(0).capitalize(), sentence)


# capitals she writes that really are letters to spell
ACRONYMS = frozenset(
    "AI API CPU GPU RAM VRAM SSD HDD USB PDF CSV JSON HTML CSS URL TCP UDP IP DNS HTTP OS PC TV "
    "UK US USA EU BST FIFO LIFO FEN PGN SAN RGB LED FAQ CEO CV ETA ASAP PM AM OK DM ID".split()
)


def emphasis(sentence: str) -> str:
    """One capitalised word in a normal sentence is stress ("you did WHAT?"), not an
    acronym: say it as the word. Known acronyms, and anything without a vowel, stay
    spelled out."""
    def word(m: re.Match) -> str:
        w = m.group(0)
        if len(w) >= 3 and w.isupper() and w not in ACRONYMS and re.search(r"[AEIOUY]", w):
            return w.lower()
        return w

    return _WORD.sub(word, sentence)


def mix_under(voice: np.ndarray, sound: np.ndarray, level: float = SFX_LEVEL) -> np.ndarray:
    """`sound` laid softly under the start of `voice` (Kokoro leads each sentence
    with a little silence, so it lands just before the first word)."""
    start = int(SFX_LEAD_S * SAMPLE_RATE)
    out = voice.copy() if len(voice) >= start + len(sound) else np.pad(voice, (0, start + len(sound) - len(voice)))
    out[start : start + len(sound)] += sound.astype(np.float32) * level
    return np.clip(out, -1.0, 1.0)


def to_level(rms: float, full_scale: float = FULL_SCALE_RMS) -> float:
    return float(min(1.0, (rms / full_scale) ** 0.8))


def block_levels(stem: np.ndarray) -> np.ndarray:
    """Mouth level per 50 ms block of a voice stem - what a clip's meter plays back.

    A produced clip is mastered hotter than live TTS, so it is scaled to its own
    loudness: the 90th-percentile voiced block opens the mouth fully - about the
    spread of live TTS - instead of most of it pinning at 1.0.
    """
    n = -(-len(stem) // BLOCK)
    padded = np.zeros(n * BLOCK, np.float32)
    padded[: len(stem)] = stem
    rms = np.sqrt(np.mean(np.square(padded.reshape(n, BLOCK)), axis=1))
    voiced = rms[rms > 0.01]
    full_scale = float(np.percentile(voiced, 90)) if len(voiced) else FULL_SCALE_RMS
    return np.array([to_level(r, full_scale) for r in rms], np.float32)


def chunks(sentence: str, words: int = CHUNK_WORDS, first: bool = False) -> list[str]:
    """A long sentence as its comma phrases (none shorter than 3 words), for an engine
    that must synthesise a whole chunk before any of it plays. The first sentence of
    an utterance also gives up its opening phrase ("Ooh, wait,") so she starts at once."""
    if first:
        m = re.match(r"((?:\S+\s+){0,5}?\S+,)\s+(.*)", sentence)
        if m and len(m.group(2).split()) >= 3:
            return [m.group(1), *chunks(m.group(2), words)]
    if len(sentence.split()) <= words:
        return [sentence]
    out: list[str] = []
    for part in _COMMA.split(sentence):
        if out and (len(out[-1].split()) < 3 or len(part.split()) < 3):
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return out


class Upsampler:
    """24 kHz -> 48 kHz for the WASAPI output: zero-stuffed and low-passed by one
    FIR whose state carries across blocks, so block edges never click."""

    def __init__(self, taps: int = 48):
        from scipy.signal import firwin

        # gain 2: half the samples are the stuffed zeros
        self.fir = (firwin(taps, 10500, fs=48000) * 2).astype(np.float64)
        self.zi = np.zeros(taps - 1)

    def __call__(self, block: np.ndarray) -> np.ndarray:
        from scipy.signal import lfilter

        stuffed = np.zeros(len(block) * 2)
        stuffed[::2] = block
        out, self.zi = lfilter(self.fir, 1.0, stuffed, zi=self.zi)
        return out.astype(np.float32)


def open_output(callback, on_ready: Callable[[object, int], None], prefer: str = "wasapi"):
    """Her output stream: WASAPI shared mode at 48 kHz in 20 ms blocks (40 ms of
    output latency on this PC), or MME at 24 kHz (100 ms, whatever the block) if
    WASAPI will not open. Returns (stream, how many output samples per 24 kHz one).

    `on_ready(stream, ratio)` runs BEFORE the stream starts: PortAudio calls `callback`
    from its own thread the moment start() is called, so whatever the callback
    needs (the ratio, the upsampler) must exist by then. Setting it after this
    returned crashed every audio block on the first real launch."""
    if prefer == "wasapi":
        try:
            import ctypes
            import sys

            if sys.platform == "win32":
                # WASAPI needs COM on the thread that opens it, and core opens the
                # speaker from a worker thread (without it: "WdmSyncIoctl" failure)
                ctypes.windll.ole32.CoInitializeEx(None, 0)
            apis = sd.query_hostapis()
            wasapi = next(a for a in apis if "WASAPI" in a["name"])
            stream = sd.OutputStream(
                samplerate=48000, channels=1, dtype="float32", blocksize=960, latency="low",
                device=wasapi["default_output_device"], callback=callback,
            )
            on_ready(stream, 2)
            stream.start()
            log.info("speaker: WASAPI, %.0f ms output latency", stream.latency * 1000)
            return stream, 2
        except Exception as error:  # no WASAPI device, or it refused the format
            log.warning("speaker: WASAPI unavailable (%s) - MME instead", error)
    stream = sd.OutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=BLOCK, latency="low", callback=callback)
    on_ready(stream, 1)
    stream.start()
    log.info("speaker: MME, %.0f ms output latency", stream.latency * 1000)
    return stream, 1


def _heard_at(timing) -> float:
    """When a block leaves the speaker, on the perf_counter clock. PortAudio's
    output DAC time is on that clock on Windows (checked: current time matches
    perf_counter to 10 us); if a host gives nonsense, assume the stream latency."""
    try:
        dac = float(timing.outputBufferDacTime)
        now = time.perf_counter()
        if abs(dac - now) < 1.0:
            return dac
    except (AttributeError, TypeError, ValueError):
        pass
    return time.perf_counter() + 0.1


class Speaker:
    # the master gain + limiter on everything played (levels.py); off only in tests
    # that check samples pass through exactly
    master_stage = True

    def __init__(self, pronunciation: Path, on_level: LevelCallback, prefer: str = "turbo"):
        self.voice = Voice(prefer, pronunciation)
        # pre-rendered openers ("Ooh!", "Hmm..."), for the engine that made them (openers.py)
        self.openers: dict[str, np.ndarray] = {}
        self.openers_engine: str | None = None
        self._last_opener: str | None = None
        self._on_level = on_level
        # what she is playing, block by block (24 kHz), with when it leaves the
        # speaker (perf_counter seconds), for anything that must tell her voice from
        # his: voice_loop's echo canceller and barge-in guard
        self.taps: list[Callable[[np.ndarray, float], None]] = []
        # her volume, 0..1: ducked the instant he may be talking over her (barge-in)
        self.gain = 1.0
        # paused mid-answer while a barge-in is checked: silence plays, nothing is
        # used up, and release() carries on from the same sample
        self.held = False
        # each entry: [audio, meter]; meter is a per-sample level track or None to
        # measure the audio itself
        self._fifo: collections.deque[list] = collections.deque()
        self._lock = threading.Lock()
        self._generation = 0
        self._first_audio: float | None = None
        self._pending_first = False
        self._played = 0
        # samples queued in this utterance so far: where the next sentence starts
        self._queued = 0
        self._marks: list[tuple[int, Callable[[], None]]] = []
        self._was_loud = False
        # the HUD's mouth level goes out at most every 50 ms, whatever the block
        self._level_at = 0.0
        self._level_acc: list[float] = []
        # output samples per 24 kHz one, and the upsampler when that is 2: both set by
        # open_output before the stream starts (_set_ratio)
        self._ratio = 1
        self._upsample: Upsampler | None = None
        self._callback_failed = False
        # the music bed (music.py): a track mixed UNDER whatever she plays - speak(),
        # play() and stop() never touch it - with its own gain, ramped per sample
        self._bed: np.ndarray | None = None
        self._bed_at = 0
        self._bed_gain = 0.0
        self._bed_target = 0.0
        self._bed_step = 0.0
        # when the output stream last called back, and when it last played sound
        # (perf_counter): a stream that stops calling back is reopened, never waited on
        self.callback_at = time.perf_counter()
        self.audible_at = 0.0
        self._reopened_at = 0.0
        self._stream, _ = open_output(self._callback, self._set_ratio)

    @property
    def engine(self) -> str:
        return self.voice.name

    def prepare(self, text: str, first: bool = False) -> list[str]:
        """Spoken text -> engine-ready chunks. Display text never comes through here.
        `first`: this text opens the utterance (its opening phrase goes out alone)."""
        turbo = self.voice.engine.tags
        sentences = [s for s in _SENTENCES.split(text.strip()) if s]
        if turbo:
            sentences = [c for i, s in enumerate(sentences) for c in chunks(s, first=first and i == 0)]
        else:
            sentences = [strip_tags(s) for s in sentences]
        # his pronunciation map is applied by the engine wrapper (voice.Voice.synth),
        # so a cached lead-in or an entrance line gets it exactly as a live reply does
        return [unshout(s) for s in sentences if s.strip()]

    def synthesize(self, text: str, speed: float = 1.0) -> np.ndarray:
        parts = [a for sentence in self.prepare(text) for a in self.voice.synth(sentence, speed)]
        return np.concatenate(parts) if parts else np.zeros(0, np.float32)

    def speak(
        self,
        text: str,
        speed: float = 1.0,
        done: Done | None = None,
        on_start: Callable[[], None] | None = None,
    ) -> float:
        """Interrupt anything playing and start speaking `text`. Returns immediately.

        `done(finished)` always runs once, on a worker thread: True after the last
        sample has played, False if stop() or a later speak() cut this one off.
        `on_start` runs on the audio thread as the first sample is heard.
        Returns the call's perf_counter stamp.
        """
        stamp = time.perf_counter()
        generation = self._begin([(0, on_start)] if on_start else [])
        threading.Thread(target=self._produce, args=(generation, text, speed, done), daemon=True).start()
        return stamp

    def play(
        self,
        audio: np.ndarray,
        levels: np.ndarray,
        marks: list[tuple[float, Callable[[], None]]] = (),
        done: Done | None = None,
    ) -> float:
        """Interrupt anything playing and play a pre-rendered clip.

        `levels` is the mouth track at one value per 50 ms block. Each mark is
        (seconds into the clip, callback); the callback runs on the audio thread when
        that sample reaches the speaker, so keep it cheap.
        """
        stamp = time.perf_counter()
        meter = np.repeat(levels, BLOCK)[: len(audio)]
        if len(meter) < len(audio):
            meter = np.pad(meter, (0, len(audio) - len(meter)))
        generation = self._begin([(int(t * SAMPLE_RATE), fn) for t, fn in marks])
        with self._lock:
            if generation == self._generation:
                self._fifo.append([np.asarray(audio, np.float32), meter])
                self._queued += len(audio)
        threading.Thread(target=self._finish, args=(generation, done), daemon=True).start()
        return stamp

    def stream(
        self,
        speed: float = 1.0,
        done: Done | None = None,
        on_start: Callable[[], None] | None = None,
        keep: bool = False,
    ) -> "SpeechStream":
        """Interrupt anything playing (or with `keep`, follow it) and open an
        utterance fed sentence by sentence, so speech can start before the whole
        reply exists. close() when the text ends; `done` then runs once the last
        sample plays (or False if cut off)."""
        generation = self._begin([(0, on_start)] if on_start else [], keep)
        stream = SpeechStream(self, generation)
        threading.Thread(target=self._produce_stream, args=(stream, speed, done), daemon=True).start()
        return stream

    def _produce_stream(self, stream: "SpeechStream", speed: float, done: Done | None) -> None:
        first = True
        try:
            while True:
                item = stream._queue.get()
                if item is None:
                    break
                text, own_speed, on_start, sound = item
                with self._lock:
                    if stream.generation != self._generation:
                        break
                self._synthesize_into_fifo(stream.generation, text, own_speed or speed, on_start, sound, first)
                # a cached lead-in ("Hmm...") plays at once: the phrase after it still opens the reply
                first = first and openers.key(text) in self.openers
        except Exception:
            log.exception("stream synthesis failed")
        self._finish(stream.generation, done)

    def hold(self) -> None:
        """Pause where she is (he may be talking over her)."""
        self.held = True

    def release(self) -> None:
        """Carry on from where hold() paused."""
        self.held = False

    def progress(self) -> tuple[float, float]:
        """(seconds played, seconds queued) of the current utterance."""
        with self._lock:
            return self._played / SAMPLE_RATE, self._queued / SAMPLE_RATE

    def stop(self) -> None:
        with self._lock:
            self.held = False
            self._generation += 1
            self._fifo.clear()
            self._marks = []

    def bed(self, audio: np.ndarray, level: float = 0.0, ramp_s: float = 0.0) -> None:
        """Start a music bed under everything she plays, at `level` after `ramp_s`."""
        with self._lock:
            self._bed = np.asarray(audio, np.float32)
            self._bed_at = 0
            self._bed_gain = 0.0
        self.bed_to(level, ramp_s)

    def bed_to(self, level: float, ramp_s: float) -> None:
        """Ramp the bed's gain to `level` over `ramp_s` (0: at once)."""
        with self._lock:
            self._bed_target = max(0.0, level)
            samples = ramp_s * SAMPLE_RATE
            self._bed_step = abs(self._bed_target - self._bed_gain) / samples if samples > 0 else float("inf")

    def bed_stop(self) -> None:
        with self._lock:
            self._bed = None
            self._bed_gain = self._bed_target = 0.0

    @property
    def bed_playing(self) -> bool:
        return self._bed is not None

    def overlay(self, audio: np.ndarray, gain: float = 1.0, delay_s: float = 0.0) -> None:
        """A one-shot sound mixed under whatever plays (her voice, the bed) - the
        panel's paper landing - without interrupting it. `delay_s`: it starts that
        long from now."""
        clip = np.asarray(audio, np.float32) * gain
        if delay_s > 0:
            clip = np.concatenate([np.zeros(int(delay_s * SAMPLE_RATE), np.float32), clip])
        with self._lock:
            shots = getattr(self, "_shots", None)
            if shots is None:
                shots = self._shots = []
            shots.append([clip, 0])

    def _mix_shots(self, out: np.ndarray) -> None:
        """Add the next block of every one-shot into `out` (under the lock)."""
        shots = getattr(self, "_shots", None)
        if not shots:
            return
        for shot in list(shots):
            clip, at = shot
            n = min(len(out), len(clip) - at)
            if n > 0:
                out[:n] += clip[at : at + n]
            shot[1] = at + max(0, n)
            if shot[1] >= len(clip):
                shots.remove(shot)

    def _mix_bed(self, out: np.ndarray) -> None:
        """Add the next block of the bed into `out` (under the lock), its gain ramped."""
        bed = getattr(self, "_bed", None)
        if bed is None:
            return
        n = min(len(out), len(bed) - self._bed_at)
        if n <= 0:
            self._bed = None
            return
        g0 = self._bed_gain
        if self._bed_step == float("inf"):
            gains = np.full(n, self._bed_target, np.float32)
        else:
            direction = 1.0 if self._bed_target >= g0 else -1.0
            ramp = g0 + direction * self._bed_step * np.arange(1, n + 1, dtype=np.float32)
            gains = np.minimum(ramp, self._bed_target) if direction > 0 else np.maximum(ramp, self._bed_target)
        self._bed_gain = float(gains[-1])
        out[:n] += bed[self._bed_at : self._bed_at + n] * gains
        self._bed_at += n
        # faded all the way out: done with it
        if self._bed_target == 0.0 and self._bed_gain == 0.0:
            self._bed = None

    @property
    def first_audio(self) -> float | None:
        """perf_counter stamp at which the current utterance's first block reached the device."""
        return self._first_audio

    def _begin(self, marks: list[tuple[int, Callable[[], None]]], keep: bool = False) -> int:
        """A new utterance. `keep`: what is still queued plays out first (her "On
        it!" before the answer) - the new one's marks count from after it."""
        with self._lock:
            self._generation += 1
            queued = sum(len(a) for a, _ in self._fifo) if keep else 0
            if not keep:
                self.held = False
                self._fifo.clear()
                self._first_audio = None
                self._pending_first = True
            self._played = 0
            self._queued = queued
            self._marks = sorted(((at + queued, fn) for at, fn in marks), key=lambda m: m[0])
            return self._generation

    def _produce(self, generation: int, text: str, speed: float, done: Done | None) -> None:
        try:
            self._synthesize_into_fifo(generation, text, speed)
        except Exception:
            log.exception("synthesis failed")
        self._finish(generation, done)

    def lead_in(self, first_text: str, cue: str | None) -> str | None:
        """A pre-rendered opener to say before a first phrase that would take a while
        to synthesise, or None (it already opens with one, or no takes are ready)."""
        if self.openers_engine != self.voice.name or not self.openers:
            return None
        chunk = self.prepare(first_text, first=True)[:1]
        if chunk and openers.key(chunk[0]) in self.openers:
            return None
        pool = [o for o in openers.BY_CUE.get(cue, openers.BY_CUE[None]) if openers.key(o) in self.openers and o != self._last_opener]
        if not pool:
            return None
        self._last_opener = random.choice(pool)
        return self._last_opener

    def _synthesize_into_fifo(
        self,
        generation: int,
        text: str,
        speed: float,
        on_start: Callable[[], None] | None = None,
        sound: np.ndarray | None = None,
        first: bool = False,
    ) -> None:
        for sentence in self.prepare(text, first):
            take = self.openers.get(openers.key(sentence)) if self.openers_engine == self.voice.name else None
            for audio in ([take] if take is not None else self.voice.synth(sentence, speed)):
                chunk = np.asarray(audio, dtype=np.float32)
                if sound is not None:
                    chunk = mix_under(chunk, sound)
                    sound = None
                with self._lock:
                    if generation != self._generation:
                        return  # interrupted: stop synthesising the rest
                    if on_start is not None:
                        # heard when playback reaches the first sample of this text
                        bisect.insort(self._marks, (self._queued, on_start), key=lambda m: m[0])
                        on_start = None
                    self._fifo.append([chunk, None])
                    self._queued += len(chunk)

    def _finish(self, generation: int, done: Done | None) -> None:
        """Wait for playback to drain, then report whether it ran to the end."""
        finished = self._drain(generation)
        if done:
            done(finished)

    def _drain(self, generation: int) -> bool:
        while True:
            with self._lock:
                if generation != self._generation:
                    return False
                if not self._fifo:
                    break
            if time.perf_counter() - self.callback_at > STALL_S:
                # the device went away (unplugged, default changed) or its driver hung:
                # the queue would never drain and whoever waits on it - her turn -
                # would wait forever. Reopen it; the rest of the queue plays there.
                self.reopen()
            time.sleep(0.02)
        time.sleep(self._stream.latency + BLOCK / SAMPLE_RATE)
        with self._lock:
            return generation == self._generation

    def reopen(self) -> None:
        """A fresh output stream (at most every 5 s), after the old one stalled."""
        now = time.perf_counter()
        if now - self._reopened_at < 5.0:
            return
        self._reopened_at = now
        log.error("speaker: no callback for %.1f s - reopening the output stream", now - self.callback_at)
        try:
            self._stream.abort()
            self._stream.close()
        except Exception:
            log.exception("speaker: closing the stalled stream failed")
        try:
            self._stream, _ = open_output(self._callback, self._set_ratio)
            self.callback_at = time.perf_counter()
        except Exception:
            log.exception("speaker: could not reopen the output stream")

    def playing(self) -> bool:
        """Whether she is audibly speaking, or has something about to play."""
        with self._lock:
            queued = bool(self._fifo)
        return queued or time.perf_counter() - self.audible_at < 1.0

    def _set_ratio(self, stream, ratio: int) -> None:
        """Everything the callback reads about its stream, before it starts."""
        self._upsample = Upsampler() if ratio == 2 else None
        self._ratio = ratio
        # samples between the callback filling a block and it leaving the speaker
        self._latency_samples = int(stream.latency * SAMPLE_RATE)

    def _callback(self, outdata, frames, timing, status) -> None:
        """PortAudio's thread. An exception here stops the stream for good - she
        goes silent and every turn waits on her forever - so none escapes: the
        block plays silence and the first failure is logged."""
        try:
            self._fill(outdata, frames, timing, status)
        except Exception:
            outdata.fill(0)
            if not self._callback_failed:
                self._callback_failed = True
                log.exception("speaker callback failed - playing silence")

    def _fill(self, outdata, frames, timing, _status) -> None:
        self.callback_at = time.perf_counter()
        # everything here is her 24 kHz voice; a 48 kHz device gets it upsampled last
        frames //= self._ratio
        out = np.zeros(frames, np.float32)
        filled = 0
        metered: list[np.ndarray] = []
        due: list[Callable[[], None]] = []
        with self._lock:
            while filled < frames and self._fifo and not self.held:
                head = self._fifo[0]
                audio, meter = head
                take = min(frames - filled, len(audio))
                out[filled : filled + take] = audio[:take]
                if meter is not None:
                    metered.append(meter[:take])
                filled += take
                if take == len(audio):
                    self._fifo.popleft()
                else:
                    head[0] = audio[take:]
                    head[1] = None if meter is None else meter[take:]
            if filled:
                self.audible_at = self.callback_at
            if filled and self._pending_first:
                self._pending_first = False
                self._first_audio = time.perf_counter()
            self._played += filled
            heard = self._played - self._latency_samples
            while self._marks and self._marks[0][0] <= heard and not self.held:
                due.append(self._marks.pop(0)[1])
            # a clip shorter than the output latency still fires its marks at the end
            if not self._fifo and filled < frames and not self.held:
                due.extend(fn for _, fn in self._marks)
                self._marks = []
            out[filled:] = 0
            # the music bed goes under her voice (not into the mouth meter)
            self._mix_bed(out)
            self._mix_shots(out)
        if self.gain != 1.0:
            out *= self.gain
        # the master stage for everything she plays: gain, then a soft limiter
        # (levels.py, config/voice.yaml output) - the echo canceller's taps see this
        if self.master_stage:
            out[:] = master_level(out)
        heard_at = _heard_at(timing)
        for tap in self.taps:
            try:
                tap(out, heard_at)
            except Exception:
                log.exception("playback tap failed")
        for fn in due:
            try:
                fn()
            except Exception:
                log.exception("playback mark failed")
        outdata[:, 0] = self._upsample(out) if self._upsample is not None else out
        if metered:
            level = float(np.mean(np.concatenate(metered)))
        else:
            level = to_level(float(np.sqrt(np.mean(np.square(out))))) if filled else 0.0
        self._level_acc.append(level)
        now = time.perf_counter()
        if now - self._level_at < BLOCK / SAMPLE_RATE and level > 1e-3:
            return
        self._level_at = now
        level, self._level_acc = max(self._level_acc), []
        loud = level > 1e-3
        # silence is reported once, not 20 times a second
        if loud or self._was_loud:
            self._on_level(level)
        self._was_loud = loud


class SpeechStream:
    """Text fed to one utterance while it is already playing. Thread-safe."""

    def __init__(self, speaker: Speaker, generation: int):
        self.generation = generation
        self._speaker = speaker
        self._queue: queue.Queue[tuple | None] = queue.Queue()
        self._closed = False

    def feed(
        self,
        text: str,
        speed: float | None = None,
        on_start: Callable[[], None] | None = None,
        sound: np.ndarray | None = None,
    ) -> None:
        """Queue a sentence. `speed` overrides the stream's rate for it; `on_start`
        runs on the audio thread as its first sample is heard; `sound` (a cue's
        effect, peak 1) is mixed softly under the sentence's first words."""
        if text.strip() and not self._closed:
            self._queue.put((text, speed, on_start, sound))

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._queue.put(None)
