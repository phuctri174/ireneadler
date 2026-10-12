r"""Run the routing and reaction evals against one model.

Run: .venv\Scripts\python evals\run_evals.py [--model gemma3:12b] [--repeat N] [--only routing|reactions]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from drawing import DrawReport, run_drawing
from harness import MODEL_DEFAULT, Ollama, Report, _record_time, run_conversation, run_reactions, run_routing, summary

ROUTING_BAR = 0.9
REACTION_BAR = 0.8
CONVERSATION_BAR = 0.8
DRAWING_BAR = 0.8


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=MODEL_DEFAULT)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--only", choices=["routing", "reactions", "drawing", "conversation", "briefing"])
    parser.add_argument("--quiet", action="store_true", help="print failures only")
    args = parser.parse_args()
    briefing_ok = True
    if args.only in (None, "briefing"):
        # greetings, SJC gold sourcing, briefing follow-ups: no model needed
        import briefing_evals

        briefing_ok = await briefing_evals.main_quiet(args.quiet)
        if args.only == "briefing":
            return 0 if briefing_ok else 1
    llm = Ollama(args.model)
    report = Report(args.model)
    try:
        if args.only in (None, "routing"):
            await run_routing(llm, report, args.repeat)
        if args.only in (None, "reactions"):
            await run_reactions(llm, report, args.repeat)
        if args.only in (None, "conversation"):
            await run_conversation(llm, report, args.repeat)
        drawing = DrawReport()
        if args.only in (None, "drawing"):
            await run_drawing(llm, drawing, lambda t: _record_time(report, t), args.repeat)
            drawing.check_with_hud()
    finally:
        await llm.close()
    for line in report.lines + drawing.lines:
        if not args.quiet or line.startswith("FAIL"):
            print(line)
    result = {**summary(report), **drawing.summary()}
    print(json.dumps(result, indent=1))
    ok = (
        briefing_ok
        and (drawing.n == 0 or drawing.right / drawing.n >= DRAWING_BAR)
        and (report.routing_n == 0 or report.routing_ok / report.routing_n >= ROUTING_BAR)
        and (report.react_n == 0 or report.react_ok / report.react_n >= REACTION_BAR)
        and (report.chat_n == 0 or report.chat_ok / report.chat_n >= CONVERSATION_BAR)
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
