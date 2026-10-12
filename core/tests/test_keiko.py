"""Keiko (irene/keiko.py, irene/strikes.py): voice-started, her answers simple and fun,
the strike recogniser's maths."""
import math
import random

from irene import keiko, strikes


def test_started_only_by_his_voice():
    for said in ("Irene, let's do keiko", "let's do some keiko!", "keiko time", "spar with me", "Let's practise kendo"):
        assert keiko.command(said, active=False) == "start", said
    for said in ("I had keiko yesterday", "my keiko was brutal", "What is keiko?", "stop", "kendo is fun"):
        assert keiko.command(said, active=False) is None, said


def test_stopped_by_stop_but_not_by_other_stops():
    for said in ("Irene, stop", "stop.", "yame!", "okay that's enough", "let's stop", "end keiko"):
        assert keiko.command(said, active=True) == "stop", said
    for said in ("stop the music please", "stop playing that video", "nice one"):
        assert keiko.command(said, active=True) is None, said


def test_her_answers_mix_and_clean_strikes_are_ippon():
    k = keiko.Keiko(rng=random.Random(4))
    k.start(0.0)
    seen = {k.strike("men", 0.98, True, 1.0).action for _ in range(60)}
    assert seen == {"block", "ippon", "strike"}
    unclean = {k.strike("kote", 0.6, False, 2.0).action for _ in range(60)}
    assert "ippon" not in unclean and "hit" in unclean
    ippon = next(a for a in (k.strike("men", 0.99, True, 3.0) for _ in range(60)) if a.action == "ippon")
    assert ippon.flags == 3 and ippon.target == "men" and "men" in ippon.line.lower() and "flags" in ippon.sounds
    assert next(a for a in (k.strike("gyaku_dou", 0.9, True, 4.0) for _ in range(60)) if a.action == "ippon").flags == 2


def test_it_ends_on_its_own():
    k = keiko.Keiko()
    k.start(0.0)
    assert not k.expired(keiko.IDLE_END_S - 1)
    assert k.expired(keiko.IDLE_END_S + 1)
    assert k.stop().action == "end" and not k.active
    assert k.strike("men", 0.99, True) is None  # off: nothing answers


def test_no_model_yet_is_said_out_loud(tmp_path, monkeypatch):
    stub = tmp_path / "strikeModel.ts"
    stub.write_text("export const STRIKE_MODEL: StrikeModel | null = null;\n", encoding="utf-8")
    monkeypatch.setattr(keiko, "MODEL_TS", stub)
    assert not keiko.model_ready(stub)
    assert "control alt shift nine" in keiko.Keiko().start(0.0).line


def _body(lw, rw, shoulders=((0.4, 0.4), (0.6, 0.4))):
    """A flat 33-landmark body with the shoulders and wrists placed; the rest at the shoulders' middle."""
    pts = [[0.5, 0.4, 0.0, 1.0] for _ in range(33)]
    pts[11][:2], pts[12][:2] = shoulders[0], shoulders[1]
    pts[15][:2], pts[16][:2] = lw, rw
    (lsx, lsy), (rsx, rsy) = shoulders
    pts[13][:2], pts[14][:2] = ((lw[0] + lsx) / 2, (lw[1] + lsy) / 2), ((rw[0] + rsx) / 2, (rw[1] + rsy) / 2)
    return [v for p in pts for v in p]


def test_features_are_measured_from_the_shoulders():
    near = strikes.frame(_body((0.48, 0.6), (0.52, 0.6)))
    # the same pose, twice the size and somewhere else: the same numbers
    far = strikes.frame(_body((0.46, 0.8), (0.54, 0.8), shoulders=((0.3, 0.4), (0.7, 0.4))))
    assert all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(near, far))
    assert strikes.frame([0.0] * 10) is None


def test_the_window_needs_coverage_and_resamples():
    samples = [(float(t), strikes.frame(_body((0.48, 0.6 - t / 4000), (0.52, 0.6 - t / 4000)))) for t in range(0, 1000, 33)]
    v = strikes.window(samples, 990.0)
    assert v is not None and len(v) == len(strikes.TRACKED) * 6 + 3
    assert strikes.window(samples[-3:], 990.0) is None


def test_the_watcher_judges_once_per_peak_after_it_settles():
    # a model that calls every window men, with a gate the watcher must respect
    n = len(strikes.TRACKED) * 6 + 3
    model = {"mean": [0.0] * n, "scale": [1.0] * n, "weights": [[0.0] * n for _ in strikes.CLASSES], "bias": [5.0, 0.0, 0.0, 0.0],
             "gate": {"threshold": {"men": 0.5, "kote": 0.5, "gyaku_dou": 0.5}, "restMs": 900.0, "speedMin": 1.0, "settleMs": 300}}
    w = strikes.Watcher(model)
    fired = []
    t = 0.0
    # still for a second, one fast swing down, still again
    for k in range(120):
        t = k * 33.0
        y = 0.6 if k < 40 else (0.3 + (k - 40) * 0.05 if k < 46 else 0.6)
        got = w.update(_body((0.48, y), (0.52, y)), t)
        if got:
            fired.append((t, got[0]))
    assert len(fired) == 1 and fired[0][1] == "men"
    # judged after the peak (AFTER_MS) and the settle time, not on the way up
    assert fired[0][0] >= 40 * 33.0 + strikes.Watcher.AFTER_MS + 300
