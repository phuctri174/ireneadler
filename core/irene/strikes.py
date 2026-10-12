"""Men, kote, gyaku-dou - from his upper body, during keiko.

A strike is a MOVEMENT, not a pose: the hands go up and come down on her men, or
snap forward and down to her right wrist, or sweep across to her left side. So the
classifier looks at the last WINDOW_MS of the body, not one frame:

  frame(body)    the arms from the midpoint of the shoulders in shoulder-widths, and
                 how far in front of them (the same 15 numbers as the kamae model,
                 hud/src/tracking/kamaeFeatures.ts) - the same strike reads the same
                 wherever he stands
  window(...)    those frames resampled at STEPS fixed moments over the window (the
                 camera's frame rate wobbles), then for each tracked number its
                 first, last, lowest and highest value and WHEN in the window the
                 lowest and highest came; plus the hands' fastest move and when
  probs(...)     a softmax over men / kote / gyaku_dou / none (the trainer's weights)

The watcher fires a strike when one class stays over ITS threshold for the trainer's
number of consecutive windows, then rests. Every number in the gate is fitted by
core/scripts/strike_train.py on his captures - none is set by hand.

hud/src/tracking/strikeFeatures.ts is the TS twin of everything here and must stay in
step: hud/tests/strike.verify.mjs replays the trainer's golden windows through it.
"""
from __future__ import annotations

import math

L_SHOULDER, R_SHOULDER, L_ELBOW, R_ELBOW, L_WRIST, R_WRIST = 11, 12, 13, 14, 15, 16

CLASSES = ("men", "kote", "gyaku_dou", "none")
WINDOW_MS = 900.0
STEPS = 9
# the per-frame numbers the window summarises (indices into frame()):
# lwx lwy rwx rwy lex ley rex rey gap midx midy depth
TRACKED = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 13)
WRIST_VIS = 11


def frame(body: list[float]) -> list[float] | None:
    """One body (flat [x, y, z, visibility] x 33) -> 15 numbers, or None without shoulders."""
    if len(body) != 132:
        return None

    def at(i: int) -> tuple[float, float, float, float]:
        return body[i * 4], body[i * 4 + 1], body[i * 4 + 2], body[i * 4 + 3]

    ls, rs = at(L_SHOULDER), at(R_SHOULDER)
    width = math.hypot(ls[0] - rs[0], ls[1] - rs[1])
    if width < 1e-3 or min(ls[3], rs[3]) < 0.5:
        return None
    mx, my, mz = (ls[0] + rs[0]) / 2, (ls[1] + rs[1]) / 2, (ls[2] + rs[2]) / 2

    def rel(i: int) -> tuple[float, float]:
        p = at(i)
        return (p[0] - mx) / width, (p[1] - my) / width

    def depth(i: int) -> float:
        return (at(i)[2] - mz) / width

    lw, rw, le, re_ = rel(L_WRIST), rel(R_WRIST), rel(L_ELBOW), rel(R_ELBOW)
    return [
        lw[0], lw[1], rw[0], rw[1],
        le[0], le[1], re_[0], re_[1],
        math.hypot(lw[0] - rw[0], lw[1] - rw[1]), (lw[0] + rw[0]) / 2, (lw[1] + rw[1]) / 2,
        min(at(L_WRIST)[3], at(R_WRIST)[3]), min(at(L_ELBOW)[3], at(R_ELBOW)[3]),
        (depth(L_WRIST) + depth(R_WRIST)) / 2, (depth(L_ELBOW) + depth(R_ELBOW)) / 2,
    ]


def window(samples: list[tuple[float, list[float] | None]], now: float) -> list[float] | None:
    """The window feature vector at `now` from (time ms, frame()) samples, oldest
    first - or None when the window isn't covered (too few bodies in it)."""
    start = now - WINDOW_MS
    valid = [(t, f) for t, f in samples if f is not None and start - 200 <= t <= now]
    if len(valid) < 4 or valid[0][0] > start + WINDOW_MS * 0.25:
        return None
    # resample: at each fixed moment, the latest body at or before it (the first, before any)
    picked: list[list[float]] = []
    j = 0
    for k in range(STEPS):
        moment = start + WINDOW_MS * k / (STEPS - 1)
        while j + 1 < len(valid) and valid[j + 1][0] <= moment:
            j += 1
        picked.append(valid[j][1])
    out: list[float] = []
    for i in TRACKED:
        series = [p[i] for p in picked]
        lo, hi = min(series), max(series)
        out += [series[0], series[-1], lo, hi, series.index(lo) / (STEPS - 1), series.index(hi) / (STEPS - 1)]
    speeds = [math.hypot(picked[k + 1][9] - picked[k][9], picked[k + 1][10] - picked[k][10]) for k in range(STEPS - 1)]
    peak = max(speeds)
    out += [peak, speeds.index(peak) / (STEPS - 2), sum(p[WRIST_VIS] for p in picked) / STEPS]
    return out


def probs(model: dict, v: list[float]) -> list[float]:
    """Softmax over CLASSES: z_c = b_c + sum_i W[c][i] * (v_i - mean_i) / scale_i."""
    x = [(a - m) / s for a, m, s in zip(v, model["mean"], model["scale"])]
    z = [b + sum(w * xi for w, xi in zip(row, x)) for row, b in zip(model["weights"], model["bias"])]
    top = max(z)
    e = [math.exp(v - top) for v in z]
    total = sum(e)
    return [v / total for v in e]


def hand_speed(prev: tuple[float, list[float]], cur: tuple[float, list[float]]) -> float:
    """How fast the hands' midpoint moved between two bodies, shoulder-widths per second."""
    dt = max(1.0, cur[0] - prev[0])
    return math.hypot(cur[1][9] - prev[1][9], cur[1][10] - prev[1][10]) * 1000.0 / dt


class Watcher:
    """When a strike happened. Feed it each body (or None) with its time in ms.

    A strike is an event: the hands' fastest moment. The watcher follows the hands'
    speed (3-sample average). AFTER_MS after a peak of at least the trainer's
    speedMin it classifies the window that now holds the whole movement - and then
    waits the trainer's settleMs: a strike starts with a raise (furikaburi) that is
    itself fast, so a FASTER peak arriving meanwhile replaces the judgement. Only an
    unbeaten judgement fires, when its top class is a strike over its threshold."""

    AFTER_MS = 250.0

    def __init__(self, model: dict):
        self.model = model
        self.samples: list[tuple[float, list[float] | None]] = []
        self.speeds: list[float] = []
        self.peak: tuple[float, float] | None = None  # (time, speed) of the fastest moment not yet judged
        # a judged peak waiting to see if a faster one follows: (time, speed, probs)
        self.pending: tuple[float, float, list[float]] | None = None
        self.rest_until = -math.inf
        self.last: list[float] = [0.0] * len(CLASSES)

    def update(self, body: list[float] | None, now: float) -> tuple[str, float] | None:
        gate = self.model["gate"]
        f = frame(body) if body else None
        prev = next((s for s in reversed(self.samples) if s[1] is not None), None)
        self.samples.append((now, f))
        while self.samples and now - self.samples[0][0] > WINDOW_MS + 400:
            self.samples.pop(0)
        if f is not None and prev is not None:
            self.speeds.append(hand_speed(prev, (now, f)))
            del self.speeds[:-3]
            speed = sum(self.speeds) / len(self.speeds)
            if self.peak is None or speed > self.peak[1]:
                self.peak = (now, speed)
            if self.pending is not None and speed > self.pending[1]:
                self.pending = None  # a faster movement: that was only the raise
        if self.peak is not None and now - self.peak[0] >= self.AFTER_MS:
            peak, self.peak = self.peak, None
            if peak[1] >= gate["speedMin"]:
                v = window(self.samples, now)
                if v is not None:
                    self.pending = (peak[0], peak[1], probs(self.model, v))
        if self.pending is None or now - self.pending[0] < self.AFTER_MS + gate["settleMs"]:
            return None
        _, _, p = self.pending
        self.pending = None
        self.last = p
        if now < self.rest_until:
            return None
        k = max(range(len(CLASSES)), key=lambda i: p[i])
        if CLASSES[k] == "none" or p[k] < gate["threshold"][CLASSES[k]]:
            return None
        self.rest_until = now + gate["restMs"]
        return CLASSES[k], p[k]
