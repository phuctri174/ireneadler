"""scripts/zoom_eval.py replays the HUD's zoom gate to decide whether a retrain
ships: its "strict" timing has to be the one gestures.ts runs, or the verdict is
about a different gate."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))  # the repo root: the real tools package
sys.path.insert(0, str(ROOT / "core" / "scripts"))


def _const(name: str) -> float:
    text = (ROOT / "hud" / "src" / "tracking" / "gestures.ts").read_text(encoding="utf-8")
    return float(re.search(rf"export const {name} = ([0-9.]+);", text).group(1))


def test_the_strict_gate_is_the_one_the_hud_runs():
    from zoom_eval import GATES

    g = GATES["strict"]
    assert g.hold_ms == _const("ZOOM_HOLD_MS")
    assert g.entry_score == _const("ZOOM_ENTRY_SCORE")
    assert g.uniform_grace_ms == _const("ZOOM_UNIFORM_GRACE_MS")
    assert g.invalid_grace_ms == _const("ZOOM_INVALID_GRACE_MS")
    # and it is stricter than what shipped before: longer hold, a confident entry
    assert g.hold_ms >= 2 * GATES["live"].hold_ms and g.entry_score > GATES["live"].entry_score


def test_a_still_hand_frame_run_needs_the_whole_confident_hold():
    from zoom_eval import GATES, run_gate

    gate = GATES["strict"]
    frames = [{"hand": True, "ts": 1000 + i * 33.0} for i in range(60)]
    # scores just past the line (the old entry) never latch the strict gate
    assert not any(run_gate(frames, [0.5] * 60, gate))
    # confident scores latch only once the hold has run
    out = run_gate(frames, [3.0] * 60, gate)
    first = out.index(True)
    assert frames[first]["ts"] - 1000 >= gate.hold_ms
    # one dip below the entry score longer than the grace resets the hold
    scores = [3.0] * 15 + [1.0] * 3 + [3.0] * 42
    out = run_gate(frames, scores, gate)
    assert frames[out.index(True)]["ts"] - 1000 >= 18 * 33.0 + gate.hold_ms
