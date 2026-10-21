"""A lecture becomes a document, like a research answer: structured, saved with the
lecture, printed as a PDF in the panel's look, listed with her research and
brought back by a click. Definitions and homework keep the lecturer's own words."""
import asyncio
import json

from irene import lecture, lecture_note, lecture_summary
from tests.test_lecture import FakeChat, transcript
from tools import panel as panel_tool
from tools import pdf


class NoteChat(FakeChat):
    """The summary's model calls, with a title, takeaways and two definitions - one
    in the lecturer's words, one made up."""

    async def __call__(self, messages):
        p = messages[0]["content"]
        if p.startswith("Below are the topics"):
            out = json.loads(await super().__call__(messages))
            out["title"] = "Hash tables"
            out["key_points"] = ["Chaining resolves collisions in hash tables.", "The moon is made of cheese."]
            return json.dumps(out)
        out = await super().__call__(messages)
        body = json.loads(out.split("```json\n", 1)[1].rsplit("\n```", 1)[0])
        body["definitions"] = [
            {"term": "chaining", "meaning": "Keeping colliding keys in a list.", "quote": "Sentence 3 about hashing and tables with chaining and probing"},
            {"term": "cuckoo hashing", "meaning": "Two tables.", "quote": "cuckoo hashing uses two tables and kicks keys out"},
        ]
        return json.dumps(body)


def summary():
    return asyncio.run(lecture_summary.summarize(transcript(), {"id": "2026-10-14_093233", "seconds": 1200, "started": 1760000000}, NoteChat(), window_words=200))


def test_definitions_and_takeaways_keep_only_what_the_lecture_said():
    s = summary()
    assert s.title == "Hash tables"
    # the made-up definition (its quote is nowhere in the transcript) is gone
    assert [d["term"] for d in s.definitions] == ["chaining"] and "chaining" in s.definitions[0]["quote"].lower()
    # a takeaway naming nothing any section says is the model's own
    assert s.key_points == ["Chaining resolves collisions in hash tables."]


def test_the_note_is_a_structured_document():
    s = summary()
    note = lecture_note.build(s, transcript(), {"id": "2026-10-14_093233", "seconds": 1200, "started": 1760000000})
    c = lecture_note.content(note)
    assert c["title"] == "Hash tables" and "· 20:00 ·" in c["subtitle"] and "words" in c["subtitle"]
    kinds = [(b["kind"], b.get("tone") or b.get("text", "")[:20]) for b in c["blocks"]]
    assert ("heading", "Overview") in kinds and ("box", "points") in kinds and ("box", "homework") in kinds and ("box", "definitions") in kinds
    homework = next(b for b in c["blocks"] if b.get("tone") == "homework")
    # the lecturer's exact words, with when he said them
    assert homework["blocks"][0]["kind"] == "quote" and "problem set two is due next thursday" in homework["blocks"][0]["text"].lower()
    assert "13:20" in homework["blocks"][0]["attribution"]
    # topics with their times, then the transcript
    headings = [b["text"] for b in c["blocks"] if b["kind"] == "heading"]
    assert any(h.startswith("1 · Hash tables · 00:00–") for h in headings) and headings[-1] == "Full transcript"
    assert not any(b.get("tone") == "research" for b in c["blocks"])  # nothing researched unless asked


def test_saved_with_the_lecture_listed_and_brought_back(tmp_path, monkeypatch):
    monkeypatch.setattr(lecture, "STORE", tmp_path)
    monkeypatch.setattr(lecture_note, "STORE", tmp_path)
    note = lecture_note.build(summary(), transcript(), {"id": "2026-10-14_093233", "seconds": 1200, "started": 1760000000})
    lecture_note.save(note)
    back = lecture_note.load("2026-10-14_093233")
    assert back is not None and back.title == "Hash tables" and back.alerts == note.alerts
    assert [n.id for n in lecture_note.saved()] == ["2026-10-14_093233"]
    item = lecture_note.rail_item(back)
    assert item["id"] == "lecture:2026-10-14_093233" and item["kind"] == "lecture" and item["length"] == "20:00"


def test_only_a_lecture_id_is_a_path():
    for bad in ("../../etc", "2026-10-14_093233/../x", ""):
        try:
            lecture_note.path_of(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_the_dashboard_lists_notes_with_research_and_recalls_only_listed_ones(tmp_path, monkeypatch):
    from irene import dashboard
    from tools import research

    monkeypatch.setattr(lecture, "STORE", tmp_path / "lectures")
    monkeypatch.setattr(lecture_note, "STORE", tmp_path / "lectures")
    monkeypatch.setattr(research, "STORE", tmp_path / "research")
    note = lecture_note.build(summary(), transcript(), {"id": "2026-10-14_093233", "seconds": 1200, "started": 1760000000})
    lecture_note.save(note)

    shown = []

    class Core:
        async def show_panel(self, content):
            shown.append(content)

    d = dashboard.Dashboard(Core())
    d._research_list()
    assert [i["id"] for i in d.state["research"]] == ["lecture:2026-10-14_093233"]
    asyncio.run(d.recall({"id": "lecture:2026-10-14_093233"}))
    asyncio.run(d.recall({"id": "lecture:2026-10-12_000000"}))  # not on the panel: refused
    assert len(shown) == 1 and shown[0]["title"] == "Hash tables"


def test_paper_keeps_the_boxes_and_their_tones_and_links_in_boxes_are_allowed():
    note = lecture_note.build(summary(), transcript(), {"id": "2026-10-14_093233", "seconds": 1200, "started": 1760000000})
    note.research = [{"section": 1, "concept": "Chaining", "items": [{"text": "Separate chaining stores a list per bucket.", "url": "https://example.org/chaining",
                                                                     "title": "Chaining", "site": "example.org"}], "shots": []}]
    c = lecture_note.content(note)
    html = pdf.render_html(c, "2026-10-14 10:00")
    assert "Irene · lecture note" in html and "tone-homework" in html and "tone-definitions" in html and "tone-research" in html
    assert lecture_note.RESEARCH_LABEL in html
    assert "https://example.org/chaining" in panel_tool.links_in(c)
