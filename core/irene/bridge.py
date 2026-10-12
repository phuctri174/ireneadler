"""WebSocket bridge to the HUD on 127.0.0.1. One JSON object per message.

core -> HUD
  {"type": "state",       "value": "dormant|listening|thinking|speaking|error"}
  {"type": "emotion",     "value": "neutral|happy|curious|concerned|confused"}
  {"type": "audio_level", "value": 0..1}            ~20 Hz while speaking
  {"type": "reaction",    "value": "<reaction name>"}
  {"type": "panel",       "value": PanelContent | null}
  {"type": "transcript",  "role": "user|irene", "text": "..."}
  {"type": "muted",       "value": true|false}
  {"type": "summon",      "phase": "start|part2|end"}   keyed to the summon clip as heard
  {"type": "activity",    "value": "<scene or prop>" | null, "loops": n}
  {"type": "draw",        "value": {...} | null}   the illustration board: a <draw> spec, or clear it
  {"type": "entrance",    "name": "...", "phase": "start|end", "ms": n}   a summon entrance, as heard

HUD -> core
  {"type": "speak", "text": "...", "source": "summon"}
  {"type": "mute",  "value": true|false}
  {"type": "sleep"}
  {"type": "calibration", "session": "...", "pose": "parallel|crossed", "frames": [...]}
  {"type": "summon_skip"}                            he typed over the entrance
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import WebSocket, WebSocketDisconnect

log = logging.getLogger("irene.bridge")

SEND_TIMEOUT_S = 2.0


class Bridge:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        # last value per sticky channel, replayed to a HUD that (re)connects
        self._sticky: dict[str, dict] = {
            "state": {"type": "state", "value": "dormant"},
            "emotion": {"type": "emotion", "value": "neutral"},
            "muted": {"type": "muted", "value": False},
            "voice": {"type": "voice", "phase": "off"},
            # screens-off mode: a HUD that (re)connects learns it at once - after a
            # core restart mid-dark, a fresh core says "not dark" and tracking resumes
            "dark": {"type": "dark", "value": False},
        }
        self.handlers: dict[str, callable] = {}
        # the clients that said hello as the HUD
        self._huds: set = set()
        # called with every new state value (voice: barge-in while speaking, the
        # follow-up window after)
        self.state_listeners: list = []
        # when the state last changed (monotonic): the watchdog's clock (app.py)
        self.state_at = time.monotonic()

    @property
    def connected(self) -> bool:
        return bool(self._clients)

    @property
    def hud_connected(self) -> bool:
        """His HUD is on the socket - not just any client (a dev script counts for
        connected, and a summon sent to it showed no window)."""
        return bool(self._huds)

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def serve(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        log.info("hud connected (%d)", len(self._clients))
        # who is on this socket: the HUD says so first; anything else (a test
        # script) is a script, and nothing it asks reaches his apps (tools/sandbox.py)
        origin = "script"
        try:
            for message in self._sticky.values():
                await ws.send_text(json.dumps(message))
            while True:
                try:
                    message = json.loads(await ws.receive_text())
                except json.JSONDecodeError:
                    continue
                if message.get("type") == "hello":
                    origin = "hud" if message.get("role") == "hud" else "script"
                    if origin == "hud":
                        self._huds.add(ws)
                    log.info("socket client: %s", origin)
                    continue
                if isinstance(message, dict):
                    message["_origin"] = origin
                handler = self.handlers.get(message.get("type"))
                if handler:
                    asyncio.create_task(handler(message))
                else:
                    log.warning("unhandled message %r", message.get("type"))
        except WebSocketDisconnect:
            pass
        finally:
            self._clients.discard(ws)
            self._huds.discard(ws)
            log.info("hud disconnected (%d)", len(self._clients))

    async def send(self, message: dict) -> None:
        if message["type"] in self._sticky:
            self._sticky[message["type"]] = message
        if message["type"] == "state":
            self.state_at = time.monotonic()
            for listener in self.state_listeners:
                listener(message["value"])
        text = json.dumps(message)
        for ws in list(self._clients):
            try:
                # a HUD that stopped reading must never stall core: everything that
                # talks to it (her state, her face, 20 Hz of mouth levels) would wait
                await asyncio.wait_for(ws.send_text(text), SEND_TIMEOUT_S)
            except Exception as error:
                if isinstance(error, asyncio.TimeoutError):
                    log.error("hud stopped reading - dropped it (it reconnects)")
                self._clients.discard(ws)

    def send_threadsafe(self, message: dict) -> None:
        """For the audio thread: hop onto the event loop and send."""
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self.send(message), self._loop)

    @property
    def current_state(self) -> str:
        return self._sticky["state"]["value"]

    async def state(self, value: str) -> None:
        await self.send({"type": "state", "value": value})

    async def emotion(self, value: str) -> None:
        await self.send({"type": "emotion", "value": value})

    async def reaction(self, value: str) -> None:
        await self.send({"type": "reaction", "value": value})

    async def panel(self, value: dict | None) -> None:
        await self.send({"type": "panel", "value": value})

    async def transcript(self, role: str, text: str) -> None:
        await self.send({"type": "transcript", "role": role, "text": text})
