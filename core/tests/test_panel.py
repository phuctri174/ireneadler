import asyncio

import pytest

from irene import fast
from tools import panel as P
from tools import research as R
from tools.registry import ToolError


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "STORE", tmp_path)
    older = R.Research("20260922-100000", "eiffel tower height", "2026-09-22 10:00", answer="It's **330 m** tall [1].")
    older.sources = [R.Source(1, "Eiffel Tower", "https://en.wikipedia.org/wiki/Eiffel_Tower", "en.wikipedia.org", "330 m.",
                              screenshot="data:image/jpeg;base64,AA", image="data:image/jpeg;base64,BB")]
    newer = R.Research("20260922-110000", "heat pump how it works", "2026-09-22 11:00")
    newer.sources = [R.Source(1, "Heat pumps", "https://energy.gov/heat-pumps", "energy.gov", "They move heat.")]
    newer.videos = [R.Video("Heat pumps explained", "Chan", "6:18", "https://www.youtube.com/watch?v=x", "data:image/jpeg;base64,CC")]
    R.save(older)
    R.save(newer)
    return tmp_path


def kinds(content):
    return [b["kind"] for b in content["blocks"]]


def test_the_last_research_shows_answer_sources_screenshots_and_videos(store):
    content, note = P.resolve("the last research", [])
    assert content["title"] == "Heat pump how it works"
    assert kinds(content) == ["heading", "heading", "link", "text", "heading", "video"]
    assert "1 sources and 1 videos" in note


def test_an_earlier_research_is_found_by_its_words(store):
    content, _ = P.resolve("the eiffel tower research", [])
    assert content["title"] == "Eiffel tower height"
    assert {"screenshot", "image", "link"} <= set(kinds(content))
    assert content["blocks"][1] == {"kind": "text", "text": "It's 330 m tall [1]."}


def test_sources_only_and_videos_only(store):
    sources, note = P.resolve("show me the sources", [])
    assert "video" not in kinds(sources) and "link" in kinds(sources) and "its sources" in note
    videos, _ = P.resolve("the videos", [])
    assert kinds(videos) == ["heading", "video"]


def test_that_means_the_newest_result_research_or_answer(store):
    answer = {"at": "20260922-120000", "title": "Explain TCP", "subtitle": "", "blocks": [{"kind": "text", "text": "..."}]}
    content, _ = P.resolve("that", [answer])
    assert content["title"] == "Explain TCP" and "at" not in content
    stale = dict(answer, at="20260922-090000")
    content, _ = P.resolve("put that on the screen", [stale])
    assert content["title"] == "Heat pump how it works"


def test_close_takes_it_down_and_nothing_to_show_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "STORE", tmp_path)
    assert P.resolve("close the panel", []) == (None, "panel closed")
    with pytest.raises(ToolError):
        P.resolve("the last research", [])


def test_only_links_it_put_on_the_panel_are_clickable(store):
    content, _ = P.resolve("eiffel", [])
    assert P.links_in(content) == {"https://en.wikipedia.org/wiki/Eiffel_Tower"}
    assert P.links_in(None) == set()


def test_display_text_becomes_blocks():
    blocks = P.text_blocks("## Key facts\n\n**Height:** 330 m\n\n* one\n* two")
    assert blocks == [{"kind": "heading", "text": "Key facts", "level": 3},
                      {"kind": "text", "text": "Height: 330 m"}, {"kind": "text", "text": "• one\n• two"}]


def test_the_tool_sends_the_content_and_the_fast_path_answers(store):
    shown = []

    class Ctx:
        async def show_panel(self, content):
            shown.append(content)

        def panel_answers(self):
            return []

    note = asyncio.run(P.show_panel(Ctx(), "sources"))
    assert shown[0]["title"] == "Heat pump how it works"
    reply = fast.reply("show_panel", {"what": "sources"}, note, "Show me the sources.")
    assert reply.startswith("<speak><cue>") and ("panel" in reply or "up now" in reply)
