"""Further reading for a lecture note: only on his word, only what the pages she read
support - each sentence with its link - and walled off from what the lecturer said."""
import asyncio

from irene import fast, lecture_note, lecture_research
from irene.brain import Conversation
from tests.test_brain import FakeHost, FakeLLM, run
from tests.test_lecture_note import summary, transcript
from tools import research as R

PAGE = ("Empirical analysis measures an algorithm by running it on real inputs and timing it. "
        "Its results depend on the machine and the inputs chosen. Asymptotic analysis instead counts operations "
        "as the input grows, independent of the machine.")


def note():
    return lecture_note.build(summary(), transcript(), {"id": "2026-10-14_093233", "seconds": 1200, "started": 1760000000})


async def fake_research(question):
    found = R.Research("20261014-100000", question, "2026-10-14 10:00")
    found.sources = [R.Source(1, "Analysis of algorithms", "https://example.org/analysis", "example.org", PAGE[:200], text=PAGE,
                              passages=[PAGE], screenshot="data:image/jpeg;base64,AAAA"),
                     R.Source(2, "Unrelated", "https://other.example/x", "other.example", "Cats.", text="Cats sleep a lot.",
                              passages=["Cats sleep a lot."], screenshot="data:image/jpeg;base64,BBBB")]
    return found


async def fake_chat(messages):
    return ("Here are 4 sentences about empirical analysis, based solely on the provided extracts:\n"
            "Empirical analysis runs an algorithm on real inputs and times it [1]. "
            "Its results depend on the machine and the inputs [1]. "
            "It was invented by Donald Knuth in 1962 at Stanford [1]. "
            "Great question!")


def test_only_sentences_a_page_supports_are_kept_each_with_its_link():
    found = asyncio.run(lecture_research.research_topic(note(), 1, "1", fake_chat, fake_research))
    texts = [i["text"] for i in found["items"]]
    assert len(texts) == 2 and all("Knuth" not in t and "Great" not in t and "extracts" not in t for t in texts)
    assert all(i["url"] == "https://example.org/analysis" for i in found["items"])
    # a screenshot only of a page it actually used
    assert [s["url"] for s in found["shots"]] == ["https://example.org/analysis"]


def test_which_topics():
    n = note()
    assert lecture_research.which(n, "2") == [2] and lecture_research.which(n, "second") == [2]
    assert lecture_research.which(n, "all") == list(range(1, min(len(n.sections), 3) + 1))
    assert lecture_research.which(n, "nonsense words") == []


def test_research_is_its_own_labelled_section_after_the_lecture():
    n = note()
    n.research = [asyncio.run(lecture_research.research_topic(n, 1, "1", fake_chat, fake_research))]
    blocks = lecture_note.content(n)["blocks"]
    box = next(b for b in blocks if b.get("tone") == "research")
    assert box["title"] == lecture_note.RESEARCH_LABEL and "NOT from the lecture" in box["title"]
    # nothing researched sits outside its box
    outside = [b.get("text", "") for b in blocks if b is not box]
    assert not any("real inputs" in t for t in outside)
    links = [b for b in box["blocks"] if b["kind"] == "link"]
    assert links and all(b["url"].startswith("https://") for b in links)


def test_he_asks_or_takes_her_offer_never_automatic():
    assert "lecture_research" in fast._lecture("Look up more on the second topic.", [])
    assert "lecture_summary" in fast._lecture("Tell me more about the second topic.", ["lecture_summary"])
    # the summary offers; nothing is researched until he says yes
    from irene import lecture_summary

    assert lecture_summary.speech(summary())[-1] == lecture_summary.OFFER
    llm = FakeLLM(["<speak>Sure.</speak>"])
    conv = Conversation(llm)
    conv._lecture_offer = True
    calls = []

    async def tool(name, args, host):
        calls.append((name, args))
        return "added to the lecture note, in its own section marked as researched online (not from the lecture):\n- X: y (from example.org)"

    conv._run_tool = tool
    run(conv, "Yes please.", FakeHost())
    assert calls == [("lecture_research", {"topic": "all"})]


def test_her_own_long_speech_is_said_whole_offer_included(monkeypatch):
    # the walkthrough of a long lecture runs past the 110-word cap for the model's
    # replies; live, the cap cut the topics, the homework notes and the offer
    from irene import lecture_summary
    from tools import lecture as lecture_tool

    class Lectures:
        spoken = [f"Sentence number {k} of a long lecture summary with several words." for k in range(20)] + [lecture_summary.OFFER]

    monkeypatch.setattr(lecture_tool, "LECTURES", Lectures())
    conv = Conversation(FakeLLM([]))

    async def tool(name, args, host):
        return "lecture summarised and already spoken (all on the panel). Sections:\n1. [00:00] A"

    conv._run_tool = tool
    turn = run(conv, "Summarise the lecture.", FakeHost())
    assert turn.reply.speak.endswith(lecture_summary.OFFER) and "Sentence number 19" in turn.reply.speak
    assert conv._lecture_offer
