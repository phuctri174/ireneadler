"""Story-mode evals (story.jsonl): he tells her about drama in his life, and she is
his friend, not his fixer.

Each case runs through the LIVE path - Conversation.respond(), his earlier story
turns first, history accumulating as in the app. Scored per reply:

  reacted   no advice he didn't ask for (story.ADVICE) - the rule that matters.
            Scored on what she SAID (after the reply guard) and, separately, on
            what the model WROTE (before it): a guard catching everything would
            hide a prompt that doesn't work
  emotion   her opening cue is one that fits the beat of the story
  short     at most STORY_WORDS spoken words (80 when he asked for advice)
  asks      she asks him something back (soft: reported, not failed)
  no tool   a story never calls a tool

  .venv\\Scripts\\python evals\\story_evals.py [--repeat N] [--only ID]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent))

from irene import story  # noqa: E402
from irene.brain import STORY_ADVICE_WORDS, STORY_WORDS, Conversation  # noqa: E402
from irene.llm import Ollama  # noqa: E402

from memory_evals import Host  # noqa: E402

BAR = 0.85


class Dropped(logging.Handler):
    """Counts the advice the reply guard dropped (what the model wrote, unsaid)."""

    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        if record.getMessage().startswith("story mode: unasked advice dropped"):
            self.lines.append(record.getMessage())


def _opener(speak: str) -> str:
    import re

    first = re.split(r"(?<=[.!?])\s", speak.strip(), maxsplit=1)[0]
    return re.sub(r"[^a-z ]", "", first.lower()).strip()


async def run_session(llm: Ollama, case: dict, dropped: Dropped) -> dict:
    """One conversation, his story told over several messages: every reply a
    reaction, no advice, and no two opening the same way."""
    conv = Conversation(llm)

    async def run_tool(name, args, host):
        return f"done: {name} ran"

    conv._run_tool = run_tool
    host = Host()
    why, said, before = [], [], len(dropped.lines)
    for message in case["session"]:
        turn = await conv.respond(message, host)
        speak = turn.reply.speak
        said.append(speak)
        if [s for s in speak.replace("?", "?.").split(".") if story.is_advice(s)]:
            why.append(f"advised in {speak[:40]!r}")
        if len(speak.split()) > STORY_WORDS:
            why.append(f"{len(speak.split())} words")
        if turn.tools_used:
            why.append(f"called {turn.tools_used}")
    openers = [_opener(s) for s in said]
    if len(set(openers)) < len(openers):
        why.append(f"repeated opener: {openers}")
    return {
        "id": case["id"], "ok": not why, "why": why, "speak": " || ".join(said), "cue": None,
        "words": max(len(s.split()) for s in said), "asks": all("?" in s for s in said),
        "model_advised": len(dropped.lines) > before,
    }


async def run_case(llm: Ollama, case: dict, dropped: Dropped) -> dict:
    if "session" in case:
        return await run_session(llm, case, dropped)
    conv = Conversation(llm)

    async def run_tool(name, args, host):
        return f"done: {name} ran"

    conv._run_tool = run_tool
    host = Host()
    for said in case.get("history", []):
        await conv.respond(said, host)
    before = len(dropped.lines)
    turn = await conv.respond(case["say"], host)
    speak = turn.reply.speak
    first = turn.reply.cues[0].name if turn.reply.cues else (turn.reply.react.name if turn.reply.react else None)
    words = len(speak.split())
    advice_case = case.get("advice", False)
    why = []
    if not advice_case:
        said_advice = [s for s in speak.replace("?", "?.").split(".") if story.is_advice(s)]
        if said_advice:
            why.append(f"advised: {said_advice[0].strip()[:60]!r}")
    if case.get("cues") and first not in case["cues"]:
        why.append(f"cue {first} not in {case['cues'][:3]}")
    if not speak.strip():
        raw = next((m["content"] for m in reversed(conv.history) if m["role"] == "assistant"), "")
        why.append(f"said nothing (model wrote {raw[:160]!r})")
    cap = STORY_ADVICE_WORDS if advice_case else STORY_WORDS
    if words > cap:
        why.append(f"{words} words > {cap}")
    if turn.tools_used:
        why.append(f"called {turn.tools_used}")
    if advice_case and not story.is_advice(speak) and "?" in speak and words < 12:
        why.append("asked for advice, gave none")
    import re

    for pattern in case.get("expect", []):
        if not re.search(pattern, speak, re.I):
            why.append(f"missing /{pattern}/")
    for pattern in case.get("forbid", []):
        m = re.search(pattern, speak, re.I)
        if m:
            why.append(f"has {m.group(0)!r}")
    return {
        "id": case["id"],
        "ok": not why,
        "why": why,
        "speak": speak,
        "cue": first,
        "words": words,
        "asks": "?" in speak,
        "model_advised": len(dropped.lines) > before,
    }


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--only")
    args = parser.parse_args()
    cases = [json.loads(l) for l in (HERE / "story.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.only:
        cases = [c for c in cases if c["id"] == args.only]
    dropped = Dropped()
    logging.getLogger("irene").addHandler(dropped)
    logging.getLogger("irene").setLevel(logging.INFO)
    llm = Ollama()
    await llm.warm()
    results = []
    started = time.perf_counter()
    try:
        for case in cases:
            for _ in range(args.repeat):
                r = await run_case(llm, case, dropped)
                results.append(r)
                flag = "PASS" if r["ok"] else "FAIL"
                raw = " [model wrote advice - guard dropped it]" if r["model_advised"] else ""
                print(f"{flag} story {r['id']:20} {r['cue']!s:13} {r['words']:3}w {'?' if r['asks'] else ' '} {'; '.join(r['why'])}{raw} | {r['speak'][:400 if 'session' in r['id'] else 120]!r}", flush=True)
    finally:
        await llm.close()
    n = len(results)
    story_cases = [r for r in results if r["id"] != "advice-asked"]
    summary = {
        "story": f"{sum(r['ok'] for r in results)}/{n}",
        "reacted_not_advised": f"{sum(not any(w.startswith('advised') for w in r['why']) for r in story_cases)}/{len(story_cases)}",
        "model_wrote_advice": f"{sum(r['model_advised'] for r in story_cases)}/{len(story_cases)}",
        "emotion_fits": f"{sum(not any(w.startswith('cue') for w in r['why']) for r in results)}/{n}",
        "short": f"{sum(not any('words >' in w for w in r['why']) for r in results)}/{n}",
        "asks_back": f"{sum(r['asks'] for r in story_cases)}/{len(story_cases)}",
        "minutes": round((time.perf_counter() - started) / 60, 1),
    }
    print(json.dumps(summary))
    return 0 if n and sum(r["ok"] for r in results) / n >= BAR else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
