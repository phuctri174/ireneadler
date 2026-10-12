"""Compare summon-capture metrics between the parallel and crossed poses.

Run: .venv\\Scripts\\python scripts\\summon_analyze.py [core/calibration/summon-<session>.jsonl]
(default: the newest capture)

For each metric, over frames with a hand in view:
  range     min..max per pose
  margin    worst-case gap: the crossed pose's least-crossed frame vs the parallel
            pose's most-crossed frame (positive = cleanly separable)
  best      the single threshold that classifies the most frames, and its accuracy
  d'        separation of the means in pooled standard deviations
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

DIR = Path(__file__).resolve().parents[1] / "calibration"
NUMERIC = [
    "cross", "tipGap", "knuckleGap", "ratio", "tipGapPalm", "knuckleGapPalm",
    "boneTipT", "boneTipU", "boneTipGap", "boneDipT", "boneDipU", "boneDipGap",
    "thumb", "index", "middle", "ring", "pinky",
]
BOOLEAN = ["boneTipCross", "boneDipCross", "summon"]


def load(path: Path) -> dict[str, list[dict]]:
    by_pose: dict[str, list[dict]] = {"parallel": [], "crossed": []}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("hand") and row.get("pose") in by_pose:
            by_pose[row["pose"]].append(row)
    return by_pose


def best_threshold(a: list[float], b: list[float]) -> tuple[float, float, str]:
    """Threshold and direction that best splits a (parallel) from b (crossed)."""
    values = sorted(set(a + b))
    best = (0.0, 0.0, ">")
    total = len(a) + len(b)
    for i in range(len(values) - 1):
        cut = (values[i] + values[i + 1]) / 2
        above = (sum(v <= cut for v in a) + sum(v > cut for v in b)) / total
        below = (sum(v > cut for v in a) + sum(v <= cut for v in b)) / total
        if above > best[1]:
            best = (cut, above, ">")
        if below > best[1]:
            best = (cut, below, "<")
    return best


def analyse(by_pose: dict[str, list[dict]]) -> list[dict]:
    rows = []
    par, crs = by_pose["parallel"], by_pose["crossed"]
    for key in NUMERIC:
        a = [r[key] for r in par if key in r]
        b = [r[key] for r in crs if key in r]
        if len(a) < 3 or len(b) < 3:
            continue
        cut, acc, direction = best_threshold(a, b)
        # margin in the direction crossed is supposed to lie
        margin = (min(b) - max(a)) if direction == ">" else (min(a) - max(b))
        sd = statistics.pstdev(a + b) or 1e-9
        pooled = ((statistics.pvariance(a) + statistics.pvariance(b)) / 2) ** 0.5 or 1e-9
        rows.append({
            "metric": key,
            "parallel": (min(a), statistics.median(a), max(a)),
            "crossed": (min(b), statistics.median(b), max(b)),
            "margin": margin,
            "margin_sd": margin / sd,
            "threshold": cut,
            "direction": direction,
            "accuracy": acc,
            "d_prime": abs(statistics.mean(b) - statistics.mean(a)) / pooled,
        })
    for key in BOOLEAN:
        a = [bool(r.get(key)) for r in par]
        b = [bool(r.get(key)) for r in crs]
        if not a or not b:
            continue
        acc = (sum(not v for v in a) + sum(b)) / (len(a) + len(b))
        rows.append({"metric": key, "true_parallel": sum(a) / len(a), "true_crossed": sum(b) / len(b), "accuracy": acc})
    return rows


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else max(DIR.glob("summon-*.jsonl"), key=lambda p: p.stat().st_mtime)
    by_pose = load(path)
    print(f"{path.name}: {len(by_pose['parallel'])} parallel, {len(by_pose['crossed'])} crossed frames with a hand\n")
    rows = analyse(by_pose)
    numeric = sorted((r for r in rows if "margin" in r), key=lambda r: (r["accuracy"], r["margin_sd"]), reverse=True)
    print(f"{'metric':15} {'parallel min/med/max':>24} {'crossed min/med/max':>24} {'margin':>8} {'margin/sd':>9} {'best cut':>12} {'acc':>6} {'d-prime':>7}")
    for r in numeric:
        p, c = r["parallel"], r["crossed"]
        print(
            f"{r['metric']:15} {p[0]:7.3f}/{p[1]:7.3f}/{p[2]:7.3f} {c[0]:7.3f}/{c[1]:7.3f}/{c[2]:7.3f} "
            f"{r['margin']:8.3f} {r['margin_sd']:9.2f} {r['direction']}{r['threshold']:10.3f} {r['accuracy']:6.1%} {r['d_prime']:7.2f}"
        )
    print()
    for r in (r for r in rows if "true_crossed" in r):
        print(f"{r['metric']:15} true on parallel {r['true_parallel']:6.1%}   true on crossed {r['true_crossed']:6.1%}   acc {r['accuracy']:6.1%}")


if __name__ == "__main__":
    main()
