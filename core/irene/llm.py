# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Ollama client. Local only: 127.0.0.1:11434.

keep_alive=-1 on every request pins the model in VRAM. Ollama's default unloads it
after 5 idle minutes and the next call then pays a ~13 s cold load.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

import httpx

log = logging.getLogger("irene.llm")

OLLAMA = "http://127.0.0.1:11434"
MODEL = "gemma3:12b"
KEEP_ALIVE = -1
# Ollama defaults to a 4096-token context and silently drops the start of anything
# longer - here, the system prompt (~3.9k tokens: persona, reply format, tools)
# went first, and multi-turn replies lost their format and invented actions.
NUM_CTX = 16384
# Ollama may still be starting, or paging a pinned model back into VRAM after
# Windows evicted it under memory pressure; give it a few chances
WARM_RETRY_S = (2, 5, 10)


def stats(done: dict) -> dict:
    """Ollama's final-chunk counters, in ms. prompt_tokens counts only the tokens it
    had to evaluate: whatever matched its cache of the previous prompt is not in it."""
    ms = lambda key: round(done.get(key, 0) / 1e6)  # noqa: E731 - Ollama reports ns
    decode = ms("eval_duration")
    out = done.get("eval_count", 0)
    return {
        "prompt_tokens": done.get("prompt_eval_count", 0),
        "prefill_ms": ms("prompt_eval_duration"),
        "output_tokens": out,
        "decode_ms": decode,
        "tok_s": round(out / (decode / 1000), 1) if decode else 0.0,
        "load_ms": ms("load_duration"),
        "total_ms": ms("total_duration"),
    }


class Ollama:
    def __init__(self, model: str = MODEL):
        self.model = model
        # Ollama's own counters for the last streamed call (see stats())
        self.last: dict = {}
        self._client = httpx.AsyncClient(base_url=OLLAMA, timeout=180)
        # out of VRAM on purpose (a lecture capture): background warm-ups wait - only
        # a real request (his turn, the summary) may load it
        self.parked = False
        # thinking models (gemma4, qwen3) answer far slower with it on; gemma3 has no
        # thinking mode and rejects the flag outright
        self._think = {} if model.startswith("gemma3") else {"think": False}

    async def chat(self, messages: list[dict], temperature: float = 0.6, json_mode: bool = False) -> str:
        """json_mode: Ollama constrains the output to valid JSON (live, gemma closed
        brackets in the wrong order often enough to lose a lecture summary's parts)."""
        r = await self._client.post(
            "/api/chat",
            json={
                "model": self.model,
                "messages": messages,
                "stream": False,
                "keep_alive": KEEP_ALIVE,
                "options": {"temperature": temperature, "num_ctx": NUM_CTX},
                **({"format": "json"} if json_mode else {}),
                **self._think,
            },
        )
        r.raise_for_status()
        return r.json()["message"]["content"]

    async def chat_stream(self, messages: list[dict], temperature: float = 0.6) -> AsyncIterator[str]:
        """Yield the reply's text as it is generated."""
        body = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "keep_alive": KEEP_ALIVE,
            "options": {"temperature": temperature, "num_ctx": NUM_CTX},
            **self._think,
        }
        async with self._client.stream("POST", "/api/chat", json=body) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    raise httpx.HTTPError(chunk["error"])
                text = chunk.get("message", {}).get("content", "")
                if text:
                    yield text
                if chunk.get("done"):
                    self.last = stats(chunk)
                    return

    async def prefill(self, messages: list[dict]) -> None:
        """Read `messages` into Ollama's cache and stop (brain.Conversation.warm_cache).
        Cancelling it closes the request; Ollama keeps what it had read."""
        if self.parked:
            return
        try:
            r = await self._client.post(
                "/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "keep_alive": KEEP_ALIVE,
                    "options": {"num_ctx": NUM_CTX, "num_predict": 1},
                    **self._think,
                },
            )
            r.raise_for_status()
            log.debug("cache warmed: %s", stats(r.json()))
        except httpx.HTTPError as error:
            log.info("cache warm-up failed (only speed is lost): %s", error)

    async def warm(self) -> bool:
        """Load the model now, pinned, so the first real command doesn't pay for it.

        Never raises: a cold model is slower, not fatal. Returns whether it loaded.
        """
        attempts = len(WARM_RETRY_S) + 1
        for attempt in range(1, attempts + 1):
            try:
                r = await self._client.post(
                    # same num_ctx as real requests, or the first one reloads the model
            "/api/generate", json={"model": self.model, "keep_alive": KEEP_ALIVE, "options": {"num_ctx": NUM_CTX}}
                )
                r.raise_for_status()
                log.info("model %s loaded (keep_alive=%s)", self.model, KEEP_ALIVE)
                return True
            except httpx.HTTPError as error:
                reason = f"{type(error).__name__}: {error}".rstrip(": ")
                if attempt == attempts:
                    log.error("ollama warm-up failed after %d tries (%s); running without a warm model", attempts, reason)
                    return False
                delay = WARM_RETRY_S[attempt - 1]
                log.warning("ollama not ready (%s); retry %d/%d in %ds", reason, attempt, attempts - 1, delay)
                await asyncio.sleep(delay)
        return False

    async def placement(self):
        """Where the model sits (Ollama /api/ps): its size and how much of it is in
        VRAM - or None when it is not loaded. Never raises (None on any error)."""
        from .vram import Placement

        try:
            r = await self._client.get("/api/ps", timeout=5)
            r.raise_for_status()
            for m in r.json().get("models", []):
                if m.get("name") == self.model or m.get("model") == self.model:
                    return Placement(int(m.get("size", 0)), int(m.get("size_vram", 0)))
        except (httpx.HTTPError, ValueError) as error:
            log.info("ollama /api/ps failed: %s", error)
        return None

    async def unload(self) -> None:
        """Drop the model from memory now (keep_alive 0), so warm() loads it fresh."""
        try:
            r = await self._client.post("/api/generate", json={"model": self.model, "keep_alive": 0}, timeout=30)
            r.raise_for_status()
            log.info("model %s unloaded", self.model)
        except httpx.HTTPError as error:
            log.warning("unloading %s failed: %s", self.model, error)

    async def close(self) -> None:
        await self._client.aclose()
