from pathlib import Path

from irene.pronounce import apply, load_rules

CONFIG = Path(__file__).resolve().parents[2] / "config" / "pronunciation.yaml"


def rules():
    return load_rules(CONFIG)


def test_tri_gets_phoneme_override():
    assert apply("Good morning, Mister Tri.", rules()) == "Good morning, Mister [Tri](/tɹˈi/)."


def test_possessive_and_punctuation():
    assert apply("Tri's files", rules()) == "[Tri](/tɹˈi/)'s files"
    assert apply("sir, Tri!", rules()) == "sir, [Tri](/tɹˈi/)!"


def test_whole_word_any_case():
    # his name in any case; never part of a longer word
    text = "trip trial Trial Tripod triangle Atri"
    assert apply(text, rules()) == text
    assert apply("tri and TRI", rules()) == "[tri](/tɹˈi/) and [TRI](/tɹˈi/)"


def test_respelling_any_case(tmp_path):
    path = tmp_path / "p.yaml"
    path.write_text("Tri:\n  say: Tree\n", encoding="utf-8")
    assert apply("hi tri, hi TRI, trip", load_rules(path, phonemes=False)) == "hi Tree, hi Tree, trip"


def test_idempotent():
    once = apply("Mister Tri", rules())
    assert apply(once, rules()) == once


def test_respelling(tmp_path):
    path = tmp_path / "p.yaml"
    path.write_text("Nguyen:\n  say: Win\n", encoding="utf-8")
    assert apply("Mr Nguyen.", load_rules(path)) == "Mr Win."


def test_a_stressed_word_is_said_but_acronyms_are_spelled():
    from irene.tts import unshout

    assert unshout("Wait, you did WHAT?") == "Wait, you did what?"
    assert unshout("Your GPU and CPU are fine.") == "Your GPU and CPU are fine."
    assert unshout("DOMAIN EXPANSION: IRENE ADLER") == "Domain Expansion: Irene Adler"
