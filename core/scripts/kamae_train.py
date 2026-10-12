r"""Train the kamae detector on the keiko captures and export it for the HUD.

    .venv\Scripts\python scripts\kamae_train.py

Kamae is where the arms are relative to the shoulders - and how far in front of
them the hands are - so every feature is measured from the midpoint of the
shoulders in shoulder-widths: the same kamae reads the same wherever he stands.
The model is a logistic regression over those few numbers, with the
standardisation folded into its weights.

What decides whether she suits up is the WATCHER (hud/src/tracking/kamaeFeatures.ts;
Watcher below is its twin): a steady hold of both hands together, scoring high,
for 1.5 s, with hysteresis on the way out. Live, a frame-level detector fired on
almost any arm movement. So the result that counts is per TAKE: does the watcher
fire during a held kamae (it must), and during a confuser (it must not)?

Held out, never trained on:
  - with two or more sessions of a profile, its newest whole session;
  - with one, the last 30% of every hold and the last rep of every motion.
Strikes and the rise into kamae start or end IN kamae, so they are neither clean
positives nor negatives: reported, never scored.

Writes hud/src/tracking/kamaeModel.ts and hud/tests/kamae.golden.json only if the
held-out result passes. Kamae live (config/hud.json kamae.enabled) is switched on
only when the desk confusers (keiko_confusers) were part of it - without them
there is no evidence that typing, a phone or a mug won't set it off.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from irene.calibration import load  # noqa: E402

ROOT = HERE.parents[1]
OUT = ROOT / "hud" / "src" / "tracking" / "kamaeModel.ts"
GOLDEN = ROOT / "hud" / "tests" / "kamae.golden.json"
HUD_CONFIG = ROOT / "config" / "hud.json"
PROFILES = ("keiko_near", "keiko_mid", "keiko_kamae", "keiko_confusers")
DESK_CONFUSERS = "keiko_confusers"
# kamae in any of its captured forms
POSITIVE = {"kamae", "kamae_near", "kamae_mid", "kamae_turned_left", "kamae_turned_right", "kamae_high", "kamae_low", "kamae_again"}
# start or end in kamae: neither clean positive nor negative
UNSCORED = {"men", "kote", "gyaku_dou", "into_kamae"}
HOLD_KINDS = POSITIVE | {"shizentai", "arms_up", "typing", "mouse", "phone_two_hands", "mug_two_hands", "leaning_back", "arms_crossed", "chin_on_hands", "shinai_resting", "standing_natural"}
# the bar, per held-out TAKE through the watcher
MIN_KAMAE_RECALL = 0.9
MAX_CONFUSER_FIRES = 0
# and per frame, for the model itself
MAX_FRAME_FALSE_POSITIVE = 0.02
# live, the pose model runs about every third camera frame
POSE_HZ = 10.0

# MediaPipe pose indices
L_SHOULDER, R_SHOULDER, L_ELBOW, R_ELBOW, L_WRIST, R_WRIST = 11, 12, 13, 14, 15, 16

FEATURE_NAMES = [
    "lwx", "lwy", "rwx", "rwy",  # wrists
    "lex", "ley", "rex", "rey",  # elbows
    "wristGap", "wristMidX", "wristMidY",
    "wristVis", "elbowVis",
    "wristDepth", "elbowDepth",  # in front of the shoulders (negative = toward the camera)
]
GAP, MID_X, MID_Y, DEPTH = 8, 9, 10, 13

# the watcher's fixed settings; the gap and steadiness limits are fitted
WATCH = {"enter": 0.7, "exit": 0.35, "holdMs": 1500, "share": 0.9, "minSamples": 10, "releaseMs": 1000, "refireMs": 3000}


def features(body: list[float]) -> list[float] | None:
    """The feature vector for one frame's 132 numbers, or None without shoulders.
    hud/src/tracking/kamaeFeatures.ts is the same function and must stay in step."""
    if not isinstance(body, list) or len(body) != 132:
        return None
    p = [body[i * 4 : i * 4 + 4] for i in range(33)]
    ls, rs = p[L_SHOULDER], p[R_SHOULDER]
    width = ((ls[0] - rs[0]) ** 2 + (ls[1] - rs[1]) ** 2) ** 0.5
    if width < 1e-3 or min(ls[3], rs[3]) < 0.5:
        return None
    mx, my, mz = (ls[0] + rs[0]) / 2, (ls[1] + rs[1]) / 2, (ls[2] + rs[2]) / 2

    def rel(point):
        return (point[0] - mx) / width, (point[1] - my) / width

    def depth(point):
        return (point[2] - mz) / width

    lw, rw, le, re_ = rel(p[L_WRIST]), rel(p[R_WRIST]), rel(p[L_ELBOW]), rel(p[R_ELBOW])
    gap = ((lw[0] - rw[0]) ** 2 + (lw[1] - rw[1]) ** 2) ** 0.5
    return [
        lw[0], lw[1], rw[0], rw[1],
        le[0], le[1], re_[0], re_[1],
        gap, (lw[0] + rw[0]) / 2, (lw[1] + rw[1]) / 2,
        min(p[L_WRIST][3], p[R_WRIST][3]), min(p[L_ELBOW][3], p[R_ELBOW][3]),
        (depth(p[L_WRIST]) + depth(p[R_WRIST])) / 2, (depth(p[L_ELBOW]) + depth(p[R_ELBOW])) / 2,
    ]


def score(model: dict, v: list[float]) -> float:
    z = model["bias"] + sum(w * (x - m) / s for w, x, m, s in zip(model["weights"], v, model["mean"], model["scale"]))
    return 1.0 / (1.0 + np.exp(-z))


class Watcher:
    """Twin of KamaeWatcher in kamaeFeatures.ts: fires on a steady held kamae."""

    def __init__(self, model: dict):
        self.model, self.g = model, model["gate"]
        self.window: list[tuple[float, bool, float, float]] = []
        self.holding = False
        self.last_in = -1e18
        self.ended_at = -1e18

    def update(self, body, now: float) -> str | None:
        g = self.g
        f = features(body) if body else None
        p = score(self.model, f) if f else 0.0
        # both hands on the tsuka, out in front toward her: pointed at her
        together = f is not None and f[GAP] <= g["gapMax"] and f[DEPTH] <= g["depthMax"]
        if self.holding:
            if p >= g["exit"] and together:
                self.last_in = now
            if now - self.last_in > g["releaseMs"]:
                self.holding, self.ended_at = False, now
                self.window.clear()
                return "end"
            return None
        self.window.append((now, p >= g["enter"] and together, f[MID_X] if f else float("nan"), f[MID_Y] if f else float("nan")))
        while self.window and now - self.window[0][0] > g["holdMs"]:
            self.window.pop(0)
        if now - self.ended_at < g["refireMs"]:
            return None
        if len(self.window) < g["minSamples"] or now - self.window[0][0] < g["holdMs"] * 0.9:
            return None
        yes = [s for s in self.window if s[1]]
        if len(yes) / len(self.window) < g["share"]:
            return None
        if np.std([s[2] for s in yes]) > g["steadyMax"] or np.std([s[3] for s in yes]) > g["steadyMax"]:
            return None
        self.holding, self.last_in = True, now
        return "start"


def takes(frames: list[dict]) -> list[list[dict]]:
    """Frames grouped into takes: one per (profile, session, step, rep) run of
    consecutive frames - a held-out tail has no frame 0 of its own."""
    out: list[list[dict]] = []
    key = None
    for f in frames:
        k = (f.get("profile"), f["session"], f["pose"], f["rep"])
        if k != key or f["i"] == 0:
            out.append([])
            key = k
        out[-1].append(f)
    return out


def split(frames: list[dict]) -> tuple[list[dict], list[dict], str]:
    """(train, test, how), per profile: its newest whole session held out when it
    has two or more, else the tail of each hold and the last rep of each motion."""
    train, test, hows = [], [], []
    for profile in sorted({f["profile"] for f in frames}):
        mine = [f for f in frames if f["profile"] == profile]
        sessions = sorted({f["session"] for f in mine})
        if len(sessions) > 1:
            train += [f for f in mine if f["session"] != sessions[-1]]
            test += [f for f in mine if f["session"] == sessions[-1]]
            hows.append(f"{profile}: session {sessions[-1]} held out whole")
            continue
        last_rep: dict[str, int] = {}
        for take in takes(mine):
            last_rep[take[0]["pose"]] = max(last_rep.get(take[0]["pose"], 0), take[0]["rep"])
        for take in takes(mine):
            label = take[0]["pose"]
            if label in HOLD_KINDS:
                cut = int(len(take) * 0.7)
                train += take[: cut - 10]
                test += take[cut:]
            elif take[0]["rep"] == last_rep[label]:
                test += take
            else:
                train += take
        hows.append(f"{profile}: one session - tail of each hold, last rep of each motion held out")
    return train, test, "; ".join(hows)


def xy(frames: list[dict]):
    rows, ys, labels = [], [], []
    for f in frames:
        v = features(f.get("body"))
        if v is None:
            continue
        rows.append(v)
        ys.append(1 if f["pose"] in POSITIVE else 0)
        labels.append(f["pose"])
    return np.array(rows), np.array(ys), labels


def fit_gate(frames: list[dict]) -> dict:
    """The watcher's limits from his own kamae: how close his hands are on the tsuka
    and how still they are over a hold window, with a margin."""
    gaps, spreads, depths = [], [], []
    for take in takes([f for f in frames if f["pose"] in POSITIVE]):
        vs = [features(f.get("body")) for f in take]
        vs = [v for v in vs if v]
        gaps += [v[GAP] for v in vs]
        depths += [v[DEPTH] for v in vs]
        n = int(WATCH["holdMs"] / 1000 * 30)
        for k in range(0, max(1, len(vs) - n), 5):
            win = vs[k : k + n]
            if len(win) > 5:
                spreads.append(max(np.std([v[MID_X] for v in win]), np.std([v[MID_Y] for v in win])))
    # depth is negative toward the camera: kamae's hands are far out in front (the
    # captured kamae: -2.95 shoulder-widths; standing, reaching, arms up: about -1.6)
    return {
        **WATCH,
        "gapMax": round(float(np.percentile(gaps, 97)) * 1.15, 4),
        "steadyMax": round(float(np.percentile(spreads, 95)) * 1.5, 4) if spreads else 0.1,
        "depthMax": round(float(np.percentile(depths, 97)) * 0.9, 4),
    }


def by_take_fires(model: dict, frames: list[dict]) -> dict[str, list[bool]]:
    """Does the watcher fire during each take (at the live pose rate)?"""
    out: dict[str, list[bool]] = {}
    for take in takes(frames):
        w = Watcher(model)
        fired, next_t = False, -1e18
        for f in take:
            t = float(f.get("t", 0))
            if t < next_t:
                continue
            next_t = t + 1000 / POSE_HZ
            fired = (w.update(f.get("body"), t) == "start") or fired
        out.setdefault(take[0]["pose"], []).append(fired)
    return out


def main() -> int:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    frames = []
    for p in PROFILES:
        try:
            frames += [{**f, "profile": p} for f in load(p)]
        except FileNotFoundError:
            pass
    if not any(f["pose"] in POSITIVE for f in frames):
        print("no kamae frames captured - run the keiko capture first")
        return 1
    if any(isinstance(f.get("pose"), list) for f in frames):
        print("unlabelled keiko frames - run scripts/keiko_relabel.py first")
        return 1
    usable = [f for f in frames if f["pose"] not in UNSCORED]
    draft = "--draft" in sys.argv
    if draft:
        # not enough captured to hold anything out honestly: fit on all of it, write
        # it so the HUD builds, and keep kamae live OFF
        train, test, how = usable, usable, "DRAFT - fitted on everything, nothing held out"
    else:
        train, test, how = split(usable)
    X, y, _ = xy(train)
    Xt, yt, test_labels = xy(test)
    scaler = StandardScaler().fit(X)
    clf = LogisticRegression(C=0.5, class_weight="balanced", max_iter=4000).fit(scaler.transform(X), y)
    model = {
        "features": FEATURE_NAMES,
        "mean": [float(v) for v in scaler.mean_],
        "scale": [float(v) for v in scaler.scale_],
        "weights": [float(v) for v in clf.coef_[0]],
        "bias": float(clf.intercept_[0]),
        "gate": fit_gate(train),
    }
    ours = np.array([score(model, list(v)) for v in Xt])
    theirs = clf.predict_proba(scaler.transform(Xt))[:, 1]
    assert np.allclose(ours, theirs, atol=1e-9), "export does not reproduce the model"

    frame_fp = float((ours[yt == 0] >= model["gate"]["enter"]).mean())
    print(f"train {len(y)} frames ({int(y.sum())} kamae), test {len(yt)} ({int(yt.sum())} kamae)")
    print(f"held out: {how}")
    print(f"gate: hands within {model['gate']['gapMax']:.2f} shoulder-widths, steady within {model['gate']['steadyMax']:.3f}, held {model['gate']['holdMs']} ms")
    print(f"per frame, non-kamae scoring above {model['gate']['enter']}: {frame_fp:.1%}")

    fires = by_take_fires(model, test)
    kamae_takes = [x for label, v in fires.items() if label in POSITIVE for x in v]
    recall = float(np.mean(kamae_takes)) if kamae_takes else 0.0
    confuser_fires = sum(sum(v) for label, v in fires.items() if label not in POSITIVE)
    confuser_takes = sum(len(v) for label, v in fires.items() if label not in POSITIVE)
    print(f"per held-out TAKE, through the watcher: kamae caught {sum(kamae_takes)}/{len(kamae_takes)}; confusers fired {confuser_fires}/{confuser_takes}")
    for label in sorted(fires):
        v = fires[label]
        print(f"  {label:18s} takes {len(v):3d}  fired {sum(v):3d}  {'(kamae)' if label in POSITIVE else ''}")
    unscored = by_take_fires(model, [f for f in frames if f["pose"] in UNSCORED])
    if unscored:
        print("  not scored (start or end in kamae): " + ", ".join(f"{k} {sum(v)}/{len(v)}" for k, v in sorted(unscored.items())))

    passed = recall >= MIN_KAMAE_RECALL and confuser_fires <= MAX_CONFUSER_FIRES and frame_fp <= MAX_FRAME_FALSE_POSITIVE
    if not passed and not draft:
        print(f"below the bar (kamae takes >= {MIN_KAMAE_RECALL:.0%}, confuser fires <= {MAX_CONFUSER_FIRES}, frame false positives <= {MAX_FRAME_FALSE_POSITIVE:.0%}) - nothing written")
        return 1

    desk = not draft and any(f["profile"] == DESK_CONFUSERS for f in test)
    model["_about"] = (
        f"Kamae detector - core/scripts/kamae_train.py. {how}. Held out: kamae takes {recall:.2f}, "
        f"confuser fires {confuser_fires}/{confuser_takes}, frame false positives {frame_fp:.3f}."
    )
    OUT.write_text(
        "// Generated by core/scripts/kamae_train.py from the keiko captures in core/calibration.\n"
        "// Do not edit by hand - retrain after a new capture.\n//\n"
        "// Logistic regression over kamaeFeatures.ts: p = sigmoid(bias + sum(w * (x - mean) / scale)),\n"
        "// and the watcher's gate: when a HELD kamae fires (kamaeFeatures.ts KamaeWatcher).\n\n"
        "export interface KamaeGate {\n  enter: number;\n  exit: number;\n  holdMs: number;\n  share: number;\n  minSamples: number;\n"
        "  releaseMs: number;\n  refireMs: number;\n  gapMax: number;\n  steadyMax: number;\n  depthMax: number;\n}\n\n"
        "export interface KamaeModel {\n  features: string[];\n  mean: number[];\n  scale: number[];\n  weights: number[];\n  bias: number;\n  gate: KamaeGate;\n  _about: string;\n}\n\n"
        f"export const KAMAE_MODEL: KamaeModel = {json.dumps(model, indent=2)};\n",
        encoding="utf-8",
    )
    sample = [f for f in frames if features(f.get("body")) is not None][::97]
    GOLDEN.write_text(
        json.dumps([{"body": f["body"], "features": features(f["body"]), "p": score(model, features(f["body"]))} for f in sample]),
        encoding="utf-8",
    )
    print(f"wrote {OUT.name} and {GOLDEN.name} ({len(sample)} golden frames)")
    config = json.loads(HUD_CONFIG.read_text(encoding="utf-8"))
    if desk:
        config["kamae"]["enabled"] = True
        print("kamae live: ON - the desk confusers were held out and never fired")
    else:
        config["kamae"]["enabled"] = False
        print(f"kamae live: OFF - no {DESK_CONFUSERS} session held out yet; record it (ctrl+alt+shift+7) and retrain")
    HUD_CONFIG.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
