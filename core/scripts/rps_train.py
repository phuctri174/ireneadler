r"""Train the rock-paper-scissors classifier on his guided captures - and ship it only if
it clears the bar on a whole session it never saw.

    .venv\Scripts\python scripts\rps_train.py [--holdout <session>] [--report-only]

Captures: core/calibration/rps-<session>.jsonl, recorded by saying "train rock paper
scissors" (core runs them as the game itself: she asks for a throw, counts the game's
own "rock... paper... scissors... shoot!", and the HUD sends the frames from 600 ms
before to 1400 ms after the shoot instant, each with t relative to it).

A throw = one take (session, label, rep). The classifier (irene/rps.py):
  features   rps.features(): per finger reach, tip-to-palm, two joint bends; tip
             gaps - distances over the palm's size and angles, so where the hand is
             and how big it looks don't matter
  model      softmax regression on the standardised features, class-balanced
  window     WHICH frames after shoot are read - fixed, [from, to] ms - is chosen
             here, from the TRAINING sessions only (cross-validated by take): the
             shortest-to-wait window with the best take accuracy
  decision   the window's frames' probabilities averaged; a throw below
             min_confidence (the 5th percentile of correct cross-validated throws)
             is "not sure - redo", never a guess

Held out: the newest session (or --holdout). Reported there, against the baseline
(rps.baseline: count the fingers whose tip is beyond their middle joint - majority
over the same window): take accuracy, per class, the confusion matrix.

Ships - writes core/irene/rps_model.json - ONLY IF on the held-out session:
  take accuracy >= 95%, every class >= 90%, and no worse than the baseline.
Otherwise nothing is written and the game stays off (it says so). The report always
goes to core/logs/rps_train_report.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from irene import rps  # noqa: E402
from irene.calibration import load, sessions  # noqa: E402

REPORT = HERE.parent / "logs" / "rps_train_report.json"
BAR_ACCURACY = 0.95
BAR_PER_CLASS = 0.90
STARTS = range(0, 701, 100)
LENGTHS = (100, 200, 300, 400)
MAX_END = 1300


def takes(frames: list[dict]) -> dict[tuple, list[dict]]:
    """(session, label, rep) -> its frames, with features computed once."""
    out: dict[tuple, list[dict]] = defaultdict(list)
    for f in frames:
        if f.get("pose") not in rps.THROWS or not isinstance(f.get("lm"), list):
            continue
        x = rps.features(f["lm"])
        if x is None:
            continue
        out[(f["session"], f["pose"], f.get("rep", 0))].append({"t": f.get("t", 0), "x": x, "lm": f["lm"]})
    return dict(out)


def window_frames(take: list[dict], window: tuple[int, int]) -> list[dict]:
    return [f for f in take if window[0] <= f["t"] <= window[1]]


def fit(take_items: list[tuple[tuple, list[dict]]], window: tuple[int, int]):
    from sklearn.linear_model import LogisticRegression

    xs, ys = [], []
    for key, take in take_items:
        for f in window_frames(take, window):
            xs.append(f["x"])
            ys.append(key[1])
    if len(set(ys)) < 3:
        return None
    X = np.vstack(xs)
    mean, scale = X.mean(axis=0), X.std(axis=0)
    scale[scale < 1e-9] = 1.0
    clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
    clf.fit((X - mean) / scale, ys)
    return rps.Model(classes=list(clf.classes_), mean=mean.tolist(), scale=scale.tolist(), coef=clf.coef_.tolist(),
                     intercept=clf.intercept_.tolist(), window_ms=list(window), min_confidence=0.0)


def judge(model: rps.Model, take_items, window) -> list[tuple[str, str | None, float]]:
    """(truth, prediction, confidence) per take - None when the window had no hand."""
    out = []
    for key, take in take_items:
        fs = window_frames(take, window)
        if not fs:
            out.append((key[1], None, 0.0))
            continue
        p = model.proba(np.vstack([f["x"] for f in fs])).mean(axis=0)
        k = int(np.argmax(p))
        out.append((key[1], model.classes[k], float(p[k])))
    return out


def baseline_judge(take_items, window) -> list[tuple[str, str | None]]:
    out = []
    for key, take in take_items:
        votes = Counter(rps.baseline(f["lm"]) for f in window_frames(take, window))
        out.append((key[1], votes.most_common(1)[0][0] if votes else None))
    return out


def accuracy(pairs) -> float:
    return sum(1 for p in pairs if p[0] == p[1]) / max(len(pairs), 1)


def per_class(pairs) -> dict[str, float]:
    return {c: accuracy([p for p in pairs if p[0] == c]) for c in rps.THROWS}


def confusion(pairs) -> dict[str, dict[str, int]]:
    out = {c: Counter() for c in rps.THROWS}
    for truth, pred, *_ in pairs:
        out[truth][pred or "none"] += 1
    return {c: dict(v) for c, v in out.items()}


def folds(train_items, k: int = 5):
    """Cross-validation folds: by session when there are several, else by take."""
    by_session = sorted({key[0] for key, _ in train_items})
    if len(by_session) >= 2:
        for s in by_session:
            yield [t for t in train_items if t[0][0] != s], [t for t in train_items if t[0][0] == s]
        return
    for i in range(k):
        yield [t for j, t in enumerate(train_items) if j % k != i], [t for j, t in enumerate(train_items) if j % k == i]


def choose_window(train_items):
    """(window, cross-validated judgements, min confidence) - the window with the best
    cross-validated take accuracy over these throws alone."""
    rng = np.random.default_rng(0)
    order = list(range(len(train_items)))
    rng.shuffle(order)
    shuffled = [train_items[i] for i in order]
    best = None
    for start in STARTS:
        for length in LENGTHS:
            window = (start, start + length)
            if window[1] > MAX_END:
                continue
            got = []
            for tr, te in folds(shuffled):
                model = fit(tr, window)
                if model is not None:
                    got += judge(model, te, window)
            acc = accuracy(got)
            # ties: the window where it is surest of the right answer (a settled hand),
            # then the sooner one
            sure = float(np.mean([c for t, p, c in got if t == p])) if any(t == p for t, p, _ in got) else 0.0
            key = (round(acc, 4), round(sure, 3), -window[1])
            if best is None or key > best[0]:
                best = (key, window, got)
    (_, window, cv) = best
    correct = sorted(c for t, p, c in cv if t == p)
    return window, cv, float(np.percentile(correct, 5)) if correct else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", default=None)
    ap.add_argument("--report-only", action="store_true", help="never write the model, even if it clears the bar")
    ap.add_argument("--dir", type=Path, default=None, help="captures folder (default core/calibration)")
    ap.add_argument("--out", type=Path, default=rps.MODEL, help="where the shipped model goes")
    ap.add_argument("--report", type=Path, default=REPORT)
    ap.add_argument("--single-session", type=int, default=0, metavar="REP",
                    help="with one session only: hold out every throw's reps >= REP (weaker than a held-out session)")
    ap.add_argument("--ship-anyway", action="store_true",
                    help="his call: write a model even below the bar - refit on EVERY session, report kept as is")
    args = ap.parse_args()
    where = {"directory": args.dir} if args.dir else {}
    sys.stdout.reconfigure(encoding="utf-8")
    runs = [p.stem[len("rps") + 1:] for p in sessions("rps", **where)]
    print(f"rps captures: {len(runs)} session(s) {runs}")
    all_takes = takes(load("rps", **where))
    if len(runs) < 2 and not args.single_session:
        print("NOT SHIPPED: needs at least two capture sessions (one is held out). Say 'train rock paper scissors' again "
              "(or --single-session: hold out the last reps of one session - a weaker test).")
        return 2
    if len(runs) < 2:
        # one sitting: the last reps of every throw are held out, never trained on.
        # Same light, same position, same day - an optimistic test, and labelled so.
        holdout = f"{runs[0]} reps >= {args.single_session}"
        test_of = lambda k: k[2] >= args.single_session  # noqa: E731
    else:
        holdout = args.holdout or runs[-1]
        test_of = lambda k: k[0] == holdout  # noqa: E731
    train_items = sorted((k, v) for k, v in all_takes.items() if not test_of(k))
    test_items = sorted((k, v) for k, v in all_takes.items() if test_of(k))
    print(f"train: {len(train_items)} throws; held out: {len(test_items)} throws ({holdout})")

    # the window, from training data alone
    window, cv, min_conf = choose_window(train_items)
    print(f"window chosen on training data: {window[0]}-{window[1]} ms after shoot (cross-validated take accuracy {accuracy(cv):.1%}); "
          f"min confidence {min_conf:.2f}")

    model = fit(train_items, window)
    model.min_confidence = round(min_conf, 3)
    held = judge(model, test_items, window)
    # a throw below min confidence is a redo, which counts as not right
    held_eff = [(t, p if c >= model.min_confidence else None, c) for t, p, c in held]
    base = baseline_judge(test_items, window)
    acc, base_acc = accuracy(held_eff), accuracy(base)
    classes = per_class(held_eff)
    redo = sum(1 for _, p, _ in held_eff if p is None)
    print(f"\nHELD-OUT session {holdout}: {len(test_items)} throws")
    print(f"  model     {acc:.1%}  per class " + ", ".join(f"{c} {v:.0%}" for c, v in classes.items()) + f"  ({redo} 'redo')")
    print(f"  baseline  {base_acc:.1%}  per class " + ", ".join(f"{c} {v:.0%}" for c, v in per_class(base).items()))
    print(f"  confusion (model) {confusion(held_eff)}")
    print(f"  confusion (baseline) {confusion(base)}")
    ships = acc >= BAR_ACCURACY and min(classes.values()) >= BAR_PER_CLASS and acc >= base_acc
    report = {
        "trained": time.strftime("%Y-%m-%d %H:%M"), "sessions": runs, "holdout": holdout, "train_throws": len(train_items),
        "holdout_throws": len(test_items), "window_ms": list(window), "cv_accuracy": accuracy(cv), "min_confidence": model.min_confidence,
        "holdout_accuracy": acc, "holdout_per_class": classes, "holdout_redo": redo, "baseline_accuracy": base_acc,
        "baseline_per_class": per_class(base), "confusion": confusion(held_eff), "baseline_confusion": confusion(base),
        "bar": {"accuracy": BAR_ACCURACY, "per_class": BAR_PER_CLASS, "beats_baseline": True}, "ships": ships,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not ships and args.ship_anyway and not args.report_only:
        # below the bar by his choice: the held-out numbers above stand as the honest
        # estimate; the model itself learns from every throw there is
        everything = sorted(all_takes.items())
        window, cv, min_conf = choose_window(everything)
        model = fit(everything, window)
        model.min_confidence = round(min_conf, 3)
        model.report = {**report, "shipped_below_bar": True, "final_window_ms": list(window),
                        "final_cv_accuracy": accuracy(cv), "final_throws": len(everything)}
        args.out.write_text(json.dumps({**model.__dict__}, indent=1), encoding="utf-8")
        print(f"\nBELOW THE BAR - shipped anyway (--ship-anyway): refit on all {len(everything)} throws, window "
              f"{window[0]}-{window[1]} ms, cross-validated {accuracy(cv):.1%}, min confidence {model.min_confidence:.2f} -> {args.out}")
        return 0
    if not ships:
        print(f"\nNOT SHIPPED: the bar is >= {BAR_ACCURACY:.0%} held out, every class >= {BAR_PER_CLASS:.0%}, and no worse than the baseline.")
        return 1
    if args.report_only:
        print("\nclears the bar (--report-only: not written)")
        return 0
    model.report = report
    args.out.write_text(json.dumps({**model.__dict__}, indent=1), encoding="utf-8")
    print(f"\nSHIPPED -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
