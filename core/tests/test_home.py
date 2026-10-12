"""His location (config/home.yaml): every turn knows it, like the date, and a
location-dependent search that names no place gets it. Asked about the weather,
she once reported New York. The tests run on config/home.example.yaml (London)."""
import asyncio

import pytest

from irene.brain import Conversation, now_section
from irene.home import HOME, load


def test_the_config_says_where_he_is():
    home = load()
    assert (home.city, home.country) == ("London", "United Kingdom")


def test_every_turn_carries_it_like_the_date():
    section = now_section("what should I wear today?")
    assert "London" in section and "United Kingdom" in section and "local time" in section
    assert "London" in Conversation(None).context("hello")


@pytest.mark.parametrize(
    "question,expect",
    [
        ("weather today", "weather today in London, United Kingdom"),
        ("Is it going to rain tomorrow?", "Is it going to rain tomorrow in London, United Kingdom"),
        ("best pho near me", "best pho near me in London, United Kingdom"),
        ("weather on Monday", "weather on Monday in London, United Kingdom"),
        # he named a place, or it is not about where he is: untouched
        ("weather in Tokyo this week", "weather in Tokyo this week"),
        ("temperature in Hanoi", "temperature in Hanoi"),
        ("weather London tomorrow", "weather London tomorrow"),
        ("history of kendo dan grades", "history of kendo dan grades"),
    ],
)
def test_a_search_that_depends_on_where_he_is_gets_his_city(question, expect):
    assert HOME.localise(question) == expect


def test_the_research_call_itself_is_localised():
    from test_brain import FakeHost, FakeLLM

    llm = FakeLLM(['<tool_call>{"name": "research", "arguments": {"question": "weather today"}}</tool_call>', "<speak>Sunny!</speak>"])
    conv = Conversation(llm)

    ran = {}

    async def fake_run(name, args, host):
        ran[name] = args
        return "ok"

    conv._run_tool = fake_run
    asyncio.run(conv.respond("should I bring an umbrella?", FakeHost()))  # the model, not a direct call
    assert ran["research"]["question"] == "weather today in London, United Kingdom"
    assert "London" in conv.history[1]["content"], "the history shows what really ran"


def test_weather_questions_go_straight_to_research_in_his_city():
    from irene.brain import parse_tool_call
    from irene.fast import direct_call

    for said, place in [("What time is sunset today?", "London"), ("Is it going to rain tomorrow?", "London"), ("What's the weather like in Tokyo this weekend?", "Tokyo")]:
        name, args = parse_tool_call(direct_call(said))
        assert name == "research" and place in args["question"], said
    for said in ("I love rainy days, they make me sleepy.", "tell me a joke about the weather", "what's the weather and set a timer"):
        assert direct_call(said) is None, said
