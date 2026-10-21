"""What he tells her about a song is FILED, whatever its shape, and she says so - or
says it wasn't (live 2026-10-19: "No, it's Blue by Yongkai" was never filed, silently)."""
import asyncio

import pytest

from irene import recall, taught
from irene.brain import Conversation
from tests.test_brain import FakeLLM
from tests.test_taught import BoardHost

LYRICS = "I think I'll picture us you with the waves the oceanless colors on your face"
QUESTION = f"Hey Irene. Do you know the name of the song with the lyrics? {LYRICS}"


@pytest.mark.parametrize("said, title, artist", [
    ("that song is Blue by yung kai", "Blue", "yung kai"),
    ("no, it's Blue by Yongkai", "Blue", "Yongkai"),
    ("No, it's blue by Yongkai", "blue", "Yongkai"),
    ("it's called Blue, by yung kai", "Blue", "yung kai"),
    ("wrong — Blue, yung kai", "Blue", "yung kai"),
    ("remember that one is Blue by yung kai", "Blue", "yung kai"),
    # his real app, 2026-10-19 22:38, his voice as Whisper heard it - was NOT filed
    ("It's blue from Yung Kai", "blue", "Yung Kai"),
    ("it's Blue, sung by yung kai", "Blue", "yung kai"),
])
def test_his_phrasings_all_file(said, title, artist):
    got = taught.teaching(said, LYRICS, False)
    assert isinstance(got, taught.Teach) and (got.title, got.artist) == (title, artist), got
    # his lyrics from the question come with it: what finds it later
    assert LYRICS in got.text and got.text.startswith(said)


def test_what_is_not_teaching():
    for said in ("Yes, it's correct", "thanks", "play it on youtube", "it's fine by me",
                 f"no it's not it should be another song please listen again {LYRICS}", "who sings it?"):
        assert not isinstance(taught.teaching(said, LYRICS, said.endswith("?")), taught.Teach), said
    # a correction with no title in it, or a naming that can't be read: not filed - and
    # she says so, never a silent pass to the model
    for said in ("no, that's wrong", "it's the one from the movie", "that's not it"):
        assert isinstance(taught.teaching(said, LYRICS, False), taught.NotFiled), said
    # a request after her answer is a request
    for said in ("play it on youtube", "can you play it", "search for it"):
        assert taught.teaching(said, LYRICS, False) is None, said
    # no song question before it: still a statement of a work
    assert isinstance(taught.teaching("no, it's Blue by Yongkai", None, False), taught.Teach)
    assert taught.teaching("I love Blue by yung kai", None, False) is None


_BGE = []


def _store(tmp_path, monkeypatch):
    # one embedding model, loaded, as the app has it (a fresh one isn't ready: told() finds nothing)
    if not _BGE:
        _BGE.append(recall.Embedder())
    store = recall.Store(tmp_path / "memory.sqlite", _BGE[0])
    monkeypatch.setattr(recall, "HIS", store)
    monkeypatch.setattr(recall, "DEV", store)
    return store


def _said(host):
    return " ".join(e[1] for e in host.events if e[0] == "say")


@pytest.mark.skipif(not recall.MODEL_DIR.exists(), reason="bge-small-en-v1.5 not installed")
def test_his_correction_is_filed_said_and_found_after_a_restart(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    llm = FakeLLM(["<speak><cue>proud</cue>That's “Strawberry Swing” by Coldplay.</speak>"])
    conv = Conversation(llm)
    asyncio.run(conv.respond(QUESTION, BoardHost()))
    host = BoardHost()
    asyncio.run(conv.respond("No, it's Blue by Yongkai", host))
    # said in code once it is filed - the model was never asked
    assert len(llm.seen) == 1 and _said(host) == "Fixed - filed “Blue” by Yongkai."
    facts = [i for i in store.items if recall.taught_fact(i)]
    assert len(facts) == 1 and facts[0].about == "taught: Blue | Yongkai" and LYRICS in facts[0].text and facts[0].source == "him"
    store.close()
    # a restart: the same file, opened fresh - his lyrics find it
    store = _store(tmp_path, monkeypatch)
    got = recall.recall(QUESTION, session="later", store=store)
    assert [i.about for i in got.items] == ["taught: Blue | Yongkai"] and "Blue" in got.section
    store.close()


@pytest.mark.skipif(not recall.MODEL_DIR.exists(), reason="bge-small-en-v1.5 not installed")
def test_a_correction_replaces_what_was_filed(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    conv = Conversation(FakeLLM(["<speak>That's “Blue” by yung kai.</speak>"]))
    asyncio.run(conv.respond("that song is Blue by yung kai, the one that goes " + LYRICS, BoardHost()))
    asyncio.run(conv.respond(QUESTION, BoardHost()))
    host = BoardHost()
    asyncio.run(conv.respond("wrong - Bluer, yung kai", host))
    facts = [i for i in store.items if recall.taught_fact(i)]
    assert [f.about for f in facts] == ["taught: Bluer | yung kai"], [f.text for f in facts]
    assert _said(host) == "Fixed - filed “Bluer” by yung kai."
    store.close()


@pytest.mark.skipif(not recall.MODEL_DIR.exists(), reason="bge-small-en-v1.5 not installed")
def test_not_filed_is_said_too(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    conv = Conversation(FakeLLM(["<speak>That's “Strawberry Swing” by Coldplay.</speak>"]))
    asyncio.run(conv.respond(QUESTION, BoardHost()))
    host = BoardHost()
    asyncio.run(conv.respond("no, that's wrong", host))
    assert "haven't filed anything" in _said(host) and not [i for i in store.items if recall.taught_fact(i)]
    # and when the write itself fails
    monkeypatch.setattr(store, "add", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    host = BoardHost()
    asyncio.run(conv.respond("remember that one is Blue by yung kai", host))
    assert _said(host) == "I couldn't file that - the memory write failed."
    store.close()


# every correction he said to her by voice on 2026-10-19, as Whisper heard it (core.log) -
# none of them was filed that day
HIS_DAY = [
    ("No, it's blue by Yongkai", "blue", "Yongkai"),
    ("That song is blue from Yung Kai okay?", "blue", "Yung Kai"),
    ("It's blue from Yongkai Irene. You should know that", "blue", "Yongkai"),
    ("It's blue from Yung Kai okay?", "blue", "Yung Kai"),
    ("It's blue from Yung Kai", "blue", "Yung Kai"),
    ("It's the song with the name Blue from Dung Kai okay?", "Blue", "Dung Kai"),
    ("It's blue from Yunkai okay?", "blue", "Yunkai"),
]


@pytest.mark.parametrize("said, title, artist", HIS_DAY)
def test_every_correction_he_said_that_day_files(said, title, artist):
    got = taught.teaching(said, LYRICS, said.rstrip().endswith("?"))
    assert isinstance(got, taught.Teach) and (got.title, got.artist) == (title, artist), got


def test_what_else_he_said_after_her_answers_that_day_is_not_filed():
    # his other messages right after a song answer, the same day: never filed, never "not filed"
    for said in ("Hey Irene.", "That's correct.", "What?", "Hi Irene.", "Hey can you",
                 "no it's not it should be another song please listen again I think I picture as you with the waves the oceanless colors on your face",
                 "Hey Irene. Do you know the name of the song that just had the lyrics? That just had the lyrics?",
                 "You can ask the flowers I sing for hours Telling all the bluebirds The beautiful and cool birds Pretty little baby I'm so in love with you"):
        assert taught.teaching(said, LYRICS, said.rstrip().endswith("?")) is None, said
    # a real question is never filed
    assert taught.teaching("is it Blue by yung kai?", LYRICS, True) is None
