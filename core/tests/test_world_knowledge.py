"""Naming a song from its lyrics (a film, a book, a person from a description) is world
knowledge: his memory is never consulted, and the answer is SAID, never left on the board.

Live 2026-10-18/19: "Do you know the name of the song with the lyrics? ..." recalled her
earlier answers to the same question; she took them as his ("Oh, you remembered that
one!"), then put '"Blue" by Yung Kai.' on the board and said "Oh, Mister Tri. You did
remember." - and each failed turn, kept, was recalled into the next, until five turns
in a row said only "Oh, Mister Tri."
"""
import asyncio

import pytest

from irene import recall
from irene.brain import Conversation
from irene.reply import unsaid_answer

from test_brain import FakeHost, FakeLLM

LIVE = ("Hey Irene. Do you know the name of the song with the lyrics? I'll imagine we fell in love I'll nab out the "
        "moonlight skies with you I think I'll picture a suit with the waves The ocean-less colors on your face")

WORLD = [
    LIVE,
    "What is the song has the lyric that I think I'll picture a suit with the waves the ocean has colors on your face",
    "Do you know the name of the song with the lyrics?",
    "What's the song that goes 'is this the real life, is this just fantasy'?",
    "Name that song: hello from the other side",
    "Which film is the one with the giant shark terrorising a beach town?",
    "What's the name of the movie where a ship hits an iceberg?",
    "What's the name of the book about a boy wizard with a lightning scar?",
    "Who wrote the book where a man wakes up as a giant bug?",
    "Who was the scientist who came up with relativity?",
    "Who's the painter that cut off his own ear?",
    "who sang hello from the other side",
    "can you guess the song, I think I'll picture us with the waves",
]
HIS = [
    "What was the song I sent you yesterday?",
    "Who sang my favourite song?",
    "What's the name of my brother's band?",
    "Do you remember the song we talked about?",
    "What song did you recommend last time?",
    "What's the name of the song you played me?",
    "What's my sister's name again?",
    "I love this song",
    "who is Trác",
]


def test_world_knowledge_is_told_apart_from_his_own_things():
    for said in WORLD:
        assert recall.world_knowledge(said), said
    for said in HIS:
        assert not recall.world_knowledge(said), said


def test_world_knowledge_never_consults_his_memory(tmp_path):
    store = recall.Store(tmp_path / "memory.sqlite")
    # exactly the poison from the live store: her earlier answers to the same question
    store.add("turn", 'He said: "Do you know the name of the song with the lyrics?" You said: "Oh, Mister Tri. You did remember."', session="old")
    store.add("turn", 'He said: "What is the song with the lyrics that I think I\'ll picture us with the waves" You said: "Oh, you remembered that one!"', session="old")
    for said in WORLD:
        got = recall.recall(said, session="now", store=store)
        # (only guidance: a song from its lyrics he never taught is one she does not know)
        assert got.skipped == "world knowledge" and not got.items and not got.past and "remember" not in got.section, said
    # his own things still do
    got = recall.recall("What was the song I asked you about with the lyrics?", session="now", store=store)
    assert not got.skipped
    store.close()


def test_a_short_answer_on_the_board_is_said():
    assert unsaid_answer("Oh, Mister Tri. You did remember.", '"Blue" by Yung Kai.') == '"Blue" by Yung Kai.'
    assert unsaid_answer("Hmm.", "Bohemian Rhapsody - Queen") == "Bohemian Rhapsody - Queen."
    # already said: nothing added
    assert unsaid_answer("That's Blue by Yung Kai, sir.", '"Blue" by Yung Kai.') is None
    # a list, a table, code, a long block: that is what the board is for
    assert unsaid_answer("Two files.", "a.pdf\nb.pdf") is None
    assert unsaid_answer("Here.", "| a | b |") is None
    assert unsaid_answer("Here.", "- one thing") is None
    assert unsaid_answer("Sure.", " ".join(["word"] * 20)) is None
    assert unsaid_answer("Sure.", "") is None


def test_the_live_reply_says_the_title_out_loud():
    llm = FakeLLM(['<speak><cue>sheepish</cue>Oh, Mister Tri. <cue>playful</cue>You *did* remember.</speak>\n<display>\n"Blue" by Yung Kai.\n</display>'])
    host = FakeHost()
    turn = asyncio.run(Conversation(llm).respond("Do you know the name of the song with the lyrics?", host))
    said = [e[1] for e in host.events if e[0] == "say"]
    assert said[-1] == '"Blue" by Yung Kai.', said
    assert "Blue" in turn.reply.speak if hasattr(turn, "reply") else True


def test_naming_it_never_opens_his_apps():
    """Routing evals 2026-10-19: lyrics questions called search_files, youtube_search and
    once youtube_play - refused, and she answers instead."""
    llm = FakeLLM(['<tool_call>{"name": "youtube_play", "arguments": {"query": "never gonna give you up"}}</tool_call>',
                   "<speak><cue>smug</cue>That's Never Gonna Give You Up, by Rick Astley.</speak>"])
    host = FakeHost()
    turn = asyncio.run(Conversation(llm).respond("Which song has the lyrics never gonna give you up, never gonna let you down?", host))
    assert "not run: he asked you to NAME it" in llm.seen[1][-1]["content"]
    # a song he never taught her is never named (his call, 2026-10-19: no guesses, right or wrong)
    said = " ".join(e[1] for e in host.events if e[0] == "say")
    assert "Rick Astley" not in said and "know" in said
    assert not any(e[0] == "tool" and e[1] == "youtube_play" and e[2] == "done" for e in host.events)
    # asked to play it: that is his to ask
    assert Conversation.naming("Which song has the lyrics never gonna give you up?")
    assert not Conversation.naming("Play the song that goes never gonna give you up")
    assert not Conversation.naming("Find me the video of the song with the lyrics never gonna give you up")



def test_the_page_in_his_browser_never_answers_the_world():
    """Live 2026-10-19: read_page_text read his own Google search for one song (right),
    then gave the same stale page for a different song (wrong). Refused whatever he said."""
    for said in ("Hey, find for me the name of the song with the lyrics you can ask the flowers I sing for hours",
                 "Search for the song with the lyrics I'll picture us with the waves"):
        llm = FakeLLM(['<tool_call>{"name": "read_page_text", "arguments": {}}</tool_call>',
                       "<speak><cue>thinking</cue>I'm not sure, sir. Maybe Pretty Little Baby? Just a guess.</speak>"])
        asyncio.run(Conversation(llm).respond(said, FakeHost()))
        assert "not run: he asked you to NAME it" in llm.seen[1][-1]["content"], said
    # his own page, asked about: still his to ask
    assert not recall.world_knowledge("What does this page say?")


def test_bare_lyrics_after_a_song_question_skip_memory_too(tmp_path):
    """Live 2026-10-19 12:56: the lyrics alone, right after "do you know the name of the
    song with the lyrics?", went to memory and came back '"Blue" by Yung Kai! You remembered!'"""
    store = recall.Store(tmp_path / "memory.sqlite")
    store.add("turn", 'He said: "Do you know the name of the song with the lyrics?" You said: "Oh, Mister Tri. You did remember."', session="old")
    asked = "Hey do you know the name of the song with the lyrics?"
    sung = "You can ask the flowers I sing for hours Telling all the bluebirds The beautiful and cool birds Pretty little baby I'm so in love with you"
    got = recall.recall(sung, session="now", store=store, before=asked)
    assert got.skipped == "world knowledge" and not got.items
    # not after a song question, or a question of his own, or a few words: memory as usual
    assert not recall.lyrics_after(sung, "what's the weather like?")
    assert not recall.lyrics_after("What did I tell you about my sister last week?", asked)
    assert not recall.lyrics_after("Thanks, Irene!", asked)
    store.close()


def test_lecture_research_is_refused_for_naming_too():
    """Routing evals 2026-10-19: Harry Potter looped on lecture_research."""
    llm = FakeLLM(['<tool_call>{"name": "lecture_research", "arguments": {"question": "boy wizard book"}}</tool_call>',
                   "<speak><cue>smug</cue>That's Harry Potter, sir.</speak>"])
    asyncio.run(Conversation(llm).respond("What's the name of the book about a boy wizard with a lightning scar?", FakeHost()))
    assert "not run: he asked you to NAME it" in llm.seen[1][-1]["content"]


# ---- teaching her, by voice, and what may answer a question about the world ------------

# his words as Whisper heard them: the teaching (built from his 12:35 transcript of the
# chorus), then his other recordings of the same question
TAUGHT = ("That song is Blue by yung kai, the one that goes I'll imagine we fell in love on up under moonlight skies "
          "with you I think I'll picture you with the waves the oceans colors on your face")
ASKED = [
    "Do you know the name of the song with the lyrics? I think a picture of you with the waves The ocean has colors on your face",
    "I mean can you help me to find the song with the lyrics I think I'll picture a seal with the waves the ocean less colors on your face",
    "What is the song has the lyric that I think I'll picture a suit with the waves the ocean has colors on your face",
]
SUNG = "I think I'll picture us you with the waves the oceanless colors on your face"
OTHER = "Hey do you know the name of the song with the lyrics that? You can ask the flowers I sit for hours Telling all the bluebirds Pretty little baby I'm so in love with you"


def test_teaching_is_a_statement_kept_as_his():
    assert recall.teaches(TAUGHT) and not recall.world_knowledge(TAUGHT)
    assert recall.teaches("The song that goes pretty little baby is called Pretty Little Baby, by Connie Francis")
    for said in ("I love this song", "this song is so good", "Is that song by Adele?", ASKED[0]):
        assert not recall.teaches(said), said
    assert recall.quoted(ASKED[0]).startswith("I think a picture") and recall.quoted("Do you know the name of the song with the lyrics?") == ""


@pytest.mark.skipif(not recall.MODEL_DIR.exists(), reason="bge-small-en-v1.5 not installed")
def test_what_he_taught_answers_asked_sung_or_said_and_survives_a_restart(tmp_path):
    # the real embedding model: tolerating Whisper's mangling is the point
    bge = recall.Embedder()
    path = tmp_path / "memory.sqlite"
    store = recall.Store(path, bge)
    store.add("fact", TAUGHT, session="taught")
    # her own invention about the same lyrics, kept the old way: never an answer
    store.add("turn", f'He said: "{ASKED[0]}" You said: "That\'s Golden Brown by The Stranglers."', session="old")
    store.close()
    store = recall.Store(path, bge)  # a restart: the same file, opened fresh
    for said in [*ASKED, SUNG]:
        got = recall.recall(said, session="now", store=store)
        assert got.skipped == "world knowledge" and [i.source for i in got.items] == ["him"], said
        assert "Blue by yung kai" in got.section and "Golden Brown" not in got.section, said
    # a song he never taught her, or a question with no lyrics yet: nothing of his, nothing of hers
    for said in (OTHER, "Do you know the name of the song with the lyrics?"):
        got = recall.recall(said, session="now", store=store)
        # (only that it is none of his: "it is NOT Blue")
        assert got.skipped == "world knowledge" and not got.items and "Blue by yung kai" not in got.section, said
    store.close()


@pytest.mark.skipif(not recall.MODEL_DIR.exists(), reason="bge-small-en-v1.5 not installed")
def test_taught_with_the_lyrics_straight_after_the_name(tmp_path):
    # "that song is Blue by yung kai" and sung on in the same breath - no "the one that
    # goes": the name in front scored 0.70-0.73 against his questions, under the cut-off
    bge = recall.Embedder()
    store = recall.Store(tmp_path / "memory.sqlite", bge)
    store.add("fact", "That song is Blue by yung kai I'll imagine we fell in love I'll nap under moonlight skies with you "
                      "I think I'll picture us you with the waves the oceanless colors on your face", session="taught")
    for said in (SUNG, "Hey Irene. Do you know the name of the song with the lyrics? I think I'll picture us you with the waves the oceanless colors on your face"):
        got = recall.recall(said, session="now", store=store)
        assert [i.source for i in got.items] == ["him"] and "Blue by yung kai" in got.section, said
    assert not recall.recall(OTHER, session="now", store=store).items
    store.close()


def test_his_own_life_keeps_its_own_path(tmp_path):
    store = recall.Store(tmp_path / "memory.sqlite")
    store.add("fact", "Trác is my younger brother, he just started university in Hanoi", session="old")
    got = recall.recall("Where is Trác studying these days?", session="now", store=store)
    assert not got.skipped and got.items and got.items[0].source == "him"
    store.close()


def test_every_item_carries_its_source_old_files_included(tmp_path):
    import sqlite3

    import numpy as np

    path = tmp_path / "memory.sqlite"
    db = sqlite3.connect(str(path))
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, at REAL NOT NULL, about TEXT NOT NULL, text TEXT NOT NULL, session TEXT NOT NULL, vec BLOB NOT NULL)")
    vec = np.zeros(384, np.float32).tobytes()
    for kind in ("fact", "turn", "research", "lecture"):
        db.execute("INSERT INTO items (kind, at, about, text, session, vec) VALUES (?, 0, '', ?, '', ?)", (kind, f"a {kind}", vec))
    db.commit()
    db.close()
    store = recall.Store(path)
    assert len(store) == 4
    assert {i.kind: i.source for i in store.items} == {"fact": "him", "turn": "her", "research": "her", "lecture": "lecture"}
    assert store.add("fact", "That film is Jaws by Spielberg, the one with the shark").source == "him"
    store.close()


def test_a_refusal_is_never_apologised_for():
    """Evals 2026-10-19: about half the replies after a refused tool opened "You're
    absolutely right, I got ahead of myself" - she took the app's rule for his correction."""
    llm = FakeLLM(['<tool_call>{"name": "youtube_play", "arguments": {"query": "boy wizard"}}</tool_call>',
                   "<speak><cue>sheepish</cue>You're absolutely right, Mister Tri. I got ahead of myself. That's Harry Potter, sir.</speak>"])
    host = FakeHost()
    asyncio.run(Conversation(llm).respond("What's the name of the book about a boy wizard with a lightning scar?", host))
    note = llm.seen[1][-1]["content"]
    assert "not from him" in note and "never apologise" in note
    said = " ".join(e[1] for e in host.events if e[0] == "say")
    assert said == "That's Harry Potter, sir.", said
