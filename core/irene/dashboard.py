# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""The second screen: keeps the dashboard's readings fresh and sends them to the HUD.

Each source refreshes on its own clock (config/dashboard.yaml); a source that
fails keeps its last reading, marked stale - nothing is ever made up. The HUD's
dashboard window gets {"type": "dashboard", ...} whenever something changed, and
sends back {"type": "dashboard_open", "url"} for a click (mouse or hand), which
opens in his Chrome only if that link is on the dashboard and the click came
from his HUD (tools/sandbox.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

from tools import basic, sandbox, system
from tools import dashboard as data
from tools import panel as panel_tool
from tools import research as research_tool

if TYPE_CHECKING:
    from .app import Core

log = logging.getLogger("irene.dashboard")
# research cards on the panel (the top card shows the newest three; the centre all)
RESEARCH_KEPT = 6
RESEARCH_THUMB_W = 360
# how often expired research is swept out
RESEARCH_SWEEP_S = 60.0


def _research_thumb(found) -> str:
    """A picture for a research card: the first page's main image, else a page
    screenshot, else a video thumbnail - small, as a data: URI ("" if none: the
    panel draws one)."""
    import base64

    picks = [s.image for s in found.sources] + [s.screenshot for s in found.sources] + [v.thumbnail for v in found.videos]
    for uri in picks:
        if uri and uri.startswith("data:image") and "," in uri:
            try:
                return data._shrink(base64.b64decode(uri.split(",", 1)[1]), width=RESEARCH_THUMB_W)
            except Exception:  # noqa: BLE001 - a broken picture: try the next
                continue
    return ""


def _shrink_uri(uri: str) -> str:
    """A data: picture made small for a card."""
    import base64

    try:
        return data._shrink(base64.b64decode(uri.split(",", 1)[1]), width=RESEARCH_THUMB_W)
    except Exception:  # noqa: BLE001 - no thumbnail: the panel draws one
        return ""


class Dashboard:
    def __init__(self, core: "Core"):
        self.core = core
        self.state: dict = {"news": [], "weather": None, "stocks": [], "system": {}, "timers": [], "research": [], "stale": {}, "lecture": None, "mode": None}
        # the research files the "research" list was read from (re-read when they change)
        self._research_names: list[str] = []
        self._sent = ""
        self._sent_fast = ""
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        data.FOCUS_HOOKS.append(self._focus)

    def _focus(self, section: str, number: int) -> None:
        """He opened an item by voice: its card to the panel's centre, held there."""
        asyncio.ensure_future(self.core.bridge.send({"type": "dashboard_focus", "section": section, "number": number}))

    async def _run(self) -> None:
        cfg = data.config()
        every = {
            "news": float((cfg.get("news") or {}).get("every_s", 900)),
            "weather": float((cfg.get("weather") or {}).get("every_s", 1800)),
            "stocks": float((cfg.get("stocks") or {}).get("every_s", 300)),
            "system": float((cfg.get("system") or {}).get("every_s", 3)),
        }
        due = dict.fromkeys(every, 0.0)
        sweep_at = 0.0
        while True:
            now = time.monotonic()
            for name, when in due.items():
                if now >= when:
                    due[name] = now + every[name]
                    asyncio.create_task(self._refresh(name))
            if now >= sweep_at:
                # research older than a day goes (tools/research.py EXPIRE_S)
                sweep_at = now + RESEARCH_SWEEP_S
                await asyncio.to_thread(research_tool.expire)
            self._research_list()
            self.state["timers"] = [{"label": t["label"], "ends": t["ends"], "total": t["minutes"] * 60} for t in basic.ACTIVE]
            # a lecture being captured: the indicator (how long, how many words)
            lectures = getattr(self.core, "lectures", None)
            self.state["lecture"] = lectures.status() if lectures is not None else None
            await self.push()
            await asyncio.sleep(1.0)

    async def _refresh(self, name: str) -> None:
        try:
            if name == "news":
                value = await data.news()
                if not value:
                    raise RuntimeError("no headlines from any feed")
            elif name == "weather":
                value = await data.weather()
            elif name == "stocks":
                value = await data.stocks()
                if not value:
                    raise RuntimeError("no quotes")
            else:
                value = await asyncio.to_thread(system.read)
            self.state[name] = value
            self.state["stale"].pop(name, None)
            if name in data.SECTIONS:
                data.ITEMS[name] = [value] if isinstance(value, dict) else list(value)
        except Exception as error:  # noqa: BLE001 - the last reading stays up, marked stale
            self.state["stale"][name] = True
            log.info("dashboard %s: kept the last reading (%s: %s)", name, type(error).__name__, error)

    def _research_list(self) -> None:
        """Her last RESEARCH_KEPT researches and lecture notes, newest first, as cards:
        title and time. They are her saved research files and the notes kept with each
        lecture (lecture_note.py) - a lecture note never expires."""
        from . import lecture_note

        store = research_tool.STORE
        names = [p.name for p in reversed(research_tool.live_paths())][:RESEARCH_KEPT]
        notes = sorted(lecture_note.STORE.glob(f"*/{lecture_note.NOTE}"), reverse=True)[:RESEARCH_KEPT] if lecture_note.STORE.exists() else []
        try:
            signature = names + [f"{p.parent.name}:{p.stat().st_mtime_ns}" for p in notes]
        except OSError:
            return  # a note being replaced: next second
        if signature == self._research_names:
            return
        items = []
        for name in names:
            try:
                found = research_tool._load(store / name)
            except Exception:  # noqa: BLE001 - a file being written: next second
                return
            question = " ".join(found.question.split())
            items.append({"id": found.id, "kind": "research", "title": question[:1].upper() + question[1:90], "at": found.at,
                          "sources": len(found.sources), "image": _research_thumb(found)})
        for path in notes:
            note = lecture_note.load(path.parent.name)
            if note is None:
                return
            item = lecture_note.rail_item(note)
            if item["image"]:
                item["image"] = _shrink_uri(item["image"])
            items.append(item)
        items.sort(key=lambda i: i["at"], reverse=True)
        self._research_names = signature
        self.state["research"] = items[:RESEARCH_KEPT]

    async def recall(self, message: dict) -> None:
        """A research card clicked: that research (or lecture note) back on the panel's
        centre stage."""
        rid = str(message.get("id", ""))
        if rid.startswith("lecture:"):
            from . import lecture_note

            # only a note that is on the panel's list
            note = lecture_note.load(rid.split(":", 1)[1]) if any(i.get("id") == rid for i in self.state["research"]) else None
            if note is None:
                log.warning("lecture note recall refused: %r is not on the panel", rid)
                return
            log.info("lecture note recalled to the panel: %s (%s)", note.title, note.id)
            await self.core.show_panel(lecture_note.content(note))
            return
        path = research_tool.STORE / f"{rid}.json"
        # only one of the cards on the panel (its id is a file name there)
        if f"{rid}.json" not in self._research_names or not path.exists():
            log.warning("research recall refused: %r is not on the panel", rid)
            return
        found = research_tool._load(path)
        log.info("research recalled to the panel: %s (%s)", found.question[:80], rid)
        await self.core.show_panel(panel_tool.research_content(found))

    async def push(self, force: bool = False) -> None:
        """What changed, to the HUD: the slow parts (news with its pictures, weather,
        quotes) only when they change; the fast ones (load, timers) on their own -
        the HUD merges both."""
        bridge = self.core.bridge
        if not bridge.hud_connected:
            self._sent = self._sent_fast = ""
            return
        fast_keys = ("system", "timers", "lecture", "mode")
        slow = {k: v for k, v in self.state.items() if k not in fast_keys}
        fast = {k: self.state[k] for k in fast_keys}
        body = json.dumps(slow, sort_keys=True, default=str)
        fast_body = json.dumps(fast, sort_keys=True, default=str)
        if body != self._sent or force:
            self._sent, self._sent_fast = body, fast_body
            await bridge.send({"type": "dashboard", **self.state})
        elif fast_body != self._sent_fast:
            self._sent_fast = fast_body
            await bridge.send({"type": "dashboard", **fast})

    async def on_open(self, message: dict) -> None:
        """A dashboard item clicked (mouse or hand) -> his Chrome, if it is on it."""
        from tools.browser import open_in_his_chrome

        sandbox.enter(message.get("_origin"))
        url = str(message.get("url", ""))
        how = message.get("how", "mouse")
        log.info("dashboard item clicked (%s, %s): %s", how, message.get("_origin", "?"), url[:120])
        if not data.allowed(url):
            log.warning("dashboard_open refused: %r is not on the dashboard", url[:120])
            return
        try:
            open_in_his_chrome(url)
        except Exception:
            log.exception("dashboard_open failed")
