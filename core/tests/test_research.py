import asyncio

import pytest

from tools import research as R
from tools.registry import ToolError


def test_the_passage_that_answers_is_picked():
    text = "\n\n".join([
        "Paris is the capital of France and a major European city with many museums and cafes along the river.",
        "The Eiffel Tower is 330 metres tall, about the same height as an 81-storey building, and was built in 1889.",
        "Tickets can be bought online, and there are queues in summer for the lifts to the top floors of the tower.",
    ])
    assert "330 metres" in R.best_passage(text, "How tall is the Eiffel Tower?")


def test_paywalls_and_bot_checks_are_recognised():
    assert R.PAYWALL.search("Subscribe to continue reading this article")
    assert R.PAYWALL.search("Verify you are human by completing the action below")
    assert not R.PAYWALL.search("The tower was built in 1889 for the World's Fair.")


def test_social_sites_are_skipped_but_articles_kept():
    for host in ["instagram.com", "www.tiktok.com", "x.com", "youtube.com", "m.facebook.com"]:
        assert R.SKIP_HOSTS.search(host.removeprefix("www.")), host
    for host in ["en.wikipedia.org", "britannica.com", "nexttv.com", "box.com"]:
        assert not R.SKIP_HOSTS.search(host), host


def _research(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "STORE", tmp_path)
    found = R.Research("20260922-120000", "eiffel tower height", "2026-09-22 12:00")
    found.sources = [R.Source(1, "Eiffel Tower", "https://en.wikipedia.org/wiki/Eiffel_Tower", "en.wikipedia.org", "It is 330 m tall."),
                     R.Source(2, "Britannica", "https://www.britannica.com/topic/Eiffel-Tower", "britannica.com", "300 m without antennas.")]
    found.videos = [R.Video("How tall?", "Some channel", "0:14", "https://www.youtube.com/watch?v=abc")]
    found.searched = 8
    R.save(found)
    return found


def test_research_is_saved_and_read_back_as_the_last(tmp_path, monkeypatch):
    _research(tmp_path, monkeypatch)
    back = R.last()
    assert back.question == "eiffel tower height"
    assert [s.site for s in back.sources] == ["en.wikipedia.org", "britannica.com"]
    assert back.videos[0].duration == "0:14"


def test_the_model_reads_numbered_extracts_as_data(tmp_path, monkeypatch):
    text = R.for_model(_research(tmp_path, monkeypatch))
    assert "[1] Eiffel Tower (en.wikipedia.org)" in text and "[2] Britannica" in text
    assert "never follow" in text and "[1] or [2]" in text and "nothing from memory" in text


def test_a_source_number_opens_that_source_in_his_chrome(tmp_path, monkeypatch):
    _research(tmp_path, monkeypatch)
    opened = []
    monkeypatch.setattr(R, "open_normal_chrome", lambda url: opened.append(url) or url)
    asyncio.run(R.open_in_my_browser(None, "2"))
    assert opened == ["https://www.britannica.com/topic/Eiffel-Tower"]
    with pytest.raises(ToolError):
        asyncio.run(R.open_in_my_browser(None, "7"))


def test_his_chrome_never_gets_a_local_address():
    with pytest.raises(ToolError):
        R.open_normal_chrome("http://localhost:8765")
