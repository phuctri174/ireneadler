r"""The zoom gate the HUD actually runs - the exported forest (zoomModel.ts) inside
the latch timing of gestures.ts updateZoomPose - replayed on captured sessions.

    .venv\Scripts\python scripts\zoom_eval.py [--sessions zoom_panel] [--model REV:path | path]

Unlike zoom_analyze.py (which compares candidate approaches it trains itself),
this scores the SHIPPED classifier, so "does the retrain beat what is live" is
answered with the two real forests on the same frames and the same timing:

    --model HEAD          the forest committed at HEAD (default: the working copy)
    --gate live|strict    today's timing, or the stricter entry (both printed by default)

Per gate it prints, for the chosen sessions:
  false zooms      confuser takes with an unbroken latch >= FALSE_ZOOM_MS, and the
                   share of confuser hand-frames latched
  zoom recall      zoom_in/out takes that latched at all, and the share of their
                   frames latched after the first 40% of the motion
Only the classifier branch is ported (latchAllowed taken as true; the pointing /
scroll flags the capture recorded stand in for otherPoseRaw).
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from irene.calibration import load_family  # noqa: E402
from zoom_analyze import CONFUSERS, FALSE_ZOOM_MS, MOTIONS, clips, take_features  # noqa: E402

MODEL = "hud/src/tracking/zoomModel.ts"
MARK = "export const ZOOM_FOREST: ZoomForest = "


@dataclass(frozen=True)
class Gate:
    """The latch timing of gestures.ts (names as there)."""

    hold_ms: float  # ZOOM_HOLD_MS
    entry_score: float  # ZOOM_ENTRY_SCORE: every frame of the hold must score this
    uniform_grace_ms: float  # ZOOM_UNIFORM_GRACE_MS: a dropout this short doesn't reset the hold
    invalid_grace_ms: float  # ZOOM_INVALID_GRACE_MS: release after this long below 0


GATES = {
    # what shipped before the panel round
    "live": Gate(hold_ms=250, entry_score=0.0, uniform_grace_ms=120, invalid_grace_ms=150),
    # the stricter entry (gestures.ts now)
    "strict": Gate(hold_ms=700, entry_score=2.0, uniform_grace_ms=60, invalid_grace_ms=150),
}


def load_forest(spec: str | None) -> dict:
    if spec is None:
        text = (ROOT / MODEL).read_text(encoding="utf-8")
    else:
        rev, _, path = spec.partition(":")
        text = subprocess.run(["git", "show", f"{rev}:{path or MODEL}"], cwd=ROOT, capture_output=True, text=True, check=True, encoding="utf-8").stdout
    body = text[text.index(MARK) + len(MARK):].strip().rstrip(";")
    return json.loads(body)


def raw_scores(forest: dict, X: np.ndarray) -> np.ndarray:
    out = np.full(len(X), forest["baseline"], dtype=np.float64)
    for tree in forest["trees"]:
        feat, thr, left, right, leaf, value = (tree[k] for k in ("feature", "threshold", "left", "right", "leaf", "value"))
        for r, x in enumerate(X):
            node = 0
            while not leaf[node]:
                node = left[node] if x[feat[node]] <= thr[node] else right[node]
            out[r] += value[node]
    return out


def run_gate(frames: list[dict], scores: np.ndarray, gate: Gate) -> list[bool]:
    """gestures.ts updateZoomPose, classifier branch, frame by frame."""
    active = False
    pending = lost = invalid = 0.0
    out = []
    for f, raw in zip(frames, scores):
        ts = float(f.get("ts") or 0.0)
        if not f.get("hand"):
            active, pending, lost, invalid = False, 0.0, 0.0, 0.0
            out.append(False)
            continue
        other = bool(f.get("pointing") or f.get("scroll"))
        if active:
            if raw < 0 or other:
                invalid = invalid or ts
                if ts - invalid >= gate.invalid_grace_ms:
                    active, invalid = False, 0.0
                    out.append(False)
                    continue
            else:
                invalid = 0.0
            out.append(True)
            continue
        if raw >= gate.entry_score and not other:
            lost = 0.0
            pending = pending or ts
            if ts - pending >= gate.hold_ms:
                active, pending = True, 0.0
                out.append(True)
                continue
        elif pending:
            lost = lost or ts
            if ts - lost >= gate.uniform_grace_ms:
                pending = lost = 0.0
        out.append(False)
    return out


def evaluate(takes: dict, forest: dict, gate: Gate) -> dict:
    conf_takes = conf_false = conf_frames = conf_latched = 0
    worst = 0.0
    zoom_takes = zoom_hit = zoom_frames = zoom_latched = 0
    for key, frames in takes.items():
        pose = key[2]
        if pose not in CONFUSERS and pose not in MOTIONS:
            continue
        scores = raw_scores(forest, take_features(frames))
        dec = run_gate(frames, scores, gate)
        live = [(z, f) for z, f in zip(dec, frames) if f.get("hand")]
        if not live:
            continue
        if pose in CONFUSERS:
            conf_takes += 1
            conf_frames += len(live)
            conf_latched += sum(z for z, _ in live)
            longest, start = 0.0, None
            for z, f in live:
                ts = float(f.get("ts") or 0.0)
                if z:
                    start = ts if start is None else start
                    longest = max(longest, ts - start)
                else:
                    start = None
            worst = max(worst, longest)
            conf_false += longest >= FALSE_ZOOM_MS
        else:
            zoom_takes += 1
            zoom_hit += any(z for z, _ in live)
            tail = live[int(len(live) * 0.4):]
            zoom_frames += len(tail)
            zoom_latched += sum(z for z, _ in tail)
    return {
        "false": (conf_false, conf_takes),
        "conf_frames": conf_latched / conf_frames if conf_frames else math.nan,
        "worst_ms": worst,
        "recall": (zoom_hit, zoom_takes),
        "zoom_frames": zoom_latched / zoom_frames if zoom_frames else math.nan,
    }


def line(label: str, r: dict) -> str:
    f, n = r["false"]
    h, m = r["recall"]
    return (f"{label:28} false zooms {f}/{n} confuser takes ({f / max(n, 1):.0%}), {r['conf_frames']:.1%} of confuser frames, "
            f"worst {r['worst_ms']:.0f} ms | zoom recall {h}/{m} takes, {r['zoom_frames']:.0%} of motion frames latched")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", default=None, help="profile or profile-session prefix to score on (default: all zoom captures)")
    parser.add_argument("--model", action="append", default=None, help="REV[:path] or 'work' (repeatable; default: work)")
    parser.add_argument("--gate", choices=sorted(GATES), action="append", default=None)
    args = parser.parse_args()
    takes = clips(load_family("zoom"))
    if args.sessions:
        takes = {k: v for k, v in takes.items() if f"{k[0]}-{k[1]}".startswith(args.sessions)}
    if not takes:
        print("no takes match")
        return 1
    print(f"{len(takes)} takes from {len({(k[0], k[1]) for k in takes})} sessions")
    for model in args.model or ["work"]:
        forest = load_forest(None if model == "work" else model)
        for name in args.gate or sorted(GATES):
            print(line(f"{model} / {name} gate", evaluate(takes, forest, GATES[name])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
