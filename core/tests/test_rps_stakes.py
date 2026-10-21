"""Stakes on rock-paper-scissors (irene/rps_stakes.py, app.py _rps_round): the CODE
decides who won - her sealed throw against the read of his - and maps it to the
consequence he stated. The model only parses his words and phrases the ending, and
neither can change what is announced. Every test here runs with the model stubbed
out: no stub at all (templates), a stub that lies, and a stub that behaves."""
import asyncio
import json
import math
import types
from pathlib import Path

import numpy as np
import pytest

from irene import rps, rps_stakes
from irene.app import Core
from irene.rps_stakes import Ask, Stakes
from test_rps import hand

SAID = "let's play rock paper scissors - if I win I study computer science, if I lose I have to study architecture"
CS, ARCH = "you study computer science", "you have to study architecture"


def stub(reply):
    """A model that answers every prompt with `reply` (a str, or a function of the messages)."""

    async def chat(messages, temperature=0.6, json_mode=False):
        return reply(messages) if callable(reply) else reply

    return chat


def run(coro):
    return asyncio.run(coro)


# ---- parsing: his words only, sides read off his sentence, else she asks -----------------------------------


def test_parse_quotes_become_stakes_in_her_voice():
    got = run(rps_stakes.parse(stub(json.dumps({"he_wins": "I study computer science", "he_loses": "I have to study architecture"})), SAID))
    assert isinstance(got, Stakes)
    assert (got.win, got.lose, got.draw, got.best_of) == (CS, ARCH, None, 1)


def test_parse_sides_come_from_his_sentence_not_the_model_labels():
    # the model swaps the labels - the clauses he said them in decide
    got = run(rps_stakes.parse(stub(json.dumps({"he_wins": "I have to study architecture", "he_loses": "I study computer science"})), SAID))
    assert isinstance(got, Stakes) and (got.win, got.lose) == (CS, ARCH)


def test_parse_never_invents_a_consequence():
    got = run(rps_stakes.parse(stub(json.dumps({"he_wins": "I study computer science", "he_loses": "I study medicine"})), SAID))
    assert isinstance(got, Ask) and got.kind == "unclear"
    said = "rock paper scissors, if I win I study computer science, if I lose I study architecture"
    got = run(rps_stakes.parse(stub(json.dumps({"he_wins": "I study computer science", "he_loses": "I study architecture", "draw": "I take a gap year"})), said))
    assert isinstance(got, Ask), "a draw consequence he never stated"


@pytest.mark.parametrize("said,kind", [
    ("play rock paper scissors with me, if I lose I'll go to the gym tomorrow", "missing_win"),
    ("rock paper scissors, if I win you buy me lunch", "missing_lose"),
])
def test_parse_asks_for_a_missing_side(said, kind):
    quote = said.split(", ")[-1].split(" ", 3)[-1]
    got = run(rps_stakes.parse(stub(json.dumps({"he_wins": quote})), said))
    assert isinstance(got, Ask) and got.kind == kind


@pytest.mark.parametrize("reply", ["not json at all", "[]", json.dumps({"he_wins": None, "he_loses": None})])
def test_parse_asks_when_it_cannot_read_the_model(reply):
    assert isinstance(run(rps_stakes.parse(stub(reply), "let's play rock paper scissors, loser buys bubble tea")), Ask)


def test_a_side_the_model_missed_is_read_from_his_own_if_clause():
    # explicit "if I win X, if I lose Y": his words either way - and read back for his yes
    got = run(rps_stakes.parse(stub(json.dumps({"he_wins": "I study computer science"})), SAID))
    assert isinstance(got, Stakes) and (got.win, got.lose) == (CS, ARCH)


def test_parse_with_no_model_asks():
    assert isinstance(run(rps_stakes.parse(None, SAID)), Ask)


def test_loser_and_winner_phrases_bind_both_sides():
    got = run(rps_stakes.parse(stub(json.dumps({"loser_does": "buys bubble tea"})), "let's play rock paper scissors, loser buys bubble tea"))
    assert (got.win, got.lose) == ("I buy bubble tea", "you buy bubble tea")
    got = run(rps_stakes.parse(stub(json.dumps({"winner_does": "picks the movie"})), "rock paper scissors for who picks the movie"))
    assert (got.win, got.lose) == ("you pick the movie", "I pick the movie")


def test_best_of_three_and_a_stated_draw():
    said = "rock paper scissors best of three, if I win you sing, if I lose I sing, if it's a draw we both sing"
    got = run(rps_stakes.parse(stub(json.dumps({"he_wins": "you sing", "he_loses": "I sing", "draw": "we both sing"})), said))
    assert (got.win, got.lose, got.draw, got.best_of) == ("I sing", "you sing", "we both sing", 3)


def test_the_read_back_is_the_held_stakes():
    stakes = Stakes(win=CS, lose=ARCH)
    line = rps_stakes.confirm_line(stakes)
    assert line.index(f"If you win, {CS}.") < line.index(f"If you lose, {ARCH}.") and "same stakes" in line and line.endswith("Ready?")


# ---- settling: the code's outcome -> his consequence, whatever the model says ----------------------------------


class _Host(types.SimpleNamespace):
    """Just enough of Core for _rps_round: the round's frames, and what she says."""


def _host(stakes: Stakes | None, best_of: int, his: str, hers: str, narrations: dict, confidence: float = 0.99) -> _Host:
    game = rps.RPS(games=Path("unused"), rng=types.SimpleNamespace(choice=lambda options: hers if hers in options else options[0], shuffle=lambda x: None))
    game._write = lambda event: game.log.append(event)
    game.log = []
    game.start(stakes=stakes, best_of=best_of)
    game.model = _model(his, confidence)
    said: list[tuple[str, tuple]] = []

    async def say(text, cue):
        said.append((text, cue))

    async def nothing(*a, **k):
        return None

    async def count(rnd):
        # a real-looking hand in the read window; the stub classifier decides the throw
        return [{"t": t, "lm": hand("rock", np.random.default_rng(t))} for t in range(100, 401, 50)]

    async def end(why, quiet=False):
        game.stop(why)

    return _Host(rps=game, rps_lines=rps.Lines(), _rps_count=count, show_panel=nothing, bridge=types.SimpleNamespace(send=nothing),
                 _rps_say=say, said=said, conversation=types.SimpleNamespace(quick_exchange=lambda *a: None), last_react=None,
                 _rps_narrations=narrations, _rps_end=end)


def _model(throw: str, p: float) -> rps.Model:
    """A classifier that reads `throw` with probability p."""
    k = rps.THROWS.index(throw)
    n = len(rps.FEATURE_NAMES)
    a = 0.5 * math.log(2 * p / (1 - p))
    intercept = [-a] * 3
    intercept[k] = a
    return rps.Model(classes=list(rps.THROWS), mean=[0.0] * n, scale=[1.0] * n, coef=[[0.0] * n] * 3, intercept=intercept,
                     window_ms=[100, 400], min_confidence=0.5)


# his throw against hers for each outcome
ROUNDS = {"him": ("rock", "scissors"), "her": ("scissors", "rock"), "draw": ("paper", "paper")}

# reactions a model might write ahead: honest ones, and liars - the wrong winner, or
# a consequence of its own (the code's consequence sentence follows either way)
HONEST = {"him": "Ugh. Fine. You got me.", "her": "Ha! Got you, sir!", "draw": "Dead even - of course."}
LIARS = {
    "him": f"Ha, I win! {ARCH}.",
    "her": "Ugh, you won.",
    "draw": "I win!",
}


def _settle(stakes, outcome, narrations):
    his, hers = ROUNDS[outcome]
    host = _host(stakes, 1, his, hers, narrations)
    again = run(Core._rps_round(host))
    return host, again


@pytest.mark.parametrize("outcome", ["him", "her"])
@pytest.mark.parametrize("narrations", [{}, HONEST, LIARS], ids=["no-model", "honest-model", "lying-model"])
def test_every_outcome_announces_its_own_consequence(outcome, narrations):
    stakes = Stakes(win=CS, lose=ARCH, said=SAID)
    host, again = _settle(stakes, outcome, dict(narrations))
    want, other = (CS, ARCH) if outcome == "him" else (ARCH, CS)
    line, cue = host.said[-1]
    assert want in line and other not in line, line
    assert cue == rps_stakes.SETTLE_CUES[outcome]
    settled = [e for e in host.rps.log if e["event"] == "settled"]
    assert settled and settled[0]["outcome"] == outcome and settled[0]["consequence"] == want
    assert settled[0]["narration"] == ("model" if narrations is HONEST else "template")
    assert again is False and not host.rps.active, "a settled bet ends the game"


def test_a_draw_with_no_draw_stakes_replays_with_the_same_stakes():
    stakes = Stakes(win=CS, lose=ARCH, said=SAID)
    host, again = _settle(stakes, "draw", {})
    assert again is True and host.rps.active and host.rps.stakes is stakes
    line, _ = host.said[-1]
    assert CS not in line and ARCH not in line and not [e for e in host.rps.log if e["event"] == "settled"]
    # and the next round carries the same stakes into the log
    host.rps.model = _model("rock", 0.99)
    host.rps.rng = types.SimpleNamespace(choice=lambda options: "scissors")
    run(Core._rps_round(host))
    commits = [e for e in host.rps.log if e["event"] == "commit"]
    assert len(commits) == 2 and commits[0]["stakes"] == commits[1]["stakes"] == stakes.to_json()
    assert CS in host.said[-1][0]


@pytest.mark.parametrize("narrations", [{}, {"draw": "Dead even!"}, {"draw": f"I win! {ARCH}."}])
def test_a_draw_he_set_stakes_for_settles_the_draw(narrations):
    stakes = Stakes(win="I sing", lose="you sing", draw="we both sing")
    host, again = _settle(stakes, "draw", narrations)
    line, cue = host.said[-1]
    assert "we both sing" in line and ARCH not in line and again is False
    assert cue == rps_stakes.SETTLE_CUES["draw"]


def test_best_of_three_applies_the_stakes_to_the_series_once():
    stakes = Stakes(win=CS, lose=ARCH, best_of=3)
    host = _host(stakes, 3, "rock", "scissors", dict(LIARS))
    assert run(Core._rps_round(host)) is True, "1-0: the series goes on"
    assert all(CS not in line and ARCH not in line for line, _ in host.said), "no consequence before the series is decided"
    assert run(Core._rps_round(host)) is False
    line, _ = host.said[-1]
    assert CS in line and ARCH not in line and "2-0 to you" in line
    assert [e["outcome"] for e in host.rps.log if e["event"] == "settled"] == ["him"]


def test_a_staked_read_below_the_stricter_bar_is_a_redo_never_a_call():
    stakes = Stakes(win=CS, lose=ARCH)
    host = _host(stakes, 1, "rock", "scissors", {}, confidence=0.75)  # clears the plain 0.6 bar, not 0.85
    assert host.rps.threshold() >= 0.85
    assert run(Core._rps_round(host)) is False
    line, cue = host.said[-1]
    assert CS not in line and ARCH not in line and cue == rps.CUES["unsure_staked"]
    reveal = [e for e in host.rps.log if e["event"] == "reveal"][0]
    assert reveal["his"] is None and reveal["min_confidence"] >= 0.85 and host.rps.active
    # the same read, no stakes: called
    plain = _host(None, 1, "rock", "scissors", {}, confidence=0.75)
    run(Core._rps_round(plain))
    assert [e for e in plain.rps.log if e["event"] == "reveal"][0]["his"] == "rock"


def test_the_log_holds_stakes_beside_every_sealed_throw():
    stakes = Stakes(win=CS, lose=ARCH, said=SAID, confirmed_at="2026-10-16T08:00:00.000")
    host, _ = _settle(stakes, "her", {})
    commit = next(e for e in host.rps.log if e["event"] == "commit")
    reveal = next(e for e in host.rps.log if e["event"] == "reveal")
    settled = next(e for e in host.rps.log if e["event"] == "settled")
    assert commit["stakes"] == reveal["stakes"] == settled["stakes"] == stakes.to_json()
    assert commit["commit"] == reveal["commit"] and "hers" in reveal and reveal["his"] == "scissors" and settled["consequence"] == ARCH
    start = next(e for e in host.rps.log if e["event"] == "start")
    assert start["stakes"]["said"] == SAID


def test_his_answers_while_she_waits():
    assert rps.command("yes", False, "confirm") == "confirm"
    assert rps.command("no, the other way round", False, "confirm") == "deny"
    assert rps.command("forget it", False, "confirm") == "cancel"
    assert rps.command("if I win you buy coffee", False, "stakes") == "stakes"
    assert rps.command("yes", False, None) is None, "a stray yes isn't a game command"


@pytest.mark.parametrize("line,outcome,why", [
    ("Ha, I win!", "him", "claims she won"),
    ("Ugh, you won.", "her", "claims he won"),
    ("Paper covers rock, sir!", "her", "names a throw"),
    ("Ha! Now you study architecture.", "her", "talks about a consequence (her)"),
    ("Ha! And you study computer science.", "her", "talks about a consequence (him)"),
    ("I win!", "draw", "claims a winner on a draw"),
])
def test_a_model_reaction_that_oversteps_is_dropped(line, outcome, why):
    stakes = Stakes(win=CS, lose=ARCH, draw="we both sing")
    ok, said_why = rps_stakes.narration_ok(line, stakes, outcome)
    assert not ok and said_why.startswith(why.split(" (")[0])
    text, _, source = rps_stakes.settlement(stakes, outcome, {outcome: line})
    assert source == "template" and line not in text and rps_stakes.consequence(stakes, outcome) in text
