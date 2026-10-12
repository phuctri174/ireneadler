r"""Routing eval with Ollama's NATIVE tool calling instead of the prompt protocol.

Measurement only - the app uses the prompt protocol. For models that support it
(gemma4, qwen3-vl); gemma3 rejects native tools.

Run: .venv\Scripts\python evals\native_routing.py --model gemma4:12b --repeat 2
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time

import httpx

from harness import Report, load
from irene.prompt import system_prompt  # noqa: E402
from tools import REGISTRY


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gemma4:12b")
    parser.add_argument("--repeat", type=int, default=2)
    args = parser.parse_args()
    tools = [{"type": "function", "function": t.spec()} for t in REGISTRY.values()]
    system = system_prompt()  # persona + reactions, no prompt-protocol tool section
    report = Report(args.model + " (native tools)")
    async with httpx.AsyncClient(base_url="http://127.0.0.1:11434", timeout=180) as client:
        for case in load("routing.jsonl"):
            for _ in range(args.repeat):
                start = time.perf_counter()
                r = await client.post("/api/chat", json={
                    "model": args.model, "stream": False, "think": False, "keep_alive": -1,
                    "tools": tools, "options": {"temperature": 0.6},
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": case["say"]}],
                })
                report.total.append(time.perf_counter() - start)
                message = r.json()["message"]
                calls = message.get("tool_calls") or []
                name = calls[0]["function"]["name"] if calls else None
                got_args = calls[0]["function"].get("arguments", {}) if calls else {}
                ok = name in case["expect"]
                report.routing_n += 1
                report.routing_ok += ok
                note = ""
                if ok and name and case.get("args"):
                    report.args_n += 1
                    good = all(float(got_args.get(k, "nan")) == float(v) for k, v in case["args"].items())
                    report.args_ok += good
                    ok = good
                    note = "" if good else f" ARGS {got_args}"
                if not ok:
                    content = (message.get("content") or "")[:90]
                    print(f"FAIL {case['id']:22} got {name or 'no tool':20} want {case['expect']}{note} {content!r}")
    print(f"\n{report.model}: routing {report.routing_ok}/{report.routing_n} "
          f"({report.routing_ok / report.routing_n:.0%}), arguments {report.args_ok}/{report.args_n}, "
          f"total p50 {Report.pct(report.total, 0.5) * 1000:.0f} ms p95 {Report.pct(report.total, 0.95) * 1000:.0f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
