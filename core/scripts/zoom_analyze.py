r"""Score the zoom gate against the captured sessions, retune it, and compare a
learned classifier against it on a held-out session.

    .venv\Scripts\python scripts\zoom_analyze.py [--holdout zoom_mid-<session>]

What counts as right, per take:
  spread / fist          a held zoom pose - zoom should be latched
  zoom_in / zoom_out     a zoom being performed - zoom should stay latched
  (and their _fast)      throughout, including the middle of the motion
  confusers              relaxed, pointing, scroll_pose, waving, scratching:
                         zoom must never latch

Frames with no hand are skipped: the gate has nothing to decide on them. Each take
is replayed warm (scripts/zoom_replay.py), starting where the live engine already
was, so a take is not punished for the latch it inherited.
"""
from __future__ import annotations

import argparse
import collections
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))  # core/, for the irene package

from irene.calibration import load_family  # noqa: E402
from zoom_replay import NAMES, Thresholds, ZoomGate, run_clip  # noqa: E402

HOLDS = ("spread", "fist")
MOTIONS = ("zoom_in", "zoom_in_fast", "zoom_out", "zoom_out_fast")
CONFUSERS = ("relaxed", "pointing", "scroll_pose", "waving", "scratching", "still_open", "pointer_moving")
ZOOM_POSES = HOLDS + MOTIONS
# a false latch shorter than this is a blip the gate corrects itself, not a zoom
FALSE_ZOOM_MS = 300.0


def report_gaps(runs: list[tuple[str, str]]) -> bool:
    """Say out loud what is not in the captures. A session missing steps was
    recorded against an older copy of the profile - the HUD imports it at startup
    - and a pose that is in no session at all is a pose the classifier will guess
    at. Returns True if anything is missing."""
    from irene.calibration import incomplete

    bad = False
    for profile in ("zoom_near", "zoom_mid", "zoom_far"):
        if not any(r[0] == profile for r in runs):
            print(f"  not captured: {profile}")
            continue
        for session, missing in incomplete(profile).items():
            bad = True
            print(f"  INCOMPLETE {profile} {session}: never recorded {', '.join(missing)}")
    seen = set()
    for profile, _ in runs:
        seen |= {f["pose"] for f in load_family("zoom") if f["profile"] == profile}
    never = [p for p in CONFUSERS if p not in seen]
    if never:
        bad = True
        print(f"  NOT IN ANY SESSION: {', '.join(never)} - the classifier has never seen these")
    return bad


def clips(frames: list[dict]) -> dict[tuple, list[dict]]:
    """Frames grouped into takes, each in capture order."""
    out: dict[tuple, list[dict]] = collections.defaultdict(list)
    for f in frames:
        out[(f["profile"], f["session"], f["pose"], f.get("rep", 0))].append(f)
    for take in out.values():
        take.sort(key=lambda f: f.get("i", 0))
    return dict(out)


def wanted(pose: str) -> bool:
    """Should the zoom gate be latched through this take?"""
    return pose in ZOOM_POSES




class Score:
    """Per-frame accuracy, split the ways that matter."""

    def __init__(self) -> None:
        self.n = collections.Counter()
        self.right = collections.Counter()
        self.dropouts = 0
        self.dropout_frames = 0
        self.false_clips = 0
        self.worst_false_ms = 0.0
        self.confuser_clips = 0
        self.tracked = 0

    def add_clip(self, pose: str, decisions: list[bool], frames: list[dict]) -> None:
        group = "hold" if pose in HOLDS else "motion" if pose in MOTIONS else "confuser"
        want = wanted(pose)
        live = [(z, f) for z, f in zip(decisions, frames) if f.get("hand")]
        if not live:
            return
        for z, _ in live:
            self.n[group] += 1
            self.right[group] += z == want
        if group == "confuser":
            self.confuser_clips += 1
            # the longest unbroken false latch, in ms - a take is only counted as a
            # false zoom if one lasted long enough to act on. A take is a slice out
            # of a running session, so the first frames may have inherited a latch
            # the gate is still in the middle of releasing; what matters is whether
            # it fires on its own during the take.
            longest = run = 0.0
            start = None
            for z, f in live:
                if z:
                    start = float(f.get("ts") or 0.0) if start is None else start
                    run = float(f.get("ts") or 0.0) - start
                    longest = max(longest, run)
                else:
                    start, run = None, 0.0
            self.worst_false_ms = max(getattr(self, "worst_false_ms", 0.0), longest)
            self.false_clips += longest >= FALSE_ZOOM_MS
        if group == "motion":
            # a dropout is a run of un-latched frames inside a zoom that was latched
            runs = 0
            prev = True
            for z, _ in live:
                if not z and prev:
                    runs += 1
                if not z:
                    self.dropout_frames += 1
                prev = z
            self.dropouts += runs

    def accuracy(self, group: str | None = None) -> float:
        if group:
            return self.right[group] / self.n[group] if self.n[group] else float("nan")
        total = sum(self.n.values())
        return sum(self.right.values()) / total if total else float("nan")

    def line(self, label: str) -> str:
        return (
            f"{label:22} overall {self.accuracy():6.2%}  "
            f"holds {self.accuracy('hold'):6.2%}  motions {self.accuracy('motion'):6.2%}  "
            f"confusers {self.accuracy('confuser'):6.2%}  "
            f"false zooms {self.false_clips}/{self.confuser_clips} takes (worst {self.worst_false_ms:.0f}ms)  "
            f"mid-motion dropouts {self.dropouts}"
        )


def score(takes: dict[tuple, list[dict]], thresholds: Thresholds) -> Score:
    s = Score()
    for (_, _, pose, _), frames in takes.items():
        decisions = [z for z, _ in run_clip(frames, thresholds)]
        s.add_clip(pose, decisions, frames)
    return s


def factor_tracking(takes: dict[tuple, list[dict]], thresholds: Thresholds, decide=None) -> tuple[int, int, list[str]]:
    """Does zoomFactor actually move the right way across each in/out take?
    Returns (tracked, total, the takes that did not). `decide` swaps in another
    gate's latch decisions while keeping the same factor arithmetic."""
    ok = total = 0
    missed = []
    for (profile, session, pose, rep), frames in takes.items():
        if pose not in MOTIONS:
            continue
        out = run_clip(frames, thresholds, latched=decide(frames) if decide else None)
        factors = [fac for (z, fac), f in zip(out, frames) if z and f.get("hand")]
        total += 1
        if len(factors) < 10:
            missed.append(f"{profile}/{pose}/rep{rep}: latched for only {len(factors)} frames")
            continue
        # compare the settled ends rather than single frames
        head = float(np.median(factors[:5]))
        tail = float(np.median(factors[-5:]))
        swing = tail - head
        want_up = pose.startswith("zoom_in")
        if (swing > 0.08) == want_up and abs(swing) > 0.08:
            ok += 1
        else:
            missed.append(f"{profile}/{pose}/rep{rep}: factor {head:.2f} -> {tail:.2f} ({swing:+.2f})")
    return ok, total, missed


# ---- the learned alternative ---------------------------------------------------

def shape(frame: dict) -> list[float]:
    """The hand's shape on one frame, scale-free: the finger metrics the thresholds
    already use, plus landmark geometry they do not."""
    lm = frame.get("lm")
    base = [float(frame.get(n) or 0.0) for n in NAMES]
    base += [float(frame.get(k) or 0.0) for k in ("spread", "ratio", "tipGapPalm", "knuckleGapPalm", "palmSpan")]
    if not isinstance(lm, list) or len(lm) != 63:
        return base + [0.0] * 8
    p = np.asarray(lm, dtype=float).reshape(21, 3)
    wrist = p[0]
    span = float(np.linalg.norm(p[9] - wrist)) or 1.0
    tips = p[[4, 8, 12, 16, 20]]
    mcp = p[[2, 5, 9, 13, 17]]
    # how far each tip is from the wrist, in palms: a fist collapses these together
    reach = np.linalg.norm(tips - wrist, axis=1) / span
    # how far the tips are from each other: a deliberate spread fans them out
    fan = float(np.mean([np.linalg.norm(tips[i] - tips[i + 1]) for i in range(4)])) / span
    curl = float(np.mean(np.linalg.norm(tips - mcp, axis=1))) / span
    return base + list(reach) + [fan, curl, float(np.std(reach))]


# How far back the motion features look. A wave is roughly two swings a second, so
# a window has to be long enough to contain a whole one - 200 ms sees only a
# half-swing, which looks exactly like a hand being moved into place.
WINDOW = 15

# The feature vector, in order. hud/src/tracking/zoomFeatures.ts builds the same
# vector live; core/tests/test_zoom_model.py checks the two agree.
FEATURE_NAMES = (
    "thumb", "index", "middle", "ring", "pinky",
    "spread", "ratio", "tipGapPalm", "knuckleGapPalm", "palmSpan",
    "reachThumb", "reachIndex", "reachMiddle", "reachRing", "reachPinky",
    "fan", "curl", "reachSpread",
    "travel", "swing", "rise", "reversals", "fingerRate", "drift",
)


def hand_xy(frame: dict) -> tuple[float, float]:
    """Where the hand is, from the wrist landmark.

    NOT the cursor (cx, cy): the cursor only tracks while a pointing pose is live,
    so during a wave, a spread or a zoom it sits perfectly still. Measured on the
    captures, cursor travel was 0.000 for waving - the one pose that moves most -
    while the wrist reads 0.518 against 0.03-0.05 for the poses that hold still.
    """
    lm = frame.get("lm")
    if isinstance(lm, list) and len(lm) == 63:
        return float(lm[0]), float(lm[1])
    return 0.0, 0.0


def take_features(frames: list[dict]) -> np.ndarray:
    """Features for a whole take, so each frame can see the few before it.

    Shape alone cannot tell a deliberate spread from a wave - both are open hands -
    so the classifier also gets how the hand is moving: a wave swings the whole hand
    across the frame while the fingers hold still, a zoom holds the hand still while
    the fingers open or close.
    """
    rows = []
    for i, f in enumerate(frames):
        past = frames[max(0, i - WINDOW) : i + 1]
        xy = [hand_xy(p) for p in past]
        cx = np.array([p[0] for p in xy])
        cy = np.array([p[1] for p in xy])
        sp = np.array([float(p.get("spread") or 0.0) for p in past])
        ts = np.array([float(p.get("ts") or 0.0) for p in past])
        dt = max((ts[-1] - ts[0]) / 1000.0, 1e-3) if len(ts) > 1 else 1e-3
        # travel of the hand centre, its side-to-side swing, and how fast the
        # fingers themselves are changing
        travel = float(np.sum(np.hypot(np.diff(cx), np.diff(cy)))) / dt if len(cx) > 1 else 0.0
        swing = float(np.ptp(cx)) / dt if len(cx) > 1 else 0.0
        rise = float(np.ptp(cy)) / dt if len(cy) > 1 else 0.0
        reversals = float(np.sum(np.diff(np.sign(np.diff(cx))) != 0)) if len(cx) > 2 else 0.0
        finger_rate = float(np.ptp(sp)) / dt if len(sp) > 1 else 0.0
        drift = float(sp[-1] - sp[0]) / dt if len(sp) > 1 else 0.0
        rows.append(shape(f) + [travel, swing, rise, reversals, finger_rate, drift])
    return np.asarray(rows, dtype=np.float32)


def dataset(takes: dict[tuple, list[dict]]) -> tuple[np.ndarray, np.ndarray]:
    X, y = [], []
    for key, frames in takes.items():
        feats = take_features(frames)
        for f, row in zip(frames, feats):
            if not f.get("hand"):
                continue
            X.append(row)
            y.append(1 if wanted(key[2]) else 0)
    return np.asarray(X, dtype=np.float32), np.asarray(y)


class LearnedGate:
    """The classifier standing in for the uniformity test, with the same hold and
    release timing wrapped round it - so the comparison is about the decision the
    gate makes, not about the smoothing on either side of it."""

    def __init__(self, model, scaler, thresholds: Thresholds, cut: float = 0.5):
        self.model, self.scaler, self.t, self.cut = model, scaler, thresholds, cut

    def run(self, frames: list[dict]) -> list[bool]:
        if not frames:
            return []
        probs = self.model.predict_proba(self.scaler.transform(take_features(frames)))[:, 1]
        gate = ZoomGate(self.t)
        gate.seed_from(frames[0])
        out = []
        for f, prob in zip(frames, probs):
            if not f.get("hand"):
                gate.reset()
                out.append(False)
                continue
            good = bool(prob >= self.cut)
            # the classifier answers "is this a zoom pose"; the timing is unchanged
            out.append(gate._pose(good, good, False, 0.0, float(f.get("ts") or 0.0), True))
        return out


def score_learned(takes: dict[tuple, list[dict]], gate: LearnedGate) -> Score:
    s = Score()
    for (_, _, pose, _), frames in takes.items():
        s.add_clip(pose, gate.run(frames), frames)
    return s


def per_pose(takes: dict[tuple, list[dict]], decide) -> dict[str, tuple[int, int]]:
    """How each pose fares: (frames decided right, frames)."""
    out: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    for key, frames in takes.items():
        pose = key[2]
        want = wanted(pose)
        for z, f in zip(decide(frames), frames):
            if not f.get("hand"):
                continue
            out[pose][1] += 1
            out[pose][0] += z == want
    return {k: (v[0], v[1]) for k, v in out.items()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdout", default=None, help="session to keep for testing (default: the last one captured)")
    args = parser.parse_args()

    frames = load_family("zoom")
    if not frames:
        print("no zoom captures in core/calibration - run ctrl+alt+shift+1/2/3 first")
        return 1
    takes = clips(frames)
    runs = sorted({(f["profile"], f["session"]) for f in frames})
    print(f"{len(frames)} frames, {len(takes)} takes, {len(runs)} sessions")
    for profile, session in runs:
        n = sum(1 for f in frames if f["profile"] == profile and f["session"] == session)
        print(f"  {profile:10} {session}  {n} frames")
    report_gaps(runs)

    held = args.holdout or f"{runs[-1][0]}-{runs[-1][1]}"
    train = {k: v for k, v in takes.items() if f"{k[0]}-{k[1]}" != held}
    test = {k: v for k, v in takes.items() if f"{k[0]}-{k[1]}" == held}
    if not test:
        print(f"holdout {held!r} matched nothing")
        return 1
    print(f"\nheld out for testing: {held}  ({sum(len(v) for v in test.values())} frames, {len(test)} takes)")
    print(f"training on         : {sum(len(v) for v in train.values())} frames, {len(train)} takes\n")

    base = Thresholds()
    today = lambda fr: [z for z, _ in run_clip(fr, base)]  # noqa: E731
    print("== (0) today's thresholds ==")
    print(" ", score(train, base).line("train"))
    print(" ", score(test, base).line("HELD OUT"))
    show_per_pose(test, today)

    print("\n== (a) retuned thresholds ==")
    best, tried = search(train)
    print(f"  searched {tried} combinations; best on train:")
    for k, v in sorted(asdict(best).items()):
        if v != getattr(base, k):
            print(f"    {k}: {getattr(base, k)} -> {round(v, 4)}")
    retuned = lambda fr: [z for z, _ in run_clip(fr, best)]  # noqa: E731
    print(" ", score(train, best).line("train"))
    print(" ", score(test, best).line("HELD OUT"))
    show_per_pose(test, retuned)

    print("\n== (b) a small learned classifier ==")
    learned = train_classifier(train, best)
    # the classifier calls mid-motion frames zoom itself, so it does not need the
    # transit grace the thresholds needed - and carrying one would only keep a false
    # latch on a wave alive longer. Tune its timing on the training takes.
    wrap, wrap_score = None, -1.0
    for hold in (250.0, 400.0, 550.0):
        for invalid in (150.0, 200.0, 300.0):
            for transit in (0.0, 300.0):
                cand = Thresholds(hold_ms=hold, invalid_grace_ms=invalid, transit_grace_ms=transit)
                learned.t = cand
                s = score_learned(train, learned)
                value = (s.accuracy("hold") + s.accuracy("motion") + 2 * s.accuracy("confuser")) / 4
                if value > wrap_score:
                    wrap, wrap_score = cand, value
    learned.t = wrap
    print(f"  timing around it: hold {wrap.hold_ms:.0f}ms, release grace {wrap.invalid_grace_ms:.0f}ms, transit grace {wrap.transit_grace_ms:.0f}ms")
    print(" ", score_learned(train, learned).line("train"))
    print(" ", score_learned(test, learned).line("HELD OUT"))
    show_per_pose(test, learned.run)

    print("\n== zoomFactor tracking, on the held-out session ==")
    for name, thresholds, decide in (("today", base, today), ("retuned", best, retuned), ("learned", best, learned.run)):
        ok, total, missed = factor_tracking(test, thresholds, decide)
        print(f"  {name:8} tracks {ok}/{total} in/out takes")
        for m in missed[:4]:
            print(f"      - {m}")
        if len(missed) > 4:
            print(f"      ... and {len(missed) - 4} more")
    return 0


def show_per_pose(takes, decide) -> None:
    """Per-pose accuracy on whichever set is passed in - held out, normally."""
    rows = per_pose(takes, decide)
    order = [p for p in ZOOM_POSES + CONFUSERS if p in rows]
    print("    held out: " + "  ".join(f"{p}={rows[p][0] / rows[p][1]:.0%}" for p in order))


def search(train: dict[tuple, list[dict]]) -> tuple[Thresholds, int]:
    """Grid over the knobs that matter, scored on training takes only.

    The score weighs a false zoom on a confuser as heavily as a dropped one, since
    both are what makes zoom feel unreliable - one fires when he did not ask, the
    other quits in the middle of the gesture he did ask for."""
    best, best_score, tried = Thresholds(), -1.0, 0
    for open_finger in (0.15, 0.22, 0.30, 0.38):
        for closed_finger in (0.02, 0.05, 0.08):
            for spread_closed in (0.5, 0.6):
                for hold in (250.0, 400.0):
                    for transit in (0.0, 400.0, 800.0, 1500.0):
                        cand = Thresholds(
                            open_finger=open_finger,
                            open_finger_release=open_finger * 0.55,
                            closed_finger=closed_finger,
                            closed_finger_release=closed_finger + 0.07,
                            spread_closed=spread_closed,
                            hold_ms=hold,
                            transit_grace_ms=transit,
                        )
                        s = score(train, cand)
                        tried += 1
                        # balance the three groups rather than letting the biggest win
                        value = (s.accuracy("hold") + s.accuracy("motion") + 2 * s.accuracy("confuser")) / 4
                        if value > best_score:
                            best, best_score = cand, value
    return best, tried


def train_classifier(train: dict[tuple, list[dict]], thresholds: Thresholds) -> LearnedGate:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler

    X, y = dataset(train)
    scaler = StandardScaler().fit(X)
    model = HistGradientBoostingClassifier(max_depth=4, max_iter=150, learning_rate=0.1, random_state=0)
    model.fit(scaler.transform(X), y)
    print(f"  trained on {len(X)} frames, {X.shape[1]} features, {int(y.sum())} of them zoom")
    return LearnedGate(model, scaler, thresholds)


if __name__ == "__main__":
    raise SystemExit(main())
