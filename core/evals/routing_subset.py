r"""Routing evals for a few cases only, repeated - to tell a flaky case from a
regression (A/B a change on exactly the cases it might have moved).

  .venv\Scripts\python evals\routing_subset.py --repeat 3 list-recent read-pdf ...
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness  # noqa: E402
from irene.llm import Ollama  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="+")
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    everything = harness.load("routing.jsonl")
    harness.load = lambda name: [c for c in everything if c["id"] in args.ids] if name == "routing.jsonl" else everything
    llm = Ollama()
    report = harness.Report(llm.model)
    try:
        await harness.run_routing(llm, report, args.repeat)
    finally:
        await llm.close()
    for line in report.lines:
        if line.startswith(("FAIL", "ok", "OK")) or "routing" in line:
            print(line)
    print(f"routing {report.routing_ok}/{report.routing_n}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
