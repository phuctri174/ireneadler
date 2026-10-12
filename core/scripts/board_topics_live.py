r"""Round 8: she COMPOSES the board for any topic - checked in the RUNNING app
(start-irene.ps1 -Dev), typed commands only, no OS input, no desktop screenshot.

  .venv\Scripts\python scripts\board_topics_live.py [--only N]

Topics with no special handling anywhere in the code. For each: the question
goes over the socket; every board message she sends while answering is replayed
exactly as the HUD applies it (spec, set, add); the board is rendered to a PNG by
the HUD's own drawing code (render_frames.mjs) at the end of the answer; the HUD's
own report ("hud board drew ...") is read back from core.log, and what became of
her drawing from logs/draw-specs.jsonl. A topic whose board is only her keywords
(or nothing) when a visual was possible FAILS; a live-numbers topic passes only
with a chart of numbers from its source.

PNGs: core/logs/board-shots/<n>-<topic>.png, a contact sheet, and a summary in
core/logs/board-topics-live.json.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import websockets

CORE = Path(__file__).resolve().parents[1]
LOG = CORE / "logs" / "core.log"
OUT = CORE / "logs" / "board-shots"
HUD = CORE.parent / "hud"

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
SPECS = CORE / "logs" / "draw-specs.jsonl"


def apply(board: dict | None, message: dict, now: float, shown_at: float) -> tuple[dict | None, float]:
    """The HUD's board_sync, in Python: a new spec starts a board; set replaces
    fields (shapes keep the moment they first appeared); add appends, stamped."""
    t = round((now - shown_at) * 1000)
    if message.get("spec") is not None:
        board = {"reveal": [], "notes": [], **message["spec"]}
        shown_at, t = now, 0
    if board is None:
        return None, shown_at
    seen = {s.get("id"): s.get("at") for s in board.get("shapes", []) if isinstance(s, dict) and s.get("id")}
    for key, value in (message.get("set") or {}).items():
        if key == "shapes":
            # (a shape of the first drawing has no moment: it keeps none, like the HUD)
            board[key] = [({**s, "at": seen[s["id"]]} if seen.get(s.get("id")) is not None else s) if s.get("id") in seen else {**s, "at": t} for s in value]
        else:
            board[key] = value
    for key, items in (message.get("add") or {}).items():
        board[key] = [*board.get(key, []), *({**i, "at": t} for i in items)]
    return board, shown_at


def only_words(board: dict | None) -> bool:
    if not board:
        return True
    if board.get("template") == "terms":
        return True
    if "shapes" in board:
        # a picture, and what it shows named on it - not an empty outline (an answer
        # cut off right after its drawing arrived once passed with two shapes)
        named = [s for s in board["shapes"] if s.get("type") == "label" and s.get("id") != "title"]
        return not any(s.get("type") != "label" for s in board["shapes"]) or len(named) < 2
    return False


def elements(board: dict | None) -> str:
    if not board:
        return "nothing drawn"
    if "shapes" in board:
        labels = [s["text"] for s in board["shapes"] if s.get("type") == "label" and s.get("id") != "title"]
        return f"{len(board['shapes'])} shapes: {', '.join(labels[:10])}"
    if board.get("template") == "chessboard":
        plies = max([int(r["key"].split(":")[1]) for r in board.get("reveal", [])] or [0])
        return f"chessboard {' '.join(board.get('moves', []))} (played to ply {plies}); notes {[n['text'] for n in board.get('notes', [])][:5]}"
    return f"{board.get('template')} labels {[r['key'] for r in board.get('reveal', [])]}"


async def ask(ws, text: str, wait: float = 240) -> tuple[str, dict | None, list[dict]]:
    await ws.send(json.dumps({"type": "command", "text": text}))
    said, spoke, board, shown_at, cleared = "", False, None, time.monotonic(), False
    trail: list[dict] = []
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            m = json.loads(await asyncio.wait_for(ws.recv(), 1))
        except asyncio.TimeoutError:
            continue
        now = time.monotonic()
        if m.get("type") == "draw" and m.get("value") is None:
            board, cleared = None, True
            trail.append({"cleared": True})
        if m.get("type") == "board_sync":
            board, shown_at = apply(board, m, now, shown_at)
            trail.append(m)
        if m.get("type") == "reply":
            said = m.get("speak", "") or said
        if m.get("type") == "state":
            spoke = spoke or m.get("value") == "speaking"
            if m.get("value") == "listening" and spoke and said:
                break
    if board is not None:
        board["_t"] = round((time.monotonic() - shown_at) * 1000) + 3000
    return said, board, trail


async def main() -> int:
    only = int(sys.argv[sys.argv.index("--only") + 1]) if "--only" in sys.argv else None
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()
    shots, results, boards = [], [], {}
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        await ws.send(json.dumps({"type": "debug_ui", "action": "show"}))
        # the room is not part of the check: a video playing nearby barged in and cut
        # her answers off (dev hook; the mic listens again at the end)
        await ws.send(json.dumps({"type": "mic_deaf", "value": True}))
        await asyncio.sleep(2)
        for n, topic in enumerate(TOPICS, 1):
            if only and n != only:
                continue
            start = LOG.stat().st_size
            spec_start = SPECS.stat().st_size if SPECS.exists() else 0
            said, board, trail = await ask(ws, topic)
            await asyncio.sleep(1.5)
            with LOG.open("rb") as f:
                f.seek(start)
                hud = [l.split("hud ", 1)[1] for l in f.read().decode("utf-8", "replace").splitlines() if "hud board" in l]
            refused = [h for h in hud if "REFUSED" in h]
            with SPECS.open("rb") as f:
                f.seek(spec_start)
                specs = [json.loads(line) for line in f.read().decode("utf-8").splitlines() if line.strip()]
            final = next((r for r in reversed(specs) if r["outcome"] in ("ok", "keywords")), None)
            kind = "chess" if board and board.get("template") == "chessboard" else (final or {}).get("kind") or ("keywords" if final else "none")
            ok = not only_words(board) and not refused and kind not in ("keywords", "outline", "none") and (topic not in LIVE or kind in ("line", "bar"))
            name = f"{n:02d}-{re.sub(r'[^a-z0-9]+', '-', topic.lower()).strip('-')[:40]}"
            boards[topic] = board
            if board:
                t = board.pop("_t")
                shots.append({"name": name, "draw": board, "t": t})
            results.append((ok, topic, elements(board), len(hud), refused, said, kind, specs))
            print(f"{'PASS' if ok else 'FAIL'}  {topic:44} [{kind}] {elements(board)[:120]}", flush=True)
            print("      her drawing: " + ("; ".join(f"{r['origin']}:{r['outcome']}{' (' + r['why'][:70] + ')' if r['why'] else ''}" for r in specs) or "none written (chess from her pages/words)"), flush=True)
            print(f"      hud reported {len(hud)} board update(s){'; REFUSED: ' + refused[0][:120] if refused else ''} | she said: {said[:110]}", flush=True)
        await ws.send(json.dumps({"type": "mic_deaf", "value": False}))
    (OUT / "shots.json").write_text(json.dumps(shots, indent=1), encoding="utf-8")
    render = subprocess.run(["node", str(HUD / "scripts" / "render_frames.mjs"), str(OUT / "shots.json"), str(OUT)], capture_output=True, text=True, cwd=str(HUD))
    print(render.stdout.strip()[-200:] or render.stderr.strip()[-400:])
    written = [x for r in results for x in r[7] if x["origin"] in ("reply", "follow-up")]
    summary = {
        "pass": f"{sum(r[0] for r in results)}/{len(results)}",
        "invalid_specs": f"{sum(x['outcome'] == 'invalid' for x in written)}/{len(written)}",
        "keywords_fallback": sum(r[6] == "keywords" for r in results),
        "hud_refused": sum(bool(r[4]) for r in results),
    }
    print(json.dumps(summary))
    (CORE / "logs" / "board-topics-live.json").write_text(json.dumps({"summary": summary, "results": [
        {"ok": r[0], "topic": r[1], "board": r[2], "hud_updates": r[3], "refused": r[4], "said": r[5], "kind": r[6], "specs": [{k: x[k] for k in ("origin", "outcome", "why", "kind", "fixed")} for x in r[7]]}
        for r in results]}, indent=1), encoding="utf-8")
    sys.path.insert(0, str(CORE / "scripts"))
    from contact_sheet import sheet

    pngs = sorted(OUT.glob("[0-9]*.png"))
    if pngs:
        sheet(pngs, OUT / "sheet.png", 3, 0.5)
    return 0 if all(r[0] for r in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
