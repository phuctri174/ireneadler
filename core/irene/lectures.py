# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Lecture capture, run by core: start/stop (voice, tool or hotkey), the language
model parked out of VRAM while it listens, the PC kept awake, the indicator, the
summary and its follow-ups. The capture itself is lecture.py; the summary
lecture_summary.py.

The model and the lecture never compete for the GPU: Whisper (shared with his mic)
is all a lecture needs, so gemma leaves VRAM when a capture starts. If he asks her
something meanwhile, Ollama loads it for that turn (a cold start, ~10 s) and it
leaves again after reload_idle_s of quiet. It comes back when the capture stops -
the summary is usually the next thing he asks for.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from tools import lecture as lecture_tool
from tools import power as power_tool
from tools.registry import ToolError

from . import lecture, lecture_board, lecture_note, lecture_research, lecture_summary, recall
from .lecture import LectureCapture, clock

if TYPE_CHECKING:
    from .app import Core

log = logging.getLogger("irene.lecture")

PARK_CHECK_S = 30.0


class Lectures:
    def __init__(self, core: "Core"):
        self.core = core
        self.capture = LectureCapture(lambda: core.voice.stt, on_change=self._changed)
        self._park_task: asyncio.Task | None = None
        self._tapped = False
        # the summary just given (follow-ups: "more on the second topic")
        self.last: tuple[Path, lecture_summary.Summary] | None = None
        # its note (lecture_note.py), and the PDF being printed for it
        self.note: lecture_note.Note | None = None
        # the summary's board, for the reply that speaks it (brain: canned_board)
        self.board: lecture_board.TopicBoards | None = None
        self._pdf_task: asyncio.Future | None = None
        self.last_turn_at = time.monotonic()
        lecture_tool.LECTURES = self

    # ---- start / stop -----------------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self.capture.active

    def status(self) -> dict | None:
        return self.capture.status()

    async def start(self, origin: str = "", device: str | None = None) -> str:
        if self.active:
            st = self.status() or {}
            return f"already listening - {clock(st.get('seconds', 0))} so far, {st.get('words', 0)} words"
        self._tap()
        session = await asyncio.to_thread(self.capture.start, device)
        freed = await self._hold()
        log.info("lecture: started (%s) - session %s%s", origin or "?", session.id, f", {freed / 1e9:.1f} GB of VRAM freed" if freed else "")
        return ("listening to the system audio now and writing the transcript as it goes (text only, no audio kept); "
                "say 'stop listening' when it's over, then ask for the summary")

    def _tap(self) -> None:
        speaker = self.core.speaker
        if speaker is not None and not self._tapped:
            # her own voice through the same speakers is not the lecture
            speaker.taps.append(self.capture.her.tap)
            self._tapped = True

    async def _hold(self) -> int:
        """While a capture runs: the PC awake, gemma out of VRAM (and kept out)."""
        power_tool.stay_awake("lecture", True)
        freed = await self._park()
        self._park_task = asyncio.create_task(self._keep_parked())
        return freed

    async def resume_interrupted(self) -> bool:
        """At startup: a capture that was running when core died (a crash, a kill) is
        picked up again - same session, same transcript - with the gap recorded."""
        found = await asyncio.to_thread(self.capture.interrupted)
        if found is None:
            return False
        session, quiet = found
        self._tap()
        await asyncio.to_thread(self.capture.resume, session)
        await self._hold()
        log.warning("lecture: resumed %s after core restarted (%.0f s since it last wrote)", session.id, quiet)
        return True

    async def stop(self, origin: str = "") -> str:
        if not self.active:
            return "not listening to anything right now"
        if self._park_task is not None:
            self._park_task.cancel()
            self._park_task = None
        session = await asyncio.to_thread(self.capture.stop)
        power_tool.stay_awake("lecture", False)
        await self._unpark()
        if session is None:
            return "not listening to anything right now"
        log.info("lecture: stopped (%s) - %s", origin or "?", session.id)
        if not session.words:
            return f"stopped after {clock(session.seconds)} - but I didn't catch any speech in it, so there's nothing to summarise"
        return f"stopped: {clock(session.seconds)} listened, {session.words:,} words in the transcript; ready to summarise when he asks"

    async def toggle(self, origin: str = "hotkey") -> None:
        """Ctrl+Alt+Shift+L: start or stop, and say so briefly."""
        from .react import resolve

        result = await (self.stop(origin) if self.active else self.start(origin))
        if self.active:
            await self.core.say("Listening. I'll write it all down.", react=resolve("takeNotes"))
        elif result.startswith("stopped:"):
            await self.core.say("Stopped listening. Ask me for the summary whenever you like.", react=resolve("headTilt"))
        else:
            await self.core.say(result[:1].upper() + result[1:] + ".", react=resolve("shrug"))

    def _changed(self) -> None:
        dash = getattr(self.core, "dashboard", None)
        if dash is not None:
            dash.state["lecture"] = self.status()

    # ---- the model out of VRAM while listening -------------------------------------------------

    async def _park(self) -> int:
        """gemma out of VRAM; returns the bytes it held there (0 if it wasn't loaded)."""
        if not bool(self.capture.config.get("unload_llm", True)):
            return 0
        llm = self.core.llm
        placement = await llm.placement()
        vram = getattr(self.core, "vram", None)
        if vram is not None:
            vram.parked = "lecture"
        llm.parked = True
        if placement is None:
            return 0
        await llm.unload()
        log.info("lecture: %s unloaded for the capture - %.2f GB of VRAM freed", llm.model, placement.size_vram / 1e9)
        return placement.size_vram

    async def _unpark(self) -> None:
        vram = getattr(self.core, "vram", None)
        if vram is not None:
            vram.parked = None
        self.core.llm.parked = False
        if bool(self.capture.config.get("unload_llm", True)):
            started = time.perf_counter()
            if await self.core.llm.warm():
                log.info("lecture: %s back in VRAM in %.1f s", self.core.llm.model, time.perf_counter() - started)

    def note_turn(self) -> None:
        self.last_turn_at = time.monotonic()

    async def _keep_parked(self) -> None:
        """A question during the capture loads the model (Ollama does it for that turn);
        after reload_idle_s of quiet it leaves VRAM again."""
        idle_s = float(self.capture.config.get("reload_idle_s", 120))
        while self.active:
            await asyncio.sleep(PARK_CHECK_S)
            if not self.active or not bool(self.capture.config.get("unload_llm", True)):
                continue
            if time.monotonic() - self.last_turn_at < idle_s or not self.core._idle_for_reload():
                continue
            placement = await self.core.llm.placement()
            if placement is not None:
                await self.core.llm.unload()
                log.info("lecture: model loaded for a question during the capture - parked again (%.2f GB freed)", placement.size_vram / 1e9)

    # ---- the summary and follow-ups ---------------------------------------------------------------

    def _latest(self) -> Path:
        found = lecture.sessions()
        if not found:
            raise ToolError("no lecture has been captured yet - he can start one by asking you to listen to it")
        return found[-1]

    async def _chat(self, messages: list[dict]) -> str:
        # each finished part of the map-reduce is a sign of life for the turn watchdog
        # (live: a summary was cancelled as "stuck" 15 s into its first call)
        self.core._progress_at = time.monotonic()
        out = await self.core.llm.chat(messages, temperature=0.2, json_mode=True)
        self.core._progress_at = time.monotonic()
        return out

    async def summary(self, ctx, expand: str = "") -> str:
        if expand:
            if self.last is None:
                raise ToolError("no lecture summary given yet - summarise it first")
            path, s = self.last
            n = lecture_summary.which_section(expand, s)
            if n is None:
                raise ToolError(f"the summary has {len(s.sections)} sections - which one? (a number or its title)")
            _meta, lines = lecture.load(path)
            return lecture_summary.expand(s, lines, n)
        path = self._latest()
        meta, lines = await asyncio.to_thread(lecture.load, path)
        if not lines:
            raise ToolError("the last lecture's transcript is empty - nothing was heard")
        still = self.active and self.capture.session is not None and self.capture.session.dir == path
        s = await lecture_summary.summarize(lines, meta, self._chat, int(self.capture.config.get("map_window_words", 1800) or 1800))
        await asyncio.to_thread((path / "summary.json").write_text, json.dumps(s.to_json(), indent=1, ensure_ascii=False), "utf-8")
        # kept in her long-term memory too ("what was in Monday's lecture?" next week)
        recall.remember_lecture(recall.lecture_title(s.to_json(), meta), recall.lecture_text(s.to_json()), at=(meta or {}).get("started"))
        self.last = (path, s)
        plan = lecture_summary.speech_plan(s)
        self.spoken = [sentence for sentence, _ in plan]
        # the summary as a document he keeps (lecture_note.py): on the panel now, in the
        # research list, and as a PDF next to the lecture - printed off the turn
        note = lecture_note.build(s, lines, {**(meta or {}), "id": (meta or {}).get("id") or path.name})
        # her board for each topic (lecture_board.py), drawn as she reaches it - and the
        # same drawings, rendered by the HUD, under their topics in the note
        self.board = None
        try:
            await self._boards(note, lines, plan)
        except Exception:  # noqa: BLE001 - a summary without drawings is still a summary
            log.exception("lecture board: the drawings failed - the note goes without them")
        await asyncio.to_thread(lecture_note.save, note)
        self.note = note
        await ctx.show_panel(lecture_note.content(note))
        self._pdf_soon(note)
        note = "\n(It is still listening - this summary is of the lecture so far.)" if still else ""
        return lecture_summary.result_text(s) + note

    async def _boards(self, note, lines: list[dict], plan) -> None:
        plans = await lecture_board.compose(note.sections, lines, self._chat)
        topics = [lecture_board.drawn_for(sec, p) for sec, p in zip(note.sections, plans)]
        bridge = self.core.bridge
        for sec, p, drawn in zip(note.sections, plans, topics):
            sec["board"] = {"layout": p.get("layout") or "outline", "dropped": p.get("dropped", [])}
            image = await lecture_board.RENDERS.render(bridge, drawn)
            if image:
                sec["image"] = image
        drawn_n = sum(1 for sec in note.sections if sec.get("image"))
        log.info("lecture board: %d of %d topic drawing(s) rendered for the note", drawn_n, len(note.sections))
        self.board = lecture_board.TopicBoards(lecture_board.overview(note.sections, note.title), topics, plan)

    async def research(self, ctx, topic: str = "") -> str:
        """Further reading on a topic of the last lecture note, on his word only
        (lecture_research.py): kept in the note's own researched section."""
        from tools import research as research_tool

        note = self.note or next(iter(lecture_note.saved()), None)
        if note is None:
            raise ToolError("there's no lecture note yet - summarise a lecture first")
        ks = lecture_research.which(note, topic)
        if not ks:
            raise ToolError(f"the note has {len(note.sections)} topics - which one? (a number or its title)")

        async def chat(messages: list[dict]) -> str:
            self.core._progress_at = time.monotonic()
            out = await self.core.llm.chat(messages, temperature=0.3)
            self.core._progress_at = time.monotonic()
            return out

        added = []
        for k in ks:
            found = await lecture_research.research_topic(note, k, topic, chat, research_tool.run_research)
            self.core._progress_at = time.monotonic()
            if found is None:
                continue
            note.research = [r for r in note.research if not (r.get("section") == k and r.get("concept") == found["concept"])] + [found]
            added.append(found)
        if not added:
            return f"researched {', '.join(note.sections[k - 1]['title'] for k in ks)} - but nothing the pages said could be kept with a source; nothing added to the note"
        await asyncio.to_thread(lecture_note.save, note)
        self.note = note
        await ctx.show_panel(lecture_note.content(note))
        self._pdf_soon(note)
        lines = [f"- {r['concept']}: " + " ".join(i["text"] for i in r["items"][:2]) + f" (from {', '.join(sorted({i['site'] for i in r['items']}))})" for r in added]
        return "added to the lecture note, in its own section marked as researched online (not from the lecture):\n" + "\n".join(lines)

    def _pdf_soon(self, note) -> None:
        """Print the note's PDF in the background (her browser takes a few seconds)."""

        async def run() -> None:
            try:
                await lecture_note.write_pdf(note)
            except Exception:  # noqa: BLE001 - a PDF that failed is logged, the note stands
                log.exception("lecture note: the PDF couldn't be written")

        self._pdf_task = asyncio.ensure_future(run())

    async def ask(self, question: str) -> str:
        path = self.last[0] if self.last else self._latest()
        _meta, lines = await asyncio.to_thread(lecture.load, path)
        found = lecture_summary.retrieve(lines, question)
        log.info("lecture ask %r: %d passage(s) at %s", question[:80], len(found), ", ".join(clock(p["t"]) for p in found) or "-")
        return lecture_summary.ask_text(question, found)
