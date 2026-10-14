r"""Past-session evals: questions whose right answer is in an EARLIER session.

Each case seeds a fresh memory store (irene/recall.py) with what was kept on earlier
days - an exchange, something he told her, a research answer, a lecture - then asks
in a new conversation, through the live turn (harness.live_turn: the app's dispatch
and Conversation.respond). Nothing of his own memory is read or written: both
stores point at a temporary folder.

  expect     regexes her answer must match (each)
  forbid     regexes it must not
  no_tool    nothing may be called (an answer from memory, not a new search)
  max_words  a standing preference ("short answers") still holds
  tool       or the remembered fact goes into this tool call ({name, contains})

Run (from core/): .venv\Scripts\python evals\recall_evals.py [--repeat N] [--only id]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import harness
from irene import provenance, recall
from irene.llm import Ollama

BAR = 0.85
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def seeded(case: dict) -> recall.Store:
    """A new store holding the case's past, each item at its own time (noon that day)."""
    store = recall.Store(Path(tempfile.mkdtemp(prefix="irene-recall-eval-")) / "memory.sqlite")
    noon = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    for p in case["past"]:
        if "weekday" in p:
            back = (noon.weekday() - _WEEKDAYS.index(p["weekday"])) % 7 or 7
        else:
            back = p["days_ago"]
        at = (noon - timedelta(days=back)).timestamp()
        store.add(p["kind"], p["text"], p.get("about", ""), at=at, session="earlier")
    return store


def check(case: dict, t: harness.Timed) -> list[str]:
    # "don’t" is "don't": a curly apostrophe failed a right answer (nothing-last-month)
    said = f"{t.reply.speak} {t.reply.display}".replace("’", "'") if t.reply else ""
    # spoken numbers count as numbers ("fifteen degrees" is 15)
    said = f"{said} {harness._spoken_numbers(said.lower())}"
    why = [f"missing /{p}/" for p in case.get("expect", []) if not re.search(p, said, re.I)]
    why += [f"has {m.group(0)!r}" for p in case.get("forbid", []) if (m := re.search(p, said, re.I))]
    if case.get("no_tool") and (t.called or t.attempts):
        why.append(f"called {[n for n, _ in t.attempts] or [t.called[0]]}")
    if case.get("unknown"):
        # an invention probe: he asks about what she was never told. Anything but "I
        # don't know" fails - any sentence that asserts one of these, or no admission
        sentences = [s for s in re.split(r"(?<=[.!?…])\s+|\n", f"{t.reply.speak}\n{t.reply.display}" if t.reply else "") if s.strip()]
        if t.called or not any(provenance.refuses(s) for s in sentences):
            why.append("confident answer: no 'I don't know'")
        for s in sentences:
            if provenance.refuses(s) or s.rstrip().endswith("?") or len(s.split()) < 2:
                continue  # saying she doesn't know it, asking him, or "Minh..." said back: not a claim
            hit = next((u for u in case["unknown"] if re.search(rf"\b{u}", s, re.I)), None)
            if hit:
                why.append(f"invented: {s[:80]!r}")
    if case.get("max_words") and t.reply and len(t.reply.speak.split()) > case["max_words"]:
        why.append(f"{len(t.reply.speak.split())} words > {case['max_words']}")
    want = case.get("tool")
    if t.called and want and t.called[0] == want["name"]:
        # the remembered fact, used as a tool's argument (the deadline, counted to)
        return [f"{k}={t.called[1].get(k)!r} lacks {v!r}" for k, v in want.get("contains", {}).items() if v.lower() not in str(t.called[1].get(k, "")).lower()]
    if t.called and not case.get("no_tool"):
        why.append(f"handed over {t.called[0]} instead of answering")
    return why


async def run(llm, cases: list[dict], repeat: int = 1, quiet: bool = False) -> dict:
    ok = n = 0
    # invention probes, scored on their own: any confident answer is a failure
    probes_ok = probes = 0
    ms: list[float] = []
    first_say: list[float] = []
    for case in cases:
        store = seeded(case)
        for _ in range(repeat):
            recall.HIS = recall.DEV = store
            t = await harness.live_turn(llm, case)
            ms.append(recall.LAST.ms)
            if t.first_say is not None:
                first_say.append(t.first_say * 1000)
            why = check(case, t)
            ok += not why
            if case.get("unknown"):
                probes += 1
                probes_ok += not why
            n += 1
            line = f"{'PASS' if not why else 'FAIL'} recall  {case['id']:22} {'; '.join(why)} | {(t.reply.speak if t.reply else t.called)!s:.140}"
            if not quiet or why:
                print(line, flush=True)
        store.close()
    return {
        "recall": f"{ok}/{n} ({ok / max(1, n):.0%})",
        "invention_probes": f"{probes_ok}/{probes} said they don't know",
        "retrieval_ms_p50": round(statistics.median(ms), 1) if ms else None,
        "retrieval_ms_max": round(max(ms), 1) if ms else None,
        "first_say_p50_ms": round(statistics.median(first_say)) if first_say else None,
        "_ok": ok,
        "_n": n,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--only", help="one case id")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    cases = harness.load("recall.jsonl")
    if args.only:
        cases = [c for c in cases if c["id"] == args.only]
    recall.EMBEDDER.load()
    llm = Ollama()
    await llm.warm()
    started = time.perf_counter()
    try:
        result = await run(llm, cases, args.repeat, args.quiet)
    finally:
        await llm.close()
    result["minutes"] = round((time.perf_counter() - started) / 60, 1)
    print(json.dumps({k: v for k, v in result.items() if not k.startswith("_")}, indent=1))
    return 0 if result["_n"] and result["_ok"] / result["_n"] >= BAR else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
