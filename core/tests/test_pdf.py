import asyncio

import pytest

from irene.brain import Conversation
from irene.fast import direct_call
from tools import REGISTRY
from tools import pdf as P
from tools.policy import Policy, set_policy
from tools.registry import ToolError
from tests.test_brain import FakeHost, FakeLLM, run

CONTENT = {
    "title": "How tall is the Eiffel Tower",
    "subtitle": "5 sources",
    "blocks": [
        {"kind": "heading", "text": "Answer"},
        {"kind": "text", "text": "It is 330 m <tall> & proud."},
        {"kind": "link", "text": "en.wikipedia.org/wiki/Eiffel_Tower", "url": "https://en.wikipedia.org/wiki/Eiffel_Tower", "note": "wikipedia"},
        {"kind": "screenshot", "src": "data:image/jpeg;base64,AAAA", "caption": "on wikipedia", "url": "https://en.wikipedia.org/wiki/Eiffel_Tower"},
        {"kind": "image", "src": "https://evil.example/x.png", "alt": "remote"},
        {"kind": "video", "title": "How tall?", "channel": "Chan", "duration": "0:14", "url": "https://www.youtube.com/watch?v=x"},
    ],
}


@pytest.fixture
def desk(tmp_path):
    (tmp_path / "Desktop").mkdir()
    (tmp_path / "Downloads").mkdir()
    set_policy(Policy({"desktop": tmp_path / "Desktop", "downloads": tmp_path / "Downloads"}, [], tmp_path / "Q", {}))
    yield tmp_path
    set_policy(None)


def test_the_panel_renders_as_html_with_live_links_and_only_embedded_images():
    page = P.render_html(CONTENT, "now")
    assert "href='https://en.wikipedia.org/wiki/Eiffel_Tower'" in page and "&lt;tall&gt; &amp; proud" in page
    assert "data:image/jpeg;base64,AAAA" in page and "evil.example" not in page
    assert "class='video' href='https://www.youtube.com/watch?v=x'" in page


def test_names_are_safe_and_nothing_is_ever_overwritten(desk):
    assert P.file_name(None, CONTENT) == "How tall is the Eiffel Tower.pdf"
    assert P.file_name("../../Windows/evil:name.PDF", CONTENT) == "Windows evil name.pdf"
    first = P.free_path("desktop", "Eiffel.pdf")
    first.write_bytes(b"old")
    second = P.free_path("desktop", "Eiffel.pdf")
    assert second.name == "Eiffel (2).pdf"
    second.write_bytes(b"old")
    assert P.free_path("desktop", "Eiffel.pdf").name == "Eiffel (3).pdf"
    with pytest.raises(ToolError):
        P.free_path("system32", "x.pdf")


def test_save_writes_a_new_file_and_says_where(desk, monkeypatch):
    async def fake_pdf(content, saved_at):
        return b"%PDF-1.7 fake"

    monkeypatch.setattr(P, "render_pdf", fake_pdf)

    class Ctx:
        def panel_content(self):
            return CONTENT

    (desk / "Desktop" / "How tall is the Eiffel Tower.pdf").write_bytes(b"keep me")
    note = asyncio.run(P.save_panel_pdf(Ctx(), location="desktop"))
    assert note.startswith("saved the panel as How tall is the Eiffel Tower (2).pdf in Desktop")
    assert (desk / "Desktop" / "How tall is the Eiffel Tower.pdf").read_bytes() == b"keep me"

    class Empty:
        def panel_content(self):
            return None

        def panel_answers(self):
            return []

    from tools import research as R

    monkeypatch.setattr(R, "STORE", desk / "research")
    with pytest.raises(ToolError):
        asyncio.run(P.save_panel_pdf(Empty(), location="desktop"))

    # "save this" straight after a research answer: that research, panel shown or not
    found = R.Research("20260928-140000", "the Queen's Gambit opening", "now")
    found.sources = [R.Source(1, "Queen's Gambit", "https://en.wikipedia.org/wiki/Queen%27s_Gambit", "en.wikipedia.org", "An opening.")]
    R.save(found)
    note = asyncio.run(P.save_panel_pdf(Empty(), location="downloads"))
    assert note.startswith("saved the panel as") and "Downloads" in note


def test_saving_is_the_one_file_change_allowed_after_outside_content():
    assert REGISTRY["save_panel_pdf"].creates_only and not REGISTRY["save_panel_pdf"].readonly
    assert not any(t.creates_only for n, t in REGISTRY.items() if n != "save_panel_pdf")


def test_save_runs_after_research_but_moving_a_file_does_not(desk, monkeypatch):
    from tools import research as R

    async def fake_research(question):
        found = R.Research("20260922-130000", "x", "now")
        R.save(found)
        return found

    async def fake_pdf(content, saved_at):
        return b"%PDF fake"

    monkeypatch.setattr(R, "STORE", desk / "research")
    monkeypatch.setattr(R, "run_research", fake_research)
    monkeypatch.setattr(P, "render_pdf", fake_pdf)

    class PanelHost(FakeHost):
        def panel_content(self):
            return CONTENT

    llm = FakeLLM([
        '<tool_call>{"name": "research", "arguments": {"question": "x"}}</tool_call>',
        '<tool_call>{"name": "save_panel_pdf", "arguments": {"location": "downloads"}}</tool_call>',
        '<tool_call>{"name": "move_to_quarantine", "arguments": {"root": "desktop", "path": "a.txt"}}</tool_call>',
        "<speak>Done, sir.</speak>",
    ])
    run(Conversation(llm), "research x and save it and tidy up", PanelHost())
    results = [m[-1]["content"] for m in llm.seen[1:]]
    assert "saved the panel as" in results[1]
    assert "refused: nothing that changes anything" in results[2]
    assert list((desk / "Downloads").glob("*.pdf"))


def test_save_phrasings_go_straight_to_the_tool():
    assert '"location": "desktop"' in direct_call("Save this as a PDF.")
    assert '"location": "downloads"' in direct_call("Save the panel to downloads")
    assert direct_call("Keep this for later.") and direct_call("save it")
    for text in ["Save me a seat.", "I need to save money.", "Save the whales!"]:
        assert direct_call(text) is None, text
