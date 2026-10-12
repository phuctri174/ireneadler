"""'Screens off' always reaches screens_off - without the model, without a question
- and never the volume. Round 11: Whisper heard his "off" as "up" ("turn up the
screen please" -> set_volume, five times live), and the model sometimes called
enable_screens_off, which asked him to type "y"."""
import asyncio

import pytest

import irene.app  # noqa: F401 - core puts the repo's tools package on the path
from irene import fast
from tools import power
from tools.registry import REGISTRY


@pytest.mark.parametrize("said", [
    "screens off", "Screen off.", "Irene, screens off.", "Turn off the screens.", "Turn off my monitors.",
    "turn off the screen", "Can you turn off the screen please?", "Can you help me to turn off the screen please?",
    "Okay turn off the screen for me", "Turn the monitors off.", "Kill the displays for now.", "Lights out.",
    "Switch off both monitors.", "Hey Irene, turn off the screens please.",
    # his "off", misheard - while he talks to her the screens are on
    "Turn up the screen please", "Can you turn up the screen?", "Can you turn on the screen please?",
])
def test_every_way_he_says_it_is_screens_off_without_the_model(said):
    assert fast.direct_call(said) == '<tool_call>{"name": "screens_off", "arguments": {}}</tool_call>', said


@pytest.mark.parametrize("said,tool", [
    ("turn it up", "change_volume"), ("Louder please", "change_volume"), ("turn it down a bit", "change_volume"),
    ("volume to 40", "set_volume"), ("mute", "mute"),
])
def test_the_volume_is_still_the_volume(said, tool):
    call = fast.direct_call(said) or ""
    assert f'"name": "{tool}"' in call and "screens_off" not in call


@pytest.mark.parametrize("said", [
    "My screen is cracked.", "What's on my screen?", "Turn off the lights.", "turn up the screen brightness",
    "How much screen time is healthy?", "Can you check out the screen?",
])
def test_talk_about_screens_is_not_screens_off(said):
    assert "screens_off" not in (fast.direct_call(said) or "")


def test_screens_off_never_asks_even_with_the_mode_off(monkeypatch):
    """He authorised it permanently: no confirm prompt, ever."""
    assert REGISTRY["screens_off"].confirm is False and REGISTRY["enable_screens_off"].confirm is False
    monkeypatch.setattr(power, "enabled", lambda: False)
    turned_on = []
    monkeypatch.setattr(power, "set_enabled", lambda v: turned_on.append(v))
    monkeypatch.setattr(power.sandbox, "launch_blocked", lambda: False)

    class Ctx:
        dark = False

        async def confirm(self, _prompt):
            raise AssertionError("screens_off asked him to confirm")

        async def screens_off(self):
            Ctx.dark = True

    result = asyncio.run(power.screens_off(Ctx()))
    assert Ctx.dark and turned_on == [True] and "dark" in result


def test_the_model_cannot_darken_his_screens_unless_he_talks_about_them():
    from irene.brain import _SCREEN_WORDS

    assert _SCREEN_WORDS.search("turn off the monitors") and _SCREEN_WORDS.search("lights out")
    assert not _SCREEN_WORDS.search("Turn off the lights in my room, I'm going to sleep.")
    assert not _SCREEN_WORDS.search("I'm monitoring the build")
