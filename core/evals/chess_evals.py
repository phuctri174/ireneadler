"""Chess evals: does she hear his moves, his commands - and is what she says true?

  .venv\\Scripts\\python evals\\chess_evals.py [--games N]

  moves      spoken moves (as Whisper writes them) -> the right legal move; illegal
             ones refused with a reason; talk never taken for a move
  commands   start / resign / takeback / stop, and phrasings that must NOT trigger
  truth      whole games against a second engine: every time she says a piece
             hangs, that she is winning or losing, an independent full-strength look
             at the same position must agree
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import chess
import chess.engine

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from irene import chess_talk  # noqa: E402
from irene.chess_game import ChessGame, colour_choice, command, parse, settings  # noqa: E402

START = chess.STARTING_FEN
OPEN = "r1bqkbnr/pppp1ppp/2n5/4p3/3PP3/5N2/PPP2PPP/RNBQKB1R b KQkq - 0 3"
MID = "r3k2r/pppq1ppp/2npbn2/2b1p3/2B1P3/2NPBN2/PPPQ1PPP/R3K2R w KQkq - 4 8"
PROMO = "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"

# (position, what he said, the move it must be: SAN, "ILLEGAL", "WHICH" or None = not a move)
MOVES: list[tuple[str, str, str | None]] = [
    (START, "e4", "e4"), (START, "E4.", "e4"), (START, "e four", "e4"), (START, "Pawn to E4", "e4"),
    (START, "I'll play e4", "e4"), (START, "Irene, e4 please", "e4"), (START, "d4", "d4"), (START, "dee four", "d4"),
    (START, "c4", "c4"), (START, "see four", "c4"), (START, "Knight to F3", "Nf3"), (START, "night to f3", "Nf3"),
    (START, "Knight F3", "Nf3"), (START, "Nf3", "Nf3"), (START, "g1 f3", "Nf3"), (START, "G1 to F3", "Nf3"),
    (START, "knight to c3", "Nc3"), (START, "Night C3.", "Nc3"), (START, "f4", "f4"), (START, "pawn to g three", "g3"),
    (START, "knight to f4", "ILLEGAL"), (START, "e5", "ILLEGAL"), (START, "bishop to c4", "ILLEGAL"),
    (START, "queen h5", "ILLEGAL"), (START, "king e2", "ILLEGAL"), (START, "castle kingside", "ILLEGAL"),
    (OPEN, "e takes d4", "exd4"), (OPEN, "pawn takes d4", "exd4"), (OPEN, "exd4", "exd4"), (OPEN, "knight takes d4", "Nxd4"),
    (OPEN, "Knight takes D4.", "Nxd4"), (OPEN, "knight takes the pawn", "Nxd4"), (OPEN, "take the pawn", "WHICH"),
    (OPEN, "knight to f6", "Nf6"), (OPEN, "bishop to b4 check", "Bb4+"), (OPEN, "queen to h4", "Qh4"),
    (MID, "castle kingside", "O-O"), (MID, "castles queenside", "O-O-O"), (MID, "castle short", "O-O"),
    (MID, "Castle long.", "O-O-O"), (MID, "O-O", "O-O"), (MID, "castle", "WHICH"), (MID, "knight to d5", "Nd5"),
    (MID, "knight takes e5", "Nxe5"), (MID, "take the bishop", "WHICH"), (MID, "bishop takes c5", "Bxc5"),
    (MID, "bishop takes the bishop on c5", "Bxc5"), (MID, "rook to b1", "Rb1"), (MID, "Rook B1", "Rb1"),
    (MID, "the queen goes to e2", "Qe2"), (MID, "knight g5", "Ng5"), (MID, "h3", "h3"), (MID, "a pawn to a3", "a3"),
    (MID, "rook to e1", "ILLEGAL"), (MID, "king to g2", "ILLEGAL"),
    (PROMO, "a8", "a8=Q+"), (PROMO, "a8 queen", "a8=Q+"), (PROMO, "a8 knight", "a8=N"), (PROMO, "promote to a knight", "a8=N"),
    (PROMO, "pawn to a8 and make it a rook", "a8=R+"),
    (MID, "what a great game", None), (MID, "are you winning?", None), (MID, "hmm let me think", None),
    (MID, "the bishop is annoying", None), (MID, "you're good at this", None), (MID, "I love this opening", None),
    (MID, "wait", None), (MID, "nice move Irene", None), (START, "how do I get better at chess?", None),
]

# (what he said, a game on?, finished?, the command it must be)
COMMANDS: list[tuple[str, bool, bool, str | None]] = [
    ("Let's play chess!", False, False, "start"), ("let's play a game of chess", False, False, "start"),
    ("Wanna play chess?", False, False, "start"), ("Do you want to play chess?", False, False, "start"),
    ("Irene, play chess with me", False, False, "start"), ("Play chess with me.", False, False, "start"),
    ("How about a game of chess?", False, False, "start"), ("Fancy a game of chess?", False, False, "start"),
    ("I challenge you to chess", False, False, "start"), ("Let's play chess, I'll be black", False, False, "start"),
    ("Start a game of chess", False, False, "start"), ("Rematch!", False, True, "start"), ("new game", True, False, "start"),
    ("play again", False, True, "start"),
    ("I resign", True, False, "resign"), ("I give up.", True, False, "resign"), ("Okay, you win.", True, False, "resign"),
    ("take that back", True, False, "takeback"), ("Can I take it back?", True, False, "takeback"),
    ("undo that", True, False, "takeback"), ("takeback please", True, False, "takeback"),
    ("let's stop the game", True, False, "stop"), ("stop playing", True, False, "stop"), ("I'm done with chess", True, False, "stop"),
    ("end the game", True, False, "stop"),
    # must NOT trigger
    ("I played chess with my dad yesterday.", False, False, None), ("What's the Sicilian Defence?", False, False, None),
    ("Explain the Queen's Gambit.", False, False, None), ("Who's the best chess player ever?", False, False, None),
    ("My friend is really good at chess.", False, False, None), ("I resign from my job tomorrow lol", False, False, None),
    ("take that back, you're not funny", False, False, None), ("new game on Steam is great", False, False, None),
    ("stop the music", True, False, "move"),
    # after the game: the engine's review
    ("Review the game", False, True, "review"), ("Can you analyse that game?", False, True, "review"),
    ("How did I play?", False, True, "review"), ("Where did I go wrong?", False, True, "review"),
    ("What was my worst move?", False, True, "review"), ("go over the game with me", False, True, "review"),
    ("Review the game", False, False, None), ("how did I play football today", False, False, None),
    ("review my essay", False, True, None),
]

# his answer to "white or black?" -> HIS colour, "random", or None (not an answer: the model)
COLOURS: list[tuple[str, str | None]] = [
    ("White.", "white"), ("white please", "white"), ("I'll take white", "white"), ("I'll be black", "black"),
    ("Black.", "black"), ("you be white", "black"), ("you can have black", "white"), ("I'll go first", "white"),
    ("you go first", "black"), ("You choose.", "random"), ("surprise me", "random"), ("I don't mind", "random"),
    ("either is fine", "random"), ("flip a coin", "random"), ("up to you", "random"), ("doesn't matter", "random"),
    ("hmm", None), ("are you any good?", None), ("what time is it", None), ("let me think", None),
]


def run_moves() -> tuple[int, int, list[str]]:
    fails = []
    for fen, said, want in MOVES:
        board = chess.Board(fen)
        p = parse(said, board)
        got = None if p is None else (board.san(p.move) if p.move else "WHICH" if p.options else "ILLEGAL")
        if got != want:
            fails.append(f"move {said!r}: got {got}, want {want}")
    return len(MOVES) - len(fails), len(MOVES), fails


def run_colours() -> tuple[int, int, list[str]]:
    fails = [f"colour {said!r}: got {colour_choice(said)}, want {want}" for said, want in COLOURS if colour_choice(said) != want]
    return len(COLOURS) - len(fails), len(COLOURS), fails


def run_commands() -> tuple[int, int, list[str]]:
    fails = []
    for said, active, finished, want in COMMANDS:
        got = command(said, active, finished)
        # mid-game, "move" only means the parser gets a look - and talk isn't a move
        if want == "move" and got == "move" and parse(said, chess.Board()) is not None:
            got = "a move?!"
        if got != want:
            fails.append(f"command {said!r} (game {'on' if active else 'off'}): got {got}, want {want}")
    return len(COMMANDS) - len(fails), len(COMMANDS), fails


async def run_truth(games: int) -> tuple[int, int, list[str]]:
    """She says it; an independent look at the same position must agree."""
    cfg = settings()
    _, him = await chess.engine.popen_uci(cfg.engine)
    _, judge = await chess.engine.popen_uci(cfg.engine)
    checked, fails = 0, []
    try:
        for n in range(games):
            game = ChessGame()
            await game.start("I'll be white")
            skill = [0, 3, 8, 20][n % 4]
            plies = 0
            while game.active and plies < 120:
                before = game.board.copy()
                r = await him.play(game.board, chess.engine.Limit(time=0.03), options={"Skill Level": skill})
                beats = await game.play(r.move)
                plies += 1
                said = " ".join(b.text for b in beats).lower()
                # "hangs": after his move, the judge's best reply captures a non-pawn
                if any(w in said for w in ("hangs your", "sitting there", "your poor", "leave your", "was hanging")):
                    checked += 1
                    after = before.copy()
                    after.push(r.move)
                    look = await judge.analyse(after, chess.engine.Limit(depth=14))
                    best = look.get("pv", [None])[0]
                    if best is None or not after.is_capture(best) or after.piece_type_at(best.to_square) == chess.PAWN:
                        fails.append(f"game {n}: said a piece hangs after {before.san(r.move)} - the judge's best reply is {after.san(best) if best else None}")
                # "winning" / "losing": the judge scores her position the same way
                for kind, sign in (("winning", 1), ("losing", -1)):
                    if any(line.lower() in said for line in chess_talk.LINES[kind]):
                        checked += 1
                        look = await judge.analyse(game.board, chess.engine.Limit(depth=14))
                        cp = look["score"].pov(game.her).score(mate_score=10000)
                        if cp * sign < 100:
                            fails.append(f"game {n}: said she is {kind} at {cp:+d} cp for her")
            await game.close()
    finally:
        await him.quit()
        await judge.quit()
    return checked - len(fails), checked, fails


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=4)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    started = time.perf_counter()
    m_ok, m_n, m_f = run_moves()
    c_ok, c_n, c_f = run_commands()
    k_ok, k_n, k_f = run_colours()
    c_f += k_f
    t_ok, t_n, t_f = await run_truth(args.games) if Path(settings().engine).exists() else (0, 0, ["engine not installed"])
    for line in [*m_f, *c_f, *t_f]:
        print("FAIL", line)
    print(json.dumps({"moves": f"{m_ok}/{m_n}", "commands": f"{c_ok}/{c_n}", "colours": f"{k_ok}/{k_n}", "true_claims": f"{t_ok}/{t_n}",
                      "games": args.games, "minutes": round((time.perf_counter() - started) / 60, 1)}))
    return 0 if not (m_f or c_f or t_f) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
