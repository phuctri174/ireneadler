"""Mode entry is code (irene/modes.py + dispatch.route): every mode's entry phrases,
and Whisper's known mishearings of them, are claimed before the fast path or the
model sees the words - and talk about the same things is not."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))

import harness  # noqa: E402
from irene import fast, modes  # noqa: E402
from irene.brain import Conversation  # noqa: E402

ENTRY = [
    # study mode
    ("Irene, go study the Sicilian", "study"), ("Learn Sicilian", "study"), ("I think you should go learn the Sicilian", "study"),
    ("Go La Sicilia", "study"), ("learn how chess works", "study"), ("Learn about black holes", "study"), ("go learn suriage waza", "study"),
    ("learn tenouchi", "study"), ("Gaula Sicilian", "study"), ("Irene, study the Caro-Kann", "study"), ("I want you to learn quantum entanglement", "study"),
    # shiai - and Whisper's spellings of it, every one from his voice
    ("Irene, let's do shiai", "shiai"), ("Let's do CI Let's do CI", "shiai"), ("Yes, let's do CI.", "shiai"), ("Let's do Xi'an.", "shiai"),
    ("Let's do xi-ai", "shiai"), ("Let's do Si An", "shiai"), ("Let's do Sii.", "shiai"), ("CI time", "shiai"),
    ("Let's do kendo", "shiai"), ("Kendo match!", "shiai"), ("Let's have a kendo match", "shiai"),
    # keiko
    ("Let's do keiko", "keiko"), ("Let's spar", "keiko"), ("Let's do kendo practice", "keiko"),
    # the strike calibration
    ("Calibrate my strikes", "strikes"), ("Calibrate my stripe", "strikes"), ("Calibrate Mindstrike", "strikes"),
    # chess, rock-paper-scissors
    ("Let's play chess!", "chess"), ("Let's have a chess match", "chess"), ("Let's play rock paper scissors", "rps"),
]
TALK = [
    "I studied the Sicilian all weekend", "I need to go study for my exam tomorrow", "study the Sicilian, they said, it's easy",
    "Learn to code with me", "I want to learn how chess works", "I learned about black holes today", "I need to learn tenouchi", "Our CI pipeline is broken again", "Let's do it here", "I love kendo",
    "my kendo match went badly", "I had a shiai yesterday and lost on a kote", "My strikes were really slow at practice today",
    "I had a chess match yesterday",
]
LECTURE = [
    "Irene, listen to this lecture for me.", "Can you take notes on the class that's about to start on my screen?",
    "Transcribe this Zoom meeting while I cook.", "I'm going to sleep, keep listening to the webinar and write it all down.",
]
NOT_LECTURE = ["Record the meeting tomorrow", "I listened to the lecture yesterday", "I have a lecture tomorrow", "can you record my screen"]


@pytest.fixture(scope="module")
def conv():
    return Conversation(None)


@pytest.mark.parametrize("said,mode", ENTRY)
def test_every_mode_entry_is_claimed_in_code(conv, said, mode):
    assert harness.who_answers(conv, said)[0] == mode


@pytest.mark.parametrize("said", TALK)
def test_talk_about_the_same_things_goes_to_the_model(conv, said):
    assert harness.who_answers(conv, said)[0] == "model"


@pytest.mark.parametrize("said", LECTURE)
def test_lecture_capture_starts_in_code(said):
    assert fast.direct_call(said) == '<tool_call>{"name": "lecture_start", "arguments": {}}</tool_call>'


@pytest.mark.parametrize("said", NOT_LECTURE)
def test_a_lecture_mentioned_is_not_started(said):
    assert fast.direct_call(said) is None or "lecture_start" not in fast.direct_call(said)


def test_mishearings_are_put_back_only_where_a_command_stands():
    assert modes.heard("Let's do CI") == "Let's do shiai"
    assert modes.heard("Our CI pipeline is broken") == "Our CI pipeline is broken"
    assert modes.heard("Calibrate my stripe") == "Calibrate my strikes"
    assert modes.heard("Go La Sicilia") == "go learn the Sicilian"
    # a lone yes is still a yes (RPS confirms the stakes with it)
    assert modes.heard("Yes") == "Yes"


def test_learn_sicilian_never_reaches_research(conv):
    """Live 2026-10-18: "Learn Sicilian" went to research through the fast path's
    chess-opening route. It is study mode now, claimed before the fast path."""
    who, found = harness.who_answers(conv, "Learn Sicilian")
    assert who == "study" and found == ("start", "Sicilian")


@pytest.mark.parametrize("said", ["I studied the Sicilian all weekend", "study the Sicilian, they said, it's easy", "the Najdorf is sharp"])
def test_naming_an_opening_is_not_asking_about_it(said):
    """The chess-opening route used to test `text + "?"` - a question, always - so any
    sentence naming an opening was researched (three live sightings)."""
    call = fast.direct_call(said)
    assert call is None or "research" not in call


@pytest.mark.parametrize("said", ["What's the Sicilian Defence?", "Explain the Caro-Kann", "Tell me about the King's Indian"])
def test_asking_about_an_opening_still_researches_it(said):
    assert '"research"' in fast.direct_call(said)


# the verb decides (2026-10-18): learn / study -> study mode, any topic; research /
# look up / search -> the research feature. Both in code, before the model.
LEARN = ["learn tenouchi", "Go learn suriage waza", "Irene, study black holes", "Learn about black holes",
         "go learn about the French Revolution", "Irene, learn kirikaeshi", "I want you to study how vaccines work"]
RESEARCH = ["research tenouchi", "Research suriage waza", "look up black holes", "search tenouchi", "search for suriage waza",
            "Search up kirikaeshi", "Irene, look up the French Revolution", "Can you research how vaccines work?"]


@pytest.mark.parametrize("said", LEARN)
def test_learn_is_study_mode_whatever_the_topic(conv, said):
    assert harness.who_answers(conv, said)[0] == "study"


@pytest.mark.parametrize("said", RESEARCH)
def test_research_is_the_research_feature_whatever_the_topic(conv, said):
    assert harness.who_answers(conv, said)[0] == "model"
    call = fast.direct_call(said)
    assert call is not None and '"research"' in call, said


@pytest.mark.parametrize("said", ["search my files for the report", "search YouTube for lofi", "search my downloads for the pdf"])
def test_searching_his_files_or_youtube_is_not_research(said):
    call = fast.direct_call(said)
    assert call is None or '"research"' not in call
