r"""A whole chess game with Irene in the RUNNING app (start-irene.ps1 -Dev), through
the dev socket only - no OS input, no screenshot, the mic deafened:

  .venv\Scripts\python scripts\chess_game_live.py [--skill 2] [--plies 160]

  colour       "let's play chess" -> she asks white or black; "white" -> said out loud
  the bug      an early "queen to e2" retracted while she thinks (the live 2026-10-15
               hang): the game must come back to his move, the full transcript played
  every ply    the HUD's echo of each board it drew (chess_shown -> chess_check) is
               checked by core against the game: every check must be ok
  never hung   after every turn: her move made, the board says YOUR MOVE
  review       at the end: her spoken summary (blunders, worst move, turning point)
               and the review on the panel - graph, key positions, every move

His moves come from a second, weak Stockfish, sent as words ("knight to f3").
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

import chess
import chess.engine
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from irene.chess_game import settings, spoken  # noqa: E402

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:34} {detail}", flush=True)


class Link:
    """The socket, drained all the time (a full queue gets the client dropped)."""

    def __init__(self, ws):
        self.ws = ws
        self.seen: list[dict] = []
        self.task = asyncio.create_task(self._read())

    async def _read(self):
        async for raw in self.ws:
            try:
                self.seen.append(json.loads(raw))
            except ValueError:
                pass

    async def send(self, msg: dict) -> None:
        await self.ws.send(json.dumps(msg))

    async def turn(self, text: str, wait: float = 90, **extra) -> tuple[str, list[dict]]:
        """Send his words; return what she said and everything seen, once she listens again."""
        start = len(self.seen)
        await self.send({"type": "command", "text": text, **extra})
        said, deadline = "", time.monotonic() + wait
        while time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            new = self.seen[start:]
            said = " ".join(m.get("speak", "") for m in new if m.get("type") == "reply")
            if said and any(m.get("type") == "state" and m.get("value") == "listening" for m in new[[m.get("type") for m in new].index("reply"):]):
                break
        await asyncio.sleep(1.2)  # the HUD's echoes of the last board
        return said, self.seen[start:]


def boards(seen):
    return [m["value"] for m in seen if m.get("type") == "draw" and m.get("value")]


def checks(seen):
    return [m for m in seen if m.get("type") == "chess_check"]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", type=int, default=2)
    ap.add_argument("--plies", type=int, default=160)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    _, him = await chess.engine.popen_uci(settings().engine)
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        link = Link(ws)
        await asyncio.sleep(1)
        await link.send({"type": "debug_ui", "action": "show"})
        await link.send({"type": "mic_deaf", "value": True})
        await asyncio.sleep(2)
        all_checks: list[dict] = []
        try:
            said, seen = await link.turn("Let's play chess!")
            print(f"      she: {said!r}")
            record("colour: she asks", "white" in said.lower() and "black" in said.lower(), said[:80])
            said, seen = await link.turn("White.")
            print(f"      she: {said!r}")
            record("colour: confirmed out loud", "white" in said.lower(), said[:80])
            all_checks += checks(seen)

            # the bug, replayed: an early transcript plays a move and is retracted
            # while she is still thinking; the full transcript is the same move
            board = chess.Board()
            said, seen = await link.turn("e4")
            all_checks += checks(seen)
            b = boards(seen)
            for san in b[-1]["history"]:
                board.push_san(san)
            print(f"      he: e4  she: {said!r}")
            early = asyncio.create_task(link.turn("Quid 2 E2", wait=30))
            await asyncio.sleep(0.35)  # mid-engine
            said, seen = await link.turn("queen to e2", retract=True)
            await early
            all_checks += checks(seen)
            b = boards(seen)
            last = b[-1] if b else {}
            print(f"      he: (early 'Quid 2 E2', retracted) queen to e2  she: {said!r}")
            record("retract: not called illegal", "legal" not in said.lower(), said[:80])
            record("retract: her move made, his turn", last.get("status") == "YOUR MOVE" and len(last.get("history", [])) == 4 and last["history"][2] == "Qe2",
                   f"{last.get('status')} {last.get('history')}")
            board = chess.Board()
            for san in last.get("history", []):
                board.push_san(san)

            # the rest of the game: his moves in words, every turn checked
            hung = 0
            plies = len(board.move_stack)
            game_over = False
            while plies < args.plies:
                r = await him.play(board, chess.engine.Limit(time=0.05), options={"Skill Level": args.skill})
                words = spoken(board, r.move)
                if r.move.promotion:
                    words = board.san(r.move)
                said, seen = await link.turn(words)
                all_checks += checks(seen)
                b = boards(seen)
                if not b:
                    # "which one?" - he says it in notation
                    print(f"      ({words!r} -> {said!r}; saying {board.san(r.move)!r})")
                    said, seen = await link.turn(board.san(r.move))
                    all_checks += checks(seen)
                    b = boards(seen)
                if not b:
                    record(f"ply {plies}: a board came", False, f"{words!r} -> {said!r}")
                    break
                last = b[-1]
                board = chess.Board()
                for san in last["history"]:
                    board.push_san(san)
                plies = len(board.move_stack)
                status = last.get("status", "")
                if board.is_game_over() or status in ("I RESIGN", "DRAW") or "MATE" in status:
                    game_over = True
                    print(f"      game over at ply {plies}: {status} - she: {said!r}")
                    review_seen = seen
                    break
                if status != "YOUR MOVE" or board.turn != chess.WHITE:
                    hung += 1
                    print(f"      !! ply {plies}: {status} after {words!r} - she: {said!r}")
                if plies % 10 == 1:
                    print(f"      ply {plies}: he {words!r} she {said[:70]!r}")
            record("never hung: always back to his move", hung == 0, f"{hung} turns left on MY MOVE, {plies} plies")
            if not game_over:
                said, review_seen = await link.turn("I resign", wait=180)
            # the review: wait for her summary and the panel
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline and not any(m.get("type") == "panel" and m.get("value") and m["value"].get("chess_review") for m in link.seen):
                await asyncio.sleep(0.5)
            await asyncio.sleep(8)
            panel = next((m["value"] for m in reversed(link.seen) if m.get("type") == "panel" and m.get("value") and m["value"].get("chess_review")), None)
            spoken_all = " ".join(m.get("speak", "") for m in link.seen[-400:] if m.get("type") == "reply")
            summary = next((m.get("speak", "") for m in reversed(link.seen) if m.get("type") == "reply" and "blunder" in m.get("speak", "")), "")
            print(f"      review: {summary!r}")
            record("review: spoken summary", "blunder" in summary and bool(re.search(r"move \d+|neither|no real mistakes", summary.lower())), summary[:100])
            kinds = [x["kind"] for x in panel["blocks"]] if panel else []
            record("review: on the panel", bool(panel) and kinds.count("image") >= 1, f"{panel['subtitle'] if panel else None} - {kinds.count('image')} images")
            text = " ".join(x.get("text", "") for x in panel["blocks"]) if panel else ""
            record("review: every move classified", any(k in text for k in ("best", "good")) and "1." in text, text[text.find('1.'):text.find('1.') + 60] if panel else "")
            # save it like research: the PDF tool on what the panel shows
            said, seen = await link.turn("Save this as a PDF in my downloads.", wait=120)
            print(f"      he: save this as a PDF  she: {said!r}")
            record("review: saved as a PDF", "pdf" in said.lower(), said[:100])
            await asyncio.sleep(2)
            all_checks += checks(link.seen)
            bad = [c for c in all_checks if not c.get("ok")]
            plies_checked = sorted({c.get("ply") for c in all_checks})
            record("every ply: HUD == game", bool(all_checks) and not bad, f"{len(all_checks)} echoes, plies {plies_checked[:3]}..{plies_checked[-3:]}, {len(bad)} diverged")
        finally:
            await link.send({"type": "mic_deaf", "value": False})
            await asyncio.sleep(1)
            link.task.cancel()
            await him.quit()
    ok = sum(r[1] for r in results)
    print(f"{ok}/{len(results)} passed")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
