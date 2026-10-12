r"""Skit mode in the RUNNING app (start-irene.ps1 -Dev), through the dev hooks only -
no OS input, no screenshot, the mic deaf (his turns are the dev "heard" hook):

  .venv\Scripts\python scripts\skit_live_check.py

  take       first_dance start to finish: her summon with the skit's entrance and
             no greeting, every line exactly as written in order, nothing put on
             her panel, the working state in the 3 s pause, nothing from the model
  silences   the pauses between her lines as heard (core.log), against the file
  abort      ctrl+alt+shift+x's message mid-take: she stops and settles
  restart    ctrl+alt+shift+k's message mid-take: the take starts over
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from irene import skit as S  # noqa: E402

LOG = Path(__file__).resolve().parents[1] / "logs" / "core.log"
# how long "he" waits before each turn ends: "Hey Irene", the rant, his apology
# (4 s: well past her 2.5 s working hold - she must wait for him), "What did you
# just say?"
TALK_S = (1.0, 3.0, 4.0, 1.2)
results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:26} {detail}", flush=True)


async def take(ws, talk=TALK_S, until=None, timeout=120.0, stop_at_end=True, wake="Hey Irene") -> list[tuple[float, dict]]:
    """Start the skit and play his part; returns every message (time, message)."""
    await ws.send(json.dumps({"type": "skit", "action": "start", "name": "first_dance"}))
    seen: list[tuple[float, dict]] = []
    waits = 0
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            m = json.loads(await asyncio.wait_for(ws.recv(), 1))
        except asyncio.TimeoutError:
            continue
        seen.append((time.monotonic(), m))
        if m.get("type") != "skit":
            continue
        if m.get("phase") == "waiting":
            action = until(waits, ws) if until else None
            if action is not None:
                waits += 1
                await action
                continue
            await asyncio.sleep(talk[min(waits, len(talk) - 1)])
            # his first turn is the wake phrase: it picks her entrance
            said = wake if waits == 0 else None
            waits += 1
            await ws.send(json.dumps({"type": "skit", "action": "heard", "seconds": 2.0, **({"said": said} if said else {})}))
        elif m.get("phase") in ("end", "error") and stop_at_end:
            break
    return seen


async def main() -> int:
    skit = S.load("first_dance")
    lines = [b.line for b in skit.beats if b.who == "irene"]
    # core.log rotates (2 MB): its lines are read by time, from the rotated file too
    log_from = time.strftime("%Y-%m-%d %H:%M:%S")
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        await ws.send(json.dumps({"type": "mic_deaf", "value": True}))
        try:
            seen = await take(ws)
            msgs = [m for _, m in seen]
            said = [m["text"] for m in msgs if m["type"] == "transcript" and m.get("role") == "irene"]
            record("lines exact, in order", said[-len(lines):] == lines and len(said) == len(lines) + 1, f"{said}")
            record("Hey Irene: domain expansion, no greeting", any(m["type"] == "summon_request" for m in msgs) and said[0] == "DOMAIN EXPANSION: IRENE ADLER IS COMING!!!", said[0][:40])
            record("no model, no reply", not any(m["type"] in ("reply", "latency") for m in msgs), "")
            panel = [m for m in msgs if m["type"] == "panel"]
            record("nothing pinned to her panel", not panel, f"{len(panel)} panel messages")
            # beat 6: her working state, up from after her apology until her next line
            # - through his whole 4 s apology, not just its 2.5 s hold
            run_at = next((t for t, m in seen if m == {"type": "tool", "name": "skit", "status": "running", "cue": "folder"}), None)
            done_at = next((t for t, m in seen if run_at and t > run_at and m.get("type") == "tool" and m.get("status") == "done"), None)
            record("working waits for his apology", run_at is not None and done_at is not None and done_at - run_at >= 4.0, f"{(done_at - run_at) if run_at and done_at else 0:.1f} s working")
            faces = [m["value"] for m in msgs if m["type"] == "emotion"]
            record("her faces", [f for f in faces if f in ("sobbing", "innocent", "peeking", "smug")] == ["sobbing", "innocent", "peeking", "smug"], f"{faces}")
            end = next((m for m in msgs if m.get("type") == "skit" and m.get("phase") == "end"), {})
            record("the take completed", bool(end.get("completed")), f"{end}")
            # smug held 2.5 s before the settle
            smug = next((t for t, m in seen if m.get("type") == "emotion" and m.get("value") == "smug"), None)
            # (the take's end comes just before her settle to neutral)
            settle = next((t for t, m in seen if smug and t > smug and m.get("type") == "skit" and m.get("phase") == "end"), None)
            record("smug held", smug is not None and settle is not None and settle - smug >= 2.5, f"{(settle - smug) if smug and settle else 0:.2f} s")

            await asyncio.sleep(1.0)
            text = "\n".join(
                line
                for path in (LOG.with_name("core.log.1"), LOG)
                if path.exists()
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
                if line[:19] >= log_from
            )
            gaps = [(int(w), int(g)) for w, g in re.findall(r"silence before line \d+: wanted (\d+) ms, heard (\d+) ms", text)]
            record("silences as asked", bool(gaps) and all(abs(g - w) <= 60 for w, g in gaps), f"{gaps}")

            # "Irene Adler": her Victorian scene, with the boot and her song - the song
            # faded out before her first word
            adler_from = time.strftime("%Y-%m-%d %H:%M:%S")
            seen = await take(ws, wake="Irene Adler")
            msgs = [m for _, m in seen]
            entrances = [m.get("name") for m in msgs if m.get("type") == "entrance" and m.get("phase") == "start"]
            said = [m["text"] for m in msgs if m["type"] == "transcript" and m.get("role") == "irene"]
            record("Irene Adler: the Victorian scene", entrances == ["victorian"] and said[1:] == lines, f"entrances {entrances}, first words {said[:2]}")
            await asyncio.sleep(1.0)
            text = "\n".join(
                line
                for path in (LOG.with_name("core.log.1"), LOG)
                if path.exists()
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
                if line[:19] >= adler_from
            )
            order = [stage for stage in ("under the boot, from", "boot start", "boot end", "entrance end", "music faded", "first line starts") if stage in text]
            positions = [text.index(stage) for stage in order]
            record("...with her song, faded before her first word", len(order) == 6 and positions == sorted(positions), f"{order}")

            # abort at his rant
            async def abort(n, ws):
                await ws.send(json.dumps({"type": "skit", "action": "abort"}))

            seen = await take(ws, until=lambda n, ws: abort(n, ws) if n == 1 else None)
            end = next((m for _, m in seen if m.get("type") == "skit" and m.get("phase") == "end"), {})
            said = [m["text"] for _, m in seen if m["type"] == "transcript" and m.get("role") == "irene"]
            record("abort mid-take", end.get("completed") is False and lines[1] not in said, f"{end}")

            # start over mid-take: the second start replaces the first
            async def restart(n, ws):
                await ws.send(json.dumps({"type": "skit", "action": "start", "name": "first_dance"}))

            seen = await take(ws, until=lambda n, ws: restart(n, ws) if n == 1 else None, timeout=45, stop_at_end=False)
            starts = [m for _, m in seen if m.get("type") == "skit" and m.get("phase") == "start"]
            record("restart mid-take", len(starts) >= 2, f"{len(starts)} starts")
            await ws.send(json.dumps({"type": "skit", "action": "abort"}))
            await asyncio.sleep(1.0)
        finally:
            await ws.send(json.dumps({"type": "mic_deaf", "value": False}))
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed" + (f" - FAILED: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
