# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""The VRAM spill guard: notice when her model has spilled out of VRAM and recover by
reloading it - so he never has to notice slow first words and restart Ollama.

What spill looks like (memory: slow-replies-are-vram-spill): other apps grow while
the model is loaded, part of it is pushed into system RAM, and everything on the GPU
slows - prefill drops to ~500-600 tok/s (from 2000+), her first audio goes from
~0.9 s to 3-4 s. Three signals, any of which starts a check:

  - Ollama's /api/ps: the model's size_vram below its size - spilled, directly
  - a turn's prefill: a real prompt evaluated far below normal speed
  - first audio: a spoken line taking far longer than normal to start

Recovery waits until she is idle (no turn, no summon, not speaking), unloads the
model (keep_alive 0), loads it again pinned (llm.warm), and checks /api/ps again.
A cooldown stops it reloading in a loop when VRAM is genuinely full (it says so in
the log: then something else is holding the GPU).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger("irene.vram")

# the pause between unload and reload (tests replace it)
RELOAD_PAUSE_S = 1.5

# a model this much short of fully in VRAM has spilled
SPILL_FRACTION = 0.97
# a prefill this slow, on a prompt this long, is the spill signature (healthy: 2000+)
SLOW_PREFILL_TOK_S = 900
MIN_PREFILL_TOKENS = 400
# first audio this slow (healthy ~0.9 s; spilled 3-4 s)
SLOW_FIRST_AUDIO_MS = 2200
# how often to look anyway, and how long after a reload before trying another
CHECK_EVERY_S = 60
COOLDOWN_S = 300
# how often to look again while she is busy
IDLE_POLL_S = 1.0
# when a reload did not fix it: VRAM is genuinely full - don't keep reloading
GIVE_UP_S = 900


@dataclass
class Placement:
    size: int
    size_vram: int

    @property
    def in_vram(self) -> float:
        return self.size_vram / self.size if self.size else 1.0

    @property
    def spilled(self) -> bool:
        return self.in_vram < SPILL_FRACTION


class VramGuard:
    def __init__(self, llm, idle: Callable[[], bool], clock: Callable[[], float] = time.monotonic):
        self.llm = llm
        self.idle = idle
        self.clock = clock
        self.suspect: str | None = None
        self.next_allowed = 0.0
        self.recoveries = 0
        # set while the model is out of VRAM on purpose (a lecture capture, lecture.py):
        # "not loaded" is then the plan, not a fault to repair
        self.parked: str | None = None
        self._wake = asyncio.Event()

    # ---- the signals ------------------------------------------------------------

    def note_turn(self, prompt_tokens: int, prefill_ms: float) -> None:
        if prompt_tokens < MIN_PREFILL_TOKENS or prefill_ms <= 0:
            return
        rate = prompt_tokens / (prefill_ms / 1000)
        if rate < SLOW_PREFILL_TOK_S:
            self._suspect(f"prefill {rate:.0f} tok/s on {prompt_tokens} tokens")

    def note_first_audio(self, ms: float | None) -> None:
        if ms is not None and ms > SLOW_FIRST_AUDIO_MS:
            self._suspect(f"first audio {ms:.0f} ms")

    def _suspect(self, why: str) -> None:
        log.warning("vram: suspect a spill (%s) - checking when she is idle", why)
        self.suspect = why
        self._wake.set()

    # ---- the check and the recovery ------------------------------------------------

    async def check(self) -> bool:
        """Look, and reload if spilled (or suspected and the model isn't fully in VRAM,
        or not loaded at all). Returns whether it reloaded."""
        if self.parked:
            self.suspect = None
            log.debug("vram: model parked (%s) - not checking", self.parked)
            return False
        placement = await self.llm.placement()
        why = self.suspect
        self.suspect = None
        if placement is None:
            log.warning("vram: %s is not loaded%s - loading it", self.llm.model, f" ({why})" if why else "")
            await self.llm.warm()
            return True
        if not placement.spilled:
            if why:
                log.info("vram: %s fully in VRAM (%.0f%%) - the slowness (%s) was something else", self.llm.model, placement.in_vram * 100, why)
            return False
        if self.clock() < self.next_allowed:
            log.info("vram: still spilled (%.0f%% in VRAM) - in cooldown, not reloading yet", placement.in_vram * 100)
            return False
        log.warning("vram: SPILL - %s only %.0f%% in VRAM (%s) - reloading it", self.llm.model, placement.in_vram * 100, why or "found by the periodic check")
        started = self.clock()
        await self.llm.unload()
        await asyncio.sleep(RELOAD_PAUSE_S)
        await self.llm.warm()
        after = await self.llm.placement()
        self.recoveries += 1
        took = self.clock() - started
        if after is not None and not after.spilled:
            log.info("vram: recovered - %s %.0f%% in VRAM after a %.1f s reload", self.llm.model, after.in_vram * 100, took)
            self.next_allowed = self.clock() + COOLDOWN_S
        else:
            share = f"{after.in_vram * 100:.0f}%" if after else "not loaded"
            log.error("vram: reload did not fix it (%s in VRAM) - something else is holding the GPU; not retrying for %d min", share, GIVE_UP_S // 60)
            self.next_allowed = self.clock() + GIVE_UP_S
        return True

    async def run(self) -> None:
        """Forever: on a suspicion (at once) or every CHECK_EVERY_S, check while idle."""
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), CHECK_EVERY_S)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            # never in the middle of something: a reload takes the model away for seconds
            while not self.idle():
                await asyncio.sleep(IDLE_POLL_S)
            try:
                await self.check()
            except Exception:
                log.exception("vram: check failed")
