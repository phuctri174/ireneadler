"""The HUD's zoom gate, in Python, so captured frames can be replayed with new
thresholds without touching the app.

This is a faithful port of updateZoomPose / updateZoomFactor and the pieces they
lean on (FingerHysteresis, OneEuroFilter) from hud/src/tracking/gestures.ts and
hud/src/tracking/oneEuro.ts. It is only ever fed the metrics the capture already
recorded per frame, so a replay sees exactly what the live engine saw.

Keep it in step with gestures.ts: tests/test_zoom_replay.py checks the replay
reproduces the decisions the live engine recorded in the capture.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

MS_PER_SECOND = 1000.0
MIN_DELTA_SECONDS = 1 / 240
MAX_DELTA_SECONDS = 1 / 5


@dataclass(frozen=True)
class Thresholds:
    """The zoom gate's tuning, named as in gestures.ts."""

    open_finger: float = 0.15
    open_finger_release: float = 0.08
    closed_finger: float = 0.02
    closed_finger_release: float = 0.09
    open_thumb: float = 0.20
    open_thumb_release: float = 0.12
    closed_thumb: float = 0.10
    closed_thumb_release: float = 0.18
    spread_closed: float = 0.5
    hold_ms: float = 250.0
    uniform_grace_ms: float = 120.0
    invalid_grace_ms: float = 200.0
    # while latched, a hand that is neither open nor closed is mid-gesture, not a
    # release: this lets a transition run without dropping out. 0 = off (today).
    transit_grace_ms: float = 0.0


def _alpha(cutoff: float, delta_seconds: float) -> float:
    tau = 1 / (2 * math.pi * cutoff)
    return 1 / (1 + tau / delta_seconds)


class _LowPass:
    def __init__(self) -> None:
        self.value = 0.0
        self.ready = False

    def filter(self, x: float, alpha: float) -> float:
        self.value = alpha * x + (1 - alpha) * self.value if self.ready else x
        self.ready = True
        return self.value

    def set(self, x: float) -> None:
        self.value, self.ready = x, True

    def reset(self) -> None:
        self.value, self.ready = 0.0, False


class OneEuro:
    def __init__(self, min_cutoff: float = 1.0, beta: float = 1.0, d_cutoff: float = 1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.value, self.derivative = _LowPass(), _LowPass()
        self.prev_value = 0.0
        self.prev_ts = -1.0

    def filter(self, x: float, ts: float) -> float:
        if self.prev_ts < 0:
            self.prev_ts, self.prev_value = ts, x
            self.value.filter(x, 1)
            self.derivative.filter(0, 1)
            return x
        delta = min(max((ts - self.prev_ts) / MS_PER_SECOND, MIN_DELTA_SECONDS), MAX_DELTA_SECONDS)
        self.prev_ts = ts
        rate = (x - self.prev_value) / delta
        self.prev_value = x
        smoothed = self.derivative.filter(rate, _alpha(self.d_cutoff, delta))
        return self.value.filter(x, _alpha(self.min_cutoff + self.beta * abs(smoothed), delta))

    def seed(self, x: float, ts: float) -> None:
        self.value.set(x)
        self.derivative.set(0)
        self.prev_value, self.prev_ts = x, ts

    def reset(self) -> None:
        self.value.reset()
        self.derivative.reset()
        self.prev_value, self.prev_ts = 0.0, -1.0


class Finger:
    """Three-way hysteresis: extended / between / curled."""

    def __init__(self) -> None:
        self.state = "between"

    def update(self, value: float, open_latch: float, open_release: float, closed_latch: float, closed_release: float) -> str:
        if self.state == "extended":
            if value < open_release:
                self.state = "curled" if value < closed_latch else "between"
        elif self.state == "curled":
            if value > closed_release:
                self.state = "extended" if value > open_latch else "between"
        elif value > open_latch:
            self.state = "extended"
        elif value < closed_latch:
            self.state = "curled"
        return self.state

    def reset(self) -> None:
        self.state = "between"


NAMES = ("thumb", "index", "middle", "ring", "pinky")
# how the capture writes a finger's class: "th=ext ix=cur md=--- rg=ext pk=ext"
_CLASS = {"ext": "extended", "cur": "curled", "---": "between"}


def _classes(frame: dict) -> tuple[str, ...]:
    """The five finger classes the live engine had on this frame."""
    parts = str(frame.get("classes") or "").split()
    got = [_CLASS.get(p.split("=")[-1], "between") for p in parts]
    return tuple(got) if len(got) == len(NAMES) else ("between",) * len(NAMES)


class ZoomGate:
    """One hand's zoom pose over time: latch, release, and the factor it reports."""

    def __init__(self, thresholds: Thresholds = Thresholds()):
        self.t = thresholds
        self.fingers = {name: Finger() for name in NAMES}
        self.active = False
        self.pending_since = 0.0
        self.uniform_lost_since = 0.0
        self.invalid_since = 0.0
        self.baseline = 0.0
        self.filter = OneEuro()

    def reset(self) -> None:
        for finger in self.fingers.values():
            finger.reset()
        self.active = False
        self.pending_since = self.uniform_lost_since = self.invalid_since = self.baseline = 0.0
        self.filter.reset()

    def seed_from(self, frame: dict) -> None:
        """Start where the live engine already was. A take is a slice out of a
        running session - the engine came into it with its latch and its finger
        hysteresis already set - so a cold start disagrees for the first few
        hundred ms. The capture records both, so the replay can begin in step."""
        for name, state in zip(NAMES, _classes(frame)):
            self.fingers[name].state = state
        self.active = bool(frame.get("zoom"))
        if self.active:
            # already latched: the factor's baseline is the spread it latched on,
            # which is the best estimate available at the edge of a take
            self.baseline = float(frame.get("spread") or 0.0)
            self.filter.reset()
            self.filter.seed(self.baseline, float(frame.get("ts") or 0.0))

    def classify(self, frame: dict) -> dict[str, str]:
        t = self.t
        out = {}
        for name in NAMES:
            thumb = name == "thumb"
            out[name] = self.fingers[name].update(
                float(frame.get(name) or 0.0),
                t.open_thumb if thumb else t.open_finger,
                t.open_thumb_release if thumb else t.open_finger_release,
                t.closed_thumb if thumb else t.closed_finger,
                t.closed_thumb_release if thumb else t.closed_finger_release,
            )
        return out

    def step(self, frame: dict, latch_allowed: bool = True) -> tuple[bool, float]:
        """One frame in, (zoom latched, zoomFactor) out."""
        if not frame.get("hand"):
            self.reset()
            return False, 1.0
        t = self.t
        ts = float(frame.get("ts") or 0.0)
        spread = float(frame.get("spread") or 0.0)
        cls = self.classify(frame)
        all_open = all(cls[n] == "extended" for n in NAMES)
        all_closed = all(cls[n] == "curled" for n in NAMES)
        uniform = all_open or all_closed

        zoom = self._pose(uniform, all_open, all_closed, spread, ts, latch_allowed)
        return zoom, self._factor(zoom, spread, ts)

    def _pose(self, uniform: bool, all_open: bool, all_closed: bool, spread: float, ts: float, latch_allowed: bool) -> bool:
        t = self.t
        if self.active:
            # mid-gesture (neither open nor closed) is only a release if it lasts:
            # transit_grace_ms extends the plain invalid grace for that case
            grace = t.invalid_grace_ms
            if t.transit_grace_ms > 0 and not uniform:
                grace = max(grace, t.transit_grace_ms)
            if not uniform:
                if self.invalid_since == 0:
                    self.invalid_since = ts
                if ts - self.invalid_since >= grace:
                    self.active = False
                    self.invalid_since = 0.0
                    self.baseline = 0.0
                    return False
            else:
                self.invalid_since = 0.0
            return True

        if not latch_allowed:
            self.pending_since = self.uniform_lost_since = 0.0
            return False

        pose_valid = all_open or (all_closed and spread < t.spread_closed)
        if pose_valid:
            self.uniform_lost_since = 0.0
            if self.pending_since == 0:
                self.pending_since = ts
            if ts - self.pending_since < t.hold_ms:
                return False
        else:
            if self.pending_since == 0:
                return False
            if self.uniform_lost_since == 0:
                self.uniform_lost_since = ts
            if ts - self.uniform_lost_since >= t.uniform_grace_ms:
                self.pending_since = self.uniform_lost_since = 0.0
            return False

        self.active = True
        self.pending_since = self.uniform_lost_since = self.invalid_since = self.baseline = 0.0
        return True

    def _factor(self, active: bool, spread: float, ts: float) -> float:
        if not active:
            self.baseline = 0.0
            return 1.0
        if self.baseline == 0:
            self.baseline = spread
            self.filter.reset()
            self.filter.seed(spread, ts)
            return 1.0
        return min(max(self.filter.filter(spread, ts) / self.baseline, 0.5), 2.0)


def run_clip(
    frames: list[dict],
    thresholds: Thresholds = Thresholds(),
    warm: bool = True,
    latched: list[bool] | None = None,
) -> list[tuple[bool, float]]:
    """Replay one take. `warm` starts it where the live engine already was (see
    seed_from); cold starts it as if it had just come out of a lockout.

    `latched` supplies the latch decisions from somewhere else (a classifier, say)
    and keeps only the factor arithmetic - so two gates can be compared on the
    zoomFactor they would produce, not just on when they fire."""
    gate = ZoomGate(thresholds)
    if warm and frames:
        gate.seed_from(frames[0])
    if latched is None:
        return [gate.step(f) for f in frames]
    out = []
    for f, on in zip(frames, latched):
        if not f.get("hand"):
            gate.reset()
            out.append((False, 1.0))
            continue
        out.append((on, gate._factor(on, float(f.get("spread") or 0.0), float(f.get("ts") or 0.0))))
    return out


def tuned(**changes) -> Thresholds:
    return replace(Thresholds(), **changes)
