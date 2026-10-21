# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""After a game: the review, the way chess.com does it - every number from the ENGINE.

  analyse()   a full-strength look at every position of the game; each move's
              centipawn loss (what the position was worth before it, from the
              mover's side, minus what it was worth after), classified
              best / good / inaccuracy / mistake / blunder, and an accuracy per side
              (lichess's win-percentage formula)
  Review      the counts, the single worst move, the turning point, the key positions
  content()   the panel (and, through tools/pdf.py, the PDF): the result, the
              evaluation graph, the key positions with the move the engine preferred,
              every move with its class

The model never rates a move here - she only says what this found (chess_game.py).
"""
from __future__ import annotations

import base64
import math
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import chess
import chess.svg

# evaluations are clipped here before the loss is taken: +12 to +8 is still winning,
# not a "blunder"; missing a mate still costs (a mate scores beyond the clip)
CLIP = 1000
MATE = 10000
KINDS = ("best", "good", "inaccuracy", "mistake", "blunder")
SYMBOL = {"best": "", "good": "", "inaccuracy": "?!", "mistake": "?", "blunder": "??"}


def classify(loss: int, played_best: bool) -> str:
    if played_best or loss <= 10:
        return "best"
    if loss < 50:
        return "good"
    if loss < 100:
        return "inaccuracy"
    if loss < 300:
        return "mistake"
    return "blunder"


def win_percent(cp: int) -> float:
    """White's winning chances (0-100) for an evaluation (lichess's curve)."""
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def move_accuracy(before_wp: float, after_wp: float) -> float:
    """lichess's per-move accuracy from the mover's win% before and after."""
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * max(0.0, before_wp - after_wp)) - 3.1669))


@dataclass
class Look:
    """One position, as the engine sees it: White's eval (cp, mates as +-MATE), its best move."""

    cp: int
    best: chess.Move | None = None
    mate: int | None = None


@dataclass
class Ply:
    index: int  # 0-based ply
    color: chess.Color
    san: str
    move: chess.Move
    fen_before: str
    before: int  # White's eval before the move (clipped)
    after: int  # White's eval after it (clipped)
    loss: int  # centipawns the mover gave away
    kind: str
    best_san: str | None
    best: chess.Move | None

    @property
    def number(self) -> int:
        return self.index // 2 + 1

    @property
    def label(self) -> str:
        """ "14. Qe2" / "14... Nxe4" """
        return f"{self.number}. {self.san}" if self.color == chess.WHITE else f"{self.number}... {self.san}"


@dataclass
class Review:
    plies: list[Ply]
    evals: list[int]  # White's eval after 0..N moves (clipped)
    he: chess.Color
    result: str  # "1-0", "0-1", "1/2-1/2", "*"
    ending: str  # how it ended, in words: "checkmate", "you resigned", ...
    accuracy: dict[bool, float] = field(default_factory=dict)
    counts: dict[bool, dict[str, int]] = field(default_factory=dict)
    worst: Ply | None = None
    turning: Ply | None = None
    key: list[Ply] = field(default_factory=list)

    def count(self, color: chess.Color, kind: str) -> int:
        return self.counts.get(color, {}).get(kind, 0)


def _clip(cp: int) -> int:
    return max(-CLIP, min(CLIP, cp))


def _terminal(board: chess.Board) -> Look | None:
    outcome = board.outcome(claim_draw=False)
    if outcome is None:
        return None
    if outcome.winner is None:
        return Look(0)
    return Look(MATE if outcome.winner == chess.WHITE else -MATE, mate=0)


async def analyse(board: chess.Board, look: Callable[[chess.Board], Awaitable[Look]], he: chess.Color,
                  result: str = "*", ending: str = "") -> Review:
    """The game in `board` (its move stack, from its root), every position looked at."""
    replay = board.root()
    positions = [replay.copy(stack=False)]
    sans: list[str] = []
    for mv in board.move_stack:
        sans.append(replay.san(mv))
        replay.push(mv)
        positions.append(replay.copy(stack=False))
    looks: list[Look] = []
    for pos in positions:
        looks.append(_terminal(pos) or await look(pos))
    evals = [_clip(lk.cp) for lk in looks]
    plies: list[Ply] = []
    acc: dict[bool, list[float]] = {chess.WHITE: [], chess.BLACK: []}
    for i, mv in enumerate(board.move_stack):
        pos = positions[i]
        color = pos.turn
        sign = 1 if color == chess.WHITE else -1
        best = looks[i].best
        played_best = best is not None and mv == best
        loss = 0 if played_best else max(0, sign * (evals[i] - evals[i + 1]))
        kind = classify(loss, played_best)
        best_san = pos.san(best) if best is not None and best in pos.legal_moves else None
        plies.append(Ply(i, color, sans[i], mv, pos.fen(), evals[i], evals[i + 1], loss, kind, best_san, best))
        wb, wa = win_percent(evals[i]), win_percent(evals[i + 1])
        if color == chess.BLACK:
            wb, wa = 100 - wb, 100 - wa
        acc[color].append(100.0 if played_best else move_accuracy(wb, wa))
    review = Review(plies, evals, he, result, ending)
    review.accuracy = {c: (sum(v) / len(v) if v else 0.0) for c, v in acc.items()}
    review.counts = {c: {k: sum(1 for p in plies if p.color == c and p.kind == k) for k in KINDS} for c in (chess.WHITE, chess.BLACK)}
    costly = [p for p in plies if p.loss > 0]
    review.worst = max(costly, key=lambda p: (p.loss, -p.index)) if costly else None
    review.turning = _turning(plies)
    bad = sorted((p for p in plies if p.kind in ("blunder", "mistake")), key=lambda p: -p.loss)
    if not bad:
        bad = sorted((p for p in plies if p.kind == "inaccuracy"), key=lambda p: -p.loss)
    review.key = sorted(bad[:3], key=lambda p: p.index)
    return review


def _band(cp: int) -> int:
    return 1 if cp >= 150 else -1 if cp <= -150 else 0


def _turning(plies: list[Ply]) -> Ply | None:
    """The move after which the game belonged to someone else: the biggest swing that
    moved the evaluation across a band (White better / level / Black better). None
    when nothing ever swung."""
    crossing = [p for p in plies if _band(p.before) != _band(p.after) and p.loss >= 100]
    pool = crossing or [p for p in plies if p.loss >= 100]
    return max(pool, key=lambda p: (p.loss, -p.index)) if pool else None


# ---- on the panel ----------------------------------------------------------------------------


def _uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def graph_svg(review: Review, width: int = 640, height: int = 200) -> str:
    """White's winning chances across the game: the white area is White's share - the
    way chess.com draws it. Blunders and mistakes are marked where they happened."""
    n = max(1, len(review.evals) - 1)
    pad_l, pad_b, pad_t = 8, 18, 8
    w, h = width - 2 * pad_l, height - pad_b - pad_t

    def xy(i: int, cp: int) -> tuple[float, float]:
        return pad_l + w * i / n, pad_t + h * (1 - win_percent(cp) / 100)

    pts = [xy(i, cp) for i, cp in enumerate(review.evals)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"{pad_l},{pad_t + h} {line} {pad_l + w},{pad_t + h}"
    mid = pad_t + h / 2
    out = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}' font-family='Segoe UI, Arial, sans-serif'>",
        f"<rect x='0' y='0' width='{width}' height='{height}' fill='#2b2a28'/>",
        f"<polygon points='{area}' fill='#ece9e2'/>",
        f"<line x1='{pad_l}' y1='{mid:.1f}' x2='{pad_l + w}' y2='{mid:.1f}' stroke='#8a8780' stroke-width='1' stroke-dasharray='4 3'/>",
        f"<polyline points='{line}' fill='none' stroke='#8a8780' stroke-width='2' stroke-linejoin='round'/>",
    ]
    for move in range(10, n // 2 + 1, 10):
        x = pad_l + w * (2 * move - 1) / n
        out.append(f"<text x='{x:.1f}' y='{height - 4}' font-size='11' fill='#b8b5ad' text-anchor='middle'>{move}</text>")
    for p in review.plies:
        if p.kind not in ("blunder", "mistake"):
            continue
        x, y = pts[p.index + 1]
        colour = "#d64545" if p.kind == "blunder" else "#e08a2e"
        out.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='5' fill='{colour}' stroke='#2b2a28' stroke-width='2'/>")
    out.append("</svg>")
    return "".join(out)


def position_svg(p: Ply, he: chess.Color) -> str:
    board = chess.Board(p.fen_before)
    arrows = [chess.svg.Arrow(p.move.from_square, p.move.to_square, color="#d64545cc")]
    if p.best is not None and p.best != p.move:
        arrows.append(chess.svg.Arrow(p.best.from_square, p.best.to_square, color="#3a9a5bcc"))
    return chess.svg.board(board, orientation=he, arrows=arrows, size=320, coordinates=True)


def _pawns(cp: int) -> str:
    if abs(cp) >= CLIP:
        return "winning" if cp > 0 else "losing"
    return f"{cp / 100:+.1f}"


def _who(review: Review, color: chess.Color) -> str:
    return "you" if color == review.he else "Irene"


def content(review: Review, when: str = "") -> dict:
    """The review as panel content - and, through tools/pdf.py, as paper."""
    he, she = review.he, not review.he
    his_side = "White" if he == chess.WHITE else "Black"
    sub = f"Game review · you {his_side.lower()} vs Irene · {review.result} · {review.ending}" + (f" · {when}" if when else "")
    blocks: list[dict] = [{"kind": "heading", "text": "Summary"}]

    def tally(color: chess.Color) -> str:
        return (f"accuracy {review.accuracy.get(color, 0):.0f}% · {review.count(color, 'blunder')} blunders · "
                f"{review.count(color, 'mistake')} mistakes · {review.count(color, 'inaccuracy')} inaccuracies · "
                f"{review.count(color, 'best')} best moves")

    lines = [f"You ({his_side}): {tally(he)}", f"Irene ({'Black' if he == chess.WHITE else 'White'}): {tally(she)}"]
    if review.worst is not None:
        w = review.worst
        alt = f" - {w.best_san} was better" if w.best_san and w.best_san != w.san else ""
        lines.append(f"Worst move: {w.label} by {_who(review, w.color)} ({w.kind}, {w.loss} centipawns){alt}")
    if review.turning is not None:
        t = review.turning
        lines.append(f"Turning point: {t.label} by {_who(review, t.color)} - the evaluation went from {_pawns(t.before)} to {_pawns(t.after)}")
    blocks.append({"kind": "box", "tone": "points", "title": "Engine verdict", "blocks": [{"kind": "text", "text": "\n".join(lines)}]})
    blocks.append({"kind": "heading", "text": "Evaluation"})
    blocks.append({"kind": "image", "src": _uri(graph_svg(review)), "alt": "Evaluation graph across the game",
                   "caption": "White's winning chances move by move (white area = White). Red dots: blunders; orange: mistakes."})
    if review.key:
        blocks.append({"kind": "heading", "text": "Key positions"})
        for p in review.key:
            alt = f" The engine preferred {p.best_san} (green arrow)." if p.best_san and p.best_san != p.san else ""
            blocks.append({"kind": "heading", "level": 3, "text": f"{p.label}{SYMBOL[p.kind]} - {p.kind} by {_who(review, p.color)}"})
            blocks.append({"kind": "image", "src": _uri(position_svg(p, he)), "alt": f"Position before {p.label}",
                           "caption": f"Played {p.san} (red arrow): {_pawns(p.before)} -> {_pawns(p.after)}, {p.loss} centipawns lost.{alt}"})
    blocks.append({"kind": "heading", "text": "Every move"})
    rows: list[str] = []
    for i in range(0, len(review.plies), 2):
        pair = review.plies[i: i + 2]
        cells = [f"{p.san}{SYMBOL[p.kind]} {p.kind}" + (f" (-{p.loss})" if p.loss and p.kind != 'best' else "") for p in pair]
        first = pair[0]
        prefix = f"{first.number}." if first.color == chess.WHITE else f"{first.number}... "
        rows.append(f"{prefix} " + "  |  ".join(cells))
    blocks.append({"kind": "text", "text": "\n".join(rows) or "No moves were played."})
    blocks.append({"kind": "text", "text": "Every number here is Stockfish's, at full strength - centipawn loss per move: "
                                          "best (the engine's move, or within 10), good (<50), inaccuracy (<100), mistake (<300), blunder (300+)."})
    return {"title": "Game review - you vs Irene", "subtitle": sub, "blocks": blocks, "chess_review": True}
