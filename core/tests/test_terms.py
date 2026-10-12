"""The research board: while she speaks a grounded answer, its key terms appear on
the board one at a time - taken from the fetched extracts, never invented."""
import asyncio

from irene.brain import StreamingReply
from irene.grounding import Grounder
from irene.terms import key_terms, short_topic
from tools import research as R

PAGE = (
    "The All Japan Kendo Federation awards grades from 1st kyu up to 8th dan. Shodan is the first dan, "
    "usually after at least 1 year of practice. Promotion to 8 dan has a pass rate below 1 percent. "
    "Gyaku-dō is a strike to the left side of the torso."
)


def found(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "STORE", tmp_path)
    r = R.Research("20260928-050000", "how do kendo dan grades work", "2026-09-28 05:00")
    r.sources = [R.Source(k, f"Kendo {k}", f"https://kendo{k}.org/grades", f"kendo{k}.org", PAGE[:200], text=PAGE) for k in (1, 2)]
    return r


def test_terms_come_from_the_sentence_and_the_fetched_text_only():
    taken = set()
    assert key_terms("The All Japan Kendo Federation sets the grades, sir.", PAGE, "kendo dan grades", taken) == ["All Japan Kendo Federation"]
    assert key_terms("Only about 1 percent pass the 8 dan exam!", PAGE, "kendo dan grades", taken) == ["1 percent", "8 dan"]
    # a name the pages never mention is never put on the board
    assert key_terms("The Moon Kendo League invented it.", PAGE, "kendo dan grades", taken) == []
    # each term once; never just the question's own words
    assert key_terms("The All Japan Kendo Federation again.", PAGE, "kendo dan grades", taken) == []
    assert key_terms("Kendo grades.", PAGE, "kendo dan grades", set()) == []


def test_the_title_is_the_topic_not_the_question():
    assert short_topic("What is gyaku-do in kendo?") == "gyaku-do in kendo"
    assert short_topic("research how kendo dan grades work") == "kendo dan grades work"


def test_a_grounded_answer_carries_its_terms_and_an_unsupported_one_none(tmp_path, monkeypatch):
    stream = StreamingReply(grounder=Grounder(found(tmp_path, monkeypatch)))
    lines = stream.feed(
        "<speak>Ooh, a good one! The All Japan Kendo Federation awards the grades [1]. "
        "Shodan is the first dan, after about a year of practice [1]. "
        "Grades are given by the Kendo Moon Council on Tuesdays [2]. "
        "Fewer than 1 percent pass the 8 dan exam [2].</speak>"
    ) + stream.finish()
    by_text = {line.text: line.terms for line in lines}
    assert by_text["Ooh, a good one!"] == ()  # chatter: nothing to show
    assert "All Japan Kendo Federation" in by_text["The All Japan Kendo Federation awards the grades."]
    assert "Shodan" in by_text["Shodan is the first dan, after about a year of practice."]
    assert not any("Moon" in t for terms in by_text.values() for t in terms), "unsupported: cut, and nothing on the board"
    assert all(line.topic == "kendo dan grades work" for line in lines if line.terms)


class _Bridge:
    def __init__(self):
        self.sent = []
        self.connected = True
        self.current_state = "thinking"

    async def send(self, m):
        self.sent.append(m)

    async def transcript(self, who, text):
        pass

    async def state(self, v):
        self.sent.append({"type": "state", "value": v})

    async def emotion(self, v):
        pass

    def send_threadsafe(self, m):
        self.sent.append(m)


def test_the_terms_go_to_the_board_as_she_says_them_and_it_stays_up(tmp_path, monkeypatch):
    from irene.app import Core, SpeechSink
    from irene.brain import Line
    from irene.reply import Reply

    core = Core()
    core.bridge = _Bridge()
    core.muted = True  # no speaker: sent as the line is taken

    async def main():
        sink = SpeechSink(core, 0.0)
        sink.line(Line("The All Japan Kendo Federation awards the grades.", None, ("All Japan Kendo Federation",), "kendo dan grades"))
        sink.line(Line("Shodan is the first dan.", None, ("Shodan",), "kendo dan grades"))
        await sink.finish(Reply("...", ""))

    asyncio.run(main())
    terms = [m for m in core.bridge.sent if m["type"] == "board_term"]
    assert [m["terms"] for m in terms] == [["All Japan Kendo Federation"], ["Shodan"]]
    assert terms[0]["title"] == "kendo dan grades"
    assert {"type": "draw", "value": None} not in core.bridge.sent, "the terms board stays up while she talks"


def test_the_model_is_never_offered_the_terms_board_and_cannot_draw_it():
    from irene import board

    assert "terms" not in board.TEMPLATES and "terms" not in board.board_section()
    assert board.check({"template": "terms", "terms": [{"text": "x", "at": 0}]}) is not None
