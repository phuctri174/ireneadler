"""Opening files she saved, and the song she put on.

Live (Round 6): she couldn't open the PDF she had just saved; and "Play Shape of
You" worked while "pause" did not - the song was in her own browser, she pressed a
blind toggle key (in dev mode not even that) and still said "Paused!"."""
import asyncio

import pytest

from irene import fast
from tools import files as F
from tools import media as M
from tools.policy import Policy, set_policy
from tools.registry import ToolError


@pytest.fixture
def desk(tmp_path, monkeypatch):
    (tmp_path / "Desktop").mkdir()
    (tmp_path / "Downloads").mkdir()
    set_policy(Policy({"desktop": tmp_path / "Desktop", "downloads": tmp_path / "Downloads"}, [], tmp_path / "Q", {}))
    opened = []
    # the real path, with the opener stubbed: not a test-script command
    monkeypatch.delenv("IRENE_DEV", raising=False)
    monkeypatch.setattr(F, "_start", opened.append)
    monkeypatch.setattr(F, "SAVED", [])
    yield tmp_path, opened
    set_policy(None)


# ---- open_file -------------------------------------------------------------------


def test_the_pdf_she_saved_opens_by_asking_for_it(desk):
    tmp, opened = desk
    pdf = tmp / "Desktop" / "Queen's Gambit.pdf"
    pdf.write_bytes(b"%PDF")
    F.remember_saved("desktop", pdf)
    assert asyncio.run(F.open_file(None, saved="last")) == "opened Queen's Gambit.pdf (desktop) in its default app"
    assert asyncio.run(F.open_file(None, saved="queen's gambit")).startswith("opened Queen's Gambit.pdf")
    assert opened == [pdf, pdf]
    assert "Queen's Gambit.pdf (desktop)" in F.saved_line()


def test_a_named_file_she_never_saved_is_not_the_last_one(desk):
    tmp, opened = desk
    pdf = tmp / "Desktop" / "Queen's Gambit.pdf"
    pdf.write_bytes(b"%PDF")
    F.remember_saved("desktop", pdf)
    with pytest.raises(ToolError, match="search_files"):
        asyncio.run(F.open_file(None, saved="tax"))
    assert opened == []


def test_only_whitelisted_documents_open_never_a_program_or_a_path_outside(desk):
    tmp, opened = desk
    (tmp / "Downloads" / "setup.exe").write_bytes(b"MZ")
    (tmp / "Downloads" / "run.bat").write_text("echo")
    (tmp / "Downloads" / "notes.txt").write_text("hi")
    for bad in ("setup.exe", "run.bat"):
        with pytest.raises(ToolError, match="only open documents"):
            asyncio.run(F.open_file(None, root="downloads", path=bad))
    with pytest.raises(ToolError):
        asyncio.run(F.open_file(None, root="downloads", path="../../Windows/notepad.exe"))
    assert asyncio.run(F.open_file(None, root="downloads", path="notes.txt")).startswith("opened notes.txt")
    assert opened == [tmp / "Downloads" / "notes.txt"]


def test_open_that_pdf_goes_straight_to_the_file_she_saved(desk):
    tmp, _ = desk
    assert fast.direct_call("open that PDF you saved") == '<tool_call>{"name": "open_file", "arguments": {"saved": "last"}}</tool_call>'
    assert fast.direct_call("Open the file from earlier.") == '<tool_call>{"name": "open_file", "arguments": {"saved": "last"}}</tool_call>'
    assert fast.direct_call("open my tax file") is None, "not one she saved: the model searches"
    assert fast.direct_call("open the panel") is None and fast.direct_call("open youtube") is None
    reply, cue = fast._opened({}, "opened Queen's Gambit.pdf (desktop) in its default app", "open that pdf")
    assert "Queen's Gambit" in reply


# ---- her player --------------------------------------------------------------------


class _Page:
    """Her YouTube tab: a video element, as the page's own JS sees it."""

    def __init__(self, paused=False, title="Ed Sheeran - Shape of You (Official Music Video)"):
        self.state = {"paused": paused, "ended": False, "time": 62, "duration": 263, "title": title, "url": "https://www.youtube.com/watch?v=JGwWNGJdvx8"}

    async def evaluate(self, script, arg=None):
        if script == M._STATE:
            return dict(self.state)
        if script == M._ACT:
            self.state["paused"] = arg == "pause"
            return True
        if script == M._NEXT:
            self.state.update(url="https://www.youtube.com/watch?v=next", title="Ed Sheeran - Perfect", paused=False)
            return "button"
        raise AssertionError(script)


@pytest.fixture
def player(monkeypatch):
    page = _Page()

    class Browser:
        async def open_pages(self):
            return [page]

    from tools import browser

    monkeypatch.setattr(browser, "BROWSER", Browser())
    real_sleep = asyncio.sleep
    monkeypatch.setattr(M.asyncio, "sleep", lambda _s: real_sleep(0))
    return page


def test_pause_and_continue_act_on_the_song_she_put_on_and_say_what_happened(player):
    assert asyncio.run(M.media_play_pause(None, "pause")) == "paused: Ed Sheeran - Shape of You (Official Music Video) at 1:02"
    assert player.state["paused"]
    assert asyncio.run(M.media_play_pause(None, "pause")).startswith("already paused"), "never a toggle back on"
    assert asyncio.run(M.media_play_pause(None, "play")).startswith("playing again")
    assert "Shape of You" in M.now_playing_line() and "playing" in M.now_playing_line()


def test_next_skips_in_her_browser(player):
    assert asyncio.run(M.media_next(None)) == "skipped to: Ed Sheeran - Perfect"


def test_with_nothing_in_her_browser_dev_mode_says_the_key_was_not_sent(monkeypatch):
    class Browser:
        async def open_pages(self):
            return []

    from tools import browser

    monkeypatch.setattr(browser, "BROWSER", Browser())
    monkeypatch.setenv("IRENE_DEV", "1")
    result = asyncio.run(M.media_play_pause(None, "pause"))
    assert result.startswith("nothing is playing that I can see; not sent")
    reply, _ = fast._play_pause({"action": "pause"}, result, "pause")
    assert "paused" not in reply.lower().replace("nothing's", ""), "never 'Paused!' over a key that never left"


def test_pause_and_continue_route_with_what_he_meant():
    assert fast.direct_call("pause the song please") == '<tool_call>{"name": "media_play_pause", "arguments": {"action": "pause"}}</tool_call>'
    assert fast.direct_call("continue") == '<tool_call>{"name": "media_play_pause", "arguments": {"action": "play"}}</tool_call>'
    assert fast.direct_call("next song") == '<tool_call>{"name": "media_next", "arguments": {}}</tool_call>'


def test_a_tool_call_with_its_arguments_written_flat_keeps_them():
    """Live: {"name": "read_page_text", "url": "..."} ran with no url at all."""
    from irene.brain import parse_tool_call

    assert parse_tool_call('<tool_call>{"name": "read_page_text", "url": "https://example.com/a"}</tool_call>') == ("read_page_text", {"url": "https://example.com/a"})
    assert parse_tool_call('<tool_call>{"name": "media_next", "arguments": {}}</tool_call>') == ("media_next", {})
    assert parse_tool_call('<tool_call>{"name": "open_file", "parameters": {"saved": "last"}}</tool_call>') == ("open_file", {"saved": "last"})
