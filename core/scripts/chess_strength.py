r"""How strong Irene really plays: whole games of the real ChessGame (book, engine, the
full-strength looks in between - everything his games go through) against a fixed
opponent, every one of her moves scored by a separate full-strength analyser.

  .venv\Scripts\python scripts\chess_strength.py --games 10 --label now
  .venv\Scripts\python scripts\chess_strength.py --elo 1450 --games 10 --label old

  opponent     Stockfish at Skill Level 8, 100 ms a move (its own process)
  analyser     Stockfish full strength, depth 12, its own process: the score before
               and after each of her moves, from her side, clamped to +-1000 cp
  loss         max(0, before - after); ACPL is its mean over her ENGINE moves (book
               moves are listed apart); a blunder loses 300 cp or more, a mistake 100+

Writes logs/chess_strength_<label>.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

import chess
import chess.engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from irene.chess_game import ChessGame, settings  # noqa: E402

CLAMP = 1000
DEPTH = 12


def cp(score: chess.engine.PovScore, colour: chess.Color) -> int:
    return max(-CLAMP, min(CLAMP, score.pov(colour).score(mate_score=100000)))


async def one_game(n: int, her_white: bool, cfg, analyser, opponent_skill: int) -> dict:
    game = ChessGame(cfg)
    _, him = await chess.engine.popen_uci(cfg.engine)
    moves: list[dict] = []
    original = game._her_move

    async def scored():
        board = game.board.copy()
        before = await analyser.analyse(board, chess.engine.Limit(depth=DEPTH))
        t0 = time.perf_counter()
        move = await original()
        took = time.perf_counter() - t0
        book = not game.book.out
        after_board = board.copy()
        after_board.push(move)
        if after_board.is_checkmate():
            after = CLAMP
        else:
            after = cp((await analyser.analyse(after_board, chess.engine.Limit(depth=DEPTH)))["score"], board.turn)
        b = cp(before["score"], board.turn)
        moves.append({"ply": len(board.move_stack), "san": board.san(move), "book": book, "best": board.san(before["pv"][0]),
                      "before": b, "after": after, "loss": max(0, b - after), "ms": round(took * 1000)})
        return move

    game._her_move = scored
    await game.start("let's play chess")
    await game.his_move("black" if her_white else "white")
    while game.active and len(game.board.move_stack) < 200:
        if game.board.turn == game.her:  # (only before her first move as White)
            break
        r = await him.play(game.board, chess.engine.Limit(time=0.1), options={"Skill Level": opponent_skill})
        await game.his_move(game.board.san(r.move))
    await him.quit()
    await game.close()
    outcome = game.board.outcome(claim_draw=False)
    result = "unfinished" if outcome is None else "draw" if outcome.winner is None else "irene" if outcome.winner == game.her else "him"
    return {"game": n, "her": "white" if her_white else "black", "result": result, "plies": len(game.board.move_stack), "moves": moves}


def summary(games: list[dict]) -> dict:
    eng = [m for g in games for m in g["moves"] if not m["book"]]
    book = [m for g in games for m in g["moves"] if m["book"]]
    losses = [m["loss"] for m in eng]
    return {
        "games": len(games),
        "results": {r: sum(g["result"] == r for g in games) for r in ("irene", "him", "draw", "unfinished")},
        "engine_moves": len(eng),
        "acpl": round(statistics.mean(losses), 1) if losses else None,
        "median_loss": statistics.median(losses) if losses else None,
        "blunders_300": sum(x >= 300 for x in losses),
        "mistakes_100": sum(100 <= x < 300 for x in losses),
        "blunders_per_game": round(sum(x >= 300 for x in losses) / len(games), 2),
        "best_move_rate": round(sum(m["san"] == m["best"] for m in eng) / len(eng), 3) if eng else None,
        "book_moves": len(book),
        "book_acpl": round(statistics.mean(m["loss"] for m in book), 1) if book else None,
        "max_book_moves_in_a_game": max((sum(m["book"] for m in g["moves"]) for g in games), default=0),
        "ms_per_engine_move": round(statistics.mean(m["ms"] for m in eng)) if eng else None,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=10)
    ap.add_argument("--elo", type=int, default=None, help="override config/chess.yaml elo")
    ap.add_argument("--think-ms", type=int, default=None)
    ap.add_argument("--opponent-skill", type=int, default=8)
    ap.add_argument("--label", default="run")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = settings()
    if args.elo is not None:
        cfg.elo = args.elo
    if args.think_ms is not None:
        cfg.think_ms = args.think_ms
    _, analyser = await chess.engine.popen_uci(cfg.engine)
    games = []
    for n in range(args.games):
        g = await one_game(n, n % 2 == 0, cfg, analyser, args.opponent_skill)
        games.append(g)
        eng = [m["loss"] for m in g["moves"] if not m["book"]]
        print(f"game {n}: her {g['her']:5} {g['result']:10} {g['plies']:3} plies  engine moves {len(eng):3}  "
              f"acpl {statistics.mean(eng) if eng else 0:6.1f}  blunders {sum(x >= 300 for x in eng)}", flush=True)
    await analyser.quit()
    s = summary(games)
    print(json.dumps(s, indent=1))
    out = Path(__file__).resolve().parent.parent / "logs" / f"chess_strength_{args.label}.json"
    out.write_text(json.dumps({"label": args.label, "elo": cfg.elo, "think_ms": cfg.think_ms, "cfg": vars(cfg) | {"hotwords": None},
                               "summary": s, "games": games}, indent=1), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    asyncio.run(main())
