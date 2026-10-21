"""Study mode (irene/study.py): his words start and stop it, every hit really moves the
bar, the reactions escalate and never repeat back to back, and the payoff hands a
chess opening to the game."""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from irene import chess_book, dispatch, study

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("said,subject", [
    ("Irene, go learn the Sicilian", "the Sicilian"),
    ("go study the Sicilian", "the Sicilian"),
    ("Hey Irene, can you go study quantum entanglement please", "quantum entanglement"),
    ("Irene, study the Caro-Kann", "the Caro-Kann"),
    ("Irene go read up on black holes for me", "black holes"),
    ("irene go learn about the french revolution now", "the french revolution"),
    # a bare order, nothing after it (live 2026-10-18: "Learn Sicilian" went to research)
    ("Learn Sicilian", "Sicilian"),
    ("study the Sicilian", "the Sicilian"),
    ("I think you should go learn the Sicilian", "the Sicilian"),
])
def test_he_sends_her_to_study(said, subject):
    assert study.command(said, False) == ("start", subject)


@pytest.mark.parametrize("said", [
    "I need to go study for my exam",
    "I'm gonna go study",
    "go study for the test",
    "let's go study",
    "study the Sicilian, they said, it's easy",   # talk: a clause after it
    "Learn to code with me",
    "Irene, go study it",
    "I studied the Sicilian yesterday",
    "what should I study tonight?",
])
def test_him_studying_is_not_her_studying(said):
    assert study.command(said, False) is None


def test_stop_only_while_she_studies():
    assert study.command("stop", True) == ("stop", None)
    assert study.command("Irene, stop studying", True) == ("stop", None)
    assert study.command("stop", False) is None
    assert study.command("stop the music", True) is None


def test_dispatch_puts_study_after_keiko_and_before_chess():
    claims = {dispatch.KEIKO: lambda s, on: None, dispatch.STUDY: lambda s, on: ("start", "x"), dispatch.CHESS: lambda s, on: "move"}
    who, found = dispatch.route("x", claims)
    assert who == dispatch.STUDY and found == ("start", "x")
    who, _ = dispatch.route("x", {**claims, dispatch.KEIKO: lambda s, on: "start"})
    assert who == dispatch.KEIKO


def started(seed: int = 1) -> study.Study:
    s = study.Study(rng=random.Random(seed))
    s.start("the Sicilian", now=0.0)
    return s


def test_unhit_the_bar_fills_slowly():
    s = started()
    assert s.progress(study.BASE_S / 2) == pytest.approx(0.5)
    assert not s.finished(study.BASE_S - 1)
    assert s.finished(study.BASE_S + 0.01)


def test_every_hit_jumps_the_bar_and_speeds_it_up():
    s = started()
    before = s.progress(10.0)
    rate = s.rate
    a = s.hit(10.0)
    assert a and a.progress == pytest.approx(before + study.HIT_JUMP)
    assert s.rate > rate
    # and keeps going faster: over the same 5 s it gains more than before the hit
    assert s.progress(15.0) - s.progress(10.0) > rate * 5


def test_hits_finish_it_much_sooner():
    s = started()
    t = 5.0
    while not s.finished(t):
        s.hit(t)
        t += 4.0
    assert t < study.BASE_S / 2, f"hitting every 4 s should at least halve it ({t:.0f} s)"


def test_the_same_swing_is_one_hit():
    s = started()
    assert s.hit(10.0)
    assert s.hit(10.3) is None
    assert s.hit(11.0)


def test_reactions_escalate():
    s = started()
    tiers = [s.hit(5.0 + 2 * k).tier for k in range(6)]
    assert tiers == ["ow", "ow", "indignant", "indignant", "uncle", "uncle"]


def test_no_reaction_face_twice_in_a_row():
    for seed in range(20):
        s = started(seed)
        cues = []
        t = 5.0
        while (a := s.hit(t)) is not None:
            cues.append(a.cue)
            t += 1.0
        assert all(x != y for x, y in zip(cues, cues[1:])), cues


def test_the_reaction_lines_stay_comic():
    # never real distress: no begging, no "it hurts", no "please stop"
    lines = " ".join(study.LINES["ow"] + study.LINES["indignant"] + study.LINES["uncle"]).lower()
    for bad in ("please stop", "hurts", "stop hitting", "i'm scared", "help"):
        assert bad not in lines


def test_every_cue_she_uses_is_in_the_pool():
    pool = {c["name"] for c in json.loads((ROOT / "config" / "cues.json").read_text(encoding="utf-8"))["cues"]}
    for kind, names in study.CUES.items():
        for name in names:
            assert name in pool, f"{kind}: {name}"
    assert {"bonked", "indignant", "surrender", "study"} <= pool


def test_finished_or_stopped_takes_no_more_hits():
    s = started()
    s.p0 = 1.0
    assert s.hit(5.0) is None
    s = started()
    s.stop(5.0)
    assert s.hit(6.0) is None


def test_a_book_defence_hands_off_to_chess_pinned():
    s = started()
    s.notes = study.Notes(summary="It answers e4 with c5.")
    done = s.finish()
    assert done.chess and done.defence == "Sicilian" and not done.fumbled
    assert "white or black" in done.challenge.lower() and "Sicilian" in done.challenge and "c5" in done.line
    assert not s.active


def test_another_chess_subject_hands_off_unpinned():
    s = study.Study(rng=random.Random(0))
    s.start("chess endgames", 0.0)
    done = s.finish()
    assert done.chess and done.defence is None


def test_a_plain_subject_is_summarised():
    s = study.Study(rng=random.Random(0))
    s.start("black holes", 0.0)
    s.notes = study.Notes(summary="Gravity so strong light can't escape.")
    done = s.finish()
    assert not done.chess and "light can't escape" in done.line and not done.challenge


def test_rushed_she_fumbles_and_says_so():
    s = started()
    s.notes = study.Notes(summary="ok", wrong="It starts 1.e4 c6.", right="It starts 1.e4 c5.")
    t = 1.0
    for _ in range(study.TOO_FAST):
        s.p0 = 0.0  # keep it open long enough to land them all
        s.hit(t)
        t += 1.0
    done = s.finish()
    assert done.fumbled
    # a book defence: mixed up with a REAL other defence, then the true first moves
    wait = done.line.index("Wait")
    assert "1.e4 c5" not in done.line[:wait] and done.line.index("1.e4 c5") > wait
    assert any(f"That's the {n}" in done.line for n in chess_book.DEFENCES if n != "Sicilian")


def test_rushed_on_a_plain_subject_the_model_fumble_is_used():
    s = study.Study(rng=random.Random(0))
    s.start("black holes", 0.0)
    s.notes = study.Notes(summary="ok", wrong="Light escapes them.", right="Not even light escapes them.")
    s.hits = study.TOO_FAST
    done = s.finish()
    assert done.fumbled and done.line.index("Light escapes") < done.line.index("Wait") < done.line.index("Not even light")


def test_not_rushed_no_fumble():
    s = started()
    s.notes = study.Notes(summary="It answers e4 with c5.", wrong="It starts 1.e4 c6.", right="It starts 1.e4 c5.")
    s.hit(1.0)
    assert not s.finish().fumbled


def test_parse_notes_keeps_only_the_right_shapes():
    raw = (
        "Here you go!\n**MUTTER:** c5... knight to f6\nMUTTER: hmm, the Najdorf\n"
        "MUTTER: " + "word " * 20 + "\nSUMMARY: The Sicilian answers 1.e4 with c5.\n"
        "WRONG: It starts 1.e4 c6.\nRIGHT: It starts 1.e4 c5.\n"
    )
    n = study.parse_notes(raw)
    assert n.mutters == ["c5... knight to f6", "hmm, the Najdorf"]
    assert n.summary.startswith("The Sicilian")
    assert n.wrong and n.right
    same = study.parse_notes("WRONG: It is c5.\nRIGHT: It is c5.")
    assert not same.wrong and not same.right


def test_the_prompt_carries_the_true_first_moves():
    assert "1.e4 c5" in study.notes_prompt("the Sicilian")
    assert study.opening_moves("Caro-Kann") == "1.e4 c6"
    assert all(study.defence(name) == name for name in chess_book.DEFENCES)


def test_mutters_wait_their_turn_and_never_follow_a_hit():
    s = started()
    s.notes = study.Notes(mutters=["c5, then Nf6"])
    assert s.mutter(1.0) is None
    s.next_mutter = 2.0
    s.hit(1.9)
    assert s.mutter(2.5) is None  # quiet after a hit
    assert s.mutter(1.9 + study.MUTTER_QUIET_AFTER_HIT_S + 0.1) == "c5, then Nf6"


def test_no_mutter_the_moment_she_stops_talking():
    s = started()
    s.next_mutter = 0.0
    s.talking(10.0)
    assert s.mutter(12.0) is None
    assert s.mutter(10.0 + study.MUTTER_QUIET_AFTER_SPEECH_S + 0.1) is not None


def test_study_faces_are_expressions_not_gestures():
    # a gesture's hands would draw over the open book
    kinds = {c["name"]: c["kind"] for c in json.loads((ROOT / "config" / "cues.json").read_text(encoding="utf-8"))["cues"]}
    for moment in ("start", "mutter", "ow", "indignant", "uncle"):
        for name in study.CUES[moment]:
            assert kinds[name] == "expression", f"{moment}: {name} is a {kinds[name]}"
