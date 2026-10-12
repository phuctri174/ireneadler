r"""Round 8, part 3: does her drawing generalise? Topics with NO special handling,
through the real conversation (gemma, her research, the follow-up for a missing
drawing, the keywords fallback) - no app, no window, no OS input.

  .venv\Scripts\python evals\draw_topics.py [--only N] [--no-research]

For each topic: every board message she sends is applied as the HUD applies it,
the final board rendered to a PNG by the HUD's own drawing code, and her drawing's
fate read from logs/draw-specs.jsonl. A topic PASSES when the board is a picture
(a chessboard or a composed drawing) - her keywords or her outline of words FAIL
whenever a visual was possible. Live numbers (gold, NVIDIA) must be researched
and on the pages, or she must say she couldn't get them ("honest": not a pass,
not a fake chart).

PNGs and a contact sheet: core/logs/draw-topics/. Summary: logs/draw-topics.json.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core" / "scripts"))

from irene import brain, drawing, illustrate  # noqa: E402
from irene.brain import Conversation  # noqa: E402
from irene.llm import Ollama  # noqa: E402
from knowledge_evals import Host as BaseHost  # noqa: E402

OUT = ROOT / "core" / "logs" / "draw-topics"

TOPICS = [
    "Explain the Ruy Lopez.",
    "Explain the London System.",
    "What's the gold price this month?",
    "How has NVIDIA stock done this year?",
    "How does a neural network work?",
    "What's the structure of an animal cell?",
    "How does the human heart work?",
    "How does HTTPS work?",
    "What are Vietnam's regions?",
    "How does photosynthesis work?",
    "What is a binary search tree?",
    "How does Git branching work?",
    "How does the water cycle work?",
    "iPhone vs Pixel - which is better?",
    "Give me a World War 2 timeline.",
    "How does an engine work?",
    "What are the kendo scoring targets?",
]
LIVE = {"What's the gold price this month?", "How has NVIDIA stock done this year?"}


def apply(board: dict | None, message: dict) -> dict | None:
    """The HUD's board_sync, in Python (at the end of the answer, times don't matter)."""
    if message.get("spec") is not None:
        board = {"reveal": [], "notes": [], **message["spec"]}
    if board is None:
        return None
    for key, value in (message.get("set") or {}).items():
        board[key] = value
    for key, items in (message.get("add") or {}).items():
        board[key] = [*board.get(key, []), *({**i, "at": 0} for i in items)]
    return board


class Host(BaseHost):
    def __init__(self):
        super().__init__()
        self.board: dict | None = None
        self.drawn: dict | None = None

    def reply_sink(self):
        host = self

        class Sink:
            def __init__(self):
                self.feed = illustrate.BoardFeed(self.send)

            def send(self, message):
                host.board = apply(host.board, message)

            def line(self, line):
                host.said.append(line.text)
                self.feed.line()
                self.feed.heard(line.text, line.terms)

            def illustrate(self, plan):
                self.feed.start(plan)

            def adopt(self, board):
                self.feed.adopt(board)

            def close_board(self):
                self.feed.close()

            def draw(self, found):
                host.drawn = found.spec

            async def finish(self, reply):
                pass

        return Sink()


def log_rows(start: int) -> list[dict]:
    with drawing.LOG_PATH.open("rb") as f:
        f.seek(start)
        return [json.loads(line) for line in f.read().decode("utf-8").splitlines() if line.strip()]


async def main() -> int:
    only = int(sys.argv[sys.argv.index("--only") + 1]) if "--only" in sys.argv else None
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()
    drawing.LOG_PATH.parent.mkdir(exist_ok=True)
    drawing.LOG_PATH.touch()
    llm = Ollama()
    # no background cache warm-up: the client closes when the run ends
    Conversation.warm_cache = lambda self: None
    results, shots = [], []
    try:
        for n, topic in enumerate(TOPICS, 1):
            if only and n != only:
                continue
            start = drawing.LOG_PATH.stat().st_size
            host = Host()
            t0 = time.perf_counter()
            turn = await Conversation(llm).respond(topic, host)
            secs = time.perf_counter() - t0
            specs = log_rows(start)
            said = " ".join(host.said)
            board = host.board
            final = next((r for r in reversed(specs) if r["outcome"] in ("ok", "keywords")), None)
            kind = "chess" if board and board.get("template") == "chessboard" else final["kind"] if final and final["outcome"] == "ok" else "keywords" if final else "none"
            visual = kind not in ("keywords", "outline", "none")
            honest = topic in LIVE and any(r["outcome"] == "refused" for r in specs) and bool(re.search(r"couldn't find|no reliable|won't draw", said, re.I))
            researched = "research" in turn.tools_used
            ok = visual and (topic not in LIVE or (kind in ("line", "bar") and researched))
            first = specs[0] if specs else None
            results.append({
                "topic": topic, "ok": ok, "kind": kind, "honest_no_chart": honest, "researched": researched, "seconds": round(secs, 1),
                "first_spec": first["outcome"] if first else "none", "first_origin": first["origin"] if first else "",
                "specs": [{k: r[k] for k in ("origin", "outcome", "why", "kind", "fixed")} for r in specs], "said": said[:300],
            })
            verdict = "PASS" if ok else "HONEST" if honest else "FAIL"
            print(f"{verdict:6} {topic:42} {kind:9} {'researched ' if researched else ''}{secs:5.1f}s  specs: "
                  + "; ".join(f"{r['origin']}:{r['outcome']}{' (' + r['why'][:60] + ')' if r['why'] else ''}" for r in specs), flush=True)
            if board:
                name = f"{n:02d}-{re.sub(r'[^a-z0-9]+', '-', topic.lower()).strip('-')[:36]}"
                shots.append({"name": name, "draw": board, "t": 60000})
    finally:
        await llm.close()
    (OUT / "shots.json").write_text(json.dumps(shots), encoding="utf-8")
    render = subprocess.run(["node", "scripts/render_frames.mjs", str(OUT / "shots.json"), str(OUT)], cwd=ROOT / "hud", capture_output=True, text=True)
    print((render.stdout.strip() or render.stderr.strip())[-200:])
    from contact_sheet import sheet

    pngs = sorted(OUT.glob("[0-9]*.png"))
    if pngs:
        sheet(pngs, OUT / "sheet.png", 3, 0.5)
    replies = [r for r in results]
    written = [r for r in results if r["first_origin"] == "reply"]
    all_specs = [s for r in results for s in r["specs"] if s["origin"] in ("reply", "follow-up")]
    summary = {
        "pass": f"{sum(r['ok'] for r in results)}/{len(results)}",
        "honest_no_chart": sum(r["honest_no_chart"] and not r["ok"] for r in results),
        "drew_in_reply": f"{len(written)}/{len(replies)}",
        "invalid_specs": f"{sum(s['outcome'] == 'invalid' for s in all_specs)}/{len(all_specs)}",
        "keywords_fallback": sum(r["kind"] == "keywords" for r in results),
    }
    print(json.dumps(summary, indent=1))
    (ROOT / "core" / "logs" / "draw-topics.json").write_text(json.dumps({"summary": summary, "results": results}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
