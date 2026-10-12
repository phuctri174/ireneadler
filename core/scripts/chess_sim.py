r"""Chess with Irene, simulated end to end against the real engine (no app, no voice):

  .venv\Scripts\python scripts\chess_sim.py

  scripted   an opening said aloud the way he would: an illegal move, a takeback, a
             piece left hanging - what she says to each, and her face
  full       whole games to the end: him as a weak engine (she should win) and as
             a strong one (she should lose), so every ending is heard
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import chess
import chess.engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from irene.chess_game import ChessGame, command, settings  # noqa: E402


def show(beats) -> None:
    for b in beats:
        print(f"    [{b.cue or '-':13}] {b.text}" + (f"   (board: {b.board['status']})" if b.board else ""))


async def turn(game: ChessGame, said: str):
    print(f"  he: {said}")
    kind = command(said, game.active, game.finished)
    beats = {"start": game.start, "stop": game.stop, "resign": game.resign, "takeback": game.takeback}.get(kind)
    beats = await beats(said) if kind == "start" else await beats() if beats else await game.his_move(said)
    if beats is None:
        print("    (not a move - the model answers)")
    else:
        show(beats)


async def scripted() -> None:
    game = ChessGame()
    for said in ("Let's play chess!", "e4", "knight to f3", "bishop to b5", "what a game, huh?", "queen to h7",
                 "take that back", "castle kingside", "rook e1"):
        await turn(game, said)
    await game.close()


async def full(him_skill: int) -> str:
    game = ChessGame()
    _, him = await chess.engine.popen_uci(settings().engine)
    await turn(game, "let's play a game of chess")
    plies = 0
    while game.active and plies < 160:
        r = await him.play(game.board, chess.engine.Limit(time=0.05), options={"Skill Level": him_skill})
        said = game.board.san(r.move)
        await turn(game, said)
        plies += 1
    await him.quit()
    await game.close()
    outcome = game.board.outcome()
    return f"{outcome.termination.name if outcome else 'unfinished'} winner={None if not outcome else ('irene' if outcome.winner == game.her else 'him' if outcome.winner is not None else 'draw')} after {len(game.board.move_stack)} plies"


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    print("== scripted ==")
    await scripted()
    print("\n== full game: he plays at skill 0 ==")
    weak = await full(0)
    print("\n== full game: he plays at skill 20 ==")
    strong = await full(20)
    print("\n", weak, "\n", strong)


if __name__ == "__main__":
    asyncio.run(main())
