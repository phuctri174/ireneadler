"""Quick replies: everyday exchanges answered from pre-rendered audio, no model."""
import asyncio
import random

import numpy as np
import pytest

from irene import entrances
from irene.quick import INTENTS, QuickReplies, normalise


def quick(seed=1):
    q = QuickReplies(entrances.load_registry(), random.Random(seed))
    q.audio = {line: np.zeros(2400, np.float32) for line in q.lines()}
    q.engine = "turbo"
    return q


@pytest.mark.parametrize(
    "said,intent",
    [
        ("Hi!", "greet"),
        ("Hey Irene, good morning.", "greet"),
        ("hello there", "greet"),
        ("How's it going?", "greet_how"),
        ("Hey Irene, how are you doing today?", "greet_how"),
        ("hi, how are you", "greet_how"),
        ("Thanks, Irene!", "thanks"),
        ("thank you so much", "thanks"),
        ("Good job.", "compliment"),
        ("you're the best, Irene", "compliment"),
        ("Okay.", "ack"),
        ("Got it, thanks sir", None),  # two intents: the model
        ("Cool.", "ack"),
        ("Never mind.", "sorry"),
        ("Are you there?", "presence"),
        ("I'm back!", "back"),
        ("Bye!", "goodbye"),
        ("Good night, Irene.", "goodnight"),
        ("What are you doing?", "doing"),
    ],
)
def test_whole_everyday_messages_match(said, intent):
    assert quick().match(said) == intent


@pytest.mark.parametrize(
    "said",
    [
        "Thanks, and set a timer for ten minutes.",
        "Hi, what's the weather in Da Lat?",
        "okay pause the music",
        "How are you going to fix this bug?",
        "What time is it?",
        "Good morning, can you research kendo grading?",
        "bye the way, what's 2 plus 2",
        "tell me a joke",
        "",
    ],
)
def test_anything_more_goes_to_the_model(said):
    assert quick().match(said) is None


def test_the_wake_phrase_and_his_name_for_her_are_not_part_of_the_match():
    assert normalise("Hey Irene, thanks!") == "thanks"
    assert normalise("Thanks, Irene.") == "thanks"
    assert normalise("thank you sir") == "thank you"


def test_every_line_is_rendered_and_every_cue_exists():
    from irene.react import BY_NAME

    from irene.quick import GREETING_INTENTS
    from irene.greeting import NAME, with_name

    q = quick()
    for intent in INTENTS:
        for line, cues in [*intent.lines, *(l for b in intent.by_band.values() for l in b)]:
            if intent.name in GREETING_INTENTS:
                # every greeting says his name, the cached audio's text included
                line = with_name(line)
                assert NAME in line
            assert line in q.audio
            assert cues and all(c in BY_NAME for c in cues), (line, cues)


def test_never_the_same_line_twice_running_and_never_the_last_cue():
    q = quick(3)
    last_line, last_cue = None, None
    for _ in range(40):
        a = q.answer("thanks", 10, avoid=(last_cue,) if last_cue else ())
        assert a.text != last_line
        assert a.cues[0] != last_cue
        last_line, last_cue = a.text, a.cues[0]


def test_what_she_was_doing_comes_from_the_entrance_or_goes_to_the_model():
    q = quick()
    assert q.answer("what are you doing?", 10, entrance=None) is None
    a = q.answer("what were you doing?", 10, entrance="chess")
    # chess is a signature entrance: one of its own answers, with its cues and sound
    import json
    from pathlib import Path

    chess = next(e for e in json.loads((Path(__file__).parents[2] / "config" / "entrances.json").read_text(encoding="utf-8"))["entrances"] if e["name"] == "chess")
    own = {d["line"]: d for d in chess["doing_answers"]}
    assert a.text in own and list(a.cues) == own[a.text]["cues"] and a.sfx == own[a.text]["sfx"] and a.audio is not None
    # all of them before any comes round again
    said = [a.text] + [q.answer("what were you doing?", 10, entrance="chess").text for _ in range(len(own) - 1)]
    assert set(said) == set(own)
    # an entrance without its own lines still answers from its "doing"
    b = q.answer("what were you doing?", 10, entrance="cards")
    assert b is not None and b.sfx is None


def test_goodbye_ends_the_conversation_and_greetings_suit_the_hour():
    q = quick()
    assert q.answer("goodbye", 22).ends and not q.answer("thanks", 22).ends
    mornings = {q.answer("good morning", 8).text for _ in range(30)}
    assert not any("evening" in t.lower() for t in mornings)
    evenings = {q.answer("hello", 21).text for _ in range(30)}
    assert not any("morning" in t.lower() for t in evenings)


class _Bridge:
    def __init__(self):
        self.sent = []
        self.connected = True
        self.current_state = "listening"

    async def send(self, m):
        self.sent.append(m)

    async def transcript(self, who, text):
        self.sent.append({"type": "transcript", "who": who, "text": text})

    async def state(self, value):
        self.sent.append({"type": "state", "value": value})

    async def emotion(self, value):
        self.sent.append({"type": "emotion", "value": value})

    def send_threadsafe(self, m):
        self.sent.append(m)


def test_core_answers_small_talk_without_the_model_and_keeps_it_in_history():
    from irene.app import Core

    core = Core()
    core.bridge = _Bridge()
    core.quick = quick()
    core.muted = True  # no audio device here

    class NoModel:
        async def chat_stream(self, *_a, **_k):
            raise AssertionError("small talk must not reach the model")
            yield ""

    core.conversation.llm = NoModel()

    async def main():
        await core.on_command({"text": "Thanks, Irene!"})
        await core._turn

    asyncio.run(main())
    said = [m["text"] for m in core.bridge.sent if m.get("type") == "transcript" and m["who"] == "irene"]
    assert len(said) == 1
    assert [m["role"] for m in core.conversation.history] == ["user", "assistant"]
    assert any(m.get("type") in ("reaction", "emotion", "activity") for m in core.bridge.sent), "every reply carries a cue"


def test_a_pending_yes_no_is_never_taken_for_small_talk():
    from irene.app import Core

    core = Core()
    core.quick = quick()
    core.conversation._panel_offer = True
    assert core.quick_answer("okay") is None
    core.conversation._panel_offer = False
    assert core.quick_answer("okay") is not None


def test_kamae_gets_a_fired_up_line_never_the_same_twice_and_only_faces():
    from irene.quick import KAMAE_LINES
    from irene.react import BY_NAME

    q = quick(5)
    last = None
    for _ in range(20):
        a = q.kamae()
        assert a.text != last and a.audio is not None
        # hands would draw over the kamae scene's own arms: expressions only
        assert all(BY_NAME[c]["kind"] == "expression" for c in a.cues)
        last = a.text
    assert "firedUp" in {c for _, cs in KAMAE_LINES for c in cs}


def test_kamae_no_longer_starts_anything():
    """The kamae pose trigger is retired (it fired on everyday arm movements): keiko
    starts only when he asks for it (keiko.py)."""
    from irene.app import Core

    core = Core()
    core.bridge = _Bridge()
    core.quick = quick()
    core.muted = True

    async def main():
        await core.on_kamae({"type": "kamae", "phase": "start"})
        assert core.bridge.sent == [] and core._turn is None
        assert not core.keiko.active

    asyncio.run(main())


def test_what_she_was_doing_reads_as_one_clean_sentence():
    import re

    from irene.quick import DOING_LINES, doing_line

    for entry in entrances.load_registry():
        for template in DOING_LINES:
            line = doing_line(template, entry)
            assert not re.search(r"[?!.,][.!?]", line) and " - " not in line, line
