"""Hearing him: the microphone, Silero VAD, and when he has finished speaking.

The endpointer is the heart of it, and it is pure - frames and VAD probabilities
in, events out - so every rule is tested without a microphone:

  speech    he started talking (a run of voice longer than a cough)
  silence   he stopped; `remaining` of `total` seconds before it is decided -
            the HUD draws it as a countdown on her face
  check     a first look is due: is what he said so far a finished sentence?
  resume    he started again inside the silence: still his turn
  end       his turn is over, with the audio

End of speech waits a full `max_silence_s` (3 s) by default, so he can pause
mid-thought. It shortens to `min_silence_s` only when the sentence clearly
ended: the words so far are a complete phrase (Whisper's own punctuation, not
ending on "and" or "um") AND his pitch fell at the end - or it was a question.
Trailing off keeps the full wait.

MicListener runs it live: sounddevice at 16 kHz, 32 ms blocks (what Silero
wants), in its own thread, handing events to the asyncio loop. While she is
speaking it can listen for barge-in: her own voice comes back through the
speakers, so it only counts as him if it is surer, longer, and clearly louder
than the echo it has been hearing.
"""
from __future__ import annotations

import logging
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .aec import Aligner, EchoCanceller, Reference

log = logging.getLogger("irene.listen")

SAMPLE_RATE = 16000
BLOCK = 512  # 32 ms: the block Silero VAD takes at 16 kHz
BLOCK_S = BLOCK / SAMPLE_RATE
PREROLL_S = 0.35  # audio kept from before the speech started, so the first word isn't clipped
MAX_UTTERANCE_S = 30.0

# a sentence that stops on one of these was not finished
_TRAILING = {
    "and", "but", "so", "or", "the", "a", "an", "to", "of", "with", "for", "because", "then",
    "if", "my", "your", "is", "are", "was", "um", "uh", "er", "erm", "like", "that", "which",
    "when", "about", "in", "on", "at", "from", "into", "i", "we", "you", "it's", "and,", "maybe",
    # a sentence left hanging on a modal or a pronoun ("...maybe we could")
    "could", "would", "should", "can", "will", "might", "must", "want", "need", "going", "gonna",
    "wanna", "they", "he", "she", "let's", "just", "really", "also", "some", "any", "this", "these",
}


def complete_phrase(text: str) -> bool:
    """Whether Whisper's words read as a finished sentence."""
    said = (text or "").strip()
    if not said or said.endswith(("...", "…", ",", "-", "—", ";", ":")):
        return False
    if not said.endswith((".", "!", "?")):
        return False
    words = re.findall(r"[a-z']+", said.lower())
    return bool(words) and words[-1] not in _TRAILING


def _f0(chunk: np.ndarray) -> float | None:
    """Fundamental frequency of a short voiced chunk by autocorrelation, or None."""
    x = chunk - chunk.mean()
    if np.sqrt(np.mean(x * x)) < 0.01:
        return None
    lo, hi = SAMPLE_RATE // 400, SAMPLE_RATE // 70  # 70-400 Hz: a speaking voice
    corr = np.correlate(x, x, mode="full")[len(x) - 1 :]
    if corr[0] <= 0:
        return None
    lag = lo + int(np.argmax(corr[lo:hi]))
    if corr[lag] / corr[0] < 0.3:  # not periodic enough to be voiced
        return None
    return SAMPLE_RATE / lag


def pitch_falls(audio: np.ndarray, tail_s: float = 0.6) -> bool:
    """Whether his pitch fell over the last voiced part of `audio`: the late f0
    is clearly below the earlier f0 of that tail. The silence after he stopped
    (the check runs into it) is trimmed off first."""
    step10 = SAMPLE_RATE // 100
    energy = np.array([np.sqrt(np.mean(audio[i : i + step10] ** 2)) for i in range(0, max(0, len(audio) - step10), step10)])
    if not len(energy) or energy.max() <= 0:
        return False
    loud = np.nonzero(energy > energy.max() * 0.1)[0]
    end = (int(loud[-1]) + 1) * step10 if len(loud) else len(audio)
    tail = audio[max(0, end - int(tail_s * SAMPLE_RATE)) : end]
    step = int(0.04 * SAMPLE_RATE)
    f0s = [f for f in (_f0(tail[i : i + step * 2]) for i in range(0, len(tail) - step * 2, step)) if f]
    if len(f0s) < 4:
        return False
    third = max(1, len(f0s) // 3)
    early, late = float(np.median(f0s[:third])), float(np.median(f0s[-third:]))
    return late < early * 0.93


@dataclass
class Event:
    kind: str  # speech | silence | check | resume | end
    remaining: float = 0.0
    total: float = 0.0
    audio: np.ndarray | None = None
    # which utterance it belongs to (a verdict for an old one is ignored)
    generation: int = 0


@dataclass
class Endpointer:
    """Frames in, events out. See the module docstring."""

    max_silence_s: float = 3.0
    min_silence_s: float = 0.9
    check_after_s: float = 0.45
    min_speech_s: float = 0.25
    vad_threshold: float = 0.5
    # how often a silence countdown is reported
    tick_s: float = 0.1
    # while someone keeps talking, a look at the last few seconds this often (the
    # voice loop checks it for a wake phrase: room talk never pauses long enough
    # for the end-of-speech check, and "Hey Irene" drowned in it)
    peek_after_s: float = 1.4
    peek_every_s: float = 0.8
    peek_window_s: float = 2.6
    # a skit (skit.py) waiting for him: his whole turn ends after exactly this much
    # silence (None: the usual max/min wait) and may run this long
    fixed_wait_s: float | None = None
    max_utterance_s: float = MAX_UTTERANCE_S
    _next_peek: float = 1.4
    _pre: list = field(default_factory=list)
    _speech: list = field(default_factory=list)
    _voiced_run: float = 0.0
    _in_speech: bool = False
    _silence: float = 0.0
    _last_tick: float = -1.0
    _checked: bool = False
    _wait: float = 0.0
    generation: int = 0

    def __post_init__(self) -> None:
        self._wait = self._full_wait()

    def _full_wait(self) -> float:
        return self.fixed_wait_s if self.fixed_wait_s is not None else self.max_silence_s

    @property
    def speaking(self) -> bool:
        return self._in_speech

    def audio(self) -> np.ndarray:
        return np.concatenate(self._speech) if self._speech else np.zeros(0, np.float32)

    def verdict(self, ended: bool, generation: int | None = None, now: bool = False) -> None:
        """The answer to a `check`: a finished sentence ends at min_silence_s - or,
        `now`, at the next silent block (the speculative start: his intent is
        already clear, so she need not wait out the tail). Speech before that block
        cancels it like any resume. A verdict for an utterance that has already
        ended is ignored."""
        if generation is not None and generation != self.generation:
            return
        if not self._in_speech:
            return
        if ended and now:
            self._wait = min(self._silence, self.min_silence_s)
        else:
            self._wait = self.min_silence_s if ended else self.max_silence_s

    def reset(self) -> None:
        self._pre, self._speech = [], []
        self._voiced_run = self._silence = 0.0
        self._in_speech = self._checked = False
        self._last_tick = -1.0
        self._wait = self._full_wait()
        self._next_peek = self.peek_after_s

    def feed(self, frame: np.ndarray, prob: float) -> list[Event]:
        voiced = prob >= self.vad_threshold
        out: list[Event] = []
        if not self._in_speech:
            self._pre.append(frame)
            keep = int(PREROLL_S / BLOCK_S) + int(self.min_speech_s / BLOCK_S) + 2
            del self._pre[:-keep]
            self._voiced_run = self._voiced_run + BLOCK_S if voiced else 0.0
            if self._voiced_run >= self.min_speech_s:
                self._in_speech = True
                self.generation += 1
                self._speech = list(self._pre)
                self._pre = []
                out.append(Event("speech", generation=self.generation))
            return out
        self._speech.append(frame)
        length = len(self._speech) * BLOCK_S
        if length >= self._next_peek:
            self._next_peek = length + self.peek_every_s
            tail = self._speech[-int(self.peek_window_s / BLOCK_S) :]
            out.append(Event("peek", audio=np.concatenate(tail), generation=self.generation))
        if voiced:
            if self._silence > 0:
                out.append(Event("resume"))
            self._silence = 0.0
            self._checked = False
            self._last_tick = -1.0
            self._wait = self._full_wait()
        else:
            self._silence += BLOCK_S
            if not self._checked and self._silence >= self.check_after_s:
                self._checked = True
                out.append(Event("check", audio=self.audio(), generation=self.generation))
            if self._silence >= self._wait or len(self._speech) * BLOCK_S >= self.max_utterance_s:
                audio = self.audio()
                self.reset()
                out.append(Event("end", audio=audio, generation=self.generation))
                return out
            if self._last_tick < 0 or self._silence - self._last_tick >= self.tick_s:
                self._last_tick = self._silence
                out.append(Event("silence", remaining=max(0.0, self._wait - self._silence), total=self._wait))
        return out


def from_config(config: dict) -> Endpointer:
    e = config["end_of_speech"]
    return Endpointer(
        max_silence_s=float(e["max_silence_s"]),
        min_silence_s=float(e["min_silence_s"]),
        check_after_s=float(e["check_after_s"]),
        min_speech_s=float(e["min_speech_s"]),
        vad_threshold=float(e["vad_threshold"]),
    )


class Vad:
    """Silero VAD: speech probability for one 32 ms block."""

    def __init__(self):
        from silero_vad import load_silero_vad

        self.model = load_silero_vad()

    def __call__(self, block: np.ndarray) -> float:
        import torch

        with torch.no_grad():
            return float(self.model(torch.from_numpy(block.astype(np.float32)), SAMPLE_RATE).item())

    def reset(self) -> None:
        self.model.reset_states()


class Playback:
    """What she is playing, as a level over time, so the mic can be compared with
    it. Fed from the Speaker's output tap (any rate); read by the mic thread."""

    def __init__(self, window_s: float = 3.0):
        self._levels: list[tuple[float, float]] = []
        self._lock = threading.Lock()
        self.window_s = window_s

    def push(self, block: np.ndarray, now: float | None = None) -> None:
        rms = float(np.sqrt(np.mean(block * block))) if len(block) else 0.0
        now = time.monotonic() if now is None else now
        with self._lock:
            self._levels.append((now, rms))
            cut = now - self.window_s
            while self._levels and self._levels[0][0] < cut:
                self._levels.pop(0)

    def level(self, now: float | None = None, lo: float = 0.02, hi: float = 0.4) -> float:
        """The loudest she played between `hi` and `lo` seconds ago - the output
        latency plus the way through the room to the mic, reverb tail included."""
        now = time.monotonic() if now is None else now
        with self._lock:
            return max((r for t, r in self._levels if now - hi <= t <= now - lo), default=0.0)


class BargeGuard:
    """Whether speech heard while she talks might be him and not her echo.

    Her voice comes back through the speakers, so the mic is compared with what
    she is playing at that moment (Playback): the echo is `coupling` times her
    level, a ratio learned as she talks (it is the room and the volume knob, so it
    holds from one sentence to the next). Speech counts as a candidate only when it
    is sure (VAD), sustained, and louder than `over` times the echo expected right
    then. voice_loop then checks the words, so a loud echo of her own sentence
    still does not interrupt her."""

    def __init__(self, vad_threshold: float = 0.8, min_speech_s: float = 0.3, over_playback: float = 1.6, coupling: float = 0.3):
        self.vad_threshold = vad_threshold
        self.min_speech_s = min_speech_s
        self.over = over_playback
        self.coupling = coupling
        # the last half-second, block by block: speech flickers (a stop consonant,
        # a breath), so "him" is most of that window, not an unbroken run
        self._recent: list[bool] = []
        self._window = max(1, int(round(0.5 / BLOCK_S)))
        self._need = max(1, int(round(min_speech_s / BLOCK_S)))

    def reset(self) -> None:
        self._recent = []

    def learn(self, ratio: float) -> None:
        """A block that was only her echo: the coupling follows it."""
        self.coupling = 0.95 * self.coupling + 0.05 * ratio

    def feed(self, block: np.ndarray, prob: float, playing: float) -> bool:
        rms = float(np.sqrt(np.mean(block * block)))
        expected = self.coupling * playing
        him = prob >= self.vad_threshold and rms > max(0.012, expected * self.over)
        if playing > 0.02 and not him and rms > 0.002:
            # plain echo (or silence under her): learn how loud she comes back
            self.learn(min(rms / playing, 3.0))
        self._recent.append(him)
        del self._recent[: -self._window]
        return sum(self._recent) >= self._need


class MicListener:
    """The live microphone: blocks -> VAD -> endpointer (or barge guard) -> events
    on the asyncio loop. `barge` is read every block: True while she is speaking."""

    def __init__(
        self,
        config: dict,
        on_event: Callable[[Event], None],
        on_barge: Callable[[np.ndarray], None],
        on_level: Callable[[float], None] | None = None,
    ):
        self.config = config
        self.endpointer = from_config(config)
        b = config["barge_in"]
        self.guard = BargeGuard(float(b["vad_threshold"]), float(b["min_speech_s"]), float(b["over_playback"]), float(b.get("coupling", 0.3)))
        # what she is playing (the Speaker's tap feeds both): the echo guard's level,
        # and the echo canceller's reference - her voice is taken back out of the mic
        # before anything listens to it
        self.playback = Playback()
        self.reference = Reference(24000)
        self.aec = EchoCanceller() if b.get("echo_cancel", True) else None
        self.aligner = Aligner(float(b.get("echo_margin_s", 0.0)))
        # debug: the last ~30 s of (mic, reference) pairs fed to the canceller
        self.dump: list[tuple[np.ndarray, np.ndarray]] | None = [] if config.get("debug") else None
        self._index = 0
        # when block 0 finished being captured (perf_counter): the earliest estimate,
        # since callbacks arrive late, never early
        self._t0: float | None = None
        self.barge_enabled = bool(b.get("enabled", True))
        self.on_event = on_event
        self.on_barge = on_barge
        self.on_level = on_level
        self.barge = False
        self.paused = False
        # dev only (mic_deaf): a live check that must not hear the room
        self.deaf = False
        self._blocks: queue.Queue[tuple[int, np.ndarray]] = queue.Queue(maxsize=400)
        self._stream = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.vad: Vad | None = None
        # a dev replay is feeding recorded audio in: the live mic's blocks are dropped
        self._replaying = False
        self._block_at = time.monotonic()

    def start(self) -> None:
        import sounddevice as sd

        self.vad = Vad()
        device = self.config["microphone"].get("device")
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE, blocksize=BLOCK, channels=1, dtype="float32", device=device, callback=self._callback
        )
        self._stream.start()
        self._thread = threading.Thread(target=self._run, name="irene-mic", daemon=True)
        self._thread.start()
        log.info("microphone open (%s)", device or "default device")

    def stop(self) -> None:
        self._stop.set()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def replay(self, audio: np.ndarray, tail_s: float = 3.5) -> None:
        """Dev only: feed recorded 16 kHz audio through everything the live mic
        feeds - VAD, endpointer, Whisper, the wake phrase - in real time, then
        silence; the live mic is ignored meanwhile. Returns at once."""

        def run() -> None:
            self._replaying = True
            # live audio already queued (seconds of it, in a talkative room) is
            # not part of it either: drop it, then start clean
            try:
                while True:
                    self._blocks.get_nowait()
            except queue.Empty:
                pass
            self._blocks.put((self._index, None))
            try:
                padded = np.concatenate([audio.astype(np.float32), np.zeros(int(tail_s * SAMPLE_RATE), np.float32)])
                for i in range(0, len(padded) - BLOCK + 1, BLOCK):
                    self._blocks.put((self._index, padded[i : i + BLOCK]))
                    time.sleep(BLOCK_S)
                # the live mic stays out until the replayed audio is all processed
                # and its utterance has ended
                deadline = time.monotonic() + 6.0
                while (self.endpointer.speaking or not self._blocks.empty()) and time.monotonic() < deadline:
                    self._blocks.put((self._index, np.zeros(BLOCK, np.float32)))
                    time.sleep(BLOCK_S)
            finally:
                self._replaying = False

        threading.Thread(target=run, name="irene-replay", daemon=True).start()

    def feed_playback(self, out: np.ndarray, heard_at: float | None = None) -> None:
        """The Speaker's output tap: every block she plays (24 kHz), and when."""
        self.playback.push(out)
        self.reference.push(out, heard_at)

    @property
    def last_block_age(self) -> float:
        """Seconds since the device last delivered audio (the voice loop's health check)."""
        return time.monotonic() - self._block_at

    def _callback(self, indata, _frames, _time, status) -> None:
        self._block_at = time.monotonic()
        if status:
            log.debug("mic: %s", status)
        index = self._index
        self._index += 1
        # the mic clock: block k ended at t0 + (k + 1) x 32 ms; t0 from the earliest arrival
        t0 = time.perf_counter() - (index + 1) * BLOCK_S
        self._t0 = t0 if self._t0 is None else min(self._t0 + 1e-6, t0)
        if self._replaying:
            return
        try:
            self._blocks.put_nowait((index, indata[:, 0].copy()))
        except queue.Full:
            pass

    def _run(self) -> None:
        assert self.vad is not None
        last_level = 0.0
        recent: list[tuple[np.ndarray, float]] = []
        last_probe = 0.0
        while not self._stop.is_set():
            try:
                index, block = self._blocks.get(timeout=0.2)
            except queue.Empty:
                continue
            if block is None:  # a replay starts (dev): a clean utterance
                self.endpointer.reset()
                continue
            if len(block) != BLOCK:
                continue
            if self.aec is not None and self._t0 is not None:
                # what she played while this block was captured, a little earlier
                # still, so her echo always lands inside the canceller's 0.5 s
                start = self.reference.index_at(self._t0 + index * BLOCK_S - self.aligner.margin_s)
                ref = self.reference.read(start) if start is not None else None
                if ref is not None and (ref.any() or self.playback.level(lo=0.0, hi=0.6) > 0):
                    if self.dump is not None:
                        self.dump.append((block.copy(), ref.copy()))
                        del self.dump[:-900]
                    if self.aligner.add(block, ref):
                        log.info("echo alignment: margin now %.0f ms", self.aligner.margin_s * 1000)
                        self.aec.reset()
                    block = self.aec.process(block, ref)
            prob = self.vad(block)
            now = time.monotonic()
            if self.on_level and now - last_level > 0.05:
                last_level = now
                self.on_level(float(np.sqrt(np.mean(block * block))))
            if self.paused or self.deaf:
                continue
            if self.barge:
                if self.endpointer.speaking:
                    self.endpointer.reset()
                recent.append((block, prob))
                del recent[:-24]
                playing = self.playback.level()
                if prob >= 0.5 and now - last_probe > 0.25:
                    last_probe = now
                    rms = float(np.sqrt(np.mean(block * block)))
                    erle = self.aec.erle_db if self.aec else 0.0
                    log.debug("barge probe: vad %.2f mic %.4f playing %.4f expected echo %.4f aec %.1f dB", prob, rms, playing, self.guard.coupling * playing, erle)
                if self.barge_enabled and self.guard.feed(block, prob, playing):
                    self.guard.reset()
                    # a candidate: voice_loop checks the words are not her own; the
                    # capture starts now so his first words are kept if it is him
                    self.barge = False
                    self.on_barge(np.concatenate([b for b, _ in recent]))
                    for b, p in recent:
                        for event in self.endpointer.feed(b, max(p, self.endpointer.vad_threshold)):
                            self.on_event(event)
                    recent = []
                continue
            recent = []
            self.guard.reset()
            for event in self.endpointer.feed(block, prob):
                self.on_event(event)
