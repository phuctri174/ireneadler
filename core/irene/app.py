"""Irene core: FastAPI + WebSocket on 127.0.0.1.

Run: .venv\\Scripts\\python -m irene.app
"""
from __future__ import annotations

import asyncio
import dataclasses
import faulthandler
import json
import logging
import os
import random
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket

from tools import REGISTRY
from tools import panel as panel_tool
from tools import power as power_tool
from tools import research as research_tool
from tools import sandbox

from . import calibration, chess_game, drawing, entrances, fast, greeting, illustrate, keiko, music, openers, presence, quick, sfx, skit, stt, summon, vram
from . import react as cues
from .brain import Conversation, Line, StreamingReply
from .bridge import Bridge
from .llm import Ollama
from .react import React
from .reply import Reply, for_chat, parse_reply
from .tts import SpeechStream
from .tts import Speaker, block_levels
from .corpus import Corpus
from .dashboard import Dashboard
from .voice_loop import Voice
from tools.localconfig import personal

HOST = "127.0.0.1"
PORT = 8765
# a voice summon while the HUD is still connecting waits this long for it
HUD_WAIT_S = 8.0
# a hold-up of core's event loop longer than this is logged (her face waits on it)
LOOP_LAG_LOG_MS = 120
# a summon boots her interface and the panel first (the HUD's boot-up animation);
# the entrance plays after it - skipped at once if he starts speaking
BOOT_S = 12.0  # hud/src/ui/boot.tsx BOOT_MS: the same timeline
# the boot's beats the music follows (hud/src/ui/boot.tsx ACT): it drops away for the
# held beat of darkness before the name, and slams back as the first letter lands
BOOT_SILENCE_S = 6.0
BOOT_NAME_S = 6.9
# the music under the silent beat: nearly gone, not cut (a cut sounds like a fault)
MUSIC_SILENCE_LEVEL = 0.05
# her boot soundtrack's level (sfx.boot, peak-normalised)
BOOT_VOLUME = 0.55
# a signature entrance's "what are you doing?" answer: its sound, and how far it
# leads her words
ANSWER_SFX_GAIN = 0.45
ANSWER_SFX_LEAD_S = 0.25
# screens-off mode: how long the lights wait for her to finish speaking, and how
# soon after lights out his mouse/keyboard counts as "I'm back"
DARK_SPEAK_WAIT_S = 8.0
DARK_INPUT_GRACE_S = 1.0
# a dark wake: the longest wait for Windows to report the displays on
# a signature entrance's answer to "what are you doing?" (app.py attached_shows):
# its body cues one after another, this far apart; a line with no body cue gets
# the one that fits its feeling
ATTACHED_GESTURE_S = 1.7
ATTACHED_SCENE_S = 2.4
ATTACHED_BODY = {
    "proud": "taDa", "sulking": "handsUp", "sheepish": "giggle", "firedUp": "excitedBounce",
    "excited": "excitedBounce", "wink": "cool", "happy": "jazzHands", "embarrassed": "facepalm",
}
DARK_WAKE_TIMEOUT_S = 6.0
# her page landing on the panel (hud/src/dashboard/Dashboard.css "the deal"): the
# paper sound when it touches down - the relay to the panel window takes a little
PAPER_LAND_S = 0.55
PAPER_GAIN = 0.32
# the longest a dark wake holds her boot for the displays to settle; past it she
# boots anyway (a monitor that never comes back must not keep her away)
DARK_WAKE_MAX_HOLD_S = 25.0
ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"
LOGS = ROOT / "core" / "logs"
# tools that take seconds: she says a cached "Let me look that up!" as one starts
SLOW_TOOLS = {"research", "daily_briefing"}
# the briefing's readings kept fresh while she is idle (tools/briefing.prefetch):
# first this long after startup, then checked this often
BRIEFING_PREFETCH_START_S = 90.0
BRIEFING_PREFETCH_EVERY_S = 60.0
# the watchdog: no state change for this long while she is not audibly speaking
# is a freeze - logged, and she recovers to listening. A slow tool that is visibly
# working (research) gets longer; its own timeouts end it well before that.
WATCHDOG_S = 15.0
WATCHDOG_SLOW_TOOL_S = 60.0
# perform(): how long each kind holds before the next (a gesture's pose is 2 s in the
# HUD; a scene is cut short)
PERFORM_HOLD_S = {"expression": 1.5, "gesture": 2.1, "scene": 5.5}

# Browsers let any page open a socket to localhost, so only the HUD's own origins
# get in. No Origin header means a local non-browser client (tests, scripts).
ALLOWED_ORIGINS = {
    "http://localhost:1420",  # tauri dev
    "http://tauri.localhost",  # tauri release on Windows
    "https://tauri.localhost",
    "tauri://localhost",
}

log = logging.getLogger("irene")

# Test hooks: with IRENE_DEV=1, a local client may drive the HUD directly - point a
# synthetic hand, play a scene or a reaction, summon, step F11, open and submit
# the command bar - so UI paths can be verified from a script without any
# OS-level input. Off by default; the HUD also ignores them outside a dev build.
DEV = os.environ.get("IRENE_DEV") == "1"
DEV_RELAY = ("debug_point", "activity", "reaction", "debug_ui")
# summon entrances: what core tells the HUD
#   {"type": "entrance", "name": ..., "phase": "start", "ms": ...}  as the clip is heard
#   {"type": "entrance", "phase": "end"}


class Core:
    def __init__(self) -> None:
        self.bridge = Bridge()
        self.llm = Ollama()
        self.speaker: Speaker | None = None
        # the track under a voice summon (config/summon_music.yaml), decoded at startup
        self.music = music.Track()
        self.summon_clip: summon.Clip | None = None
        self.entrances = entrances.load_registry()
        # weights and repeat rule re-read from config/entrances.json on every summon
        self.picker = entrances.Picker(self.entrances, live=True)
        self.entrance_clips: dict[str, entrances.Clip] = {}
        # the entrance playing now, so typing or a command can skip it
        self._entrance: asyncio.Task | None = None
        # a voice wake waiting for the HUD to hand the summon back (summon_by_voice)
        self._voice_summon: asyncio.Future | None = None
        # her greeting after an entrance; what she was doing in it is the
        # conversation's (Conversation.entered)
        self.greeter = greeting.Greeter()
        # when he talks to her and what about, across restarts (presence.py): her
        # greeting knows how long it's been, when he started today, what was last
        self.presence = presence.Presence()
        # the everyday exchanges, answered from pre-rendered audio (quick.py)
        self.quick = quick.QuickReplies(self.entrances)
        self.last_entrance: str | None = None
        self._sounds: dict = {}
        self.muted = False
        self.last_ttfa: float | None = None
        self._last_working: str | None = None
        # when the last "one sec" / "On it!" was heard (it can be a turn's first audio)
        self.working_heard_at: float | None = None
        # the panel: what's on it (its links are the only ones a click may open) and
        # her earlier detailed answers, newest first, for "put that on the screen"
        self.panel_links: set[str] = set()
        self.panel_content: dict | None = None
        self.panel_answers: list[dict] = []
        # the reaction shown with the previous reply; the same one never plays twice running
        self.last_react: str | None = None
        # and the one it opened with: a swapped-in cue avoids both
        self.last_opening: str | None = None
        self.conversation = Conversation(self.llm)
        # a chess game with him (chess_game.py): the engine plays her moves; while it
        # is on, the board stays up and the model knows the game is on
        self.chess = chess_game.ChessGame()
        self.conversation.game = self.chess
        # keiko with him (keiko.py): started by his voice only; his strikes come from
        # the HUD's recogniser
        self.keiko = keiko.Keiko()
        self._keiko_watch: asyncio.Task | None = None
        self._turn: asyncio.Task | None = None
        # where the current turn began in the history, so a premature one can go
        self._turn_mark: int | None = None
        # the watchdog's view of a turn: a tool running now, and the last sign of life
        self._tool_running: str | None = None
        # the model has the prompt and has not written a word yet (prefill)
        self._prefilling = False
        self._progress_at = time.monotonic()
        self._confirms: dict[str, asyncio.Future[bool]] = {}
        self._shield: asyncio.Future[None] | None = None
        self.bridge.handlers["command"] = self.on_command
        self.bridge.handlers["capture_shield_ack"] = self.on_capture_shield_ack
        self.bridge.handlers["confirm_reply"] = self.on_confirm_reply
        self.bridge.handlers["speak"] = self.on_speak
        self.bridge.handlers["mute"] = self.on_mute
        self.bridge.handlers["sleep"] = self.on_sleep
        self.bridge.handlers["calibration"] = self.on_calibration
        self.bridge.handlers["summon_skip"] = self.on_summon_skip
        self.bridge.handlers["open_link"] = self.on_open_link
        self.bridge.handlers["kamae"] = self.on_kamae
        self.bridge.handlers["keiko_strike"] = self.on_keiko_strike
        # the HUD's side of a voice summon, into core.log (summon path 3-6)
        self.bridge.handlers["hud_trace"] = self.on_hud_trace
        # her window shown or hidden: shown, she listens without a wake word
        self.bridge.handlers["visibility"] = self.on_visibility
        # the HUD's own timings every 10 s: tracking, body tracking, her face
        self.bridge.handlers["hud_perf"] = self.on_hud_perf
        # voice (Phase 6): the microphone, and the read-aloud corpus recorder
        self.voice = Voice(self)
        self.corpus = Corpus(self)
        # the second screen's info dashboard (news, weather, stocks, load, timers)
        self.dashboard = Dashboard(self)
        self.bridge.handlers["dashboard_open"] = self.dashboard.on_open
        self.bridge.handlers["dashboard_refresh"] = lambda _m: self.dashboard.push(force=True)
        self.bridge.handlers["research_recall"] = self.dashboard.recall
        # screens-off mode (tools/power.py): the monitors dark, she still listens
        self.dark = False
        self._dark_since = 0.0
        self._dark_monitors = 1
        self._dark_task: asyncio.Task | None = None
        self.bridge.handlers["screens_off"] = self.on_screens_off
        # the boot-up animation is running (entrance_then_greeting)
        self.booting = False
        # research cleared or expired: out of her memory and off the panel
        research_tool.FORGET_HOOKS.append(self._research_gone)
        # his Chrome opening: her windows stop being topmost so it comes in front
        from tools import browser as browser_tool

        browser_tool.BEFORE_OPEN.append(lambda: self.bridge.send_threadsafe({"type": "yield_front"}))
        self.bridge.handlers["listen"] = self.on_listen
        self.bridge.handlers["corpus"] = self.corpus.on_message
        # skit mode (skit.py): his scripted scenes for filming, on ctrl+alt+shift+k / x
        self.skit = skit.Skits(self)
        self.bridge.handlers["skit"] = self.skit.on_message
        if DEV:
            for kind in DEV_RELAY:
                self.bridge.handlers[kind] = self.bridge.send
            self.bridge.handlers["say_reply"] = self.on_say_reply
            self.bridge.handlers["play_entrance"] = self.on_play_entrance
            self.bridge.handlers["wake"] = self.on_wake
            self.bridge.handlers["voice_heard"] = self.on_voice_heard
            self.bridge.handlers["voice_replay"] = self.on_voice_replay
            self.bridge.handlers["mic_deaf"] = self.on_mic_deaf
            # dev only: screens-off mode through its real path (enter_dark), for
            # the live check - his scripted commands are sandboxed otherwise
            self.bridge.handlers["dev_screens_off"] = lambda _m: self.enter_dark()
            # dev only: what a recognised "Hey Irene" does next (summon_by_voice) -
            # the dark wake checked without the room's voices in the mic
            self.bridge.handlers["dev_wake"] = lambda _m: self.summon_by_voice(adler=False)
            log.warning("dev relay on: %s, say_reply", ", ".join(DEV_RELAY))

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self.loop = loop
        self.bridge.bind(loop)
        t0 = time.perf_counter()
        self.speaker = await asyncio.to_thread(
            Speaker,
            personal("pronunciation.yaml"),
            lambda level: self.bridge.send_threadsafe({"type": "audio_level", "value": round(level, 3)}),
        )
        log.info("voice %s ready in %.1fs", self.speaker.engine, time.perf_counter() - t0)
        self.music.load_in_background()
        voice = self.speaker.voice
        self.summon_clip = await asyncio.to_thread(summon.load_or_render, lambda: voice._kokoro().pipeline)
        self.entrance_clips = await asyncio.to_thread(entrances.load_all, voice, self.entrances)
        self.speaker.openers = await asyncio.to_thread(openers.load_or_render, voice)
        self.speaker.openers_engine = voice.name
        if voice.name == "turbo" and not summon.TURBO_WAV.exists():
            await asyncio.to_thread(summon.render_turbo, voice.engine)
        log.info("entrances: %s", ", ".join(f"{n} {c.duration:.1f}s" for n, c in self.entrance_clips.items()))
        # small talk in her voice: from the cache, or rendered in the background (a
        # minute, once) - until then it goes to the model like anything else
        self._quick_task = asyncio.create_task(asyncio.to_thread(self.quick.load_or_render, voice))
        # held so the task can't be garbage-collected mid-flight
        self._warm_task = asyncio.create_task(self._warm_llm())
        self._searx_task = asyncio.create_task(self._warm_search())
        self._idle_task = asyncio.create_task(self._watch_idle())
        self._watchdog_task = asyncio.create_task(self._watchdog())
        self._lag_task = asyncio.create_task(self._watch_loop_lag())
        # the VRAM spill guard: reloads the model when it has spilled (vram.py)
        self.vram = vram.VramGuard(self.llm, self._idle_for_reload)
        self._vram_task = asyncio.create_task(self.vram.run())
        self._briefing_task = asyncio.create_task(self._keep_briefing_warm())
        self.dashboard.start()
        # the briefing's Vietnamese headlines, in English - by her own model, locally
        from tools import briefing as briefing_tool

        briefing_tool.TRANSLATE = self.translate
        if self.voice.start(loop):
            log.info("voice on: wake with 'Hey Irene' or 'Irene Adler'")
        await self.bridge.send({"type": "voice", "phase": "asleep" if self.voice.available else "off"})

    async def translate(self, texts: list[str]) -> list[str] | None:
        """Vietnamese (headlines, a summary) into short natural English, by her own
        local model - the same model and context size as her turns, so nothing reloads.
        None if the reply can't be read as one English line per input."""
        import re as _re

        prompt = (
            "Translate each Vietnamese text into natural English, in sentence case (a news headline, not Title Case). "
            "Keep names; write Vietnamese place and person names without accents. Translate only - add nothing. "
            "Reply with ONLY a JSON array of strings, same order, same count.\n" + json.dumps(texts, ensure_ascii=False)
        )
        raw = await self.llm.chat([{"role": "user", "content": prompt}], temperature=0.2)
        m = _re.search(r"\[.*\]", raw, _re.S)
        try:
            out = json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            out = None
        if not isinstance(out, list) or len(out) != len(texts) or not all(isinstance(t, str) and t.strip() for t in out):
            log.warning("translation unreadable: %r", raw[:200])
            return None
        return [t.strip() for t in out]

    def _idle_for_reload(self) -> bool:
        """Nothing going on that a model reload would interrupt."""
        busy = lambda task: task is not None and not task.done()  # noqa: E731
        speaking = self.speaker is not None and self.speaker.progress()[1] > self.speaker.progress()[0] + 0.05
        return not (self.booting or busy(self._turn) or busy(self._entrance) or speaking)

    async def _keep_briefing_warm(self) -> None:
        """"What's new today" answered at once: the briefing's sources fetched (and
        new Vietnamese headlines translated) while she is idle and the HUD is up,
        before the 15-minute cache runs out - never during a turn. A translation
        pushes the conversation out of Ollama's prompt cache: it is read back in."""
        from tools import briefing as briefing_tool

        await asyncio.sleep(BRIEFING_PREFETCH_START_S)
        while True:
            try:
                if self.bridge.hud_connected and self._idle_for_reload() and not self.dark:
                    translated = await briefing_tool.prefetch()
                    if translated:
                        log.info("briefing prefetch: %d new headline(s) translated - re-reading the conversation", translated)
                        self.conversation.warm_cache()
            except Exception:  # noqa: BLE001 - a prefetch must never take core down
                log.exception("briefing prefetch failed")
            await asyncio.sleep(BRIEFING_PREFETCH_EVERY_S)

    async def _watch_idle(self) -> None:
        """Five quiet minutes end the conversation; tell the HUD so the bar clears."""
        while True:
            await asyncio.sleep(20)
            if self.conversation.expired() and not (self._turn and not self._turn.done()):
                self.conversation.reset()
                await self.bridge.send({"type": "conversation", "event": "reset"})

    async def on_screens_off(self, message: dict) -> None:
        """Ctrl+Alt+Shift+O, from his HUD: the same as "Irene, screens off"."""
        sandbox.enter(message.get("_origin"))
        if not power_tool.enabled():
            log.info("screens-off: asked (hotkey) - turned off in config/power.yaml, nothing done")
            await self.say("Screens-off mode is turned off in my settings. Ask me to turn it on and I will.")
            return
        if sandbox.launch_blocked():
            log.info("screens off asked by a script - not done")
            return
        await self.enter_dark()

    async def enter_dark(self) -> None:
        """Her windows away, hand tracking and face paused, then - once she has
        finished speaking - the monitors off. The mic and wake phrases keep going.
        The way back never depends on her hearing: any mouse move or key press after
        the lights go out ends the mode (Windows lights the displays itself). Every
        step is logged as "screens-off:" - the screens are dark, the log is the
        only witness."""
        if self.dark:
            return
        self.dark = True
        self._dark_since = time.monotonic()
        # every monitor on the desktop now has to be back before a wake boots her
        self._dark_monitors = max(1, power_tool.monitors())
        # watching what Windows says about the displays (for the wake)
        await asyncio.to_thread(power_tool.display_watch)
        log.info("screens-off: ON - her windows away, tracking suspended; monitors off once she stops speaking")
        await self.bridge.send({"type": "dark", "value": True})
        self._dark_task = asyncio.create_task(self._dark_watch())

    async def _dark_watch(self) -> None:
        """Lights out once she is quiet; then watch for his hand on the mouse or
        keyboard, and say every 30 s that the mode still holds."""
        deadline = time.monotonic() + DARK_SPEAK_WAIT_S
        await asyncio.sleep(0.5)
        while self.bridge.current_state in ("speaking", "thinking") and time.monotonic() < deadline and self.dark:
            await asyncio.sleep(0.2)
        if not self.dark:
            return
        await asyncio.to_thread(power_tool.displays_off)
        lights_out = time.monotonic()
        log.info("screens-off: monitors off posted (SC_MONITORPOWER 2), system held awake; mic listening for a wake phrase")
        reported = lights_out
        while self.dark:
            await asyncio.sleep(0.25)
            idle_s = await asyncio.to_thread(power_tool.idle_ms) / 1000
            if not self.dark:
                # ended meanwhile (a wake phrase) - its own display nudge is not his input
                return
            since_out = time.monotonic() - lights_out
            # his input after the lights went out (not the hotkey's own key-up, not
            # a twitch in the first moment): he is back - Windows has already lit
            # the displays; her mode ends with them
            if since_out > DARK_INPUT_GRACE_S and idle_s < since_out - DARK_INPUT_GRACE_S:
                log.info("screens-off: his mouse/keyboard input %.1f s ago (%.0f s after lights out) - waking", idle_s, since_out)
                await self.exit_dark("mouse/keyboard input")
                return
            if time.monotonic() - reported >= 30:
                reported = time.monotonic()
                log.info("screens-off: still dark %.0f s - last input %.0f s ago, voice %s, HUD %s",
                         since_out, idle_s, "listening" if self.voice.available else "OFF", "connected" if self.bridge.hud_connected else "gone")

    async def exit_dark(self, why: str) -> None:
        """A wake phrase (or any summon) in screens-off mode: the monitors on, her
        tracking back - the summon itself brings her up."""
        if not self.dark:
            return
        self.dark = False
        if self._dark_task and not self._dark_task.done() and self._dark_task is not asyncio.current_task():
            self._dark_task.cancel()
        log.info("screens-off: OFF (%s) after %.0f s - lighting the monitors", why, time.monotonic() - self._dark_since)
        appearing = why in ("a wake phrase", "a summon")
        if appearing:
            # a black surface on every monitor FIRST: whenever a panel comes alive,
            # it shows something - never her boot into a dead screen
            await self.bridge.send({"type": "warmup", "on": True, "onAt": None})
            need = self._dark_monitors
        started = time.monotonic()
        await asyncio.to_thread(power_tool.displays_on)
        await self.bridge.send({"type": "dark", "value": False})
        log.info("screens-off: monitors on posted, system sleep allowed again, HUD told (tracking back)")
        if appearing:
            # Windows says "on" before a monitor shows an image (OLED especially):
            # its word, then the displays have to STAY on - every monitor back on
            # the desktop, nothing changing - for the whole hold, the black surfaces
            # up all along. Any drop or display change starts the hold again.
            watch = power_tool.display_watch()
            lit = await asyncio.to_thread(watch.wait_on, DARK_WAKE_TIMEOUT_S)
            on_at = time.time()
            # the counter runs from Windows' FIRST "on" and is never reset: the
            # first number he can read is the real gap
            await self.bridge.send({"type": "warmup", "on": True, "onAt": on_at * 1000})
            settle = power_tool.wake_delay_s()
            log.info("screens-off: displays %s after %.1f s (at %s) - warm-up surfaces count from there; her boot once they have been "
                     "on %.1f s unbroken with %d monitors. The first counter value he can read = the real gap to an image.",
                     "reported ON" if lit else f"not reported on within {DARK_WAKE_TIMEOUT_S:.0f} s", time.monotonic() - started,
                     time.strftime("%H:%M:%S", time.localtime(on_at)) + f".{int(on_at % 1 * 1000):03d}", settle, need)
            counted_from = time.monotonic()
            restarts = 0
            why_waiting = ""
            while True:
                now = time.monotonic()
                # no watch (or no "on" ever reported): the hold counts from now
                on = watch.is_on() or not watch.working or not lit
                count = power_tool.monitors()
                since_change = now - max(counted_from, watch.changed_at if watch.working else 0.0)
                if on and count >= need and since_change >= settle:
                    break
                waiting = "displays not on" if not on else f"{count}/{need} monitors" if count < need else ""
                if waiting and waiting != why_waiting:
                    restarts += 1
                    log.info("screens-off: hold restarts - %s (%.1f s after the wake)", waiting, now - started)
                why_waiting = waiting
                if waiting:
                    counted_from = now
                if now - started > DARK_WAKE_MAX_HOLD_S:
                    log.warning("screens-off: displays never settled in %.0f s (%s) - her boot starts anyway", DARK_WAKE_MAX_HOLD_S, waiting or "still changing")
                    break
                await asyncio.sleep(0.1)
            log.info("screens-off: hold over %.1f s after the wake, %.1f s after Windows' ON (%d restarts, %d monitors) - her boot starts "
                     "(the warm-up surfaces go as her windows come up)", time.monotonic() - started, time.time() - on_at, restarts, power_tool.monitors())

    async def _watch_loop_lag(self) -> None:
        """The event loop itself held up: everything core sends the HUD (her
        emotions, her mouth, her state) waits behind it, and the face catches up
        in a jump. Every hold-up over LOOP_LAG_LOG_MS goes into core.log."""
        tick = 0.05
        last = time.perf_counter()
        while True:
            await asyncio.sleep(tick)
            now = time.perf_counter()
            lag_ms = (now - last - tick) * 1000
            last = now
            if lag_ms > LOOP_LAG_LOG_MS:
                state = self.bridge.current_state
                log.warning("event loop held up %.0f ms (state %s)", lag_ms, state)

    async def _watchdog(self) -> None:
        """A state that stops changing while she is not speaking is a freeze: the
        HUD shows her waiting, and nothing she hears reaches her. Seen live - a turn
        waited forever on a speaker that had stopped playing. Log what everything
        was doing, then recover to listening."""
        while True:
            await asyncio.sleep(1.0)
            try:
                why = self.stuck()
                if why:
                    await self.recover(why)
            except Exception:
                log.exception("watchdog check failed")

    def stuck(self, now: float | None = None) -> str | None:
        """Why she is frozen, or None. `now`: monotonic seconds (tests)."""
        now = time.monotonic() if now is None else now
        state = self.bridge.current_state
        if state in ("listening", "dormant"):
            return None
        if state == "speaking" and self.speaker is not None and self.speaker.playing():
            # her talking is a sign of life: the quiet is counted from when she
            # stops, not from the state change (live, a research answer was killed
            # the moment a gap between two sentences came, 16 s after "speaking")
            self._progress_at = now
            return None
        quiet = now - max(self.bridge.state_at, self._progress_at)
        # a slow tool, or the model still reading a long prompt (live, Round 8: with VRAM
        # short, a research answer's 12k tokens took 15 s before its first word and was
        # killed as a freeze): alive, only slow
        limit = WATCHDOG_SLOW_TOOL_S if self._tool_running in SLOW_TOOLS or self._prefilling else WATCHDOG_S
        if quiet < limit:
            return None
        return f"state {state!r} unchanged for {quiet:.0f} s" + (" with nothing playing" if state == "speaking" else "")

    def snapshot(self) -> dict:
        """What everything was doing, for the log."""
        turn = self._turn
        speaker = self.speaker
        mic = self.voice.mic
        return {
            "state": self.bridge.current_state,
            "turn": "none" if turn is None else "done" if turn.done() else "running",
            "tool": self._tool_running,
            "entrance": bool(self._entrance and not self._entrance.done()),
            "confirms": len(self._confirms),
            "speaker": None if speaker is None else {
                "queued": len(speaker._fifo), "callback_age_s": round(time.perf_counter() - speaker.callback_at, 1),
                "engine": speaker.engine,
            },
            "voice": {"awake": self.voice.awake, "barge": getattr(mic, "barge", None), "paused": getattr(mic, "paused", None), "speaking": getattr(getattr(mic, "endpointer", None), "speaking", None)},
            "hud": self.bridge.connected,
            "history": len(self.conversation.history),
        }

    async def recover(self, why: str) -> None:
        """Back to listening from wherever she was stuck."""
        import io

        log.error("watchdog: %s - recovering to listening. %s", why, json.dumps(self.snapshot()))
        turn = self._turn
        if turn is not None and not turn.done():
            trace = io.StringIO()
            if hasattr(turn, "print_stack"):
                turn.print_stack(limit=20, file=trace)
            stack = trace.getvalue()
            log.error("watchdog: the stuck turn was at:\n%s", stack)
            turn.cancel()
        if self._entrance and not self._entrance.done():
            self._entrance.cancel()
        for future in self._confirms.values():
            if not future.done():
                future.set_result(False)
        if self.speaker:
            self.speaker.stop()
        self._tool_running = None
        self._progress_at = time.monotonic()
        mic = self.voice.mic
        if mic is not None:
            mic.barge = False
            mic.paused = False
            mic.endpointer.reset()
        self.voice.wake_for(self.voice.follow_up_s)
        for message in ({"type": "entrance", "phase": "end"}, {"type": "summon", "phase": "end"}, {"type": "activity", "value": None}):
            await self.bridge.send(message)
        await self.bridge.emotion("neutral")
        await self.bridge.state("listening")
        await self.bridge.send({"type": "voice", "phase": "listening"})

    async def _warm_llm(self) -> None:
        # warm() never raises; this guard is for anything unforeseen, so a warm-up
        # problem can only ever cost speed, never the backend
        try:
            await self.llm.warm()
        except Exception:
            log.exception("ollama warm-up crashed; continuing without a warm model")

    async def _warm_search(self) -> None:
        """Her SearXNG takes a few seconds to start: do it now, not on the first question."""
        try:
            await research_tool.SEARX.ensure()
        except Exception as error:  # not installed, or it failed: research reports it when used
            log.info("search engine not started: %s", error)

    def say_working(self, lines: list[str] = openers.WORKING) -> None:
        """A pre-rendered "one sec" while a slow tool runs (or `lines`: "On it!" as a
        quick one starts) - instant, never the same twice running; skipped when
        muted or when no takes are cached."""
        speaker = self.speaker
        if self.muted or not speaker or speaker.openers_engine != speaker.engine:
            return
        pool = [t for t in lines if openers.key(t) in speaker.openers and t != self._last_working]
        if not pool:
            return
        self._last_working = random.choice(pool)
        self.working_heard_at = None
        stream = speaker.stream()

        def heard() -> None:
            self.working_heard_at = time.perf_counter()

        stream.feed(self._last_working, on_start=heard)
        stream.close()

    def with_sound(self, speech: np.ndarray, name: str) -> np.ndarray:
        """`speech` with the named sound effect (sfx.py) mixed under its start: the
        sound first, her words ANSWER_SFX_LEAD_S after it."""
        if name not in self._sounds:
            self._sounds[name] = sfx.render(name, np.random.default_rng(3))
        sound = ANSWER_SFX_GAIN * self._sounds[name]
        lead = int(ANSWER_SFX_LEAD_S * sfx.SR)
        out = np.zeros(max(len(sound), lead + len(speech)), np.float32)
        out[: len(sound)] += sound
        out[lead : lead + len(speech)] += speech
        return out

    def cue_sound(self, react: React | None):
        """A cue's little sound effect (config/cues.json sfx), rendered once and kept."""
        name = react.sfx if react else None
        if not name:
            return None
        if name not in self._sounds:
            self._sounds[name] = sfx.render(name, np.random.default_rng(3))
        return self._sounds[name]

    def attached_shows(self, answer: "quick.Answer") -> tuple[list[tuple[float, dict]], React | None]:
        """A line's own cues as a timeline - (seconds after its first sample, message):
        never swapped for "variety", never filtered. The first expression is her face
        for the whole line; the body cues (gestures, scenes) play one after another,
        BIG - full body, not just the face; a later expression changes her face
        midway. A line with no body cue gets one that fits its first feeling, so she
        always moves. Returns the timeline and the last body cue (what the next reply
        must not open on)."""
        names = [n for n in answer.cues if n in cues.BY_NAME]
        faces = [n for n in names if cues.BY_NAME[n]["kind"] == "expression"]
        body = [n for n in names if cues.BY_NAME[n]["kind"] in ("gesture", "scene")]
        if not body:
            body = [ATTACHED_BODY.get(faces[0] if faces else "", "excitedBounce")]
        timeline: list[tuple[float, dict]] = []
        if faces:
            timeline.append((0.0, {"type": "emotion", "value": faces[0]}))
        at = 0.0
        for name in body:
            if cues.BY_NAME.get(name, {}).get("kind") == "scene":
                timeline.append((at, {"type": "activity", "value": name, "loops": 1}))
                at += ATTACHED_SCENE_S
            else:
                timeline.append((at, {"type": "reaction", "value": name, "big": True}))
                at += ATTACHED_GESTURE_S
        for k, name in enumerate(faces[1:], 1):
            timeline.append((min(at, ATTACHED_GESTURE_S * k), {"type": "emotion", "value": name}))
        timeline.sort(key=lambda x: x[0])
        last = body[-1]
        self.last_opening = body[0]
        self.last_react = last
        return timeline, React(last, cues.BY_NAME[last]["kind"], asked=True)

    def react_messages(self, react: React | None, opening: bool = True, text: str = "") -> list[dict]:
        """What to send the HUD for a cue. A reply's opening cue never repeats the one
        the previous reply ended on (unless he asked for it): another that fits `text`
        plays instead. Later cues in a reply are de-duplicated by the stream."""
        name = react.name if react else None
        if opening and name is not None and name == self.last_react and not react.asked:
            # another that fits the same moment if there is one, else one from the
            # words - and not the previous reply's opening either
            avoid = (name, self.last_opening) if self.last_opening else (name,)
            other = [n for n in react.family if n not in avoid]
            react = cues.of_family(tuple(other)) if other else cues.fallback(text, avoid=avoid)
            log.info("reaction %s would repeat the previous reply: %s instead", name, react.name)
            name = react.name
        if opening:
            self.last_opening = name
        self.last_react = name
        if react is None:
            return []
        if react.kind == "gesture":
            return [{"type": "reaction", "value": react.name}]
        if react.kind == "expression":
            return [{"type": "emotion", "value": react.name}]
        return [{"type": "activity", "value": react.name, "loops": 1}]

    async def say(self, text: str, speed: float = 1.0, after: str = "listening", react: React | None = None) -> None:
        """Speak `text` and hold the speaking state until the last sample plays.
        A reaction plays as the first word is heard. Muted, the words still go to the
        transcript and the reaction still shows; only the audio is skipped."""
        assert self.speaker
        loop = asyncio.get_running_loop()
        finished: asyncio.Future[bool] = loop.create_future()
        shows = self.react_messages(react)
        expression = any(m["type"] == "emotion" for m in shows)
        self.voice.heard_her(text)
        await self.bridge.transcript("irene", text)
        if self.muted or not text.strip():
            for message in shows:
                await self.bridge.send(message)
            if expression:
                # no speech to hold it for: keep the face a moment, then settle
                loop.call_later(2.5, lambda: asyncio.ensure_future(self.bridge.emotion("neutral")))
            await self.bridge.state(after)
            return
        await self.bridge.state("speaking")

        def on_start() -> None:
            for message in shows:
                self.bridge.send_threadsafe(message)

        stamp = self.speaker.speak(
            text,
            speed=speed,
            # guarded: a newer summon or turn may have cancelled this one already
            done=lambda ok: loop.call_soon_threadsafe(lambda: finished.done() or finished.set_result(ok)),
            on_start=on_start if shows else None,
        )
        completed = await finished
        if expression and completed:
            await self.bridge.emotion("neutral")
        first = self.speaker.first_audio
        if first:
            log.info("first audio %.0f ms after speak()", (first - stamp) * 1000)
            if getattr(self, "vram", None):
                self.vram.note_first_audio((first - stamp) * 1000)
        # cut off (mute, sleep, newer speech): whoever interrupted owns the state now
        if completed:
            await self.bridge.state(after)

    async def on_speak(self, message: dict) -> None:
        text = str(message.get("text", "")).strip()
        if not text:
            return
        if message.get("source") == "summon":
            if self.skit.active:
                # mid-skit: the skit's own summon beat (or a stray hotkey, ignored) -
                # never a drawn entrance and a greeting over the scene
                self.skit.claim_summon()
                return
            await self.exit_dark("a summon")
            # the hand sign is always the domain expansion; "Irene Adler" the
            # Victorian lady; the hotkey and "Hey Irene" a random one from the pool
            by = message.get("by")
            if by in ("voice", "adler"):
                log.info("summon path 7: the HUD handed the summon back (%s) - the entrance plays", by)
            if by in ("voice", "adler") and self._voice_summon and not self._voice_summon.done():
                self._voice_summon.set_result(True)
            name = entrances.DOMAIN if by == "sign" else "victorian" if by == "adler" else None
            # his wake phrase brings her up with music; the hotkey and the sign don't
            await self.summon_entrance(name, music=by in ("voice", "adler"))
        else:
            await self.say(text)

    async def summon_by_voice(self, adler: bool, timeout: float = 1.5) -> None:
        """A voice wake: the same as ctrl+alt+i. The HUD is asked to summon (the
        window shows even when hidden, the interface flares) and the summon comes
        back here through on_speak like the hotkey's. With no HUD, or no answer in
        time, the entrance plays anyway - she is never silent because a window is."""
        by = "adler" if adler else "voice"
        await self.exit_dark("a wake phrase")
        if not self.bridge.hud_connected:
            # the HUD may still be connecting (just launched, or reloading): wait
            # for it rather than play an entrance with no window
            log.info("summon path 2: no HUD connected yet - waiting up to %.0f s for it", HUD_WAIT_S)
            deadline = time.monotonic() + HUD_WAIT_S
            while not self.bridge.hud_connected and time.monotonic() < deadline:
                await asyncio.sleep(0.1)
        if self.bridge.hud_connected:
            log.info("summon path 2: asking the HUD to summon (by %s)", by)
            self._voice_summon = asyncio.get_running_loop().create_future()
            await self.bridge.send({"type": "summon_request", "by": by})
            try:
                await asyncio.wait_for(asyncio.shield(self._voice_summon), timeout)
                return
            except asyncio.TimeoutError:
                log.warning("summon path STOPPED: the HUD did not hand the summon back in %.1f s - playing it here, the window may not show", timeout)
            finally:
                self._voice_summon = None
        else:
            log.warning("summon path STOPPED at 2: no HUD connected - the entrance plays with no window")
        await self.summon_entrance("victorian" if adler else None, music=True)

    async def summon_entrance(self, name: str | None = None, music: bool = False) -> None:
        """A summon: the named entrance, or a random one (never the last), then the
        listening face - and after it, her greeting."""
        entry = next((e for e in self.entrances if e["name"] == name), None) if name else self.picker.pick()
        if entry is None:
            log.warning("no entrance named %r", name)
            return
        if name:
            # named (the hand sign, "Irene Adler", a dev hook): not a draw - and it
            # counts as the last one played, for the repeat rule
            self.picker.last = entry["name"]
            log.info("summon entrance: %s (named, not drawn)", entry["name"])
        else:
            log.info("summon entrance: %s (drawn: %s)", entry["name"], self.picker.why)
        if self._entrance and not self._entrance.done():
            self._entrance.cancel()
        self.last_entrance = entry["name"]
        # what she was doing goes into her context now: he may talk over the greeting
        self.conversation.entered(entry)
        self._entrance = asyncio.create_task(self.entrance_then_greeting(entry, music))

    def _music_start(self) -> bool:
        """The summon track under the boot: fading in now, dropping away for the
        boot's beat of silence and slamming back on the name. False if there is none."""
        speaker = self.speaker
        track = self.music.audio
        if speaker is None or self.muted or track is None or not hasattr(speaker, "bed"):
            if self.music.cfg.enabled and track is None:
                log.info("summon music: not ready (or no file) - the boot plays without it")
            return False
        cfg = self.music.cfg
        speaker.bed(track, cfg.level, cfg.fade_in_s)
        loop = asyncio.get_running_loop()
        loop.call_later(BOOT_SILENCE_S, speaker.bed_to, cfg.level * MUSIC_SILENCE_LEVEL, 0.15)
        loop.call_later(BOOT_NAME_S, speaker.bed_to, cfg.level, 0.04)
        log.info("summon music: %s under the boot, from %.0f s", cfg.file.name, cfg.start_s)
        return True

    def _music_fade(self, why: str) -> None:
        speaker = self.speaker
        if speaker is not None and getattr(speaker, "bed_playing", False):
            speaker.bed_to(0.0, self.music.cfg.fade_out_s)
            log.info("summon music: fading out over %.1f s (%s)", self.music.cfg.fade_out_s, why)

    async def entrance_then_greeting(self, entry: dict, music: bool = False) -> None:
        """The entrance, then her hello - "Good evening, Mister Tri, how can I help?",
        put a little differently every time, and never the same line twice running."""
        # the boot-up first: frames, labels, cards, readouts (the HUD draws it on show)
        # - and its soundtrack, on the same timeline, through her speaker (so the echo
        # canceller knows it is hers)
        scored = music and self._music_start()
        # his cursor goes for the whole introduction - Windows' and the hand's ring -
        # and comes back with her greeting's last word (HUD: intro_cursor.rs)
        await self.bridge.send({"type": "intro_cursor", "hidden": True})
        try:
            await self._boot_entrance_greeting(entry, scored)
        except asyncio.CancelledError:
            # cut short (he spoke, a command, a new summon): the music goes too
            if scored:
                self._music_fade("summon cut short")
            raise
        finally:
            # (a newer summon took over: its intro keeps the cursor hidden)
            if asyncio.current_task() is self._entrance or self._entrance is None or self._entrance.done():
                await self.bridge.send({"type": "intro_cursor", "hidden": False})

    async def _boot_entrance_greeting(self, entry: dict, scored: bool) -> None:
        await self._boot_only(scored)
        if entry["name"] == entrances.DOMAIN:
            await self.play_summon(entry["line"])
        else:
            await self.play_entrance(self.entrance_clips[entry["name"]], entry["line"])
        ctx = self.greeting_context()
        line = self.greeter.for_entrance(entry, time.localtime().tm_hour, ctx)
        log.info("greeting: %r (%s; noticed: %s)", line, self.greeter.last_kind,
                 ", ".join(o.kind for o in greeting.observations(ctx)) or "nothing")
        # the music goes as she greets him: a slow fade under her hello
        if scored:
            self._music_fade("she greets him")
        await self.say(line, react=cues.fallback(line, avoid=self.last_react))
        self.conversation.greeted(line)

    async def _boot_only(self, scored: bool) -> None:
        """The boot-up's soundtrack and its 12 s (the HUD draws it on show)."""
        if self.speaker is not None and not self.muted:
            if "boot" not in self._sounds:
                self._sounds["boot"] = sfx.render("boot", np.random.default_rng(7))
            sound = self._sounds["boot"]
            # under the music the boot's own sound is the accents only, quieter
            self.speaker.play((BOOT_VOLUME * (0.45 if scored else 1.0)) * sound, np.zeros(len(sound) // 1200 + 1, np.float32))
        self.booting = True
        try:
            await asyncio.sleep(BOOT_S)
        finally:
            self.booting = False
        log.info("boot-up done (%.1f s): the entrance plays", BOOT_S)

    async def play_entrance(self, clip: entrances.Clip, line: str) -> None:
        """An entrance clip with the HUD's animation keyed to it: entrance/start as the
        first sample is heard. Muted, the animation runs on the same clock silently."""
        assert self.speaker
        loop = asyncio.get_running_loop()
        start = {"type": "entrance", "name": clip.name, "phase": "start", "ms": clip.ms}
        self.voice.heard_her(line)
        await self.bridge.transcript("irene", line)
        await self.bridge.state("speaking")
        completed = True
        try:
            if self.muted:
                await self.bridge.send(start)
                await asyncio.sleep(clip.duration)
            else:
                finished: asyncio.Future[bool] = loop.create_future()
                self.speaker.play(
                    clip.audio,
                    clip.levels,
                    marks=[(0.0, lambda: self.bridge.send_threadsafe(start))],
                    done=lambda ok: loop.call_soon_threadsafe(lambda: finished.done() or finished.set_result(ok)),
                )
                completed = await finished
        finally:
            await self.bridge.send({"type": "entrance", "phase": "end"})
        if completed:
            await self.bridge.state("listening")

    async def skip_boot(self) -> None:
        """He spoke during the boot-up: it jumps to its end, and the entrance after
        it is skipped - straight to listening."""
        if not self.booting:
            return
        log.info("boot-up skipped: he spoke")
        await self.bridge.send({"type": "boot_skip"})
        await self.on_summon_skip({})

    async def on_summon_skip(self, _message: dict) -> None:
        """He started typing (or talking) over the entrance: straight to listening."""
        if not (self._entrance and not self._entrance.done()):
            return
        log.info("entrance skipped")
        self._entrance.cancel()
        if self.speaker:
            self.speaker.stop()
        await self.bridge.send({"type": "entrance", "phase": "end"})
        await self.bridge.send({"type": "summon", "phase": "end"})
        await self.bridge.emotion("neutral")
        await self.bridge.state("listening")

    async def on_voice_heard(self, message: dict) -> None:
        """Dev only: act as if the mic heard `text` (Whisper sure of it) - the voice
        path from the wake phrase on, without a room to be noisy in."""
        from .stt import Heard

        heard = Heard(str(message.get("text", "")), -0.1, 0.0, 1.0, 0.0)
        await self.voice.on_heard(heard, np.zeros(16000, np.float32), bool(message.get("awake", False)))

    async def on_hud_perf(self, message: dict) -> None:
        log.info("hud perf: %s", json.dumps({k: v for k, v in message.items() if k != "type"}))

    async def on_visibility(self, message: dict) -> None:
        self.voice.set_visible(bool(message.get("visible")))

    def _research_gone(self, ids: list[str], why: str) -> None:
        """Research removed (tools/research.py clear_all / expire - the sweep runs in
        a worker thread): on the event loop, the conversation and session notes drop
        it, and the panel closes if it is showing one of it."""

        def drop() -> None:
            self.conversation.forget_research(why)
            shown = (self.panel_content or {}).get("research")
            if shown and (why == "cleared" or shown in ids):
                log.info("research %s: the panel was showing %s - closed", why, shown)
                asyncio.ensure_future(self.show_panel(None))

        loop = getattr(self, "loop", None)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not None and running is loop or loop is None:
            drop()
        else:
            loop.call_soon_threadsafe(drop)

    async def on_hud_trace(self, message: dict) -> None:
        step = str(message.get("step", ""))[:200]
        # the board reports what it drew (an illustrated answer); the rest is the summon path
        log.info("hud %s", step) if step.startswith(("board", "panel", "skit")) else log.info("summon path %s", step)

    async def on_voice_replay(self, message: dict) -> None:
        """Dev only: one of his saved voice turns (voice_data/turns/<day>/<id>.wav)
        through the live mic pipeline, as if he had just said it."""
        import soundfile as sf

        name = str(message.get("turn", ""))
        path = (self.voice.data.dir / "turns" / f"{name}.wav").resolve()
        if self.voice.data.dir.resolve() not in path.parents or not path.exists() or self.voice.mic is None:
            log.warning("voice replay refused: %r (mic %s)", name, "on" if self.voice.mic else "off")
            return
        audio, _ = sf.read(path, dtype="float32")
        log.info("voice replay: %s (%.1f s)", name, len(audio) / 16000)
        self.voice.mic.replay(audio)

    async def on_mic_deaf(self, message: dict) -> None:
        """Dev only: the mic stops acting on anything (a live check in a room where a
        video plays - Round 8: its speech barged in and cut her answers off). The
        typed commands of the check still reach her."""
        if self.voice.mic is not None:
            self.voice.mic.deaf = bool(message.get("value"))
            log.info("mic %s (dev)", "deaf" if self.voice.mic.deaf else "listening again")

    async def on_wake(self, message: dict) -> None:
        """Dev only: a wake phrase, as if heard ("Irene", or "Irene Adler" with
        adler: true) - the real voice-summon path, music included, without the mic."""
        await self.summon_by_voice(bool(message.get("adler")))

    async def on_play_entrance(self, message: dict) -> None:
        """Dev only: play one entrance by name, as a summon would."""
        await self.summon_entrance(str(message.get("name", "")) or None)

    async def play_summon(self, text: str) -> None:
        """The produced summon clip, with the HUD's domain-expansion sequence keyed to it:
        summon/start as the clip begins, summon/part2 as "Irene Adler" is heard, then
        summon/end. Muted, the same timeline runs silently so the visuals still play."""
        assert self.speaker and self.summon_clip
        clip = self.summon_clip
        loop = asyncio.get_running_loop()

        def phase(name: str):
            return lambda: self.bridge.send_threadsafe({"type": "summon", "phase": name})

        self.voice.heard_her(text)
        await self.bridge.transcript("irene", text)
        await self.bridge.emotion("happy")
        await self.bridge.state("speaking")
        if self.muted:
            phase("start")()
            await asyncio.sleep(clip.part2_at)
            phase("part2")()
            await asyncio.sleep(clip.duration - clip.part2_at)
            completed = True
        else:
            finished: asyncio.Future[bool] = loop.create_future()
            self.speaker.play(
                clip.audio,
                clip.levels,
                marks=[(0.0, phase("start")), (clip.part2_at, phase("part2"))],
                done=lambda ok: loop.call_soon_threadsafe(lambda: finished.done() or finished.set_result(ok)),
            )
            completed = await finished
        await self.bridge.send({"type": "summon", "phase": "end"})
        if completed:
            await self.bridge.emotion("neutral")
            await self.bridge.state("listening")

    async def on_say_reply(self, message: dict) -> None:
        """Dev only: play a raw model-format reply (<cue>/<speak>/<display>) exactly as a
        streamed one plays - each sentence's cue as that sentence is heard."""
        raw = str(message.get("raw", ""))
        sink = SpeechSink(self, time.perf_counter())
        stream = StreamingReply()
        for line in [*stream.feed(raw), *stream.finish()]:
            sink.line(line)
        reply = parse_reply(raw)
        await sink.finish(dataclasses.replace(reply, react=stream.react or reply.react))

    # ---- typed conversation (the command bar) ----------------------------------

    async def on_listen(self, _message: dict) -> None:
        """The LISTEN button: hear him now, no wake word - or, without a microphone,
        say so and fall back to typing."""
        if not await self.voice.listen_now():
            await self.bridge.send({"type": "voice", "phase": "off"})
            await self.bridge.reaction("noMic")

    async def on_command(self, message: dict) -> None:
        text = str(message.get("text", "")).strip()[:2000]
        if not text:
            return
        if self.skit.active:
            # a take is being filmed: nothing but the script speaks (abort it first)
            log.info("command while skit %s runs - ignored: %r", self.skit.skit.name if self.skit.skit else "?", text[:80])
            return
        # his command (the HUD, the mic) acts for real; a test script's never
        # reaches his apps (tools/sandbox.py). The turn task inherits this.
        sandbox.enter(message.get("_origin"), bool(message.get("real_launch")))
        log.info("command from %s: %s", message.get("_origin", "?"), sandbox.describe())
        if message.get("via") != "voice":
            # typed right after a voice turn, close to what was heard: his correction
            fixed = self.voice.data.correction_for(text, "typed")
            if fixed:
                log.info("correction stored: %r", fixed)
        await self.on_summon_skip({})
        if message.get("retract"):
            # the full transcript of what she began answering early: the early turn goes
            await self.retract_turn(settle=False)
        # a new command cuts off whatever she was still saying or thinking
        self._turn_mark = len(self.conversation.history)
        if self._turn and not self._turn.done():
            self._turn.cancel()
            if self.speaker:
                self.speaker.stop()
            for future in self._confirms.values():
                if not future.done():
                    future.set_result(False)
        keiko_kind = keiko.command(text, self.keiko.active)
        if keiko_kind is not None:
            self._turn = asyncio.create_task(self._respond_keiko(text, keiko_kind))
            return
        kind = self.chess_claims(text)
        if kind is not None:
            if message.get("_origin") in sandbox.HIS:
                self.presence.heard()
            self._turn = asyncio.create_task(self._respond_chess(text, kind))
            return
        answer = self.quick_answer(text)
        # (after the greeting read how long it had been)
        if message.get("_origin") in sandbox.HIS:
            self.presence.heard()
        if answer is not None:
            self._turn = asyncio.create_task(self._respond_quick(text, answer, time.perf_counter()))
            return
        self._turn = asyncio.create_task(self._respond(text))

    async def retract_turn(self, settle: bool = True, why: str = "the full transcript differs") -> None:
        """The reply begun on his first words was premature (the speculative start):
        he was still talking, or the full transcript says otherwise. It stops, and
        it leaves the history as if it had never started."""
        if self._turn and not self._turn.done():
            self._turn.cancel()
        if self.speaker:
            played, queued = self.speaker.progress()
            if queued:
                log.info("speech cut (%s): %.1f of %.1f s played", why, played, queued)
            self.speaker.stop()
        for future in self._confirms.values():
            if not future.done():
                future.set_result(False)
        if self._turn_mark is not None:
            del self.conversation.history[self._turn_mark :]
            self._turn_mark = None
        log.info("early turn retracted (%s)", why)
        if settle:
            await self.bridge.send({"type": "draw", "value": None})
            await self.bridge.emotion("neutral")
            await self.bridge.state("listening")

    def greeting_context(self) -> greeting.Context:
        """What is real right now, for her greeting: the clock, his city's weather
        (the dashboard's reading - not a stale one), the presence log, a timer."""
        from datetime import datetime

        from tools import basic

        from .home import HOME

        seen = self.presence.seen()
        state = self.dashboard.state
        weather = state.get("weather") if not state.get("stale", {}).get("weather") else None
        timer = None
        if basic.ACTIVE:
            t = min(basic.ACTIVE, key=lambda a: a["ends"])
            timer = {"label": t.get("label", ""), "left_s": t["ends"] - time.time()}
        return greeting.Context(
            now=datetime.now(), weather=weather, since_last_s=seen.since_last_s, first_today=seen.first_today,
            usual_hour=seen.usual_hour, topic=seen.topic, topic_at=seen.topic_at, timer=timer,
            city=getattr(HOME, "city", "") or "town",
        )

    def quick_answer(self, text: str) -> quick.Answer | None:
        """Her pre-rendered answer to an everyday exchange, or None for the model.
        Not while a yes/no is pending (her panel offer), and only in the voice
        that is speaking now."""
        if not self.quick.ready or (self.speaker and self.quick.engine != self.speaker.engine):
            return None
        if self.conversation._panel_offer:
            return None
        if self.quick.match(text) in ("greet", "back"):
            # "hi Irene": greeted like someone who has been paying attention - said
            # live (it is about now), when there is something real to say
            avoid = tuple(self.conversation.last_cues) + ((self.last_react,) if self.last_react else ())
            line = self.greeter.considerate(self.greeting_context())
            if line is not None:
                fits = tuple(c for c in ("wave", "happy", "headTilt", "excitedBounce") if c not in avoid)
                log.info("greeting (quick, %s): %r", self.greeter.last_kind, line)
                return quick.Answer("greet", line, fits or ("peace",), False, None)
        return self.quick.answer(
            text,
            time.localtime().tm_hour,
            entrance=self.conversation.recent_entrance(),
            avoid=tuple(self.conversation.last_cues) + ((self.last_react,) if self.last_react else ()),
        )

    async def on_kamae(self, message: dict) -> None:
        """The kamae pose trigger is retired - it fired on everyday arm movements, and
        keiko now starts only when he asks for it (keiko.py). Logged, never acted on."""
        log.info("kamae %s from the HUD - ignored (keiko starts by voice)", message.get("phase"))

    async def _respond_keiko(self, text: str, kind: str) -> None:
        """"Let's do keiko" / "stop": she suits up in the dojo facing him, or bows out."""
        await self.bridge.transcript("user", text)
        if kind == "start":
            if self.chess.active:
                await self.chess.stop()
                stt.context_terms("chess", None)
            answer = self.keiko.start()
            await self.bridge.send({"type": "keiko", "action": "start"})
            if self._keiko_watch is None or self._keiko_watch.done():
                self._keiko_watch = asyncio.create_task(self._keiko_watchdog())
        else:
            answer = self.keiko.stop()
        log.info("keiko %s: %r", kind, answer.line)
        await self._keiko_answer(answer)
        if answer.action == "end":
            await self.bridge.send({"type": "keiko", "action": "end"})
        self.conversation.quick_exchange(text, answer.line, answer.cue)
        await self.bridge.emotion("neutral")
        await self.bridge.state("listening")

    async def on_keiko_strike(self, message: dict) -> None:
        """He struck (the HUD's recogniser): her answer - block, take it (a clean one
        is ippon, with the flags), or strike back. Not kept in the conversation."""
        strike = str(message.get("strike", ""))
        p = float(message.get("p") or 0.0)
        clean = bool(message.get("clean"))
        answer = self.keiko.strike(strike, p, clean)
        log.info("keiko strike %s p=%.2f%s -> %s", strike, p, " clean" if clean else "", answer.action if answer else "ignored (keiko is off)")
        if answer is None:
            return
        if self._turn and not self._turn.done():
            self._turn.cancel()
            if self.speaker:
                self.speaker.stop()
        self._turn = asyncio.create_task(self._keiko_strike_turn(answer))

    async def _keiko_strike_turn(self, answer: "keiko.Answer") -> None:
        message = {"type": "keiko", "action": answer.action}
        if answer.target:
            message["target"] = answer.target
        if answer.flags:
            message["flags"] = answer.flags
        await self.bridge.send(message)
        await self._keiko_answer(answer)
        await self.bridge.emotion("neutral")
        await self.bridge.state("listening")

    async def _keiko_answer(self, answer: "keiko.Answer") -> None:
        """Her sounds (the kiai, the shinai, the flags), then her line with its face."""
        for name in answer.sounds:
            if self.speaker and not self.muted:
                await self._play_sound(name)
        react = cues.resolve(answer.cue) if answer.cue else None
        if self.speaker:
            await self.say(answer.line, react=react, after="speaking")
        else:
            await self.bridge.transcript("irene", answer.line)
            for m in self.react_messages(react, text=answer.line):
                await self.bridge.send(m)
        await self.bridge.send({"type": "reply", "display": "", "speak": answer.line})

    async def _keiko_watchdog(self) -> None:
        """Keiko ends by itself when he stops striking (keiko.IDLE_END_S)."""
        while self.keiko.active:
            await asyncio.sleep(5)
            if self.keiko.expired():
                answer = self.keiko.stop("timeout")
                log.info("keiko timed out: %r", answer.line)
                await self._keiko_answer(answer)
                await self.bridge.send({"type": "keiko", "action": "end"})
                await self.bridge.emotion("neutral")
                await self.bridge.state("listening")

    def idle_board(self) -> dict | None:
        """What the board shows when a reply draws nothing: the chess game if one is on."""
        return self.chess.board_spec() if self.chess.active else None

    def chess_claims(self, text: str) -> str | None:
        """His words as chess: "start" / "stop" / "resign" / "takeback" / "move" - or
        None, for everything else (mid-game too: "you're good at this" is for her,
        not the board). Matched in code; the model never sees a move."""
        kind = chess_game.command(text, self.chess.active, self.chess.finished)
        if kind == "move" and not self.chess.claims(text):
            return None
        return kind

    async def _respond_chess(self, text: str, kind: str) -> None:
        """His chess command or move: the engine's answer, said beat by beat - each
        with its face, its board and the piece's knock. No model call."""
        received = time.perf_counter()
        await self.bridge.transcript("user", text)
        game = self.chess
        try:
            if kind == "start":
                beats = await game.start(text)
            elif kind == "stop":
                beats = await game.stop()
            elif kind == "resign":
                beats = await game.resign()
            elif kind == "takeback":
                beats = await game.takeback()
            else:
                beats = await game.his_move(text)
        except (FileNotFoundError, OSError, chess_game.chess.engine.EngineError) as error:
            log.error("chess engine unavailable: %s", error)
            game.active = False
            beats = [chess_game.Beat("My chess engine isn't set up yet - run setup_stockfish once, and then I'm all yours.", "sheepish", None)]
        stt.context_terms("chess", game.cfg.hotwords if game.active else None)
        if beats is None:
            # not a move after all: hers to answer, the board stays
            await self._respond(text)
            return
        said = [b.text for b in beats if b.text]
        heard_at: float | None = None
        for beat in beats:
            if beat.board is not None:
                await self.bridge.send({"type": "draw", "value": beat.board})
            if beat.sfx and self.speaker and not self.muted:
                await self._play_sound(beat.sfx)
            if not beat.text:
                continue
            react = cues.resolve(beat.cue) if beat.cue else None
            if heard_at is None:
                heard_at = time.perf_counter()
            if self.speaker:
                await self.say(beat.text, react=react, after="speaking")
            else:
                await self.bridge.transcript("irene", beat.text)
                for message in self.react_messages(react, text=beat.text):
                    await self.bridge.send(message)
        await self.bridge.send({"type": "reply", "display": "", "speak": " ".join(said)})
        # in the history like any exchange, so what she said about the game is hers
        last = next((b.cue for b in reversed(beats) if b.cue), None)
        self.conversation.quick_exchange(text, " ".join(said) or "(the board moved)", last)
        log.info("chess %s: %r -> %r (%.0f ms to first words)", kind, text[:60], " | ".join(said)[:200], ((heard_at or received) - received) * 1000)
        if not game.active:
            asyncio.get_running_loop().call_later(6.0, lambda: asyncio.ensure_future(self._chess_board_down()))
        await self.bridge.emotion("neutral")
        await self.bridge.state("listening")

    async def _chess_board_down(self) -> None:
        """A finished game's board, a few seconds after the last word: her face back."""
        if not self.chess.active:
            await self.bridge.send({"type": "draw", "value": None})

    async def _play_sound(self, name: str) -> None:
        """A sound effect on its own, before her words (a piece set down, a shinai)."""
        if name not in self._sounds:
            self._sounds[name] = sfx.render(name, np.random.default_rng(3))
        audio = 0.6 * self._sounds[name]
        loop = asyncio.get_running_loop()
        finished: asyncio.Future[bool] = loop.create_future()
        self.speaker.play(audio, block_levels(audio) * 0, done=lambda ok: loop.call_soon_threadsafe(lambda: finished.done() or finished.set_result(ok)))
        await finished

    async def _respond_quick(self, text: str, answer: quick.Answer, received: float, said: str | None = None) -> None:
        """A quick reply: his words, her pre-rendered line with its cue as it is
        heard, the board cleared - the same as a model reply, minus the model.
        `said`: what goes in the history when he said nothing (kamae)."""
        if text:
            await self.bridge.transcript("user", text)
        if answer.attached:
            # a signature entrance's answer: its own cues, all of them, enforced
            timeline, react = self.attached_shows(answer)
            shows = [m for at, m in timeline if at == 0.0]
            later = [(at, m) for at, m in timeline if at > 0.0]
        else:
            react = cues.of_family(answer.cues, avoid=self.last_react)
            shows = self.react_messages(react, text=answer.text)
            later = []
        self.voice.heard_her(answer.text)
        await self.bridge.send({"type": "draw", "value": self.idle_board()})
        await self.bridge.transcript("irene", answer.text)
        await self.bridge.send({"type": "reply", "display": "", "speak": answer.text})
        # kamae is her body answering his, not something he said: kept out of the
        # conversation (false triggers used to fill it with "[he took kamae]")
        self.conversation.quick_exchange(text or said or "", answer.text, react.name if react else None, answer.ends, record=answer.intent != "kamae")
        heard: dict[str, float] = {}
        completed = True
        if self.muted or not self.speaker:
            for message in shows:
                await self.bridge.send(message)
            for at, message in later:
                asyncio.get_running_loop().call_later(at, self.bridge.send_threadsafe, message)
        else:
            loop = asyncio.get_running_loop()
            finished: asyncio.Future[bool] = loop.create_future()

            def on_start() -> None:
                heard["at"] = time.perf_counter()
                for message in shows:
                    self.bridge.send_threadsafe(message)
                # the rest of the line's cues, in order, as the line goes on
                for at, message in later:
                    loop.call_soon_threadsafe(loop.call_later, at, self.bridge.send_threadsafe, message)

            await self.bridge.state("speaking")
            done = lambda ok: loop.call_soon_threadsafe(lambda: finished.done() or finished.set_result(ok))  # noqa: E731
            if answer.audio is None:
                # not rendered yet (the first minute of a fresh install): said live
                self.speaker.speak(answer.text, done=done, on_start=on_start)
            else:
                audio = answer.audio
                if answer.sfx:
                    # a signature entrance's answer: its sound leads (the kiai, the piece
                    # clack), her line comes in over it - always
                    audio = self.with_sound(audio, answer.sfx)
                self.speaker.play(audio, block_levels(audio), marks=[(0.0, on_start)], done=done)
                log.info("speech queued (quick %s): %r - %.1f s (line %.1f s%s)", answer.intent, answer.text, len(audio) / sfx.SR,
                         len(answer.audio) / sfx.SR, f" + sound {answer.sfx}" if answer.sfx else "")
            if answer.audio is None and answer.sfx:
                # said live (a play() would cut the speech off): the one case its sound
                # can't go under it - only before the quick lines have rendered
                log.warning("doing answer: %r not rendered yet - said live, sound %s skipped", answer.text, answer.sfx)
            played, queued = self.speaker.progress()
            completed = await finished
            if not completed:
                log.warning("speech NOT finished (quick %s): %r was cut off", answer.intent, answer.text)
            else:
                log.info("speech finished (quick %s): all of %r played", answer.intent, answer.text)
        latency = (heard["at"] - received) * 1000 if "at" in heard else None
        self.last_ttfa = latency
        log.info("quick reply (%s) -> first audio %s ms: %r", answer.intent, f"{latency:.0f}" if latency is not None else "-", answer.text)
        if answer.attached:
            log.info("doing answer (%s): cues %s, sound %s", self.last_entrance or "?",
                     " -> ".join(f"{m.get('value')}({m['type']}{', big' if m.get('big') else ''} @{at:.1f}s)" for at, m in [(0.0, m) for m in shows] + later),
                     answer.sfx or "none")
        self.log_quick(text, answer, received, latency)
        if not completed:
            return
        if any(m["type"] == "emotion" for m in shows):
            await self.bridge.emotion("neutral")
        await self.bridge.state("listening")
        if answer.ends:
            await self.bridge.send({"type": "conversation", "event": "ended"})
            self.voice.sleep()

    def log_quick(self, text: str, answer: quick.Answer, received: float, latency: float | None) -> None:
        record = {
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "said": text[:120],
            "quick": answer.intent,
            "tools": [],
            "llm_calls": 0,
            "ttfa_ms": round(latency) if latency is not None else None,
            "turn_ms": round((time.perf_counter() - received) * 1000),
            "voice": self.speaker.engine if self.speaker else None,
            "raw": answer.text,
        }
        if getattr(self, "vram", None):
            self.vram.note_turn(record["prompt_tokens"], record["prefill_ms"])
            self.vram.note_first_audio(record["ttfa_ms"])
        LOGS.mkdir(exist_ok=True)
        with (LOGS / "turns.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    async def _respond(self, text: str) -> None:
        received = time.perf_counter()
        await self.bridge.transcript("user", text)
        host = TurnHost(self, received)
        self.last_ttfa = None
        # a new question, a new board: nothing of the last answer's drawing stays up
        # (a plain command - "pause" - leaves it alone)
        if fast.direct_call(text) is None:
            await self.bridge.send({"type": "draw", "value": self.idle_board()})
        # what is playing on his PC right now, for her context ("pause" acts on it)
        try:
            from tools import media as media_tool

            await asyncio.wait_for(media_tool.refresh_now_playing(), 0.4)
        except Exception:
            pass
        try:
            turn = await self.conversation.respond(text, host)
            self.log_turn(text, turn, received)
            if "research" in turn.tools_used and not sandbox.os_input_blocked():
                # what they were doing, for next time's greeting ("Still on the Sicilian?")
                self.presence.topic(text)
            self.keep_answer(text, turn)
        except asyncio.CancelledError:
            log.info("turn cancelled by a newer command")
            self.conversation.cut_off()
            raise
        except Exception as error:
            log.exception("turn failed")
            await self.bridge.send({"type": "reply", "display": f"Something went wrong: {type(error).__name__}", "speak": ""})
            await self.bridge.emotion("concerned")
            await self.bridge.state("error")
            await asyncio.sleep(2.5)
            await self.bridge.emotion("neutral")
            await self.bridge.state("listening")
            return
        if turn.ended:
            await self.bridge.send({"type": "conversation", "event": "ended"})
            self.voice.sleep()

    def keep_answer(self, text: str, turn) -> None:
        """A reply with detail to read is kept for the panel; a research answer goes
        with its research."""
        display = turn.reply.display.strip()
        if "research" in turn.tools_used:
            research_tool.attach_answer(turn.reply.speak, turn.claims)
            # the details go up by themselves once she has said the summary
            try:
                content, _ = panel_tool.resolve("last research", self.panel_answers)
            except research_tool.ToolError:
                content = None
            if content:
                asyncio.ensure_future(self.show_panel(content))
            return
        if not display or "show_panel" in turn.tools_used:
            return
        title = text.strip().rstrip("?.!")[:80] or "Her answer"
        self.panel_answers.insert(0, {
            "at": time.strftime("%Y%m%d-%H%M%S"),
            "title": title[:1].upper() + title[1:],
            "subtitle": time.strftime("%Y-%m-%d %H:%M"),
            "blocks": panel_tool.text_blocks(display),
        })
        del self.panel_answers[10:]
        # an answer with detail: the detail goes on the panel, not only into words
        asyncio.ensure_future(self.show_panel({k: v for k, v in self.panel_answers[0].items() if k != "at"}))

    def show_order(self, names: list[str]) -> list[React]:
        """The cues to perform: his (or the model's) names resolved, props and
        unknowns dropped; none given -> her own varied pick, the newest cue included."""
        chosen = [r for r in map(cues.resolve, names) if r is not None and r.kind != "prop"]
        if names:
            return chosen[:6]
        rng = random.Random()
        gestures = rng.sample(list(cues.GESTURES), 2)
        faces = rng.sample([e for e in cues.EXPRESSIONS if e != "starryEyed"], 1)
        # the newest cue always gets its moment
        picks = [gestures[0], "starryEyed", gestures[1], faces[0]]
        if rng.random() < 0.5:
            picks.append(rng.choice(list(cues.SCENES)))
        return [r for r in map(cues.resolve, picks) if r is not None]

    async def perform(self, names: list[str]) -> list[str]:
        """A little show: each cue in turn, with its sound, held long enough to read."""
        order = self.show_order(names)
        # the show is her face, not a wait: out of "thinking" (amber, eyes up) for it
        await self.bridge.state("listening")
        for react in order:
            for message in self.react_messages(dataclasses.replace(react, asked=True)):
                await self.bridge.send(message)
            sound = self.cue_sound(react)
            if sound is not None and self.speaker and not self.muted:
                self.speaker.play(0.5 * sound, np.zeros(len(sound) // 1200 + 1, np.float32))
            await asyncio.sleep(PERFORM_HOLD_S.get(react.kind, 1.5))
            if react.kind == "scene":
                await self.bridge.send({"type": "activity", "value": None})
        await self.bridge.emotion("neutral")
        log.info("performed: %s", ", ".join(r.name for r in order))
        return [r.name for r in order]

    async def show_panel(self, content: dict | None) -> None:
        self.panel_links = panel_tool.links_in(content)
        self.panel_content = content
        await self.bridge.panel(content)
        if content is not None:
            self.paper_lands()

    def paper_lands(self) -> None:
        """Her page dealt onto the panel: the paper-settle sound as it touches down
        (Dashboard.css dk-deal-in: contact at half its 1000 ms) - mixed under
        whatever she is saying, through her own speaker (the echo canceller's)."""
        speaker = self.speaker
        if speaker is None or self.muted or self.dark or not hasattr(speaker, "overlay"):
            return
        if "paper" not in self._sounds:
            self._sounds["paper"] = sfx.render("paper", np.random.default_rng(5))
        speaker.overlay(self._sounds["paper"], PAPER_GAIN, PAPER_LAND_S)
        log.info("panel: her page dealt in (paper lands in %.2f s)", PAPER_LAND_S)

    async def on_open_link(self, message: dict) -> None:
        """A link clicked on the panel -> his own Chrome, if the panel really had it."""
        sandbox.enter(message.get("_origin"))
        url = str(message.get("url", ""))
        log.info("panel link clicked (%s): %s", message.get("_origin", "?"), url[:120])
        if url not in self.panel_links:
            log.warning("open_link refused: %r was not on the panel", url[:120])
            await self.bridge.send({"type": "link_opened", "url": url, "ok": False})
            return
        try:
            research_tool.open_normal_chrome(url)
            log.info("panel link opened in his Chrome: %s", url)
            await self.bridge.send({"type": "link_opened", "url": url, "ok": True})
        except research_tool.ToolError as error:
            log.warning("open_link failed: %s", error)
            await self.bridge.send({"type": "link_opened", "url": url, "ok": False})

    def log_turn(self, text: str, turn, received: float) -> None:
        """One line per turn: what it cost and where the time went (logs/turns.jsonl)."""
        calls = turn.calls
        decode = sum(c.get("decode_ms", 0) for c in calls)
        out = sum(c.get("output_tokens", 0) for c in calls)
        record = {
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "said": text[:120],
            "tools": turn.tools_used,
            "llm_calls": len(calls),
            "prompt_tokens": sum(c.get("prompt_tokens", 0) for c in calls),
            "prefill_ms": sum(c.get("prefill_ms", 0) for c in calls),
            "output_tokens": out,
            "tok_s": round(out / (decode / 1000), 1) if decode else 0.0,
            "llm_ms": sum(c.get("total_ms", 0) for c in calls),
            "tool_ms": round(turn.tool_ms),
            "ttfa_ms": round(self.last_ttfa) if self.last_ttfa is not None else None,
            "first_text_ms": round(getattr(self, "last_first_text_ms", 0) or 0),
            "turn_ms": round((time.perf_counter() - received) * 1000),
            "voice": self.speaker.engine if self.speaker else None,
            "calls": calls,
            # the model's own text, to see what it wrote before its first spoken phrase
            "raw": next((m["content"] for m in reversed(self.conversation.history) if m["role"] == "assistant"), "")[:1500],
        }
        LOGS.mkdir(exist_ok=True)
        with (LOGS / "turns.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        log.info(
            "turn: %d call(s), %d prompt tok, prefill %d ms, %d out tok at %.0f tok/s, tools %d ms, first audio %s ms",
            record["llm_calls"], record["prompt_tokens"], record["prefill_ms"], out, record["tok_s"], record["tool_ms"], record["ttfa_ms"],
        )

    async def on_confirm_reply(self, message: dict) -> None:
        future = self._confirms.get(str(message.get("id", "")))
        if future and not future.done():
            future.set_result(bool(message.get("ok")))

    async def on_capture_shield_ack(self, _message: dict) -> None:
        if self._shield and not self._shield.done():
            self._shield.set_result(None)

    async def capture_shield(self, on: bool, timeout: float = 0.7) -> None:
        """Exclude the HUD window from screen capture (or stop excluding it) and wait
        until the HUD says it's done, so a screenshot never catches her overlay."""
        if not self.bridge.connected:
            return
        self._shield = asyncio.get_running_loop().create_future()
        await self.bridge.send({"type": "capture_shield", "on": on})
        try:
            await asyncio.wait_for(self._shield, timeout)
        except asyncio.TimeoutError:
            log.warning("capture shield %s: no ack from the HUD", "on" if on else "off")
        finally:
            self._shield = None

    async def ask_confirm(self, prompt: str, timeout: float = 60.0) -> bool:
        ident = uuid.uuid4().hex[:12]
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._confirms[ident] = future
        await self.bridge.send({"type": "confirm", "id": ident, "prompt": prompt})
        await self.bridge.state("listening")
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            log.info("confirmation timed out: %s", prompt)
            return False
        finally:
            self._confirms.pop(ident, None)
            await self.bridge.send({"type": "confirm_done", "id": ident})

    async def on_mute(self, message: dict) -> None:
        self.muted = bool(message.get("value"))
        if self.muted and self.speaker:
            # cut off mid-word; the interrupted say() leaves the state to us
            self.speaker.stop()
            await self.bridge.state("listening")
            await self.bridge.emotion("neutral")
        await self.bridge.send({"type": "muted", "value": self.muted})
        log.info("tts %s", "muted" if self.muted else "unmuted")

    async def on_calibration(self, message: dict) -> None:
        try:
            path, count = await asyncio.to_thread(calibration.write, message)
        except ValueError as error:
            log.warning("calibration rejected: %s", error)
            return
        log.info("calibration %s/%s rep %s: %d frames -> %s", message.get("profile", "summon"), message.get("pose"), message.get("rep", 0), count, path)

    async def on_sleep(self, _message: dict) -> None:
        if self.speaker:
            self.speaker.stop()
        await self.bridge.send({"type": "draw", "value": None})
        await self.bridge.emotion("neutral")
        await self.bridge.state("dormant")
        log.info("sleep")


class TurnHost:
    """One turn's view of the app, as the conversation sees it (brain.Host)."""

    def __init__(self, core: Core, received: float):
        self.core = core
        self.received = received
        # a slow tool's "let me look that up" plays once a turn
        self.working_said = False

    async def thinking(self) -> None:
        await self.core.bridge.state("thinking")

    async def confirm(self, prompt: str) -> bool:
        answer = await self.core.ask_confirm(prompt)
        # his y/n is a typed command too: time the rest of the turn from it, not
        # from the original request, so latency never counts his reading time
        self.received = time.perf_counter()
        return answer

    async def tool_status(self, name: str, status: str) -> None:
        # a sign of life for the watchdog, and which tool is working
        self.core._progress_at = time.monotonic()
        self.core._tool_running = name if status in ("starting", "running", "confirm") else None
        if status == "starting":
            # the model is still writing the call: a slow tool's "one sec", or a quick
            # one's "On it!", goes now - her first word, before the call is complete
            if not self.working_said and ((name in SLOW_TOOLS and not _ready(name)) or name in fast.TEMPLATES):
                self.working_said = True
                self.core.say_working(openers.ACKS if name in fast.TEMPLATES else openers.WORKING)
            return
        # the tool's prop plays while it runs (tools/: Tool.cue), whatever the model says
        tool = REGISTRY.get(name)
        prop = cues.prop(tool.cue if tool else None)
        await self.core.bridge.send({"type": "tool", "name": name, "status": status, "cue": prop.name if prop else None})
        if status == "running" and name in SLOW_TOOLS and not self.working_said and not _ready(name):
            self.working_said = True
            self.core.say_working()

    def alive(self) -> None:
        """The model is still writing this turn: a sign of life for the watchdog."""
        self.core._progress_at = time.monotonic()
        self.core._prefilling = False

    def prefilling(self, on: bool) -> None:
        """The model has the prompt and is reading it: slow is not frozen."""
        self.core._progress_at = time.monotonic()
        self.core._prefilling = on

    def reply_sink(self) -> "SpeechSink":
        # after her "On it!" / "Let me look that up!", the answer follows it rather
        # than cutting it off
        return SpeechSink(self.core, self.received, follow=self.working_said)

    async def announce(self, text: str) -> None:
        await self.core.say(text)

    def forget(self) -> None:
        self.core.conversation.reset()

    async def capture_shield(self, on: bool) -> None:
        await self.core.capture_shield(on)

    async def show_panel(self, content: dict | None) -> None:
        await self.core.show_panel(content)

    def panel_answers(self) -> list[dict]:
        return self.core.panel_answers

    def panel_content(self) -> dict | None:
        return self.core.panel_content

    async def perform(self, names: list[str]) -> list[str]:
        return await self.core.perform(names)

    async def screens_off(self) -> None:
        await self.core.enter_dark()


def _ready(name: str) -> bool:
    """A slow tool that will answer at once this time (the briefing, from its cache):
    no "one sec" in front of it."""
    if name != "daily_briefing":
        return False
    from tools import briefing as briefing_tool

    return briefing_tool.ready()


class SpeechSink:
    """A streaming reply into speech: the stream opens on the first sentence, each
    sentence's cue plays as that sentence is heard, and finish() waits for the last
    sample before settling the face."""

    def __init__(self, core: Core, received: float, follow: bool = False):
        self.core = core
        self.received = received
        self.follow = follow
        self.loop = asyncio.get_running_loop()
        self.stream: SpeechStream | None = None
        self.finished: asyncio.Future[bool] = self.loop.create_future()
        # every cue message this reply sent (or will send), for settling the face
        self.shows: list[dict] = []
        self.heard_at: float | None = None
        self.cued = False
        self.drew = False
        self.first_text_at: float | None = None
        self.first_text = ""
        # messages sent from sync code; finish() lets them all go out first, in order
        self._sent: list[asyncio.Future] = []
        # the answer's board (illustrate.py), moved on as each sentence is HEARD
        self.feed = illustrate.BoardFeed(self._send_board)
        # every sentence handed to the speech stream, in order (logged at finish)
        self.fed: list[str] = []

    def _send_board(self, message: dict) -> None:
        self.drew = True
        self._sent.append(asyncio.ensure_future(self.core.bridge.send(message)))

    def illustrate(self, plan) -> None:
        """The board for this answer (illustrate.Live), or None: no board."""
        self.feed.start(plan)

    def adopt(self, board) -> None:
        """Her drawing arrived (or the keywords that stand in for it)."""
        self.feed.adopt(board)

    def close_board(self) -> None:
        """No more sentences: what she never named goes up with the last one."""
        self.feed.close()

    def line(self, line: Line) -> None:
        core = self.core
        core.voice.heard_her(line.text)
        cue = line.cue
        if cue is None and not self.cued:
            # every reply shows a cue: none from the model -> one from what she says
            cue = cues.fallback(line.text, avoid=core.last_react)
            log.info("cue fallback: %s for %r", cue.name, line.text[:50])
        # the reply's first cue may not repeat the one the last reply ended on
        shows = core.react_messages(cue, opening=not self.cued, text=line.text) if cue else []
        self.cued = self.cued or cue is not None
        self.shows += shows
        # a grounded research sentence's key terms go on the board as it is heard
        # (her face to the corner) - unless the answer has its own board, which
        # moves on with the sentence instead (illustrate.BoardFeed)
        illustrated = self.feed.plan is not None
        terms = {"type": "board_term", "terms": list(line.terms), "title": line.topic} if line.terms and not illustrated else None
        if terms is not None:
            self.drew = True
        self.feed.line()
        if core.muted or not core.speaker:
            for message in [*shows, *([terms] if terms else [])]:
                self._sent.append(asyncio.ensure_future(core.bridge.send(message)))
            self.feed.heard(line.text, line.terms)
            return
        first = self.stream is None
        if first:
            self.first_text_at = time.perf_counter()
            self.first_text = line.text
            asyncio.ensure_future(core.bridge.state("speaking"))
            self.stream = core.speaker.stream(done=lambda ok: self.loop.call_soon_threadsafe(self._done, ok), keep=self.follow)

        def on_start() -> None:
            if first:
                self.heard_at = time.perf_counter()
            for message in shows:
                core.bridge.send_threadsafe(message)
            if terms is not None:
                core.bridge.send_threadsafe(terms)
            # (the audio thread): the board moves on in the loop, in order
            self.loop.call_soon_threadsafe(self.feed.heard, line.text, line.terms)

        if first:
            # Turbo needs a while for any phrase: a cached "Ooh!"/"Hmm..." goes first
            lead = core.speaker.lead_in(line.text, cue.name if cue else None)
            if lead:
                # her face and the cue's sound go with the lead-in, the moment it's heard
                self.stream.feed(lead, on_start=on_start, sound=core.cue_sound(cue))
                self.stream.feed(line.text, speed=cue.speed if cue else None)
                self.fed += [lead, line.text]
                return
        self.stream.feed(line.text, speed=cue.speed if cue else None, on_start=on_start, sound=core.cue_sound(cue))
        self.fed.append(line.text)

    def _done(self, ok: bool) -> None:
        if not self.finished.done():
            self.finished.set_result(ok)

    def draw(self, found) -> None:
        """The reply's drawing, as soon as it is complete: the board sketches while
        she talks. One that fails the checks is logged and not sent - nothing drawn."""
        if found.spec is None:
            log.warning("draw refused: %s", found.error)
            return
        if drawing.is_spec(found.spec):
            # one of hers that reached here without an answer's board: shown whole
            try:
                board, _ = illustrate.board_for(found.spec, "", None)
            except drawing.SpecError as error:
                log.warning("draw refused: %s", error)
                return
            self._send_board(board.snapshot())
            last = board.finish()
            if last:
                self._send_board(last)
            return
        self.drew = True
        log.info("draw: %s", found.spec.get("template", "shapes"))
        self._sent.append(asyncio.ensure_future(self.core.bridge.send({"type": "draw", "value": found.spec})))

    async def finish(self, reply: Reply) -> None:
        core = self.core
        if not self.drew and reply.draw is not None:
            self.draw(reply.draw)
        if not self.drew:
            # a reply with no drawing takes the board down: her face comes back (a
            # chess game's board stays)
            await core.bridge.send({"type": "draw", "value": core.idle_board()})
        if self._sent:
            await asyncio.gather(*self._sent)
        if not self.cued:
            # nothing was spoken: a display-only reply still shows a cue - its own, or
            # one that fits what it says
            react = reply.react or cues.fallback(reply.display or reply.speak, avoid=core.last_react)
            shows = core.react_messages(react, text=reply.display or reply.speak)
            self.shows += shows
            if not core.muted:
                for message in shows:
                    await core.bridge.send(message)
        await core.bridge.transcript("irene", reply.speak)
        await core.bridge.send({"type": "reply", "display": for_chat(reply.display), "speak": reply.speak})
        completed = True
        if self.stream is not None:
            self.stream.close()
            completed = await self.finished
            played, queued = core.speaker.progress() if core.speaker else (0.0, 0.0)
            spoken = " ".join(self.fed)
            missing = " ".join(reply.speak.split()) != " ".join(spoken.split()) and not " ".join(spoken.split()).endswith(" ".join(reply.speak.split()))
            log.info("speech %s: intended %r | synthesised and queued %d sentence(s) %r | %.1f s queued%s",
                     "finished" if completed else "NOT finished - cut off", reply.speak[:300], len(self.fed), spoken[:300], queued,
                     " | MISMATCH: not everything she meant was queued" if missing and reply.speak.strip() else "")
            ack = core.working_heard_at
            if ack is not None and ack >= self.received:
                # her "On it!" was the first thing he heard
                self.heard_at = min(self.heard_at, ack) if self.heard_at is not None else ack
            if self.heard_at is not None:
                latency = (self.heard_at - self.received) * 1000
                core.last_ttfa = latency
                text_ms = (self.first_text_at - self.received) * 1000 if self.first_text_at else 0
                log.info("command -> first audio %.0f ms (first phrase from the model at %.0f ms: %r)", latency, text_ms, self.first_text)
                core.last_first_text_ms = text_ms
                await core.bridge.send({"type": "latency", "command_to_audio_ms": round(latency)})
        if not completed:
            return  # cut off: whoever interrupted owns the face now
        if any(m["type"] == "emotion" for m in self.shows):
            await core.bridge.emotion("neutral")
        await core.bridge.state("listening")


core = Core()


def log_memory() -> None:
    """RAM and VRAM once everything is loaded: a leak elsewhere (or a stale core)
    shows up here before it starves her."""
    import psutil

    from tools import system

    s = system.read()
    own = psutil.Process().memory_info().rss / 2**30
    log.info(
        "memory at startup: RAM %s GB (%d%%), this core %.1f GB; VRAM %s GB (%s%%)",
        s["ram_gb"], s["ram"], own, s.get("vram_gb", "?"), s.get("vram", "?"),
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await core.start()
    log.info("core up on ws://%s:%d/ws", HOST, PORT)
    log_memory()
    yield
    log.info("core shutting down")
    core.voice.stop()
    await core.llm.close()


app = FastAPI(lifespan=lifespan)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    origin = ws.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        log.warning("rejected websocket from origin %r", origin)
        await ws.close(code=1008)
        return
    await core.bridge.serve(ws)


_FAULT_LOG = None


def main() -> None:
    # a native crash (torch, audio driver) otherwise vanishes without a trace - and
    # into a file, not only its console window (Round 7: core once died silently).
    # Windows also reports first-chance COM errors here (0x8001010e at mic start):
    # those are handled and harmless; a real crash is the LAST trace in the file.
    LOGS.mkdir(exist_ok=True)
    global _FAULT_LOG
    _FAULT_LOG = open(LOGS / "core-faults.log", "a", encoding="utf-8")  # noqa: SIM115 - open for the process's life
    _FAULT_LOG.write(f"\n--- core started {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    _FAULT_LOG.flush()
    faulthandler.enable(file=_FAULT_LOG)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
    # and on disk (local only): a freeze once left nothing to read
    from logging.handlers import RotatingFileHandler

    LOGS.mkdir(exist_ok=True)
    handler = RotatingFileHandler(LOGS / "core.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
