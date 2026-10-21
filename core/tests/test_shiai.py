"""Shiai (irene/shiai.py), the whole spec: his strikes are men only; she attacks men or
kote; he dodges and blocks; she dodges, parries and counters; a countdown then a
shouted hajime; a pause after each point then hajime; the score; first to two."""
from __future__ import annotations

import random

from irene import shiai


class Dice(random.Random):
    """Every roll goes the way the test says."""

    def __init__(self, pick: str, target: str = "men") -> None:
        super().__init__(0)
        self.pick, self.target = pick, target

    def choices(self, population, weights=None, k=1):
        if tuple(population) == shiai.TARGETS:
            return [self.target]
        return [self.pick]

    def uniform(self, a, b):
        return a


def bout(pick: str, target: str = "men") -> shiai.Shiai:
    """A bout under way: started, and its countdown's hajime called."""
    s = shiai.Shiai(rng=Dice(pick, target))
    s.start(now=0.0)
    s.hajime(now=0.0)
    return s


def attack(s: shiai.Shiai) -> shiai.Answer:
    a = s.tick(now=s.next_attack + 0.01)
    assert a.action == "windup" and s.attacking is not None
    return a


def test_start_and_stop_by_voice_only():
    for said in ("Irene, let's do shiai", "shiai time", "let's have a kendo match", "first to two!", "Shall we do a bout?"):
        assert shiai.command(said, False) == "start", said
    for said in ("I had a shiai yesterday", "what is shiai?", "let's have a chess match", "let's do keiko"):
        assert shiai.command(said, False) is None, said
    assert shiai.command("yame", True) == "stop"
    assert shiai.command("stop the music", True) is None


def test_it_is_first_to_two_and_nothing_counts_before_hajime():
    s = shiai.Shiai(rng=Dice("take"))
    a = s.start(now=0.0)
    assert "sanbon shobu" in a.line.lower() and a.score == (0, 0) and s.paused
    assert s.strike(now=1.0) is None and s.tick(now=60.0) is None
    go = s.hajime(now=5.0)
    assert go.line == "Hajime!" and not s.paused
    s.strike(now=6.0)
    s.hajime(now=12.0)
    end = s.strike(now=13.0)
    assert end.over and (s.you, s.her) == (2, 0) and "Shobu ari!" in end.line and not s.active


def test_every_strike_of_his_is_a_men():
    s = bout("take")
    a = s.strike(now=1.0)
    assert a.line.startswith("Men ari!") and a.call == "MEN ARI" and a.who == "you" and a.flags == 3


def test_one_swing_is_one_strike():
    """Live in bogu one swing came through the detector as 2-3 events over 1.4 s: she
    answers the first, and the rest of the same swing are nothing."""
    s = bout("parry")
    assert s.strike(now=1.0).action == "block"
    assert s.strike(now=1.5) is None and s.strike(now=2.4) is None
    assert s.strike(now=1.0 + shiai.STRIKE_GAP_S + 0.6) is not None, "a later swing is a new strike"


def test_she_parries_dodges_and_counters():
    for pick, hud in (("parry", "block"), ("dodge", "dodge")):
        s = bout(pick)
        assert s.strike(now=1.0).action == hud and (s.you, s.her) == (0, 0)
    s = bout("counter", target="kote")
    a = s.strike(now=1.0)
    assert (s.you, s.her) == (0, 1) and a.line.startswith("Kote ari!") and a.who == "her"


def test_she_attacks_with_men_or_kote_only():
    assert set(shiai.TARGETS) == {"men", "kote"}
    for target in ("men", "kote"):
        s = bout("parry", target=target)
        assert attack(s).target == target


def test_her_attack_lands_if_he_stands_there():
    s = bout("parry", target="kote")
    attack(s)
    assert s.tick(now=s.attacking + 0.5) is None
    landed = s.tick(now=s.attacking + shiai.WINDOW_S + 0.1)
    assert landed.action == "ippon" and (s.you, s.her) == (0, 1) and landed.line.startswith("Kote ari!")
    assert landed.before == [{"type": "keiko", "action": "impact", "target": "kote", "result": "hit"}]


def test_he_dodges_by_stepping_back_or_aside():
    for step in ("retreat", "side"):
        s = bout("parry")
        attack(s)
        a = s.move(step, now=s.attacking + 0.4)
        assert a.action == "impact" and a.result == "dodged" and s.attacking is None and s.her == 0
    s = bout("parry")
    attack(s)
    assert s.move("advance", now=s.attacking + 0.4) is None and s.attacking is not None


def test_he_blocks_her_men_with_his_hands_up():
    s = bout("parry", target="men")
    attack(s)
    a = s.move("block", now=s.attacking + 0.5)
    assert a.action == "impact" and a.result == "blocked" and (s.you, s.her) == (0, 0)
    # outside her window, hands up are nothing
    assert s.move("block", now=200.0) is None


def test_hands_up_against_her_kote_leave_it_open():
    s = bout("parry", target="kote")
    attack(s)
    assert s.move("block", now=s.attacking + 0.3) is None and s.attacking is not None
    landed = s.tick(now=s.attacking + shiai.WINDOW_S + 0.1)
    assert landed.line.startswith("Kote ari!") and any(x in landed.line for x in shiai.LINES["open"])


def test_a_point_pauses_play_until_hajime():
    s = bout("take")
    a = s.strike(now=1.0)
    assert a.reset == "NIHONME" and s.paused
    assert s.strike(now=4.0) is None and s.tick(now=50.0) is None and s.move("retreat", now=4.1) is None
    s.hajime(now=6.0)
    assert not s.paused and s.strike(now=8.0) is not None


def test_one_all_is_shobu():
    s = bout("take")
    s.strike(now=1.0)
    s.hajime(now=2.0)
    s.rng.pick = "counter"
    assert s.strike(now=10.0).reset == "SHOBU" and (s.you, s.her) == (1, 1)


def test_every_point_carries_the_score_for_the_board():
    s = shiai.Shiai(rng=random.Random(3))
    s.start(now=0.0)
    s.hajime(now=0.0)
    t, seen = 1.0, []
    while s.active and t < 500:
        a = s.strike(now=t)
        if a is not None and a.score is not None:
            seen.append(a.score)
            assert a.score == (s.you, s.her)
            if a.reset:
                s.hajime(now=t + 1)
        t += 10.0
    assert seen and shiai.TO_WIN in seen[-1]


def test_she_calls_it_when_he_wanders_off():
    s = bout("parry")
    s.next_attack = 1e9
    a = s.tick(now=shiai.IDLE_END_S + 1)
    assert a.over and a.action == "end" and not s.active


def test_the_beat_is_configured(tmp_path):
    assert shiai.beat()["startCountdownS"] == 5.0 and shiai.beat()["pauseS"] == 5.0, "the shipped: 5 s and 5 s"
    path = tmp_path / "shiai.json"
    path.write_text('{"startCountdownS": 7, "pauseS": 4}', encoding="utf-8")
    assert shiai.beat(path)["startCountdownS"] == 7.0 and shiai.beat(path)["pauseS"] == 4.0


def test_every_cue_she_uses_is_registered():
    from irene import react, strike_tuning

    names = {c["name"] for c in react.CUES}
    used = {c for pool in shiai.CUES.values() for c in pool} | set(strike_tuning.CUES.values())
    assert used <= names, used - names


def test_hajime_is_shouted_not_read():
    import numpy as np

    from irene import sfx
    from irene.summon_fx import SR

    t = np.arange(int(0.5 * SR)) / SR
    voice = np.concatenate([np.zeros(int(0.3 * SR)), 0.3 * np.sin(2 * np.pi * 220 * t), np.zeros(int(0.3 * SR))]).astype(np.float32)
    out = sfx.shout(voice, np.random.default_rng(1))
    assert out.dtype == np.float32 and abs(float(np.max(np.abs(out))) - 1.0) < 1e-3
    assert len(out) < len(voice) * 0.6 and np.max(np.abs(out[: int(0.02 * SR)])) > 0.3


def test_his_men_heights_are_his_to_nudge(tmp_path):
    """The men sequence's two heights, against his own kamae, come from config/shiai.json."""
    strikes = {"minVis": 0.4}
    t = shiai.men_tuning(strikes)
    assert (t["raiseAboveKamae"], t["finishAboveKamae"]) == (1.8, 1.1) and t["holdMs"] == 400 and t["minVis"] == 0.4
    path = tmp_path / "shiai.json"
    path.write_text('{"menRaiseAboveKamae": 1.3, "menZanshinAboveKamae": 0.7}', encoding="utf-8")
    t = shiai.men_tuning(strikes, path)
    assert (t["raiseAboveKamae"], t["finishAboveKamae"]) == (1.3, 0.7)
