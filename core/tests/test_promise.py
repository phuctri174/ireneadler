"""A filler line is a prefix to a turn still running, never the whole reply."""
import asyncio

from irene.brain import Conversation, KEEP_PROMISE
from irene.reply import drop_promise, promises_action
from tests.test_brain import FakeHost, FakeLLM, run


def test_it_spots_a_promise_of_work():
    for said in ["Ooh, let me look that up for you...", "Let me check that, sir.",
                 "One moment!", "Hold on...", "I'll go and find out.", "Checking it up now."]:
        assert promises_action(said), said


def test_it_leaves_alone_what_is_not_a_promise_of_work():
    for said in ["I looked it up - tenouchi is the grip.", "Hmm, let me think about that.",
                 "Let me explain.", "According to the sources, it's the grip.",
                 "Tenouchi is the grip at the moment of the cut."]:
        assert promises_action(said) is None, said


def test_a_filler_does_not_end_the_turn_it_forces_the_tool():
    # she says she will look it up and calls nothing; the turn must not end there
    llm = FakeLLM([
        "<speak><cue>thinking</cue>Ooh, let me look that up for you...</speak>",
        '<tool_call>{"name": "get_time", "arguments": {}}</tool_call>',
        "<speak>It's just gone noon, sir.</speak>",
    ])
    turn = run(Conversation(llm), "what time is it in Hanoi right now?", FakeHost())
    assert turn.tools_used == ["get_time"], "the promised work has to actually run"
    assert "noon" in turn.reply.speak
    # the nudge went to the model, naming what went wrong
    nudged = [m["content"] for msgs in llm.seen for m in msgs if m["content"] == KEEP_PROMISE]
    assert nudged, "the model is told it promised and called nothing"


def test_the_filler_is_kept_as_a_prefix_not_replayed_as_the_answer():
    llm = FakeLLM([
        "<speak>Let me check that.</speak>",
        '<tool_call>{"name": "get_time", "arguments": {}}</tool_call>',
        "<speak>Noon, sir.</speak>",
    ])
    turn = run(Conversation(llm), "could you check the clock for me?", FakeHost())
    # the turn's reply is the ANSWER; the filler was already spoken on its way past
    assert "Noon" in turn.reply.speak
    assert promises_action(turn.reply.speak) is None


def test_an_empty_promise_is_never_left_in_the_reply():
    # nothing can perform it and the nudge does not help: she must not claim it
    llm = FakeLLM([
        "<speak>Let me go and check the weather station.</speak>",
        "<speak>Let me go and check the weather station.</speak>",
        "<speak>Let me go and check the weather station.</speak>",
    ])
    turn = run(Conversation(llm), "tell me a joke about rain", FakeHost())
    assert promises_action(turn.reply.speak) is None, turn.reply.speak


def test_a_promise_after_real_work_is_left_alone():
    # system_status has no fast-path template, so the model's own reply survives
    llm = FakeLLM([
        '<tool_call>{"name": "system_status", "arguments": {}}</tool_call>',
        "<speak>All healthy. Let me check the disks again tomorrow, sir.</speak>",
    ])
    turn = run(Conversation(llm), "how is the machine doing?", FakeHost())
    assert turn.tools_used == ["system_status"]
    # the work happened, so the line about next time is hers to keep
    assert "healthy" in turn.reply.speak.lower()
    assert "tomorrow" in turn.reply.speak.lower()


def test_drop_promise_keeps_the_substance():
    assert drop_promise("Tenouchi is the grip. Let me look that up for more.") == "Tenouchi is the grip."
    assert drop_promise("Let me look that up.") == ""


def test_standing_by_an_opinion_or_being_stuck_on_something_is_not_a_promise():
    from irene.reply import promises_action

    # a line from the (since cut) gaming entrance: it once sent "what are you doing?" off to research
    assert promises_action("Losing, sir. That last boss is cheating, I stand by it.") is None
    assert promises_action("I'm hardstuck on it, sir.") is None
    for filler in ("On it!", "Right, on it.", "I'm on it, sir.", "Please stand by.", "Hold on a second."):
        assert promises_action(filler), filler
