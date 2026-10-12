import asyncio

from irene.brain import Conversation
from irene.grounding import Grounder, strip_citations
from irene.reply import for_chat
from tools import research as R
from tests.test_brain import FakeHost, FakeLLM, run

KENDO = (
    "Gyaku-do is a strike to the left side of the opponent's do (torso), the reverse of the usual "
    "right do. It is scored less often than migi-do. Men is a strike to the head."
)


def research(tmp_path, monkeypatch, text=KENDO, sources=2):
    monkeypatch.setattr(R, "STORE", tmp_path)
    found = R.Research("20260922-120000", "what is gyaku-do in kendo", "2026-09-22 12:00")
    found.sources = [R.Source(k, f"Kendo {k}", f"https://kendo{k}.org/techniques", f"kendo{k}.org", text[:200], text=text)
                     for k in range(1, sources + 1)]
    found.searched = 8
    R.save(found)
    return found


def test_a_claim_the_sources_dont_support_is_cut_and_a_supported_one_keeps_its_quote(tmp_path, monkeypatch):
    g = Grounder(research(tmp_path, monkeypatch))
    assert g.check("Ooh, good question!") == "Ooh, good question!"
    assert g.check("Gyaku-dō is a quick backward step to evade an attack [1].") is None
    assert g.check("It's a strike to the left side of the opponent's torso [1].") == "It's a strike to the left side of the opponent's torso."
    assert g.check("Players score it less often than the right side [2].") is not None
    assert g.check("It was invented in 1850 by the samurai.") is None
    assert g.check("Want the details on the panel?") is not None
    claims = g.record()
    assert len(claims) == 2 and all("left side" in c["quote"] or "less often" in c["quote"] for c in claims)
    assert g.dropped == ["Gyaku-dō is a quick backward step to evade an attack.", "It was invented in 1850 by the samurai."]
    assert g.notes() == []  # two sources, most claims held


def test_thin_sources_are_said_out_loud(tmp_path, monkeypatch):
    g = Grounder(research(tmp_path, monkeypatch, sources=1))
    g.check("It's a strike to the left side of the opponent's torso.")
    assert "thin" in g.notes()[0]


def test_disagreeing_numbers_are_said_out_loud(tmp_path, monkeypatch):
    found = research(tmp_path, monkeypatch)
    found.sources[0].text = "The Eiffel Tower is 330 metres tall including its antennas, the tallest structure in Paris."
    found.sources[1].text = "The Eiffel Tower is 300 metres tall and was the tallest structure in the world until 1930."
    found.question = "how tall is the eiffel tower"
    g = Grounder(found)
    assert g.check("The Eiffel Tower is 330 metres tall, the tallest structure in Paris [1].")
    assert "agree" in g.notes()[0]


def test_a_research_answer_is_spoken_grounded_and_offers_the_panel(tmp_path, monkeypatch):
    found = research(tmp_path, monkeypatch)

    async def fake_research(question):
        return found

    monkeypatch.setattr(R, "run_research", fake_research)
    llm = FakeLLM([
        '<tool_call>{"name": "research", "arguments": {"question": "gyaku-do kendo"}}</tool_call>',
        "<speak><cue>curious</cue>Ooh, a kendo one! Gyaku-dō is a quick backward step to evade [1]. "
        "It's a strike to the left side of the opponent's torso [1]. It's the reverse of the usual right dō [2].</speak>"
        "\n<display>See https://kendo1.org/techniques</display>",
    ])
    host = FakeHost()
    conv = Conversation(llm)
    turn = run(conv, "What is gyaku-do in kendo?", host)
    said = [e[1] for e in host.events if e[0] == "say"]
    assert not any("backward" in s for s in said)
    assert any("left side" in s for s in said) and "panel" in said[-1]
    assert turn.reply.display == "" and "[1]" not in turn.reply.speak
    assert [c["text"] for c in turn.claims] == ["It's a strike to the left side of the opponent's torso."]

    shown = []

    class PanelHost(FakeHost):
        async def show_panel(self, content):
            shown.append(content)

        def panel_answers(self):
            return []

    turn = run(conv, "Yes please!", PanelHost())
    assert turn.tools_used == ["show_panel"] and shown and shown[0]["title"].startswith("What is gyaku")


def test_the_chat_never_shows_urls_or_markdown_links():
    text = for_chat("**Height:** 330 m [1]\nSee [Wikipedia](https://en.wikipedia.org/wiki/X) or https://britannica.com/x.\n## Facts")
    assert "http" not in text and "**" not in text and "Wikipedia" in text and "##" not in text
    assert strip_citations("It is tall [1, 2].") == "It is tall."


def test_speech_before_a_research_call_is_held_and_dropped():
    from irene.brain import StreamingReply

    s = StreamingReply(hold=True)
    raw = ("<speak>Ooh, let me see! The tower is about 324 metres tall. It was built in 1889.</speak>"
           '<tool_call>{"name": "research", "arguments": {"question": "eiffel"}}</tool_call>')
    lines = [line.text for line in s.feed(raw)] + [line.text for line in s.finish()]
    assert lines == ["Ooh, let me see!"] and s.said == ["Ooh, let me see!"]
    # no call: the held sentences play once the reply is complete
    s = StreamingReply(hold=True)
    first = [line.text for line in s.feed("<speak>Canberra, sir. It was picked as a compromise. ")]
    rest = [line.text for line in s.feed("Neat, right?</speak>")] + [line.text for line in s.finish()]
    assert first == ["Canberra, sir."] and rest == ["It was picked as a compromise.", "Neat, right?"]


def test_a_sentence_keeps_its_supported_clause(tmp_path, monkeypatch):
    found = research(tmp_path, monkeypatch, text="The adult human body has 206 bones. Babies are born with about 300 bones that fuse over time.")
    found.question = "how many bones are in the human body"
    g = Grounder(found)
    assert g.check("Most adults have 206 bones, though some counts reach 213.") == "Most adults have 206 bones."
