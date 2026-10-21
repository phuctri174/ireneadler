"""The strike event's tuning (irene/strike_tuning.py): a threshold from three swings,
nudged by one number - no model, no training."""
from __future__ import annotations

import json
import random

from irene import strike_tuning as st


def _config(tmp_path, **over):
    raw = json.loads(st.CONFIG.read_text(encoding="utf-8"))
    raw.update(over)
    path = tmp_path / "strike_event.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_the_shipped_config_reads_and_every_knob_is_there():
    s = st.settings()
    for key in ("fraction", "stopRatio", "stopMs", "refractoryMs", "minVis", "maxPeak"):
        assert isinstance(s[key], (int, float))
    assert set(s["calibration"]) >= {"seconds", "floorSpeed", "swings", "minEven"}
    assert set(s["shiai"]) == {"scaleRatio", "lateral", "windowMs", "refractoryMs", "holdMs", "graceMs"}


def test_threshold_is_the_fraction_of_the_median_of_three(tmp_path):
    config = _config(tmp_path, fraction=0.6)
    r = st.calibrate([26.1, 9.0, 22.0, 17.9, 10.1], config)
    assert r.ok and r.peaks == [26.1, 22.0, 17.9]
    assert r.median == 22.0 and r.threshold == 13.2


def test_uneven_swings_are_not_saved(tmp_path):
    # 19.8, 9.2, 7.0: a threshold from those would fire on everything
    r = st.calibrate([19.8, 9.2, 7.0, 6.2], _config(tmp_path))
    assert not r.ok and r.why == "uneven"


def test_fewer_than_three_swings_is_not_a_calibration(tmp_path):
    assert st.calibrate([20.0, 18.0], _config(tmp_path)).why == "few"
    assert st.calibrate([], _config(tmp_path)).peaks == []


def test_no_calibration_means_no_tuning_and_the_nudge_moves_it(tmp_path):
    state = tmp_path / "cal.json"
    assert st.threshold(_config(tmp_path), state) is None
    assert st.tuning(config=_config(tmp_path), state=state) is None
    st.save(st.calibrate([20.0, 18.0, 16.0], _config(tmp_path)), state)
    assert st.threshold(_config(tmp_path, fraction=0.5), state) == 9.0
    # he nudges the fraction down: more sensitive, without calibrating again
    assert st.threshold(_config(tmp_path, fraction=0.4), state) == 7.2
    t = st.tuning(moves=True, config=_config(tmp_path, fraction=0.5), state=state)
    assert t["strikes"]["threshold"] == 9.0 and t["moves"]["windowMs"] == 500
    assert st.tuning(config=_config(tmp_path), state=state)["moves"] is None


def test_calibration_listens_at_the_low_floor(tmp_path):
    t = st.calibration_tuning(_config(tmp_path))
    assert t["strikes"]["threshold"] == st.settings()["calibration"]["floorSpeed"]


def test_she_says_the_numbers_back():
    text, cue = st.line(st.Result(True, [26.1, 22.0, 17.9], 22.0, 13.2), random.Random(1))
    assert "26" in text and "13" in text and cue == "measure"
    assert st.line(st.Result(False, [], why=""), random.Random(1))[1] == "concerned"
    assert "2" in st.line(st.Result(False, [20.0, 18.0], why="few"), random.Random(1))[0]


def test_calibrate_command():
    for said in ("Irene, calibrate my strikes", "calibrate my hits", "recalibrate the strikes", "Can you calibrate my swings?",
                 "let's recalibrate my men"):
        assert st.command(said) == "calibrate", said
    for said in ("calibrate the monitor", "my strikes were slow today", "how do you calibrate a scale?"):
        assert st.command(said) is None, said
