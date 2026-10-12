"""Media transport and system volume.

media_play_pause / media_next / media_previous act on the song or video in
Irene's own browser directly (the element itself, read back after), and only
otherwise send the Windows media keys, for whatever player owns the media
session - his normal Chrome, Spotify. Volume goes through the default output
device (pycaw).

With IRENE_DEV set the media keys are logged, not sent - and she says so: the -Dev
test hooks must never put OS-level input into his apps (CLAUDE.md). Her own
browser is not OS input, so it is controlled in dev mode too.
"""
from __future__ import annotations

import asyncio
import ctypes
import logging
import os
from ctypes import wintypes

from . import sandbox
from .registry import ToolContext, ToolError, tool

log = logging.getLogger("irene.tools.media")

VK_MEDIA_NEXT_TRACK, VK_MEDIA_PREV_TRACK, VK_MEDIA_PLAY_PAUSE = 0xB0, 0xB1, 0xB3
_KEYEVENTF_KEYUP, _INPUT_KEYBOARD = 0x0002, 1


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        # MOUSEINPUT is the largest member; pad so sizeof(INPUT) matches Windows
        _fields_ = [("ki", _KEYBDINPUT), ("_pad", ctypes.c_byte * 32)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send_media_key(vk: int) -> None:
    """Press and release one media key (SendInput)."""
    events = (_INPUT * 2)()
    for k, flags in enumerate((0, _KEYEVENTF_KEYUP)):
        events[k].type = _INPUT_KEYBOARD
        events[k].ki = _KEYBDINPUT(vk, 0, flags, 0, 0)
    sent = ctypes.windll.user32.SendInput(2, events, ctypes.sizeof(_INPUT))
    if sent != 2:
        raise ToolError("Windows refused the media key")


def press(vk: int, what: str) -> str:
    """The OS media key, for a player that isn't hers (his Chrome, Spotify). She
    can't see which player takes it, and says so; in dev mode it is not sent at all -
    and she says that too (live, she answered "Paused!" to a key that never left)."""
    if sandbox.os_input_blocked():
        log.info("test: media key %s (0x%02X) logged, not sent", what, vk)
        done = {"play/pause": "paused or played", "next track": "skipped", "previous track": "sent back"}.get(what, "changed")
        return f"not sent: a test never presses media keys - nothing was {done}"
    _send_media_key(vk)
    return f"key sent: {what} to whatever player has the media session (I can't see which)"


# --- her own player: the song she put on (youtube_play) ------------------------------
#
# Live, "Play Shape of You" worked and "pause" did not: the song was in HER browser,
# she pressed a blind toggle key (in dev mode not even that) and reported "Paused!".
# The media in her own browser is controlled directly - the element itself, no key,
# no OS input - and read back, so what she says is what happened.

_STATE = """() => {
  const m = [...document.querySelectorAll('video, audio')].find((e) => (e.currentSrc || e.src) && e.duration > 0);
  if (!m) return null;
  return { paused: m.paused, ended: m.ended, time: Math.round(m.currentTime), duration: Math.round(m.duration),
           title: document.title.replace(/^\\(\\d+\\)\\s*/, '').replace(/ - YouTube$/, ''), url: location.href };
}"""
_ACT = """(what) => {
  const m = [...document.querySelectorAll('video, audio')].find((e) => (e.currentSrc || e.src) && e.duration > 0);
  if (!m) return false;
  if (what === 'pause') m.pause(); else if (what === 'play') m.play(); else if (what === 'restart') { m.currentTime = 0; m.play(); }
  return true;
}"""
_NEXT = """() => {
  const b = document.querySelector('.ytp-next-button');
  if (b && b.offsetParent !== null && !b.getAttribute('aria-disabled')) { b.click(); return 'button'; }
  const up = document.querySelector('ytd-compact-video-renderer a#thumbnail[href], ytd-watch-next-secondary-results-renderer a#thumbnail[href], yt-lockup-view-model a[href*="/watch"]');
  return up ? up.href : null;
}"""

# what she last knew was playing in her browser, for the conversation's context
NOW_PLAYING: dict = {}


def _remember(state: dict | None) -> None:
    import time

    NOW_PLAYING.clear()
    if state:
        NOW_PLAYING.update(state, at=time.time())


def now_playing_line() -> str:
    """One line for her context: what her browser is playing, or nothing."""
    if not NOW_PLAYING:
        return ""
    import time

    ago = int((time.time() - NOW_PLAYING.get("at", 0)) / 60)
    state = "ended" if NOW_PLAYING.get("ended") else "paused" if NOW_PLAYING.get("paused") else "playing"
    where = NOW_PLAYING.get("where", "your browser")
    return f"Playing on {where}: {NOW_PLAYING.get('title', 'a video')} ({state}, as of {ago} min ago). 'Pause', 'continue', 'next' act on it."


async def her_player():
    """(page, state) of the media in her own browser, or None. Never starts Chrome."""
    from .browser import BROWSER

    for page in reversed(await BROWSER.open_pages()):
        try:
            state = await page.evaluate(_STATE)
        except Exception:
            continue
        if state:
            return page, state
    return None


async def _settled(page, want) -> dict | None:
    """Her player's state once `want(state)` holds (or 3 s)."""
    state = None
    for _ in range(15):
        await asyncio.sleep(0.2)
        try:
            state = await page.evaluate(_STATE)
        except Exception:
            return None
        if state and want(state):
            break
    return state


# --- his media session: Chrome (YouTube in his profile), Spotify, any player -----------
#
# Windows' media session API (System Media Transport Controls): the real state and
# title of what is playing, and pause/play/skip on that session itself - no
# keystroke, no blind toggle. A test script's command never touches it
# (tools/sandbox.py).

_PLAYING, _PAUSED = 4, 5  # GlobalSystemMediaTransportControlsSessionPlaybackStatus


async def _manager():
    try:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
    except ImportError:
        return None
    try:
        return await Manager.request_async()
    except Exception:
        log.exception("media session manager unavailable")
        return None


async def his_session():
    """(session, state) of what plays on his PC - his Chrome first, else whatever
    Windows calls current - or None."""
    manager = await _manager()
    if manager is None:
        return None
    sessions = list(manager.get_sessions())
    current = manager.get_current_session()
    ordered = sorted(sessions, key=lambda s: ("chrome" not in (s.source_app_user_model_id or "").lower(), s is not current))
    for session in ordered:
        state = await _session_state(session)
        if state is not None:
            return session, state
    return None


async def _session_state(session) -> dict | None:
    try:
        status = int(session.get_playback_info().playback_status)
        props = await session.try_get_media_properties_async()
    except Exception:
        return None
    artist, name = (props.artist or "").strip(), (props.title or "").strip()
    # YouTube's titles often carry the artist already: "Ed Sheeran - Shape of You"
    title = (name if artist and artist.lower() in name.lower() else " - ".join(x for x in (artist, name) if x)) or "something"
    return {"title": title, "paused": status != _PLAYING, "ended": False, "app": session.source_app_user_model_id or "", "where": "his PC"}


async def _session_settled(session, want) -> dict | None:
    state = None
    for _ in range(15):
        await asyncio.sleep(0.2)
        state = await _session_state(session)
        if state and want(state):
            break
    return state


async def refresh_now_playing() -> None:
    """What plays right now, for her context (app.py calls it as a turn starts)."""
    found = await his_session()
    if found is not None:
        _remember(found[1])


@tool(
    "media_play_pause",
    "Pause or resume what is playing - in his Chrome, Spotify or any player (Windows' media session), "
    "or in Irene's own browser. action: pause, play (resume) or toggle.",
    {"type": "object", "properties": {"action": {"type": "string", "enum": ["pause", "play", "toggle"], "description": "pause; play = resume/continue; toggle if unsure"}}, "required": []},
    readonly=False,
    cue="headphones",
)
async def media_play_pause(_ctx: ToolContext, action: str = "toggle") -> str:
    if not sandbox.launch_blocked():  # his player, not a keystroke: allowed like a launch
        found = await his_session()
        if found is not None:
            session, state = found
            want = action if action in ("pause", "play") else ("play" if state["paused"] else "pause")
            if want == "pause" and state["paused"]:
                _remember(state)
                return f"already paused: {state['title']}"
            if want == "play" and not state["paused"]:
                _remember(state)
                return f"already playing: {state['title']}"
            await (session.try_pause_async() if want == "pause" else session.try_play_async())
            after = await _session_settled(session, lambda s: s["paused"] == (want == "pause"))
            _remember(after or state)
            if after is None or after["paused"] != (want == "pause"):
                return f"tried to {want} {state['title']} but the player didn't respond"
            return f"{'paused' if want == 'pause' else 'playing again'}: {after['title']}"
    found = await her_player()
    if found is None:
        return "nothing is playing that I can see; " + press(VK_MEDIA_PLAY_PAUSE, "play/pause")
    page, state = found
    want = action if action in ("pause", "play") else ("play" if state["paused"] else "pause")
    if want == "pause" and state["paused"]:
        _remember(state)
        return f"already paused: {state['title']}"
    if want == "play" and not state["paused"] and not state["ended"]:
        _remember(state)
        return f"already playing: {state['title']}"
    await page.evaluate(_ACT, "restart" if state["ended"] and want == "play" else want)
    after = await _settled(page, lambda s: s["paused"] == (want == "pause"))
    _remember(after or state)
    if after is None or after["paused"] != (want == "pause"):
        return f"tried to {want} {state['title']} but the player didn't respond"
    return f"{'paused' if want == 'pause' else 'playing again'}: {after['title']} at {after['time'] // 60}:{after['time'] % 60:02d}"


@tool("media_next", "Skip to the next song or video - in his Chrome, Spotify or any player, or in Irene's own browser.", readonly=False, cue="headphones")
async def media_next(_ctx: ToolContext) -> str:
    if not sandbox.launch_blocked():  # his player, not a keystroke: allowed like a launch
        found = await his_session()
        if found is not None:
            session, state = found
            ok = await session.try_skip_next_async()
            after = await _session_settled(session, lambda s: s["title"] != state["title"])
            if not ok and (after is None or after["title"] == state["title"]):
                return f"no next video to go to after {state['title']}"
            _remember(after or state)
            return f"skipped to: {(after or state)['title']}"
    found = await her_player()
    if found is None:
        return "nothing is playing that I can see; " + press(VK_MEDIA_NEXT_TRACK, "next track")
    page, state = found
    how = await page.evaluate(_NEXT)
    if not how:
        return f"no next video to go to after {state['title']}"
    if how != "button":
        await page.goto(how, wait_until="domcontentloaded", timeout=20000)
    after = await _settled(page, lambda s: s["url"] != state["url"] and not s["paused"])
    for _ in range(10):  # the title follows the new video a little later
        if after and after["title"] != state["title"]:
            break
        after = await _settled(page, lambda s: s["title"] != state["title"])
    if after is None or after["url"] == state["url"]:
        return f"tried to skip {state['title']} but nothing changed"
    if after["paused"]:
        await page.evaluate(_ACT, "play")
    _remember(after)
    return f"skipped to: {after['title']}"


@tool("media_previous", "Go back to the previous song or video - in his Chrome, Spotify or any player, or in Irene's own browser.", readonly=False, cue="headphones")
async def media_previous(_ctx: ToolContext) -> str:
    if not sandbox.launch_blocked():  # his player, not a keystroke: allowed like a launch
        found = await his_session()
        if found is not None:
            session, state = found
            ok = await session.try_skip_previous_async()
            after = await _session_settled(session, lambda s: s["title"] != state["title"])
            _remember(after or state)
            if after is not None and after["title"] != state["title"]:
                return f"back to: {after['title']}"
            return f"back to the start of: {state['title']}" if ok else f"there's nothing before {state['title']}"
    found = await her_player()
    if found is None:
        return "nothing is playing that I can see; " + press(VK_MEDIA_PREV_TRACK, "previous track")
    page, state = found
    if state["time"] > 5:
        # like any player: back to the start of this one first
        await page.evaluate(_ACT, "restart")
        _remember(state)
        return f"back to the start of: {state['title']}"
    try:
        await page.go_back(wait_until="domcontentloaded", timeout=20000)
    except Exception:
        return f"there's nothing before {state['title']}"
    after = await _settled(page, lambda s: s["url"] != state["url"])
    if after is None or after["url"] == state["url"]:
        return f"there's nothing before {state['title']}"
    _remember(after)
    return f"back to: {after['title']}"


# --- volume --------------------------------------------------------------------


def _with_endpoint(fn):
    """Run fn(endpoint_volume) on a COM-initialised worker thread."""
    import comtypes
    from pycaw.pycaw import AudioUtilities

    comtypes.CoInitialize()
    try:
        return fn(AudioUtilities.GetSpeakers().EndpointVolume)
    finally:
        comtypes.CoUninitialize()


def _level(endpoint) -> int:
    return round(endpoint.GetMasterVolumeLevelScalar() * 100)


def _set(percent: float):
    def apply(endpoint) -> str:
        if sandbox.os_input_blocked():
            # like the media keys: the -Dev test hooks and benchmarks never touch his sound
            log.info("test: volume to %d%% logged, not set", round(percent))
            return f"volume is now {max(0, min(100, round(percent)))}%"
        endpoint.SetMasterVolumeLevelScalar(max(0.0, min(100.0, percent)) / 100, None)
        if percent > 0 and endpoint.GetMute():
            endpoint.SetMute(0, None)  # asking for a level means he wants to hear it
        return f"volume is now {_level(endpoint)}%"

    return apply


async def volume_now() -> int:
    return await asyncio.to_thread(_with_endpoint, _level)


@tool(
    "set_volume",
    "Set the system volume to a level.",
    {
        "type": "object",
        "properties": {"percent": {"type": "number", "description": "0-100"}},
        "required": ["percent"],
    },
    readonly=False,
    cue="headphones",
)
async def set_volume(_ctx: ToolContext, percent: float) -> str:
    if not 0 <= percent <= 100:
        raise ToolError("percent must be between 0 and 100")
    return await asyncio.to_thread(_with_endpoint, _set(percent))


@tool(
    "change_volume",
    "Turn the system volume up or down by an amount.",
    {
        "type": "object",
        "properties": {"delta": {"type": "number", "description": "percentage points: +10 louder, -10 quieter"}},
        "required": ["delta"],
    },
    readonly=False,
    cue="headphones",
)
async def change_volume(_ctx: ToolContext, delta: float) -> str:
    if not -100 <= delta <= 100:
        raise ToolError("delta must be between -100 and 100")
    return await asyncio.to_thread(_with_endpoint, lambda e: _set(_level(e) + delta)(e))


@tool(
    "mute",
    "Mute or unmute the system sound.",
    {
        "type": "object",
        "properties": {"on": {"type": "boolean", "description": "true mutes, false unmutes"}},
        "required": ["on"],
    },
    readonly=False,
    cue="headphones",
)
async def mute(_ctx: ToolContext, on: bool) -> str:
    def apply(endpoint) -> str:
        if sandbox.os_input_blocked():
            log.info("test: mute %s logged, not set", on)
            return "sound muted" if on else "sound on, volume 40%"
        endpoint.SetMute(1 if on else 0, None)
        return "sound muted" if on else f"sound on, volume {_level(endpoint)}%"

    return await asyncio.to_thread(_with_endpoint, apply)
