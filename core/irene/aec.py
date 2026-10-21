# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Acoustic echo cancellation: her voice taken back out of the microphone.

Over speakers, everything she says comes back into the mic - quieter, delayed,
coloured by the room. Left in, it trips the VAD, gets transcribed as if he said
it, and she interrupts herself or answers her own sentence. We know exactly what
she played (the Speaker's output tap), so the echo can be predicted and
subtracted: an adaptive filter learns the path speaker -> room -> mic and removes
its prediction, leaving him.

  EchoCanceller   partitioned-block frequency-domain NLMS (the design behind
                  most software AECs): 512-sample blocks at 16 kHz, a 0.5 s echo
                  path in 16 partitions, per-bin normalised steps. It freezes its
                  learning while he talks over her (double talk), so it never
                  learns to cancel HIM.
  Reference       what she played, as one continuous 16 kHz stream lined up with
                  the microphone's own sample clock - both streams run all the
                  time, so block k of the mic always pairs with the same stretch
                  of her output, with no jitter.
"""
from __future__ import annotations

import threading

import numpy as np
from scipy.signal import resample_poly

BLOCK = 512
FFT = 2 * BLOCK
PARTITIONS = 16  # 16 x 32 ms = 0.51 s of echo path: speaker + room + both latencies


class EchoCanceller:
    def __init__(self, partitions: int = PARTITIONS, mu: float = 0.5):
        self.p = partitions
        self.mu = mu
        bins = FFT // 2 + 1
        self.W = np.zeros((partitions, bins), np.complex128)
        self.X = np.zeros((partitions, bins), np.complex128)
        self._x_prev = np.zeros(BLOCK)
        self._power = np.full(bins, 1e-6)
        self.erle_db = 0.0  # echo return loss enhancement of the last block, dB
        self.converged = False
        self.double_talk = False
        # how hard the residual-echo suppressor leans on bins her echo still owns
        self.suppression = 2.0
        self._good = 0
        self._heard = 0  # blocks of her playing seen so far
        self.resets = 0  # times it went wrong and started over
        self._span_power = np.zeros(partitions)  # her energy in each of the last P blocks

    def reset(self) -> None:
        self.__init__(self.p, self.mu)

    def process(self, mic: np.ndarray, ref: np.ndarray) -> np.ndarray:
        """One 512-sample block of mic and of what she played -> the mic without her."""
        d = mic.astype(np.float64)
        x = ref.astype(np.float64)
        spectrum = np.fft.rfft(np.concatenate([self._x_prev, x]))
        self._x_prev = x
        self.X = np.roll(self.X, 1, axis=0)
        self.X[0] = spectrum
        y = np.fft.irfft(np.sum(self.W * self.X, axis=0))[BLOCK:]
        e = d - y
        pd, pe, py, px = float(d @ d), float(e @ e), float(y @ y), float(x @ x)
        self._span_power = np.roll(self._span_power, 1)
        self._span_power[0] = px
        # the echo it predicts comes from the last half-second of her playing (the
        # room's tail), so that is what it is weighed against, not just this block
        if not np.isfinite(py) or py > 2.0 * float(self._span_power.max()) + 1e-4 * BLOCK:
            # it has run away: an echo predicted louder than she is actually playing
            # cannot be the room - start learning the room again
            self.resets += 1
            self.W[:] = 0
            self.converged, self._good, self._heard = False, 0, 0
            self.erle_db = 0.0
            return mic.astype(np.float32)
        bypass = pe > pd
        self.erle_db = 10 * np.log10((pd + 1e-9) / (pe + 1e-9))
        playing = px > 1e-5 * BLOCK
        if playing:
            # double talk: once it knows the room, a mic much louder than the echo it
            # predicts is him talking over her - learning from that would teach it
            # to cancel HIM, so it holds still until he stops
            self.double_talk = self.converged and pd > 3.0 * py + 1e-5 * BLOCK
            if not self.double_talk:
                self._adapt(e)
            self._good = self._good + 1 if self.erle_db > 6.0 else max(0, self._good - 1)
            self._heard += 1
            # it knows the room after a run of good blocks - or simply after ~3 s of
            # her talking: in a noisy room the ERLE of the whole mic never looks good
            # even when her part of it is gone, and double-talk protection must not
            # wait for a number that will never come
            self.converged = self.converged or self._good >= 12 or self._heard >= 94
        else:
            self.double_talk = False
        if bypass:
            # a block it would make worse (the mic gated her echo out, the room
            # changed): never hand on a mic worse than the raw one - this block
            # passes through untouched
            return mic.astype(np.float32)
        return self._suppress(e, y) if playing else e.astype(np.float32)

    def _suppress(self, e: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Residual echo: what the linear filter could not remove (the speaker's own
        distortion, a room that moved) - bins where the predicted echo still
        dominates are turned down; bins where he is louder pass."""
        window = np.hanning(BLOCK)
        E = np.fft.rfft(e * window)
        Y = np.fft.rfft(y * window)
        ratio = (np.abs(Y) ** 2) / (np.abs(E) ** 2 + 1e-9)
        gain = np.clip(1.0 - self.suppression * ratio, 0.08, 1.0)
        cleaned = np.fft.irfft(E * gain, n=BLOCK)
        # undo the window's loss of level where it is safe; the edges stay soft
        return (cleaned / np.maximum(window, 0.25)).astype(np.float32)

    def _adapt(self, e: np.ndarray) -> None:
        E = np.fft.rfft(np.concatenate([np.zeros(BLOCK), e]))
        # per-bin power of what she is playing now (smoothed): the NLMS normaliser,
        # regularised so a bin she barely plays in (her resampled voice has almost
        # nothing near 8 kHz) cannot take a huge step on room noise and run away
        self._power = 0.85 * self._power + 0.15 * np.abs(self.X[0]) ** 2
        floor = 0.1 * float(np.mean(self._power)) + 1e-4
        step = self.mu / (self._power * self.p + floor)
        grad = np.conj(self.X) * E * step
        # gradient constraint: keep each partition a causal 512-tap filter
        g = np.fft.irfft(grad, axis=1)
        g[:, BLOCK:] = 0
        # a slight leak: what it stops being told fades, rather than drifting
        self.W = self.W * 0.9995 + np.fft.rfft(g, axis=1)


class Aligner:
    """Keeps her echo where the canceller can reach it.

    The reference is taken `margin_s` before each mic block was captured; the
    devices' real latencies are never quite what they report (on his PC the
    reference ran 148 ms early), so while she talks this measures where her echo
    actually sits - the lag of the mic's cross-correlation with the reference - and
    moves the margin until the echo lands `target_s` into the filter. Two
    agreeing measurements are needed before it moves, so one noisy stretch (him
    talking, the room) never throws it off."""

    def __init__(self, margin_s: float = 0.0, target_s: float = 0.04, window_blocks: int = 94):
        self.margin_s = margin_s
        self.target_s = target_s
        self.window = window_blocks
        self._mic: list[np.ndarray] = []
        self._ref: list[np.ndarray] = []
        self._last: float | None = None

    def add(self, mic: np.ndarray, ref: np.ndarray) -> bool:
        """One (mic, reference) pair as fed to the canceller. True when the margin
        moved (the canceller should start learning again)."""
        self._mic.append(mic)
        self._ref.append(ref)
        if len(self._mic) < self.window:
            return False
        m = np.concatenate(self._mic).astype(np.float64)
        r = np.concatenate(self._ref).astype(np.float64)
        self._mic, self._ref = [], []
        if r.std() < 0.02:
            return False
        lag = echo_lag(m, r)
        if lag is None:
            return False
        agreed = self._last is not None and abs(lag - self._last) < 0.012
        self._last = lag
        if agreed and abs(lag - self.target_s) > 0.015:
            self.margin_s += lag - self.target_s
            self._last = None
            return True
        return False


def echo_lag(mic: np.ndarray, ref: np.ndarray, span_s: float = 0.45, min_peak: float = 0.12) -> float | None:
    """How much later her echo is in `mic` than in `ref` (seconds), or None when
    the correlation is too weak to trust."""
    n = 1 << int(np.ceil(np.log2(len(mic) + len(ref))))
    cc = np.fft.irfft(np.fft.rfft(mic, n) * np.conj(np.fft.rfft(ref, n)), n)
    span = int(span_s * 16000)
    lags = np.concatenate([np.arange(0, span), np.arange(-span, 0)])
    values = np.concatenate([cc[:span], cc[-span:]])
    k = int(np.argmax(np.abs(values)))
    peak = abs(values[k]) / (np.sqrt(np.dot(mic, mic) * np.dot(ref, ref)) + 1e-12)
    return lags[k] / 16000 if peak >= min_peak else None


class Reference:
    """Her output as a continuous 16 kHz stream, indexed by sample count.

    The Speaker's output callback runs all the time (zeros when she is quiet) and
    pushes every block here at its own rate; the mic thread asks for the 512
    samples that pair with each mic block. Pairing is by sample count from the
    moment the mic started, so it stays locked to both devices' clocks."""

    def __init__(self, rate: int = 24000, keep_s: float = 3.0):
        self.rate = rate
        # when sample 0 of the stream reached the speaker (perf_counter): the lowest
        # estimate seen, since a late callback only ever makes it look later
        self._t0: float | None = None
        self._buf = np.zeros(0, np.float32)
        self._start = 0  # absolute index (at `rate`) of _buf[0]
        self._written = 0
        self._keep = int(keep_s * rate)
        self._lock = threading.Lock()

    def push(self, block: np.ndarray, heard_at: float | None = None) -> None:
        with self._lock:
            if heard_at is not None:
                t0 = heard_at - self._written / self.rate
                self._t0 = t0 if self._t0 is None else min(self._t0 + 1e-6, t0)
            self._buf = np.concatenate([self._buf, block.astype(np.float32)])
            self._written += len(block)
            extra = len(self._buf) - self._keep
            if extra > 0:
                self._buf = self._buf[extra:]
                self._start += extra

    def index_at(self, t: float) -> int | None:
        """The 16 kHz sample index she was playing at perf_counter time `t`."""
        if self._t0 is None:
            return None
        return int((t - self._t0) * 16000)

    @property
    def written(self) -> int:
        """Samples written so far, at 16 kHz."""
        return int(self._written * 16000 / self.rate)

    def read(self, at16: int, n: int = BLOCK) -> np.ndarray:
        """The n samples at 16 kHz starting at absolute 16 kHz index `at16`;
        zeros for anything not written yet or already dropped."""
        margin = 48
        a = int(at16 * self.rate / 16000) - margin
        b = int((at16 + n) * self.rate / 16000) + margin
        with self._lock:
            out = np.zeros(b - a, np.float32)
            lo, hi = max(a, self._start), min(b, self._start + len(self._buf))
            if hi > lo:
                out[lo - a : hi - a] = self._buf[lo - self._start : hi - self._start]
        if not out.any():
            return np.zeros(n, np.float32)
        if self.rate == 16000:
            y = out
        else:
            from math import gcd

            g = gcd(16000, self.rate)
            y = resample_poly(out, 16000 // g, self.rate // g)
        m = int(round(margin * 16000 / self.rate))
        y = y[m : m + n]
        return np.pad(y, (0, n - len(y))).astype(np.float32) if len(y) < n else y.astype(np.float32)
