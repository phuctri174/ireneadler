"""A research answer is a real spoken summary, every time.

Live, she said "I can only say part of it - it's all in the panel, want me to
show it?" in place of an answer: grounding had cut most of what the model said,
and the grounder's own note sent him to the panel. Now what grounding cuts is made
up from the fetched pages themselves, a panel offer in place of the answer is
never spoken, and the offer only ever comes after the summary."""
import re

from irene.brain import StreamingReply
from irene.grounding import Grounder, _speakable
from tools import research as R

GAMBIT = (
    "The Queen's Gambit is a chess opening that starts with the moves d4, d5 and c4. "
    "White offers a pawn to lure Black's d-pawn away from the centre. "
    "It is not a true gambit, because Black cannot keep the extra pawn without making concessions. "
    "The two main answers are the Queen's Gambit Accepted and the Queen's Gambit Declined. "
    "The Slav Defence, with c6, is one of the most solid ways to decline it. "
    "The opening is one of the oldest known and is still played at the highest level of chess. "
    "See also: [edit] References https://example.org/chess"
)


def research(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "STORE", tmp_path)
    found = R.Research("20260928-120000", "the Queen's Gambit opening", "2026-09-28 12:00")
    found.sources = [R.Source(k, f"Chess {k}", f"https://chess{k}.org/qg", f"chess{k}.org", GAMBIT[:200], text=GAMBIT, passages=[GAMBIT]) for k in (1, 2)]
    found.searched = 8
    R.save(found)
    return found


def test_a_thin_answer_is_made_a_real_summary_from_the_pages_themselves(tmp_path, monkeypatch):
    g = Grounder(research(tmp_path, monkeypatch))
    said = [g.check("The Queen's Gambit starts with d4, d5 and c4 [1].")]
    assert g.check("It was invented by Napoleon in 1805.") is None  # cut
    fill = g.fill(said, 5)
    assert 3 <= len(fill) <= 5
    joined = " ".join(fill)
    assert "d4, d5 and c4" not in joined, "never what she already said"
    assert not re.search(r"http|\[|See also", joined)
    assert len(g.claims) == 1 + len(fill), "each filled sentence is a claim with its own quote"


def test_a_page_sentence_is_only_said_when_it_reads_as_speech():
    assert _speakable("White offers a pawn [3] to lure Black's pawn (the d-pawn) away from the centre.") == "White offers a pawn to lure Black's pawn away from the centre."
    assert _speakable("See also: Queen's Gambit Declined.") is None
    assert _speakable("Retrieved 12 March 2021 from the archive of chess games online.") is None
    assert _speakable("Too short.") is None


def test_the_panel_in_place_of_an_answer_is_never_said(tmp_path, monkeypatch):
    g = Grounder(research(tmp_path, monkeypatch))
    s = StreamingReply(grounder=g)
    lines = s.feed(
        "<speak>I can only say part of it, sir. It's all in the panel - want me to show it? "
        "The Queen's Gambit is a chess opening that starts with d4, d5 and c4 [1].</speak>"
    ) + s.finish()
    said = " ".join(line.text for line in lines)
    assert "panel" not in said and "part of it" not in said
    assert "d4, d5 and c4" in said


def test_the_grounder_never_sends_him_to_the_panel_for_the_rest(tmp_path, monkeypatch):
    g = Grounder(research(tmp_path, monkeypatch))
    for sentence in ["Napoleon invented it in 1805.", "It was banned in 1920.", "Kasparov hated it in 1999."]:
        g.check(sentence)
    assert not any("panel" in n for n in g.notes())


def test_a_research_turn_speaks_four_to_six_sentences_then_offers_the_panel(tmp_path, monkeypatch):
    """Through Conversation.respond: the model's answer is mostly cut, and she still
    speaks a summary, the offer last."""
    import asyncio

    from irene.brain import Conversation
    from tests.test_brain import FakeHost, FakeLLM

    found = research(tmp_path, monkeypatch)

    monkeypatch.setattr(R, "last", lambda: found)
    llm = FakeLLM([
        '<tool_call>{"name": "research", "arguments": {"question": "the Queen\'s Gambit opening"}}</tool_call>',
        "<speak><cue>thinking</cue>The Queen's Gambit starts with d4, d5 and c4 [1]. "
        "It was invented by Napoleon in 1805. Garry Kasparov banned it in 1999. "
        "I can only say part of it - it's all on the panel.</speak>",
    ])
    conv = Conversation(llm)
    host = FakeHost()
    turn = asyncio.run(_respond(conv, host, found, monkeypatch))
    said = [e[1] for e in host.events if e[0] == "say"]
    summary, offer = said[:-1], said[-1]
    assert "panel" in offer.lower()
    sentences = [x for x in re.split(r"(?<=[.!?])\s+", " ".join(summary)) if len(x.split()) >= 4]
    assert 4 <= len(sentences) <= 6, sentences
    assert not any("panel" in x.lower() or "part of it" in x for x in summary)


async def _respond(conv, host, found, monkeypatch):
    from irene import brain

    from tools.registry import ToolResult

    async def run_tool(self, name, args, host):
        return ToolResult(R.for_model(found), tainted=True)

    monkeypatch.setattr(brain.Conversation, "_run_tool", run_tool)
    return await conv.respond("Research the Queen's Gambit opening.", host)


def test_i_dont_know_is_never_her_answer_she_researches_instead(tmp_path, monkeypatch):
    """Round 7: she said "I don't know" and waited to be told to look it up. The
    admission is dropped unsaid and the research runs on his own question."""
    import asyncio

    from irene import brain
    from irene.brain import Conversation
    from tests.test_brain import FakeHost, FakeLLM
    from tools.registry import ToolResult

    found = research(tmp_path, monkeypatch)
    monkeypatch.setattr(R, "last", lambda: found)
    asked = []

    async def run_tool(self, name, args, host):
        asked.append((name, args))
        return ToolResult(R.for_model(found), tainted=True)

    monkeypatch.setattr(brain.Conversation, "_run_tool", run_tool)
    llm = FakeLLM([
        "<speak><cue>sheepish</cue>Hmm, I'm not sure about the latest on that, sir. You might want to check online.</speak>",
        "<speak><cue>thinking</cue>The Queen's Gambit starts with d4, d5 and c4 [1]. White offers a pawn to lure Black's d-pawn away from the centre [1].</speak>",
    ])
    host = FakeHost()
    turn = asyncio.run(Conversation(llm).respond("Tell me about that old pawn sacrifice idea.", host))
    said = " ".join(e[1] for e in host.events if e[0] == "say")
    assert asked and asked[0][0] == "research" and "pawn sacrifice" in asked[0][1]["question"]
    assert "not sure" not in said and "check online" not in said, "the admission was never said"
    assert "d4, d5 and c4" in said and turn.tools_used == ["research"]
