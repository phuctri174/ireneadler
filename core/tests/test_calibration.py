import json

import pytest

from irene.calibration import write

SESSION = "2026-09-21T12-30-00"


def test_writes_labelled_jsonl(tmp_path):
    frames = [{"t": 0, "cross": 0.12, "boneTipCross": False, "mode": "idle"}, {"t": 33, "cross": 0.5, "boneTipCross": True, "mode": "summon"}]
    path, n = write({"session": SESSION, "pose": "crossed", "frames": frames}, tmp_path)
    assert n == 2
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [l["pose"] for l in lines] == ["crossed", "crossed"]
    assert lines[1]["boneTipCross"] is True and lines[1]["cross"] == 0.5


def test_second_pose_appends_to_same_session(tmp_path):
    write({"session": SESSION, "pose": "parallel", "frames": [{"t": 0}]}, tmp_path)
    path, _ = write({"session": SESSION, "pose": "crossed", "frames": [{"t": 0}]}, tmp_path)
    assert [json.loads(l)["pose"] for l in path.read_text(encoding="utf-8").splitlines()] == ["parallel", "crossed"]


@pytest.mark.parametrize("session", ["../../evil", "2026-09-21T12-30-00/../x", "", "x" * 30])
def test_rejects_path_like_sessions(tmp_path, session):
    with pytest.raises(ValueError):
        write({"session": session, "pose": "crossed", "frames": []}, tmp_path)


def test_rejects_unknown_pose(tmp_path):
    with pytest.raises(ValueError):
        write({"session": SESSION, "pose": "peace", "frames": []}, tmp_path)


def test_drops_malformed_frames(tmp_path):
    frames = [{"t": 1}, {"t": {"nested": 1}}, "nope", {"x" * 50: 1}]
    _, n = write({"session": SESSION, "pose": "parallel", "frames": frames}, tmp_path)
    assert n == 1


def test_zoom_profile_takes_with_reps_and_landmarks(tmp_path):
    landmarks = [0.1] * 63
    path, n = write({"profile": "zoom_mid", "session": SESSION, "pose": "zoom_in", "rep": 4,
                     "frames": [{"t": 0, "lm": landmarks, "zoomFactor": 1.2, "zoomState": "LATCHED"}]}, tmp_path)
    assert path.name == f"zoom_mid-{SESSION}.jsonl" and n == 1
    line = json.loads(path.read_text(encoding="utf-8"))
    assert line["rep"] == 4 and line["lm"] == landmarks and line["profile"] == "zoom_mid"


def test_every_configured_profile_label_is_accepted(tmp_path):
    from irene.calibration import labels

    assert set(labels()) >= {"summon", "zoom_panel", "zoom_near", "zoom_mid", "zoom_far"}
    # each distance is its own profile, so the labels inside are plain
    for profile in ("zoom_panel", "zoom_near", "zoom_mid", "zoom_far"):
        names = labels()[profile]
        for stem in ("spread", "fist", "zoom_in", "zoom_in_fast", "zoom_out", "zoom_out_fast"):
            assert stem in names, f"{profile}: {stem}"
        assert len(names) == len(set(names))
    # No confuser may live only in a profile that might not be run. A classifier
    # that has never seen the two-finger scroll pose latches zoom on it, and a zoom
    # latch suppresses scroll, summon and pointing - so the set that is always
    # captured has to be complete on its own.
    always_run = set(labels()["zoom_near"]) | set(labels()["zoom_mid"])
    assert {"relaxed", "pointing", "scroll_pose", "waving", "scratching"} <= always_run
    for optional in ("zoom_far",):
        assert not set(labels()[optional]) - always_run, f"{optional} has a pose nothing else captures"
    # the panel distance (where a still hand latched zoom live) is the one he runs
    # now: it carries every confuser on its own, plus the two only seen at the panel
    assert {"relaxed", "pointing", "scroll_pose", "waving", "scratching", "still_open", "pointer_moving"} <= set(labels()["zoom_panel"])
    for profile, names in labels().items():
        for name in names:
            write({"profile": profile, "session": SESSION, "pose": name, "frames": []}, tmp_path)


def test_the_zoom_family_runs_nearest_first_and_each_take_is_about_three_minutes():
    import json as _json

    from irene.calibration import PROFILES, distances, family

    assert family("zoom") == ["zoom_panel", "zoom_near", "zoom_mid", "zoom_far"]
    assert [distances()[p] for p in family("zoom")] == [0.5, 0.7, 1.0, 1.3]
    assert "summon" not in family("zoom")

    profiles = _json.loads(PROFILES.read_text(encoding="utf-8"))["profiles"]
    for name in family("zoom"):
        steps = profiles[name]["steps"]
        takes = sum(s.get("reps", 1) for s in steps)
        # recording, plus the countdown and settle before each take
        minutes = (sum(s.get("reps", 1) * s["seconds"] for s in steps) + takes * 3.6) / 60
        assert 2.5 <= minutes <= 3.5, f"{name}: {minutes:.1f} min"


@pytest.mark.parametrize("message", [
    {"profile": "../x", "pose": "fist"},
    {"profile": "zoom_mid", "pose": "crossed"},
    {"profile": "zoom", "pose": "fist"},  # the family name is not itself a profile
    {"profile": "zoom_mid", "pose": "fist", "rep": -1},
    {"profile": "zoom_mid", "pose": "fist", "rep": True},
])
def test_rejects_bad_profile_label_or_rep(tmp_path, message):
    with pytest.raises(ValueError):
        write({"session": SESSION, "frames": [], **message}, tmp_path)


def test_drops_frames_with_non_numeric_lists(tmp_path):
    from irene.calibration import MAX_LIST

    # a list of non-numbers, and one longer than the cap (which is 132 now that a
    # pose frame carries 33 landmarks x 4) - both dropped, the good one kept
    _, n = write({"profile": "zoom_mid", "session": SESSION, "pose": "fist",
                  "frames": [{"lm": [1, "x"]}, {"lm": [0.0] * (MAX_LIST + 1)}, {"lm": [0.5, 0.5]}]}, tmp_path)
    assert n == 1


def test_sessions_accumulate_and_merge_with_their_session_kept(tmp_path):
    from irene.calibration import load, sessions

    other = "2026-09-28T10-00-00"
    write({"profile": "zoom_mid", "session": SESSION, "pose": "fist", "frames": [{"t": 0}, {"t": 1}]}, tmp_path)
    write({"profile": "zoom_mid", "session": SESSION, "pose": "spread", "frames": [{"t": 2}]}, tmp_path)
    write({"profile": "zoom_mid", "session": other, "pose": "zoom_in", "rep": 3, "frames": [{"t": 3}]}, tmp_path)
    # a second run writes its own file; the first is left alone
    assert [p.name for p in sessions("zoom_mid", tmp_path)] == [f"zoom_mid-{SESSION}.jsonl", f"zoom_mid-{other}.jsonl"]

    frames = load("zoom_mid", tmp_path)
    assert len(frames) == 4
    assert {f["session"] for f in frames} == {SESSION, other}
    assert {f["pose"] for f in frames} == {"fist", "spread", "zoom_in"}
    assert [f["pose"] for f in frames if f["session"] == other] == ["zoom_in"]


def test_the_three_distances_merge_into_one_set_each_frame_knowing_its_distance(tmp_path):
    from irene.calibration import load_family

    for profile in ("zoom_near", "zoom_mid", "zoom_far"):
        write({"profile": profile, "session": SESSION, "pose": "zoom_in", "rep": 1, "frames": [{"t": 0}, {"t": 1}]}, tmp_path)
    # the far one run a second time: it adds to the set rather than replacing it
    write({"profile": "zoom_far", "session": "2026-09-29T09-00-00", "pose": "zoom_out", "frames": [{"t": 2}]}, tmp_path)

    frames = load_family("zoom", tmp_path)
    assert len(frames) == 7
    assert sorted({f["distance_m"] for f in frames}) == [0.7, 1.0, 1.3]
    assert {f["profile"] for f in frames} == {"zoom_near", "zoom_mid", "zoom_far"}
    # a whole session can be held out for testing
    held_out = [f for f in frames if f["session"] == "2026-09-29T09-00-00"]
    assert len(held_out) == 1 and held_out[0]["distance_m"] == 1.3
    # the summon capture is a different family and never leaks in
    write({"profile": "summon", "session": SESSION, "pose": "crossed", "frames": [{"t": 9}]}, tmp_path)
    assert len(load_family("zoom", tmp_path)) == 7


def test_a_corrupt_line_does_not_sink_the_merge(tmp_path):
    from irene.calibration import load

    write({"profile": "zoom_mid", "session": SESSION, "pose": "fist", "frames": [{"t": 0}]}, tmp_path)
    with (tmp_path / f"zoom_mid-{SESSION}.jsonl").open("a", encoding="utf-8") as f:
        f.write("not json\n\n")
    assert len(load("zoom_mid", tmp_path)) == 1


def test_a_session_recorded_against_an_older_profile_is_flagged(tmp_path):
    from irene.calibration import incomplete, labels

    steps = labels()["zoom_mid"]
    stale, fresh = SESSION, "2026-09-30T08-00-00"
    # a run that missed one step - the HUD was still holding the profile it
    # imported at startup, which is exactly how scroll_pose went missing
    for pose in steps:
        if pose != "scroll_pose":
            write({"profile": "zoom_mid", "session": stale, "pose": pose, "frames": [{"t": 0}]}, tmp_path)
    for pose in steps:
        write({"profile": "zoom_mid", "session": fresh, "pose": pose, "frames": [{"t": 0}]}, tmp_path)

    found = incomplete("zoom_mid", tmp_path)
    assert found == {stale: ("scroll_pose",)}, found
    assert fresh not in found, "a complete session is not flagged"
    assert incomplete("summon", tmp_path) == {}, "a profile with no sessions has no gaps"


def test_the_keiko_profiles_cover_the_sign_the_strikes_and_confusers(tmp_path):
    from irene.calibration import PROFILES, distances, family, labels
    import json as _json

    assert set(family("keiko")) == {"keiko_near", "keiko_mid", "keiko_kamae", "keiko_confusers", "keiko_strikes"}
    assert [distances()[p] for p in ("keiko_near", "keiko_mid")] == [1.0, 1.6]
    # the zoom family must not have swallowed them, nor they it
    assert not set(family("keiko")) & set(family("zoom"))

    profiles = _json.loads(PROFILES.read_text(encoding="utf-8"))["profiles"]
    for name in ("keiko_near", "keiko_mid"):
        names = labels()[name]
        # the sign, the three strikes he asked for, and confusers for each
        assert "kamae" in names
        for strike in ("men", "kote", "gyaku_dou"):
            assert strike in names, f"{name}: {strike}"
        assert {"shizentai", "arms_up", "reaching", "scratching", "stretching"} <= set(names)
        assert len(names) == len(set(names))
        # it reads the upper body, not a hand - the HUD arms the pose model on this
        assert profiles[name]["tracks"] == "pose"
        steps = profiles[name]["steps"]
        takes = sum(s.get("reps", 1) for s in steps)
        minutes = (sum(s.get("reps", 1) * s["seconds"] for s in steps) + takes * 3.6) / 60
        assert 2.5 <= minutes <= 3.5, f"{name}: {minutes:.1f} min"


def _minutes(steps: list[dict]) -> float:
    takes = sum(s.get("reps", 1) for s in steps)
    return (sum(s.get("reps", 1) * s["seconds"] for s in steps) + takes * 3.6) / 60


def test_the_new_keiko_captures_have_many_kamae_and_every_confuser_he_named():
    """Almost any arm movement set kamae off live. keiko_kamae is more of the real
    thing; keiko_confusers is everything he does at the desk that must never fire it."""
    from irene.calibration import PROFILES, labels
    import json as _json

    profiles = _json.loads(PROFILES.read_text(encoding="utf-8"))["profiles"]
    kamae = labels()["keiko_kamae"]
    assert sum(1 for n in kamae if n.startswith("kamae")) >= 7
    confusers = set(labels()["keiko_confusers"])
    named = {"reaching", "stretching", "typing", "drinking", "scratching", "waving", "hair", "leaning_back",
             "arms_crossed", "phone_two_hands", "talking_gestures"}
    assert named <= confusers, named - confusers
    # the ones where both hands meet in front, like on a tsuka
    assert {"mug_two_hands", "chin_on_hands", "clapping", "shinai_resting"} <= confusers
    for name in ("keiko_kamae", "keiko_confusers"):
        assert profiles[name]["tracks"] == "pose"
    assert _minutes(profiles["keiko_kamae"]["steps"]) <= 4
    assert _minutes(profiles["keiko_confusers"]["steps"]) <= 9


def test_a_pose_frame_survives_the_write(tmp_path):
    # 33 landmarks x (x, y, z, visibility) = 132 numbers, which used to be over the cap
    body = [0.5] * 132
    path, n = write({"profile": "keiko_near", "session": SESSION, "pose": "kamae",
                     "frames": [{"t": 0, "pose": body, "hand": False}]}, tmp_path)
    assert n == 1
    line = json.loads(path.read_text(encoding="utf-8"))
    # the step label is "pose" too: it must not be overwritten by the landmarks
    assert line["pose"] == "kamae"
    assert len(line["body"]) == 132 and line["body"][0] == 0.5
