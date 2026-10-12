r"""A turn has to finish what it starts, live.

  .venv\Scripts\python evals\turn_completes.py

She used to answer "what is tenouchi?" with "Ooh, let me look that up for you..."
and stop there - a filler with no tool call, so nothing ran and no answer came.
That is worse than a slow answer: she claims an action she never took.

Every case here is a question she cannot answer from memory, asked the way he
actually asks it - NO "look it up" tacked on, which is what evals/research_answers.py
adds and which hides this bug entirely. A turn passes only if:

  never ends on a filler   the last thing she says is not another promise
  a filler is kept            if she said one, a tool ran and a real answer followed

The filler itself is welcome: it is the prefix of a turn still running.

Whether she SHOULD look a given term up is deliberately not scored here. The
router already answers "what does X mean" from knowledge on purpose - 13 of the
15 definition questions in routing.jsonl expect no tool at all - so making that a
pass condition would encode a policy this file does not own. `ran_a_tool` and
`answered` are reported for reading, not for passing.

Needs Ollama, her SearXNG and Chrome. No OS input.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import irene  # noqa: E402,F401
from irene.brain import Conversation  # noqa: E402
from irene.llm import Ollama  # noqa: E402
from irene.reply import promises_action  # noqa: E402
from research_answers import Host  # noqa: E402

# (what he types, a word the real answer should contain)
CASES = [
    ("anyway, what is tenouchi?", r"grip|hand|squeez|tenouchi"),
    ("what is tenouchi?", r"grip|hand|squeez|tenouchi"),
    ("Anyway - my teacher told me to improve my tenouchi. What's that?", r"grip|hand|squeez|tenouchi"),
    ("what's gyaku-dou in kendo?", r"do|dou|strike|left|side"),
    ("what is a tsuba on a shinai?", r"guard|hand|hilt|tsuba"),
    ("who won the 2019 Kendo World Championship men's team event?", r"japan|korea|team|won|final"),
    ("what does jodan-no-kamae mean?", r"stance|above|head|high|upper"),
    ("how heavy is a regulation shinai?", r"gram|kg|\d|weigh"),
]
OUT = ROOT / "core" / "logs" / "turn-completes.json"


async def main() -> int:
    # her answers carry Japanese romanisation (jodan, do); a cp1252 console
    # would die on the first macron
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    llm = Ollama()
    rows = []
    for question, want in CASES:
        conv = Conversation(llm)  # each question fresh
        host = Host()
        started = time.perf_counter()
        turn = await conv.respond(question, host)
        said = [s for s in host.said if s.strip()]
        spoken = " ".join(said)
        last = said[-1] if said else ""
        ended_on_filler = bool(promises_action(last)) and len(said) <= 1
        row = {
            "question": question,
            "ran_a_tool": bool(turn.tools_used),
            "tools": turn.tools_used,
            "ended_on_filler": ended_on_filler,
            "filler_first": bool(said and promises_action(said[0])),
            "words": len(spoken.split()),
            "answered": bool(re.search(want, spoken, re.I)),
            "seconds": round(time.perf_counter() - started, 1),
            "said": spoken,
        }
        # the invariant this file owns: a filler is a prefix, never the whole turn
        row["pass"] = not row["ended_on_filler"] and (
            not row["filler_first"] or (row["ran_a_tool"] and row["words"] >= 12)
        )
        rows.append(row)
        mark = "OK  " if row["pass"] else "FAIL"
        print(f"{mark} {row['words']:3d}w tools={turn.tools_used or '-'} filler_first={row['filler_first']} "
              f"{row['seconds']:5.1f}s  {question}\n     {spoken[:220]}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    passed = sum(r["pass"] for r in rows)
    stalled = sum(r["ended_on_filler"] for r in rows)
    print(
        f"\n{passed}/{len(rows)} turns finished what they started; "
        f"{stalled} ended on a filler; "
        f"{sum(r['filler_first'] for r in rows)} played a filler first; "
        f"{sum(r['ran_a_tool'] for r in rows)} ran a tool -> {OUT.relative_to(ROOT)}"
    )
    await llm.close()
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
