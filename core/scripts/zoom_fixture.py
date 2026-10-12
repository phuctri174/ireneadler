r"""Bake a few real captured takes into a fixture the HUD tests can replay.

    .venv\Scripts\python scripts\zoom_fixture.py

The zoom gate is a learned classifier now, so the hand-built poses in
hud/tests/gestures.verify.mjs cannot validate it: they carry z = 0 on every
landmark and put the fingers on straight lines, which is geometry that never
comes out of real tracking. This writes hud/tests/zoom.engine.json - whole takes
of real landmarks, one per behaviour that matters - and zoom.verify.mjs runs them
through the whole GestureEngine.

core/calibration is not in the repo, so the fixture is: it has to be committed
for the tests to run on a fresh clone. Only what the engine reads is kept (the
landmarks, the cursor and the clock), rounded, which is about a tenth of the raw
capture.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from irene.calibration import load_family  # noqa: E402
from zoom_analyze import CONFUSERS, HOLDS, MOTIONS, clips  # noqa: E402

OUT = HERE.parents[1] / "hud" / "tests" / "zoom.engine.json"
# one take each: enough to pin the behaviour without carrying the whole capture
WANTED = HOLDS + MOTIONS + CONFUSERS


def pick(takes: dict, pose: str) -> tuple | None:
    """The first complete take of a pose, preferring one with the hand in view
    throughout - a take that lost tracking tests the tracker, not the gate."""
    best, best_share = None, 0.0
    for key in sorted(takes):
        if key[2] != pose:
            continue
        frames = takes[key]
        share = sum(1 for f in frames if f.get("hand")) / max(len(frames), 1)
        if share > best_share:
            best, best_share = key, share
        if best_share > 0.995:
            break
    return best


def main() -> int:
    takes = clips(load_family("zoom"))
    if not takes:
        print("no zoom captures in core/calibration - run ctrl+alt+shift+1 and ctrl+alt+shift+2 first")
        return 1

    out = []
    for pose in WANTED:
        key = pick(takes, pose)
        if key is None:
            print(f"  no take of {pose} - skipped")
            continue
        frames = takes[key]
        kept = []
        for f in frames:
            lm = f.get("lm")
            kept.append(
                {
                    "ts": round(float(f.get("ts") or 0.0), 1),
                    "cx": round(float(f.get("cx") or 0.0), 4),
                    "cy": round(float(f.get("cy") or 0.0), 4),
                    "lm": [round(float(v), 4) for v in lm] if isinstance(lm, list) and len(lm) == 63 else None,
                }
            )
        out.append(
            {
                "take": f"{key[0]}/{key[2]}/rep{key[3]}",
                "pose": pose,
                # what the gate is supposed to do through this take
                "expect": "never" if pose in CONFUSERS else "latched",
                "frames": kept,
            }
        )
        print(f"  {pose:12} {key[0]}/rep{key[3]}  {len(kept)} frames")

    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    n = sum(len(t["frames"]) for t in out)
    print(f"\nwrote {OUT.relative_to(HERE.parents[1])}: {len(out)} takes, {n} frames, {OUT.stat().st_size / 1024:.0f} KB")
    missing = [p for p in WANTED if not any(t["pose"] == p for t in out)]
    if missing:
        print(f"MISSING takes for: {', '.join(missing)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
