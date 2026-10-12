"""His commands reach his apps; a test's never do. Anything he will look at opens
in HIS Chrome profile.

Round 6/7: he runs Irene with -Dev every day, and the old guard (IRENE_DEV =
never send keys, never open his Chrome) meant "pause" never paused and panel
links never opened - for him."""
import asyncio
import contextvars

from tools import browser, media, sandbox


def in_context(fn):
    return contextvars.copy_context().run(fn)


def test_his_commands_are_real_and_a_scripts_never_reach_his_apps():
    def check(origin, real_launch=False):
        sandbox.enter(origin, real_launch)
        return sandbox.os_input_blocked(), sandbox.launch_blocked()

    assert in_context(lambda: check("hud")) == (False, False)
    assert in_context(lambda: check("mic")) == (False, False)
    assert in_context(lambda: check("script")) == (True, True)
    assert in_context(lambda: check("replay")) == (True, True)
    assert in_context(lambda: check(None)) == (True, True)
    # a live check may ask to open a page for real - never to press keys
    assert in_context(lambda: check("script", real_launch=True)) == (True, False)


def test_his_profile_is_found_by_his_account_name(monkeypatch, tmp_path):
    import json

    state = tmp_path / "Google" / "Chrome" / "User Data"
    state.mkdir(parents=True)
    (state / "Local State").write_text(json.dumps({"profile": {"info_cache": {
        "Default": {"name": "Your Chrome", "gaia_name": "Alex Nguyen"},
        "Profile 1": {"name": "Irene", "gaia_name": "Irene Adler"},
    }}}), encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    exe, directory = browser.his_chrome()
    assert directory == "Default" and exe.name == "chrome.exe"


def test_pages_he_looks_at_launch_into_his_profile(monkeypatch):
    launched = []
    monkeypatch.setattr(browser.subprocess, "Popen", lambda args, **_k: launched.append(args))
    monkeypatch.setattr(browser, "his_chrome", lambda: (browser.Path(__file__), "Default"))

    def as_him():
        sandbox.enter("hud")
        return asyncio.run(browser.open_url(None, "chess.com"))

    assert in_context(as_him) == "opened https://chess.com in his Chrome"
    assert launched == [[__file__, "--profile-directory=Default", "https://chess.com"]]

    def as_a_script():
        sandbox.enter("script")
        return asyncio.run(browser.open_url(None, "chess.com"))

    in_context(as_a_script)
    assert len(launched) == 1, "a test script never opens his Chrome"


def test_youtube_plays_in_his_chrome_and_she_knows_what(monkeypatch):
    launched = []
    monkeypatch.setattr(browser, "open_in_his_chrome", launched.append)

    async def found(query, count=5):
        return [{"url": "https://www.youtube.com/watch?v=JGwWNGJdvx8", "title": "Shape of You", "channel": "Ed Sheeran"}]

    monkeypatch.setattr(browser, "search_youtube", found)
    result = asyncio.run(browser.youtube_play(None, "Shape of You"))
    assert result.startswith("playing in his Chrome: Shape of You")
    assert launched == ["https://www.youtube.com/watch?v=JGwWNGJdvx8"]
    assert "Shape of You" in media.now_playing_line()


class _Session:
    """His media session (Chrome), as Windows reports it."""

    source_app_user_model_id = "Chrome"

    def __init__(self):
        self.status, self.title = 4, "Shape of You"

    def get_playback_info(self):
        return type("Info", (), {"playback_status": self.status})()

    async def try_get_media_properties_async(self):
        return type("Props", (), {"artist": "Ed Sheeran", "title": self.title})()

    async def try_pause_async(self):
        self.status = 5
        return True

    async def try_play_async(self):
        self.status = 4
        return True

    async def try_skip_next_async(self):
        self.title = "Perfect"
        return True


def test_pause_and_next_act_on_his_media_session_not_a_key(monkeypatch):
    session = _Session()

    async def his():
        return session, await media._session_state(session)

    monkeypatch.setattr(media, "his_session", his)
    monkeypatch.setattr(media, "_send_media_key", lambda vk: (_ for _ in ()).throw(AssertionError("a key was sent")))
    real_sleep = asyncio.sleep
    monkeypatch.setattr(media.asyncio, "sleep", lambda _s: real_sleep(0))

    def as_him(fn):
        sandbox.enter("mic")
        return asyncio.run(fn())

    assert in_context(lambda: as_him(lambda: media.media_play_pause(None, "pause"))) == "paused: Ed Sheeran - Shape of You"
    assert in_context(lambda: as_him(lambda: media.media_play_pause(None, "pause"))) == "already paused: Ed Sheeran - Shape of You"
    assert in_context(lambda: as_him(lambda: media.media_play_pause(None, "play"))) == "playing again: Ed Sheeran - Shape of You"
    assert in_context(lambda: as_him(lambda: media.media_next(None))) == "skipped to: Ed Sheeran - Perfect"

    def as_a_script():
        sandbox.enter("script")
        return asyncio.run(media.media_play_pause(None, "pause"))

    assert "not sent" in in_context(as_a_script) and session.status == 4, "a test never touches his player"
