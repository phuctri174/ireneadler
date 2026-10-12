r"""Pitch variation of every rendered candidate: F0 standard deviation per line
(Praat's pitch tracker via parselmouth, voiced frames only), in Hz and in
semitones - the objective "not monotone" measure. Reads
core/voice_samples/expressive/<model>/*.wav (+ timing.json), prints a table and
writes metrics.json next to them.

Run from core/: .venv\Scripts\python scripts\expressive\metrics.py
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

import numpy as np
import parselmouth

ROOT = Path(__file__).resolve().parents[2] / "voice_samples" / "expressive"


def f0(path: Path) -> np.ndarray:
    snd = parselmouth.Sound(str(path))
    # an adult female voice: 100-500 Hz covers speech, gasps and laughs
    pitch = snd.to_pitch(time_step=0.01, pitch_floor=100, pitch_ceiling=500)
    values = pitch.selected_array["frequency"]
    return values[values > 0]


def main() -> None:
    table = {}
    for folder in sorted(p for p in ROOT.iterdir() if p.is_dir()):
        wavs = sorted(folder.glob("*.wav"))
        if not wavs:
            continue
        timing = json.loads((folder / "timing.json").read_text(encoding="utf-8")) if (folder / "timing.json").exists() else {}
        rows = {}
        for w in wavs:
            hz = f0(w)
            if len(hz) < 10:
                continue
            st = 12 * np.log2(hz / np.median(hz))
            rows[w.stem] = {"f0_std_hz": round(float(np.std(hz)), 1), "f0_std_st": round(float(np.std(st)), 2), "f0_range_st": round(float(np.percentile(st, 95) - np.percentile(st, 5)), 1)}
        ttfa = [v["ttfa_ms"] for v in timing.get("lines", {}).values()]
        table[folder.name] = {
            "lines": rows,
            "mean_f0_std_hz": round(statistics.mean(r["f0_std_hz"] for r in rows.values()), 1),
            "mean_f0_std_st": round(statistics.mean(r["f0_std_st"] for r in rows.values()), 2),
            "ttfa_p50_ms": round(statistics.median(ttfa)) if ttfa else None,
            "ttfa_max_ms": max(ttfa) if ttfa else None,
            "vram_mb": timing.get("vram_mb"),
        }
    (ROOT / "metrics.json").write_text(json.dumps(table, indent=1), encoding="utf-8")
    print(f"{'model':20} {'F0 sd Hz':>9} {'F0 sd st':>9} {'TTFA p50':>9} {'TTFA max':>9} {'VRAM MB':>8}")
    for name, t in table.items():
        print(f"{name:20} {t['mean_f0_std_hz']:9} {t['mean_f0_std_st']:9} {str(t['ttfa_p50_ms']):>9} {str(t['ttfa_max_ms']):>9} {str(t['vram_mb']):>8}")
        print("   " + "  ".join(f"{k}:{v['f0_std_st']}" for k, v in t["lines"].items()))


if __name__ == "__main__":
    main()
