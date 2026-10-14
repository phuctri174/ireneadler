r"""The model's raw output for a few routing cases - to see what it really wrote
when a case fails (a wrong tool, or the right one with empty arguments).

  .venv\Scripts\python evals\routing_raw.py web-read-url read-pdf
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness  # noqa: E402
from irene.llm import Ollama  # noqa: E402


async def main() -> int:
    ids = sys.argv[1:]
    llm = Ollama()
    try:
        for case in harness.load("routing.jsonl"):
            if case["id"] in ids:
                # the live turn (harness.live_turn): every call the model wrote, then
                # what the turn handed over or said
                t = await harness.live_turn(llm, case)
                print(f"--- {case['id']}: {case['say']}\n    wrote: {t.attempts}\n    ran: {t.called}\n    said: {t.raw[:400]}  [{t.llm_calls} model calls, {t.who}]")
    finally:
        await llm.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
