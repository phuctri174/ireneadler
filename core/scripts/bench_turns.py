r"""Speed benchmark: real turns through a running core (start-irene.ps1 -Dev, or
IRENE_DEV=1 python -m irene.app), as typed commands over the socket - no OS input.
Each turn's cost comes from core's own log (core/logs/turns.jsonl).

  .venv\Scripts\python scripts\bench_turns.py [label]

Prints a table (and writes core/logs/bench-<label>.json): LLM calls, prompt
tokens actually evaluated, prefill ms, output tokens, tokens/s, tool ms, time to
first audio. Media keys are only logged in dev mode; the timer is an hour out.
"""
from __future__ import annotations

import asyncio
import json
import statistics
import sys
from pathlib import Path

import websockets

LOGS = Path(__file__).resolve().parents[1] / "logs"
CHAT = [
    "Hey Irene, how's it going?",
    "Tell me a joke.",
    "What's 15 percent of 240?",
    "What's the capital of Japan?",
    "Tell me more about it.",
    "I'm a bit tired today.",
]
TOOLS = [
    "What time is it exactly?",
    "Set a timer for 60 minutes for laundry.",
    "Skip this song.",
    "Pause the music.",
    "How's my PC doing?",
]


async def turn(ws, text: str) -> dict:
    lines_before = (LOGS / "turns.jsonl").read_text(encoding="utf-8").count("\n") if (LOGS / "turns.jsonl").exists() else 0
    await ws.send(json.dumps({"type": "command", "text": text}))
    while True:
        m = json.loads(await asyncio.wait_for(ws.recv(), 60))
        if m.get("type") == "state" and m.get("value") == "listening":
            break
    for _ in range(50):
        lines = (LOGS / "turns.jsonl").read_text(encoding="utf-8").splitlines()
        if len(lines) > lines_before:
            return json.loads(lines[-1])
        await asyncio.sleep(0.1)
    raise RuntimeError(f"no log line for {text!r}")


async def main(label: str) -> None:
    rows = []
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        try:
            while True:
                await asyncio.wait_for(ws.recv(), 0.5)
        except asyncio.TimeoutError:
            pass
        for kind, texts in (("chat", CHAT), ("tool", TOOLS)):
            for text in texts:
                r = await turn(ws, text)
                r["kind"] = kind
                rows.append(r)
                print(f"{kind:4} {text[:38]:38} calls {r['llm_calls']}  prompt {r['prompt_tokens']:5}  prefill {r['prefill_ms']:5} ms  out {r['output_tokens']:4}  {r['tok_s']:5} tok/s  tools {r['tool_ms']:5} ms  first audio {r['ttfa_ms']} ms", flush=True)
                await asyncio.sleep(0.5)
    summary = {}
    for kind in ("chat", "tool"):
        rs = [r for r in rows if r["kind"] == kind]
        ttfa = [r["ttfa_ms"] for r in rs if r["ttfa_ms"] is not None]
        summary[kind] = {
            "turns": len(rs),
            "llm_calls_mean": round(statistics.mean(r["llm_calls"] for r in rs), 2),
            "prompt_tokens_median": statistics.median(r["prompt_tokens"] for r in rs),
            "prefill_ms_median": statistics.median(r["prefill_ms"] for r in rs),
            "tok_s_median": statistics.median(r["tok_s"] for r in rs),
            "tool_ms_median": statistics.median(r["tool_ms"] for r in rs),
            "ttfa_ms_median": statistics.median(ttfa) if ttfa else None,
            "ttfa_ms_max": max(ttfa) if ttfa else None,
        }
    (LOGS / f"bench-{label}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "run"))
