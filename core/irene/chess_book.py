# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Irene's opening book: what she plays in the first moves - chosen here, never by the
language model and never by the engine.

  as White      always 1.e4
  as Black      vs 1.e4: the Sicilian, the Caro-Kann or the Nimzowitsch Defence,
                picked at random once per game
                vs 1.d4: the Nimzo-Indian when he allows it (1.d4 Nf6 2.c4 e6 3.Nc3 Bb4)
                anything else: straight to the engine

Each defence is a few main lines in SAN from move one. While the game is still on one
of the chosen defence's lines her next move is the line's next move (a random one where
lines branch); the first time he leaves them, the engine takes over for good. The lines
run at most MAX_DEPTH of her moves (6, as Black); config/chess.yaml book_moves cuts
that shorter - a book move is perfect theory, whatever her Elo.
"""
from __future__ import annotations

import random

import chess

AS_WHITE: tuple[str, ...] = ("e4",)

DEFENCES: dict[str, tuple[str, ...]] = {
    "Sicilian": (
        "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6",
        "e4 c5 Nf3 d6 Bb5+ Bd7 Bxd7+ Qxd7",
        "e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 Nf6 Nc3 e5",
        "e4 c5 Nf3 Nc6 Bb5 g6",
        "e4 c5 Nf3 e6 d4 cxd4 Nxd4 a6",
        "e4 c5 Nc3 Nc6 g3 g6 Bg2 Bg7",
        "e4 c5 Nc3 Nc6 Nf3 g6",
        "e4 c5 c3 Nf6 e5 Nd5 d4 cxd4",
        "e4 c5 d4 cxd4 c3 dxc3 Nxc3 Nc6",
        "e4 c5 Bc4 e6",
        "e4 c5 f4 d5",
        "e4 c5 d3 Nc6",
    ),
    "Caro-Kann": (
        "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5 Ng3 Bg6",
        "e4 c6 d4 d5 Nd2 dxe4 Nxe4 Bf5 Ng3 Bg6",
        "e4 c6 d4 d5 e5 Bf5 Nf3 e6",
        "e4 c6 d4 d5 exd5 cxd5 Bd3 Nc6 c3 Nf6",
        "e4 c6 d4 d5 exd5 cxd5 c4 Nf6 Nc3 e6",
        "e4 c6 Nc3 d5 Nf3 Bg4 h3 Bxf3 Qxf3 e6",
        "e4 c6 Nf3 d5 Nc3 Bg4",
        "e4 c6 d3 d5 Nd2 e5",
        "e4 c6 c4 d5 exd5 cxd5",
    ),
    "Nimzowitsch Defence": (
        "e4 Nc6 d4 d5 e5 Bf5",
        "e4 Nc6 d4 d5 Nc3 dxe4 d5 Ne5",
        "e4 Nc6 d4 d5 exd5 Qxd5 Nf3 Bg4",
        "e4 Nc6 Nf3 d6 d4 Nf6 Nc3 Bg4",
        "e4 Nc6 Nc3 e5 Nf3 Nf6",
        "e4 Nc6 Bc4 Nf6",
    ),
}

VS_D4: tuple[str, ...] = (
    "d4 Nf6 c4 e6 Nc3 Bb4 e3 O-O",
    "d4 Nf6 c4 e6 Nc3 Bb4 Qc2 O-O a3 Bxc3+ Qxc3 b6",
    "d4 Nf6 c4 e6 Nc3 Bb4 Nf3 c5",
    "d4 Nf6 c4 e6 Nc3 Bb4 f3 d5",
    "d4 Nf6 c4 e6 Nc3 Bb4 a3 Bxc3+ bxc3 c5",
    "d4 Nf6 c4 e6 Nc3 Bb4 Bg5 h6 Bh4 c5",
    # he sidesteps Nc3: no Nimzo today - a sound line, then the engine
    "d4 Nf6 c4 e6 Nf3 b6",
    "d4 Nf6 c4 e6 g3 d5",
    "d4 Nf6 Nf3 e6 c4 b6",
)


# the longest line, in her moves: Black's 6 (the Nimzo-Indian's ...b6); White's is 1.e4
MAX_DEPTH = max(len(line.split()) // 2 for line in (*VS_D4, *(x for d in DEFENCES.values() for x in d)))


def _clean(san: str) -> str:
    return san.rstrip("+#")


class Book:
    """Her book for one game: the defence she picked, and whether she has left it."""

    def __init__(self, rng: random.Random | None = None, max_moves: int = MAX_DEPTH):
        self.rng = rng or random.Random()
        self.defence: str | None = None
        self.out = False
        # her book moves at most (config/chess.yaml book_moves), then the engine
        self.max_moves = max_moves
        self.played = 0

    def move(self, board: chess.Board, her: chess.Color) -> chess.Move | None:
        """Her book move in this position, or None (the engine plays)."""
        if self.out or board.turn != her:
            return None
        if self.played >= self.max_moves:
            self.out = True
            return None
        history = _history(board)
        if her == chess.WHITE:
            lines: tuple[str, ...] = AS_WHITE
        elif history[:1] == ["e4"]:
            if self.defence is None:
                self.defence = self.rng.choice(sorted(DEFENCES))
            lines = DEFENCES[self.defence]
        elif history[:1] == ["d4"]:
            lines = VS_D4
        else:
            lines = ()
        nexts = sorted({seq[len(history)] for seq in (line.split() for line in lines)
                        if len(seq) > len(history) and [_clean(m) for m in seq[: len(history)]] == history})
        if not nexts:
            self.out = True
            return None
        try:
            move = board.parse_san(self.rng.choice(nexts))
            self.played += 1
            return move
        except ValueError:
            self.out = True
            return None


def _history(board: chess.Board) -> list[str]:
    replay = board.root()
    out = []
    for mv in board.move_stack:
        out.append(_clean(replay.san(mv)))
        replay.push(mv)
    return out
