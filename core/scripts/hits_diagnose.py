r"""Why strikes are hard to see: the hits capture, strike takes against everything else.

    .venv\Scripts\python scripts\hits_diagnose.py [profile]     (default: hits)

Measures, never guesses, per session and per step:

  nobody    frames where the pose model found no body at all
  out       wrist frames with the wrist outside the image (range / framing)
  vis       wrist visibility, in-frame only, on fast frames vs slow ones - a drop
            that only shows when the wrist moves fast is blur
  sh p10    shoulder visibility, worst tenth (an arm across the body: occlusion)
  dt        ms between processed frames, and frames the camera presented that the
            loop never saw (skipped) - whether frames drop, and where
  poseMs    the body model's own cost per frame
  exposure  what the camera reported for the session (auto or manual, and time)

Low visibility everywhere, at rest too, with a long exposure time, is lighting.
"""
from __future__ import annotations

import collections
import json
import math
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from irene.calibration import load  # noqa: E402

L_SHOULDER, R_SHOULDER, L_WRIST, R_WRIST = 11, 12, 15, 16
FAST = 8.0  # shoulder-widths per second: clearly moving, not drifting


def _at(body: list[float], i: int) -> list[float]:
    return body[i * 4 : i * 4 + 4]


def _p(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else math.nan


def _med(xs: list[float]) -> float:
    return st.median(xs) if xs else math.nan


def step_stats(takes: list[list[dict]]) -> dict:
    s = collections.defaultdict(list)
    for take in takes:
        take = sorted(take, key=lambda f: f.get("ts", f["t"]))
        prev = None
        for f in take:
            s["frames"].append(1)
            if "dtMs" in f:
                if f["dtMs"]:
                    s["dt"].append(f["dtMs"])
                s["skipped"].append(f.get("skipped", 0))
                if f.get("poseMs"):
                    s["poseMs"].append(f["poseMs"])
            body = f.get("body")
            if not isinstance(body, list) or len(body) != 132:
                s["nobody"].append(1)
                prev = None
                continue
            ls, rs = _at(body, L_SHOULDER), _at(body, R_SHOULDER)
            width = math.hypot(ls[0] - rs[0], ls[1] - rs[1])
            s["shoulder"].append(min(ls[3], rs[3]))
            for i in (L_WRIST, R_WRIST):
                p = _at(body, i)
                inside = 0 <= p[0] <= 1 and 0 <= p[1] <= 1
                s["out"].append(0 if inside else 1)
                if prev is None or width < 1e-3:
                    continue
                q = _at(prev[1], i)
                dt = max(1e-3, (f.get("ts", f["t"]) - prev[0]) / 1000)
                fast = math.hypot(p[0] - q[0], p[1] - q[1]) / width / dt > FAST
                if fast:
                    s["fast_out"].append(0 if inside else 1)
                if inside:
                    s["vis_fast" if fast else "vis_slow"].append(p[3])
            prev = (f.get("ts", f["t"]), body)
    return s


def main() -> None:
    profile = sys.argv[1] if len(sys.argv) > 1 else "hits"
    frames = load(profile)
    if not frames:
        raise SystemExit(f"no {profile} capture in core/calibration - record it first (ctrl+alt+shift+0)")
    profiles = json.loads((HERE.parents[1] / "config" / "capture_profiles.json").read_text(encoding="utf-8"))["profiles"]
    diagnostic = profiles.get(profile, {}).get("diagnosticOnly", {})
    by_session = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(list)))
    for f in frames:
        by_session[f["session"]][f["pose"]][f["rep"]].append(f)
    for session, steps in sorted(by_session.items()):
        modes = collections.Counter((f.get("exposureMode", "?"), f.get("exposureTime", "?"), f.get("camW"), f.get("camH"), f.get("camFps"))
                                    for f in frames if f["session"] == session)
        print(f"\n== {profile} {session}   camera (mode, exposureTime x100us, w, h, fps): {dict(modes)}")
        if session in diagnostic:
            print(f"   diagnostic only - the trainer never reads it: {diagnostic[session]}")
        print(f"{'step':14} {'takes':>5} {'frames':>6} {'nobody':>6} {'out%':>5} {'fastOut%':>8} "
              f"{'vis fast':>8} {'vis slow':>8} {'sh p10':>6} {'dt med':>6} {'dt p95':>6} {'skipped':>7} {'poseMs':>6}")
        for step, reps in steps.items():
            s = step_stats(list(reps.values()))
            pct = lambda xs: 100 * st.mean(xs) if xs else math.nan  # noqa: E731
            print(f"{step:14} {len(reps):5d} {len(s['frames']):6d} {len(s['nobody']):6d} {pct(s['out']):5.1f} "
                  f"{pct(s['fast_out']):8.1f} {_med(s['vis_fast']):8.3f} {_med(s['vis_slow']):8.3f} "
                  f"{_p(s['shoulder'], .1):6.3f} {_med(s['dt']):6.1f} {_p(s['dt'], .95):6.1f} "
                  f"{int(sum(s['skipped'])):7d} {_med(s['poseMs']):6.1f}")


if __name__ == "__main__":
    main()
