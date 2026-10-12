"""Multi-turn memory evals (memory.jsonl): a later question that depends on what he
said 3-8 turns earlier - a correction, a preference, a requirement, "the second
one", a topic he comes back to, "you got that wrong, try again".

Every case runs through the LIVE path - Conversation.respond(), turn by turn,
history accumulating exactly as in the app - not a hand-built prompt: layout
changes once passed the prompt()-based evals and still broke live behaviour.
Tools return the case's canned text (nothing touches the web or the OS).

  .venv\\Scripts\\python evals\\memory_evals.py [--repeat N]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent))

from irene.brain import Conversation  # noqa: E402
from irene.llm import Ollama  # noqa: E402
from irene.reply import Reply  # noqa: E402

BAR = 0.8
APOLOGY = re.compile(r"\bapolog\w*|\bmy fault\b|\bsorry\b|\bmy bad\b|\bnot again\b|\bdid i forget\b|\brepeating myself\b|\bslipped up\b|\bgot (?:it|that) wrong\b", re.I)


class Sink:
    def line(self, line):
        pass

    def draw(self, found):
        pass

    async def finish(self, reply: Reply):
        pass


class Host:
    """What a turn needs from the app, minus the app."""

    async def thinking(self):
        pass

    async def confirm(self, prompt):
        return True

    async def tool_status(self, name, status):
        pass

    def reply_sink(self):
        return Sink()

    async def announce(self, text):
        pass

    def forget(self):
        pass

    async def capture_shield(self, on):
        pass

    async def show_panel(self, content):
        pass

    def panel_answers(self):
        return []

    def panel_content(self):
        return None

    async def perform(self, names):
        return names


def check(case: dict, reply: Reply, tools: list[str]) -> list[str]:
    """Why the final answer fails the case (empty: it passes)."""
    text = f"{reply.speak} {reply.display}"
    why = []
    for pattern in case.get("expect", []):
        if not re.search(pattern, text, re.I):
            why.append(f"missing /{pattern}/")
    for pattern in case.get("forbid", []):
        m = re.search(pattern, text, re.I)
        if m:
            why.append(f"has {m.group(0)!r}")
    # remembering is not a mistake: she once apologised in half the answers
    m = APOLOGY.search(reply.speak)
    if m:
        why.append(f"apologised ({m.group(0)!r})")
    if case.get("max_words") and len(reply.speak.split()) > case["max_words"]:
        why.append(f"{len(reply.speak.split())} words > {case['max_words']}")
    if case.get("no_tool") and tools:
        why.append(f"called {tools} again instead of remembering")
    return why


async def run_case(llm: Ollama, case: dict) -> tuple[bool, str]:
    conv = Conversation(llm)
    canned = case.get("tools", {})

    async def run_tool(name, args, host):
        return canned.get(name, f"done: {name} ran")

    conv._run_tool = run_tool
    for role, content in case.get("history", []):
        conv.history.append({"role": role, "content": content})
    host = Host()
    for said in case["turns"]:
        await conv.respond(said, host)
    turn = await conv.respond(case["ask"], host)
    why = check(case, turn.reply, turn.tools_used)
    return not why, f"{'PASS' if not why else 'FAIL'} memory {case['id']:26} {'; '.join(why)} | said: {turn.reply.speak[:110]!r}"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--only", help="one case id")
    args = parser.parse_args()
    cases = [json.loads(l) for l in (HERE / "memory.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.only:
        cases = [c for c in cases if c["id"] == args.only]
    llm = Ollama()
    await llm.warm()
    ok = n = 0
    started = time.perf_counter()
    try:
        for case in cases:
            for _ in range(args.repeat):
                passed, line = await run_case(llm, case)
                ok += passed
                n += 1
                print(line, flush=True)
    finally:
        await llm.close()
    print(json.dumps({"memory": f"{ok}/{n} ({100 * ok // max(1, n)}%)", "minutes": round((time.perf_counter() - started) / 60, 1)}))
    return 0 if n and ok / n >= BAR else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
