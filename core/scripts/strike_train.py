r"""Train the keiko strike recogniser (men, kote, gyaku-dou) on his captures, for the HUD.

    .venv\Scripts\python scripts\strike_train.py

Reads every keiko capture there is (core/calibration/keiko_*.jsonl: keiko_strikes -
ctrl+alt+shift+9 - plus keiko_near / keiko_mid / keiko_kamae / keiko_confusers if
recorded). The features and the watcher are irene/strikes.py (the HUD's twin is
hud/src/tracking/strikeFeatures.ts).

Labels. A strike take is three or four seconds: kamae, the strike, back to kamae.
Only the strike itself is the strike: the windows that END just after the take's
own fastest movement of the hands (its apex). The rest of a strike take is left
out - the raise and the follow-through look like the strike for a second either
side (the first capture showed it). Every frame of every other take (kamae holds,
the confusers) is "none".

The model: a softmax regression over the window features, class-balanced, L2.

The gate - fitted here, never by hand: the watcher judges each peak of hand speed
over speedMin (half his slowest training strike's apex), once, a moment after it;
a class fires when it is the top one AND over its threshold. Each threshold is the
highest that class ever scored on a window of a confuser or hold take in training
(so no training confuser would fire it), nudged up by the spread of those scores. The "clean"
mark (an ippon-worthy strike) is the median peak of correctly fired training strikes.

Held out, never trained on - the whole newest session of a profile when it has two
or more; otherwise the last rep of every motion and the tail of every hold. It
ships (hud/src/tracking/strikeModel.ts and hud/tests/strike.golden.json) only if,
held out, NO confuser take fires and at least 75% of strike takes fire their own
strike and nothing else.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from irene import strikes  # noqa: E402
from irene.calibration import load  # noqa: E402

ROOT = HERE.parents[1]
OUT_TS = ROOT / "hud" / "src" / "tracking" / "strikeModel.ts"
OUT_GOLDEN = ROOT / "hud" / "tests" / "strike.golden.json"
PROFILES = ("keiko_strikes", "keiko_near", "keiko_mid", "keiko_kamae", "keiko_confusers")
# a capture's step label -> the strike it is (variants of one strike are that strike)
STRIKE_OF = {
    "men": "men", "men_small": "men", "men_fast": "men", "men_step": "men",
    "kote": "kote", "kote_small": "kote", "kote_fast": "kote", "kote_step": "kote",
    "gyaku_dou": "gyaku_dou", "gyaku_dou_fast": "gyaku_dou", "gyaku_dou_step": "gyaku_dou",
}
HOLD_KINDS = {"kamae", "shizentai", "arms_up", "shinai_resting", "standing_natural", "typing", "mouse",
              "phone_two_hands", "mug_two_hands", "leaning_back", "arms_crossed", "chin_on_hands",
              "kamae_near", "kamae_mid", "kamae_turned_left", "kamae_turned_right", "kamae_high", "kamae_low", "kamae_again",
              "kamae_hold", "chudan_hold", "jodan_hold"}
APEX_BEFORE_MS, APEX_AFTER_MS = 0.0, 350.0      # positive: window ends this close after the apex
REST_MS = 900.0
L2 = 1e-2


def takes(frames: list[dict]) -> list[list[dict]]:
    out: list[list[dict]] = []
    key = None
    for f in frames:
        k = (f.get("profile"), f["session"], f["pose"], f["rep"])
        if k != key or f["i"] == 0:
            out.append([])
            key = k
        out[-1].append(f)
    return out


def split(frames: list[dict]) -> tuple[list[list[dict]], list[list[dict]], list[str]]:
    train, test, how = [], [], []
    for profile in sorted({f["profile"] for f in frames}):
        mine = [f for f in frames if f["profile"] == profile]
        sessions = sorted({f["session"] for f in mine})
        if len(sessions) > 1:
            train += takes([f for f in mine if f["session"] != sessions[-1]])
            test += takes([f for f in mine if f["session"] == sessions[-1]])
            how.append(f"{profile}: session {sessions[-1]} held out whole")
            continue
        last: dict[str, int] = {}
        for take in takes(mine):
            last[take[0]["pose"]] = max(last.get(take[0]["pose"], 0), take[0]["rep"])
        for take in takes(mine):
            label = take[0]["pose"]
            if label in HOLD_KINDS:
                cut = int(len(take) * 0.7)
                train.append(take[: max(0, cut - 10)])
                test.append(take[cut:])
            elif take[0]["rep"] == last[label] and (last[label] > 0 or label in STRIKE_OF):
                test.append(take)
            else:
                train.append(take)
        how.append(f"{profile}: one session - last rep of each motion, tail of each hold held out")
    return [t for t in train if t], [t for t in test if t], how


def speed_track(take: list[dict]) -> list[tuple[float, float]]:
    """(time, the watcher's 3-sample average hand speed) through a take."""
    out, last, recent = [], None, []
    for f in take:
        v = strikes.frame(f.get("body") or [])
        if v is None:
            continue
        cur = (float(f["t"]), v)
        if last is not None:
            recent = (recent + [strikes.hand_speed(last, cur)])[-3:]
            out.append((cur[0], sum(recent) / len(recent)))
        last = cur
    return out


def apex(take: list[dict]) -> float | None:
    """When the hands moved fastest in this take (ms)."""
    track = speed_track(take)
    return max(track, key=lambda x: x[1])[0] if len(track) >= 5 else None


def raise_peaks(take: list[dict], peak: float) -> list[float]:
    """The fast moments before a strike's apex (the raise): local speed maxima at
    least 300 ms before it, at least a third of its speed."""
    track = speed_track(take)
    top = max(s for _, s in track)
    return [track[k][0] for k in range(1, len(track) - 1)
            if track[k][1] >= track[k - 1][1] and track[k][1] >= track[k + 1][1]
            and track[k][1] >= top / 3 and track[k][0] <= peak - 300]


def windows(take: list[dict]) -> list[tuple[list[float], str, float]]:
    """(features, label, t) for each frame of a take where the window is covered."""
    label = take[0]["pose"]
    strike = STRIKE_OF.get(label)
    peak = apex(take) if strike else None
    raises = raise_peaks(take, peak) if peak is not None else []
    samples: list[tuple[float, list[float] | None]] = []
    out = []
    for f in take:
        t = float(f["t"])
        samples.append((t, strikes.frame(f.get("body") or [])))
        v = strikes.window(samples, t)
        if v is None:
            continue
        if strike is None:
            out.append((v, "none", t))
        elif peak is not None:
            if peak + APEX_BEFORE_MS <= t <= peak + APEX_AFTER_MS:
                out.append((v, strike, t))
            elif any(r + APEX_BEFORE_MS <= t <= r + APEX_AFTER_MS for r in raises):
                # the raise before it: fast, but not the strike
                out.append((v, "none", t))
            # the rest of a strike take is the raise before it and the follow-through
            # after it - on the first capture these scored as strikes a full second from
            # the apex - so it is neither: kamae and the confusers supply "none"
    return out


def fit(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-6] = 1.0
    xs = (x - mean) / scale
    k = len(strikes.CLASSES)
    counts = np.bincount(y, minlength=k).astype(float)
    weight = (len(y) / (k * np.maximum(counts, 1)))[y]
    w = np.zeros((k, xs.shape[1]))
    b = np.zeros(k)
    onehot = np.eye(k)[y]
    lr = 0.5
    for step in range(3000):
        z = xs @ w.T + b
        z -= z.max(axis=1, keepdims=True)
        p = np.exp(z)
        p /= p.sum(axis=1, keepdims=True)
        g = (p - onehot) * weight[:, None] / len(y)
        w -= lr * (g.T @ xs + L2 * w)
        b -= lr * g.sum(axis=0)
    return mean, scale, w, b


def take_result(model: dict, take: list[dict]) -> list[str]:
    """The strikes the watcher fires during a take, at the camera's own rate."""
    watch = strikes.Watcher(model)
    fired = []
    for f in take:
        got = watch.update(f.get("body"), float(f["t"]))
        if got:
            fired.append(got[0])
    # a take ends where the capture stopped, not where he did: the watcher's answer
    # comes a moment after the strike, so it keeps watching (no body) for a while
    end = float(take[-1]["t"])
    for k in range(1, 46):
        got = watch.update(None, end + k * 33.0)
        if got:
            fired.append(got[0])
    return fired


def peak_p(model: dict, take: list[dict], strike: str) -> float:
    watch = strikes.Watcher(model)
    best = 0.0
    k = strikes.CLASSES.index(strike)
    end = float(take[-1]["t"])
    for f in [*take, *({"t": end + j * 33.0} for j in range(1, 46))]:
        watch.update(f.get("body"), float(f["t"]))
        best = max(best, watch.last[k])
    return best


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    frames = []
    for profile in PROFILES:
        for f in load(profile):
            f["profile"] = profile
            frames.append(f)
    if not frames:
        print("no keiko captures yet - record keiko_strikes (ctrl+alt+shift+9) first")
        return 1
    train, test, how = split(frames)
    print("held out:", "; ".join(how))
    rows = [(*w, take[0]["pose"] in STRIKE_OF) for take in train for w in windows(take)]
    x = np.array([r[0] for r in rows])
    y = np.array([strikes.CLASSES.index(r[1]) for r in rows])
    print("training windows:", {c: int((y == i).sum()) for i, c in enumerate(strikes.CLASSES)})
    mean, scale, w, b = fit(x, y)
    model = {"mean": mean.tolist(), "scale": scale.tolist(), "weights": w.tolist(), "bias": b.tolist()}
    # the gate, from the training data: no "none" window may pass a threshold
    p_all = np.array([strikes.probs(model, list(v)) for v in x])
    # (a raise inside a strike take is the settle step's to supersede, not the threshold's)
    confuser = np.array([not r[3] for r in rows])
    threshold = {}
    for k, c in enumerate(strikes.CLASSES[:-1]):
        none_p = p_all[(y == len(strikes.CLASSES) - 1) & confuser, k]
        top = float(none_p.max()) if len(none_p) else 0.5
        threshold[c] = round(min(0.99, max(0.5, top + float(none_p.std()))), 4)
    # a peak worth judging: well under his slowest training strike (a fraction of
    # its apex speed), so every real strike is looked at; the classifier says no
    apexes = [max(s for _, s in speed_track(t)) for t in train if t[0]["pose"] in STRIKE_OF and len(speed_track(t)) >= 5]
    # how long a judgement waits for a faster peak: the longest raise-to-strike gap
    # in his training strikes (the raise must always be superseded)
    gaps = [apex(t) - r for t in train if t[0]["pose"] in STRIKE_OF and apex(t) is not None for r in raise_peaks(t, apex(t))]
    settle = float(min(1000.0, max(300.0, max(gaps) - strikes.Watcher.AFTER_MS + 50))) if gaps else 600.0
    model["gate"] = {"threshold": threshold, "restMs": REST_MS, "speedMin": round(float(min(apexes)) * 0.5, 4), "settleMs": round(settle)}
    # the clean mark: median peak of correctly fired training strikes
    peaks = [peak_p(model, t, STRIKE_OF[t[0]["pose"]]) for t in train if t[0]["pose"] in STRIKE_OF and take_result(model, t) == [STRIKE_OF[t[0]["pose"]]]]
    model["gate"]["clean"] = round(float(np.median(peaks)), 4) if peaks else 0.95
    print("gate:", model["gate"])

    def report(name: str, takes_: list[list[dict]]) -> tuple[int, int, int, int, list[str]]:
        ok_s = n_s = ok_n = n_n = 0
        lines = []
        for t in takes_:
            label = t[0]["pose"]
            fired = take_result(model, t)
            strike = STRIKE_OF.get(label)
            if strike:
                n_s += 1
                good = fired and all(f == strike for f in fired)
                ok_s += bool(good)
                if not good:
                    lines.append(f"  {name} {label} rep {t[0]['rep']}: fired {fired or 'nothing'}")
            else:
                n_n += 1
                ok_n += not fired
                if fired:
                    lines.append(f"  {name} {label} rep {t[0]['rep']}: FALSE {fired}")
        return ok_s, n_s, ok_n, n_n, lines

    tr = report("train", train)
    te = report("held-out", test)
    print(f"train:    strikes {tr[0]}/{tr[1]}, confusers silent {tr[2]}/{tr[3]}")
    print(f"held-out: strikes {te[0]}/{te[1]}, confusers silent {te[2]}/{te[3]}")
    for line in te[4]:
        print(line)
    passed = te[1] > 0 and te[2] == te[3] and te[0] / te[1] >= 0.75
    sessions = sorted({(f["profile"], f["session"]) for f in frames})
    model["features"] = len(mean)
    model["classes"] = list(strikes.CLASSES)
    model["_about"] = (
        f"trained on {', '.join(f'{p} {s}' for p, s in sessions)}; held out: strikes {te[0]}/{te[1]}, "
        f"confusers silent {te[2]}/{te[3]}" + ("" if any(p == "keiko_strikes" for p, _ in sessions) else
        " - PROVISIONAL: no keiko_strikes capture yet (ctrl+alt+shift+9); its confusers are what make it safe")
    )
    # golden takes for the TS twin (hud/tests/strike.verify.mjs), with the model that
    # made them inside: parity is checked whether or not this model ships
    golden = []
    for t in [t for t in test if t[0]["pose"] in STRIKE_OF][:3] + [t for t in test if t[0]["pose"] not in STRIKE_OF][:1]:
        samples, out = [], []
        for f in t:
            samples.append((float(f["t"]), strikes.frame(f.get("body") or [])))
            v = strikes.window(samples, float(f["t"]))
            if v is not None and len(out) < 6:
                out.append({"now": float(f["t"]), "window": v, "probs": strikes.probs(model, v)})
        golden.append({"label": t[0]["pose"], "frames": [{"t": float(f["t"]), "body": f.get("body")} for f in t], "checks": out, "fired": take_result(model, t)})
    OUT_GOLDEN.write_text(json.dumps({"model": model, "takes": golden}), encoding="utf-8")
    if not passed:
        print("NOT shipped: held out, it must keep every confuser silent and get 75% of strikes")
        return 1
    OUT_TS.write_text(
        "// Generated by core/scripts/strike_train.py from the keiko captures in core/calibration.\n"
        "// Do not edit by hand - retrain after a new capture.\n\n"
        "import type { StrikeModel } from \"./strikeFeatures\";\n\n"
        f"export const STRIKE_MODEL: StrikeModel | null = {json.dumps(model, indent=2)};\n",
        encoding="utf-8",
    )
    print(f"shipped: {OUT_TS.relative_to(ROOT)} and {OUT_GOLDEN.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
