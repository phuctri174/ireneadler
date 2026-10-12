import random

from irene.greeting import BANDS, NAME, PLAYFUL, Greeter, band


def test_the_hour_picks_the_band():
    assert band(5) == "morning" and band(11) == "morning"
    assert band(12) == "afternoon" and band(17) == "afternoon"
    assert band(18) == "evening" and band(23) == "evening" and band(2) == "evening"


def test_she_greets_by_the_hour_and_never_repeats_herself():
    greeter = Greeter(random.Random(7))
    lines = [greeter.next(9) for _ in range(60)]
    for a, b in zip(lines, lines[1:]):
        assert a != b, a
    assert len(set(lines)) > 8, "the greeting should vary"
    # a morning greeting is a morning one - afternoon and evening never leak in
    from irene.greeting import with_name

    for line in lines:
        if line in {with_name(p) for p in PLAYFUL}:
            continue
        assert line.startswith(BANDS["morning"]), line
        assert "afternoon" not in line and "evening" not in line


def test_every_greeting_says_his_name():
    """His ask: "Mister Tri" in EVERY greeting - enforced in code (greeting.with_name)."""
    greeter = Greeter(random.Random(11))
    lines = [greeter.next(h) for h in (8, 14, 21) for _ in range(80)]
    assert all(NAME in line for line in lines), [l for l in lines if NAME not in l][:3]
    import json
    from pathlib import Path

    from irene.greeting import with_name

    entries = json.loads((Path(__file__).parents[2] / "config" / "entrances.json").read_text(encoding="utf-8"))["entrances"]
    for e in entries:
        for _ in range(20):
            assert NAME in greeter.for_entrance(e, 10), e["name"]
        for g in e.get("greetings", ()):
            assert NAME in g, (e["name"], g)
    assert with_name("Did you miss me?") == "Did you miss me, Mister Tri?"
    assert with_name("You rang, sir?") == "You rang, Mister Tri?"
    playful = [line for line in lines if line in {with_name(p) for p in PLAYFUL}]
    assert playful, "she sometimes skips the greeting for something playful"


def test_every_line_is_a_finished_sentence():
    greeter = Greeter(random.Random(3))
    for hour in (8, 14, 21):
        for _ in range(40):
            line = greeter.next(hour)
            assert line[0].isupper() and line[-1] in ".?!", line
            assert "  " not in line and ", ," not in line, line
