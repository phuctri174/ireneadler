"""A work he taught her, answered: the card, and nothing said about it he didn't say."""
import asyncio

import pytest

from irene import illustrate, recall, taught
from irene.brain import Conversation
from irene.drawing import FACE, H, W
from tests.test_brain import FakeHost, FakeLLM, FakeSink

# his own words as Whisper heard them (2026-10-19), sung straight on after the name
TAUGHT = ("That song is Blue by yung kai I'll imagine we fell in love I'll nap under moonlight skies with you "
          "I think I'll picture us you with the waves the oceanless colors on your face")
ASKED = "Hey Irene. Do you know the name of the song with the lyrics? I think I'll picture us you with the waves the oceanless colors on your face"


def test_the_work_his_statement_names():
    n = taught.named(TAUGHT)
    assert (n.kind, n.title, n.after[:2]) == ("song", "Blue", ["yung", "kai"])
    framed = taught.named("The song that goes pretty little baby is called Pretty Little Baby, by Connie Francis")
    assert framed.title == "Pretty Little Baby" and taught.artist(framed, "It's Pretty Little Baby by Connie Francis.") == "Connie Francis"
    assert taught.named("Blue is a song by yung kai").title == "Blue"
    assert taught.named("I love this song") is None
    # where his name ends is read from what she says: never his lyrics
    assert taught.artist(n, "It's “Blue” by yung kai, Mister Tri.") == "yung kai"
    assert taught.artist(n, "It's Blue, sir.") == "" and taught.says_title(n, "That one's Blue.")


def test_nothing_about_it_he_did_not_say():
    for invented in (
        "It was a big hit in 1958, and it's still catchy.",
        "That's “Pretty Baby” by Frankie Avalon.",
        "It's from his debut album, sir.",
        "A lovely indie pop song.",
        "He sings it so softly.",
        "It came out a couple of years ago.",
        "It went viral on TikTok.",
    ):
        assert taught.unknown(invented, TAUGHT), invented
    for feeling in (
        "It's “Blue” by yung kai, Mister Tri.",
        "It's Blue by Yung Kai.",
        "It feels like drifting on a quiet sea under the moonlight.",
        "That line about oceanless colors really hits.",
        "You keep coming back to it - every single time I hear those waves.",
        "So tender, sir.",
    ):
        assert taught.unknown(feeling, TAUGHT) is None, feeling
    # what he did teach may be said
    assert taught.unknown("It came out in 2024.", TAUGHT + ". It came out in 2024") is None


def _inside(shapes):
    for s in shapes:
        for x, y in [(s.get("x"), s.get("y")), (s.get("x1"), s.get("y1")), (s.get("x2"), s.get("y2"))]:
            if x is not None:
                assert 0 <= x < W and 0 <= y < H, s
                if s["type"] == "label":
                    assert not (x >= FACE[0] and y < FACE[1]), s


def test_the_card_comes_up_as_she_names_it():
    card = taught.CardBoard(taught.named(TAUGHT), TAUGHT)
    assert card.snapshot() is None and card.step("Ooh, I know this one.") is None
    message = card.step("It's “Blue” by yung kai, Mister Tri.")
    shapes = message["spec"]["shapes"]
    labels = {s["text"]: s for s in shapes if s["type"] == "label"}
    assert labels["BLUE"].get("size") == 2 and "YUNG KAI" in labels and "SONG" in labels
    # his words picture the sea, the night sky and love: abstract figures, never a cover
    assert taught.moods(TAUGHT) == ["water", "night", "love"]
    assert any(s["type"] == "sprite" and s["name"] == "heart" for s in shapes)
    _inside(shapes)
    assert card.step("It's lovely.") is None and card.finish() is None


def test_never_named_it_still_ends_on_the_card():
    card = taught.CardBoard(taught.named(TAUGHT), TAUGHT)
    card.step("Oh, that one.")
    labels = {s["text"] for s in card.finish()["spec"]["shapes"] if s["type"] == "label"}
    assert "BLUE" in labels and not any("IMAGINE" in t for t in labels)


class BoardSink(FakeSink):
    """A sink with the real board feed: every sentence heard as it is said."""

    def __init__(self, host):
        super().__init__(host)
        self.feed = illustrate.BoardFeed(lambda m: host.events.append(("board", m)))

    def illustrate(self, plan):
        self.feed.start(plan)

    def adopt(self, board):
        self.feed.adopt(board)

    def line(self, line):
        super().line(line)
        self.feed.line()
        self.feed.heard(line.text)

    def draw(self, found):
        self.host.events.append(("draw", found.spec))


class BoardHost(FakeHost):
    def reply_sink(self):
        return BoardSink(self)


@pytest.mark.skipif(not recall.MODEL_DIR.exists(), reason="bge-small-en-v1.5 not installed")
def test_her_answer_is_his_and_comes_with_its_card(tmp_path, monkeypatch):
    store = recall.Store(tmp_path / "memory.sqlite", recall.Embedder())
    monkeypatch.setattr(recall, "HIS", store)
    monkeypatch.setattr(recall, "DEV", store)
    store.add("fact", TAUGHT, session="taught")
    llm = FakeLLM([
        "<speak><cue>proud</cue>It's “Blue” by yung kai, Mister Tri. It was a big hit in 1958. "
        "It feels like moonlight on the water - soft and a little dreamy.</speak>"
        '<draw>{"title": "Lyrics", "layout": "row", "items": ["Suit", "Waves", "Scholars"]}</draw>'
    ])
    host = BoardHost()
    asyncio.run(Conversation(llm).respond(ASKED, host))
    said = " ".join(e[1] for e in host.events if e[0] == "say")
    assert said == "It's “Blue” by yung kai, Mister Tri. It feels like moonlight on the water - soft and a little dreamy."
    # the section asked for the fuller answer, held to what he said
    context = " ".join(m["content"] for m in llm.seen[0] if isinstance(m.get("content"), str))
    assert "three short spoken sentences" in context and "That is ALL you know about it" in context
    boards = [e[1] for e in host.events if e[0] == "board"]
    assert len(boards) == 1 and "spec" in boards[0]
    assert not any(e[0] == "draw" for e in host.events)  # her own drawing never replaces the card
    labels = {s["text"] for s in boards[0]["spec"]["shapes"] if s["type"] == "label"}
    assert {"BLUE", "YUNG KAI"} <= labels and "SCHOLARS" not in labels
    # the history holds what she said: the invented line is not copied next time
    store.close()


OTHER = "Hey do you know the name of the song with the lyrics? You can ask the flowers I sing for hours Telling all the bluebirds Pretty little baby I'm so in love with you"


def test_his_title_named_as_an_answer_not_as_a_word():
    n = taught.named(TAUGHT)
    assert taught.names(n, "“Blue” by yung kai. Again.") and taught.names(n, "It's Blue by yung kai.")
    assert not taught.names(n, "Something soft and blue, like the sea.")


@pytest.mark.skipif(not recall.MODEL_DIR.exists(), reason="bge-small-en-v1.5 not installed")
def test_an_untaught_song_is_never_answered_with_his(tmp_path, monkeypatch):
    # live 2026-10-19: nothing of his matched, and she said "Blue by yung kai. Again. You're obsessed."
    store = recall.Store(tmp_path / "memory.sqlite", recall.Embedder())
    monkeypatch.setattr(recall, "HIS", store)
    monkeypatch.setattr(recall, "DEV", store)
    store.add("fact", TAUGHT, session="taught")
    got = recall.recall(OTHER, session="now", store=store)
    assert not got.items and "it is NOT “Blue”" in got.section
    llm = FakeLLM(["<speak><cue>proud</cue>“Blue” by yung kai. Again. You're obsessed.</speak>"])
    host = BoardHost()
    asyncio.run(Conversation(llm).respond(OTHER, host))
    said = " ".join(e[1] for e in host.events if e[0] == "say")
    assert "Blue" not in said and "don't know" in said
    assert "it is NOT “Blue”" in llm.seen[0][-1]["content"] or any("it is NOT “Blue”" in str(m.get("content")) for m in llm.seen[0])
    store.close()


UNTAUGHT = ("Hey, find for me the the name of the song with the lyrics You can ask the flowers I sit for hours Telling on the "
            "bluebirds The beautiful and cool birds Pretty little baby I'm so in love with you")


def test_naming_an_untaught_song_is_a_guess():
    for guessed in (
        "It's “Pretty Little Baby” by Durand Jones & The Indications.",
        "That's Pretty Little Baby, a Connie Francis classic.",
        "Sounds like Frankie Avalon to me.",
    ):
        assert taught.unknown(guessed, UNTAUGHT) or taught.guess(guessed, UNTAUGHT), guessed
    for honest in ("I don't know that one, sir.", "Teach me?", "It sounds like a sweet old love song.", "Bluebirds and flowers - lovely, Mister Tri."):
        assert not taught.unknown(honest, UNTAUGHT) and not taught.guess(honest, UNTAUGHT), honest


@pytest.mark.skipif(not recall.MODEL_DIR.exists(), reason="bge-small-en-v1.5 not installed")
def test_an_untaught_song_from_its_lyrics_is_not_guessed(tmp_path, monkeypatch):
    # live 2026-10-19: "It's “Pretty Little Baby” by Durand Jones & The Indications."
    store = recall.Store(tmp_path / "memory.sqlite", recall.Embedder())
    monkeypatch.setattr(recall, "HIS", store)
    monkeypatch.setattr(recall, "DEV", store)
    store.add("fact", TAUGHT, session="taught")
    got = recall.recall(UNTAUGHT, session="now", store=store)
    assert got.lyrics and not got.items and "you don't know it" in got.section
    # a question with no lyrics, or about the world in general, is not this
    assert not recall.recall("Who invented the telephone?", session="now", store=store).lyrics
    for reply, kept in (
        ("<speak><cue>proud</cue>Oh! It's “Pretty Little Baby” by Durand Jones & The Indications. Such a sweet one.</speak>", None),
        ("<speak><cue>curious</cue>Hmm, I don't know that one, sir. Teach me?</speak>", "Hmm, I don't know that one, sir. Teach me?"),
    ):
        host = BoardHost()
        asyncio.run(Conversation(FakeLLM([reply])).respond(UNTAUGHT, host))
        said = " ".join(e[1] for e in host.events if e[0] == "say")
        if kept:
            assert said == kept
        else:
            assert "Durand" not in said and "sweet one" not in said and "don't know" in said
    store.close()


@pytest.mark.skipif(not recall.MODEL_DIR.exists(), reason="bge-small-en-v1.5 not installed")
def test_one_line_of_what_he_taught_finds_it(tmp_path):
    # live 2026-10-19 16:04: Whisper heard "a suit" this time - whole to whole 0.75, missed
    store = recall.Store(tmp_path / "memory.sqlite", recall.Embedder())
    store.add("fact", "That song is Blue by yung kai, the one that goes I'll imagine we fell in love on up under moonlight "
                      "skies with you I think I'll picture you with the waves the oceans colors on your face", session="taught")
    said = "I mean do you know the name of the song with the lyrics I think I'll picture a suit with the waves the oceanless colors on your face"
    assert [i.source for i in recall.recall(said, session="now", store=store).items] == ["him"]
    store.close()


def test_a_contraction_is_no_name():
    # live 2026-10-19: "I’ve" (curly) was read as a name, and an honest reply went whole
    for honest in ("I don't think I’ve heard you play it before.", "You’ll have to teach me, Mister Tri’s favourite?", "I'd love to learn it."):
        assert taught.guess(honest, UNTAUGHT) is None, honest


@pytest.mark.skipif(not recall.MODEL_DIR.exists(), reason="bge-small-en-v1.5 not installed")
def test_a_follow_up_about_it_is_held_to_his_words_too(tmp_path, monkeypatch):
    # live 2026-10-19: "what else do you know about it?" -> "Well, it was released in
    # 2023, a bit of a sleeper hit. It's been used in a few TikTok videos" - invented
    store = recall.Store(tmp_path / "memory.sqlite", recall.Embedder())
    monkeypatch.setattr(recall, "HIS", store)
    monkeypatch.setattr(recall, "DEV", store)
    store.add("fact", TAUGHT, session="taught")
    # an old turn about it in his memory, as the live store has: it is recalled for the
    # follow-up, and must not switch the rule off (live, it did)
    store.add("turn", 'He said: "what do you know about Blue by yung kai?" You said: "Blue by yung kai - so dreamy."', session="old")
    llm = FakeLLM([
        "<speak><cue>proud</cue>It's “Blue” by yung kai, Mister Tri. Moonlight and waves.</speak>",
        "<speak><cue>happy</cue>Well, it was released in 2023, a bit of a sleeper hit. It's been used in a few TikTok videos.</speak>",
        "<speak><cue>happy</cue>Sure, here's one.</speak>",
    ])
    conv = Conversation(llm)
    asyncio.run(conv.respond(ASKED, BoardHost()))
    host = BoardHost()
    asyncio.run(conv.respond("Haha, what else do you know about it?", host))
    said = " ".join(e[1] for e in host.events if e[0] == "say")
    assert "2023" not in said and "TikTok" not in said and "all you've" in said.lower() or "everything you've told me" in said
    assert "All you know about it is what he told you" in llm.seen[1][-1]["content"] or any("All you know about it" in str(m.get("content")) for m in llm.seen[1])
    # something else entirely: the song is put down
    asyncio.run(conv.respond("tell me a joke", BoardHost()))
    assert conv.about is None
    store.close()


def test_where_it_was_used_is_a_fact_too():
    # live 2026-10-19, after the year was dropped: "I've also seen it paired with a few anime edits"
    for claim in ("I've also seen it paired with a few anime edits.", "It's been used in a few TikTok videos.", "It was trending last summer."):
        assert taught.unknown(claim, TAUGHT), claim
