from irene.app import Core
from irene.react import resolve


def test_react_routes_by_kind():
    core = Core()
    assert core.react_messages(resolve("thumbsUp")) == [{"type": "reaction", "value": "thumbsUp"}]
    assert core.react_messages(resolve("concerned")) == [{"type": "emotion", "value": "concerned"}]
    assert core.react_messages(resolve("kendo")) == [{"type": "activity", "value": "kendo", "loops": 1}]
    assert core.react_messages(None) == []


def test_same_reaction_never_twice_running():
    core = Core()
    assert core.react_messages(resolve("giggle")) == [{"type": "reaction", "value": "giggle"}]
    # the same again: another cue plays instead - never none, never the same
    swapped = core.react_messages(resolve("giggle"), text="Haha, good one!")
    assert swapped and swapped[0]["value"] != "giggle"
    assert core.react_messages(resolve("giggle"))  # and giggle may come back after


def test_a_reply_the_model_left_uncued_still_gets_one_that_fits():
    from irene.react import fallback

    assert fallback("Checkmate in three, sir.").name == "chess"
    assert fallback("Oh no, that failed.").name in ("concerned", "sad", "facepalm")
    assert fallback("Wow, what a view!").name in ("starryEyed", "surprised", "excitedBounce")
    for _ in range(20):
        assert fallback("Tokyo, sir.", avoid="happy").name != "happy"
        assert fallback("Checkmate!", avoid="chess").name == "thinking"


def test_a_reply_without_reaction_resets_the_run():
    core = Core()
    core.react_messages(resolve("wave"))
    core.react_messages(None)
    assert core.react_messages(resolve("wave"))


def test_an_action_he_asks_for_plays_even_twice_running():
    import dataclasses

    core = Core()
    kendo = dataclasses.replace(resolve("kendo"), asked=True)
    assert core.react_messages(kendo)
    assert core.react_messages(kendo)


def test_a_repeat_in_an_emotional_moment_swaps_within_the_moment():
    from irene.react import of_family

    core = Core()
    laugh = of_family(("giggle", "wink"))
    assert core.react_messages(laugh)[0]["value"] == "giggle"
    # his second joke in a row: a wink, not something unrelated
    assert core.react_messages(laugh, text="Haha")[0] == {"type": "emotion", "value": "wink"}


def test_the_fallback_reaches_for_her_body():
    from irene.react import _ANYTIME, BY_NAME, fallback

    assert {"headTilt", "excitedBounce"} <= set(_ANYTIME)
    moving = sum(BY_NAME[n]["kind"] == "gesture" for n in _ANYTIME)
    assert moving >= len(_ANYTIME) / 2, "mostly cues that move, not a face that barely changes"
    assert fallback("Hmm, maybe.", avoid="thinking").name in ("headTilt", "shrug")
    assert fallback("Yay, that's brilliant!", avoid="happy").name in ("excitedBounce", "excited", "proud")


def test_a_used_up_moment_reaches_outside_it_rather_than_repeat_an_opening():
    from irene.react import of_family

    core = Core()
    core.react_messages(of_family(("sad", "concerned")))  # "my cat died": opens sad...
    core.react_messages(resolve("concerned"), opening=False)  # ...ends concerned
    # "I'm so tired": the stream picked concerned (sad opened last time)
    shown = core.react_messages(of_family(("concerned", "sad")), text="So tired, sir.")
    assert shown[0]["value"] not in ("sad", "concerned")
