# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Chess with Irene: a real engine plays her moves, he plays his by voice.

The language model never chooses a move and never judges one. Here:

  parse()     his words -> a legal move: "e4", "knight to f3", "castle kingside",
              "take the bishop", "e takes d5", "g1 f3", "e8 queen" - with what
              Whisper makes of them ("night to F3", "e four"). A move that isn't
              legal is refused with the reason; one that could be two moves asks
              which ("the knight on b1 or the one on f3?")
  ChessGame   the game: her opening book (chess_book.py), then Stockfish limited to
              a club player's rating (config/chess.yaml: UCI_Elo) picks her moves -
              ONE position, every change atomic; a full-strength look at the position after every
              move decides what she says about it, so what she says is true -
              "that hangs your knight" only when the engine's best reply takes it
  Beat        what she says and shows, in order: a line, its cue, and the board
              as it should look when she starts saying it

His commands are matched in code (command()): start, resign, takeback, stop, review.
Before move one she asks his colour (colour_choice()); after the game the engine
reviews every move (chess_review.py) and she narrates what it found.
Everything else he says mid-game goes to the model as usual, with the game in
her context (section()) - she can banter, but she never picks or rates a move.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import chess
import chess.engine
import yaml

from . import chess_book, chess_review
from . import chess_talk as talk

log = logging.getLogger("irene.chess")

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "chess.yaml"

PIECE_WORDS = {
    "pawn": chess.PAWN, "pawns": chess.PAWN, "porn": chess.PAWN, "pond": chess.PAWN,
    "knight": chess.KNIGHT, "knights": chess.KNIGHT, "night": chess.KNIGHT, "nite": chess.KNIGHT, "horse": chess.KNIGHT,
    "bishop": chess.BISHOP, "bishops": chess.BISHOP,
    "rook": chess.ROOK, "rooks": chess.ROOK, "rock": chess.ROOK, "brook": chess.ROOK, "rookie": chess.ROOK,
    "queen": chess.QUEEN, "queens": chess.QUEEN, "queenie": chess.QUEEN, "quid": chess.QUEEN,
    "king": chess.KING, "kings": chess.KING,
}
PIECE_NAME = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop", chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king"}
VALUE = {chess.PAWN: 100, chess.KNIGHT: 300, chess.BISHOP: 310, chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0}

_NUMBERS = {"one": "1", "won": "1", "two": "2", "too": "2", "three": "3", "tree": "3", "four": "4", "for": "4", "fore": "4",
            "five": "5", "six": "6", "seven": "7", "eight": "8", "ate": "8"}
# what Whisper writes for a file letter said on its own ("bee four")
_LETTERS = {"ay": "a", "bee": "b", "be": "b", "see": "c", "sea": "c", "cee": "c", "dee": "d", "e": "e", "ee": "e",
            "eff": "f", "ef": "f", "gee": "g", "aitch": "h", "age": "h", "each": "h"}

_SQUARE = re.compile(r"\b([a-h])\s?-?\s?([1-8])\b")
_SAN = re.compile(r"^(?:[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=?[QRBN])?|O-O(?:-O)?|0-0(?:-0)?)[+#]?$")
_CAPTURE = re.compile(r"\b(?:takes|take|taking|took|captures|capture|capturing|x|eats|grab|grabs|by)\b")
_CASTLE = re.compile(r"\b(?:castle|castles|castling|o-o(?:-o)?|0-0(?:-0)?)\b")
_FILLER = re.compile(
    r"\b(?:irene|okay|ok|um+|uh+|hmm+|so|well|then|and|now|please|alright|right|"
    r"i'?ll\s+(?:play|go|move|do|take)|i\s+(?:play|go|move)|let\s+me\s+(?:play|go|move|try)|my\s+move\s+is|i'?m\s+going|"
    r"i\s+want\s+to|move|play|go|with\s+(?:my|the)|the|my|your|a|an|on|square|to|from|check|mate|checkmate)\b"
)


@dataclass
class Parsed:
    """What his words were, as a move."""

    move: chess.Move | None = None
    # several legal moves fit what he said: which one?
    options: list[chess.Move] = field(default_factory=list)
    # nothing legal fits: why not, in her words
    illegal: str = ""


def _normalise(text: str) -> str:
    t = (text or "").lower()
    t = t.replace("’", "'")
    t = re.sub(r"[,.!?;:\"]", " ", t)
    # "e four", "f three", "bee four" -> e4, f3, b4
    words = t.split()
    out: list[str] = []
    for w in words:
        if out and w in _NUMBERS and (out[-1] in _LETTERS or re.fullmatch(r"[a-h]", out[-1])):
            prev = _LETTERS.get(out[-1], out[-1])
            out[-1] = prev + _NUMBERS[w]
            continue
        if out and re.fullmatch(r"[1-8]", w) and out[-1] in _LETTERS:
            out[-1] = _LETTERS[out[-1]] + w
            continue
        out.append(w)
    t = " ".join(out)
    t = re.sub(r"\b(king|queen)\s*'?s?\s*side\b", r"\1side", t)
    t = re.sub(r"\b(king|queen)'s\b", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def _squares(t: str) -> list[int]:
    return [chess.parse_square(f + r) for f, r in _SQUARE.findall(t)]


def _pieces(t: str) -> list[tuple[int, int]]:
    """(position in the text, piece type) for every piece he named."""
    return [(m.start(), PIECE_WORDS[m.group(0)]) for m in re.finditer(r"\b(?:" + "|".join(sorted(PIECE_WORDS, key=len, reverse=True)) + r")\b", t)]


def _promotion(t: str) -> int | None:
    m = re.search(r"(?:promot\w*|=|equals|becomes|make\s+it|into)\s*(?:(?:to|a|an)\s+)*(queen|rook|bishop|knight|night|q|r|b|n)\b", t)
    if not m:
        m = re.search(r"\b[a-h][18]\s*(queen|rook|bishop|knight)\b", t)
    if not m:
        return None
    w = m.group(1)
    return {"q": chess.QUEEN, "r": chess.ROOK, "b": chess.BISHOP, "n": chess.KNIGHT}.get(w) or PIECE_WORDS.get(w)


def _castle(board: chess.Board, t: str) -> Parsed | None:
    if not _CASTLE.search(t) and not re.search(r"\b(?:kingside|queenside)\b", t):
        return None
    side = "q" if re.search(r"queenside|long|o-o-o|0-0-0", t) else "k" if re.search(r"kingside|short|o-o|0-0", t) else None
    legal = [m for m in board.legal_moves if board.is_castling(m)]
    pick = [m for m in legal if side is None or (board.is_kingside_castling(m) if side == "k" else board.is_queenside_castling(m))]
    if len(pick) == 1:
        return Parsed(pick[0])
    if len(pick) > 1:
        return Parsed(options=pick)
    which = {"k": "kingside", "q": "queenside", None: ""}[side]
    if board.is_check():
        why = "you can't castle out of check"
    elif not board.has_castling_rights(board.turn):
        why = "your king has already moved"
    elif side == "k" and not board.has_kingside_castling_rights(board.turn) or side == "q" and not board.has_queenside_castling_rights(board.turn):
        why = f"that rook has already moved, so no castling {which}"
    else:
        why = f"you can't castle {which} right now - there's something in the way, or the king would cross an attacked square".replace("  ", " ")
    return Parsed(illegal=why)


def _from_san(board: chess.Board, text: str) -> chess.Move | None:
    """A move he (or Whisper) wrote in notation: "Nf3", "exd5", "O-O"."""
    for token in re.findall(r"[A-Za-z0-9=+#-]+", text or ""):
        if not _SAN.match(token) or token.islower() and len(token) == 2:
            continue
        try:
            return board.parse_san(token)
        except ValueError:
            continue
    return None


def parse(text: str, board: chess.Board) -> Parsed | None:
    """His words as a move in this position - or None when they are not a move at all."""
    t = _normalise(text)
    castled = _castle(board, t)
    if castled is not None:
        return castled
    san = _from_san(board, text)
    if san is not None:
        return Parsed(san)
    squares = _squares(t)
    named = _pieces(t)
    capture = _CAPTURE.search(t)
    promo = _promotion(t)
    if promo is not None:
        # "a8 queen": the queen is what the pawn becomes, not what moves
        named = [(at, p) for at, p in named if not (p == promo and (at > (t.find(chess.square_name(squares[0])) if squares else -1)))]
        if not squares:
            promotions = [mv for mv in board.legal_moves if mv.promotion == promo]
            if len(promotions) == 1:
                return Parsed(promotions[0])
    # "e takes d5": a pawn from the e-file
    pawn_file = None
    m = re.search(r"(?:^|\s)([a-h])\s+(?:takes|take|captures|x)\b", t)
    if m:
        pawn_file = chess.FILE_NAMES.index(m.group(1))
    if not squares and not (capture and named) and not named:
        return None
    if not squares and named and not capture:
        # just "knight": not a move he can mean
        return None
    mover = victim = None
    if capture:
        before = [p for at, p in named if at < capture.start()]
        after = [p for at, p in named if at > capture.start()]
        mover = before[-1] if before else (chess.PAWN if pawn_file is not None else None)
        victim = after[0] if after else None
    elif named:
        mover = named[0][1]
    origin = target = None
    if len(squares) >= 2:
        origin, target = squares[0], squares[1]
    elif len(squares) == 1:
        target = squares[0]

    def fits(move: chess.Move) -> bool:
        piece = board.piece_at(move.from_square)
        if piece is None:
            return False
        if origin is not None and move.from_square != origin:
            return False
        if target is not None and move.to_square != target:
            return False
        if mover is not None and piece.piece_type != mover:
            return False
        if pawn_file is not None and (piece.piece_type != chess.PAWN or chess.square_file(move.from_square) != pawn_file):
            return False
        if capture and not board.is_capture(move):
            return False
        if victim is not None:
            taken = chess.PAWN if board.is_en_passant(move) else (board.piece_type_at(move.to_square))
            if taken != victim:
                return False
        if move.promotion and move.promotion != (promo or chess.QUEEN):
            return False
        return True

    legal = [mv for mv in board.legal_moves if fits(mv)]
    if mover is None and not capture and target is not None and origin is None and len(legal) > 1:
        # "e4" is a pawn move when a pawn can make it
        pawns = [mv for mv in legal if board.piece_type_at(mv.from_square) == chess.PAWN]
        legal = pawns or legal
    if len(legal) == 1:
        return Parsed(legal[0])
    if len(legal) > 1:
        return Parsed(options=legal)
    return Parsed(illegal=_why_not(board, fits, mover, victim, target, capture is not None))


def _why_not(board: chess.Board, fits, mover: int | None, victim: int | None, target: int | None, capture: bool) -> str:
    """Why nothing legal fits what he said, in her words."""
    pseudo = [mv for mv in board.pseudo_legal_moves if fits(mv)]
    if pseudo:
        return "you're in check - deal with that first" if board.is_check() else "that would leave your king in check"
    where = chess.square_name(target) if target is not None else ""
    what = PIECE_NAME.get(mover, "piece") if mover else "piece"
    if target is not None:
        own = board.piece_at(target)
        if own is not None and own.color == board.turn:
            return f"you've already got your own {PIECE_NAME[own.piece_type]} on {where}"
        if capture and own is None:
            return f"there's nothing on {where} to take"
    if victim is not None:
        return f"none of your pieces can take a {PIECE_NAME[victim]} right now"
    if mover is not None and not board.pieces(mover, board.turn):
        return f"you don't have a {what} any more"
    if target is not None:
        return f"no {what} of yours can get to {where} from there" if mover else f"none of your pieces can reach {where} in one move"
    return "I can't find a legal move like that"



def spoken(board: chess.Board, move: chess.Move) -> str:
    """A move as she says it: "knight to f3", "pawn takes d5", "castles kingside"."""
    if board.is_castling(move):
        return "castles kingside" if board.is_kingside_castling(move) else "castles queenside"
    piece = PIECE_NAME[board.piece_type_at(move.from_square)]
    to = chess.square_name(move.to_square)
    if board.is_capture(move):
        taken = chess.PAWN if board.is_en_passant(move) else board.piece_type_at(move.to_square)
        said = f"{piece} takes {PIECE_NAME[taken]} on {to}"
    else:
        said = f"{piece} to {to}"
    if move.promotion:
        said += f", and it's a {PIECE_NAME[move.promotion]}"
    return said


def which(board: chess.Board, options: list[chess.Move]) -> str:
    """Her question when his move could be two: "the knight on b1 or the one on f3?" """
    if all(board.is_castling(m) for m in options):
        return "kingside or queenside"
    kinds = {board.piece_type_at(m.from_square) for m in options}
    if len(kinds) == 1:
        name = PIECE_NAME[kinds.pop()]
        froms = sorted({chess.square_name(m.from_square) for m in options})
        if len(froms) > 1:
            return f"the {name} on {froms[0]} or the one on {froms[1]}" if len(froms) == 2 else f"which {name} - " + ", ".join(froms)
        tos = sorted({chess.square_name(m.to_square) for m in options})
        return f"to {', '.join(tos[:-1])} or {tos[-1]}"
    return " or ".join(spoken(board, m) for m in options[:3])


# ---- commands --------------------------------------------------------------------------

_START = re.compile(
    r"^\W*(?:(?:hey\s+)?irene\W+)?(?:(?:let'?s|let\s+us|wanna|do\s+you\s+want\s+to|want\s+to|shall\s+we|can\s+we|could\s+we|"
    r"how\s+about|fancy|you\s+up\s+for|up\s+for|time\s+for)\s+(?:a\s+)?(?:play\s+|have\s+(?:a\s+)?|do\s+(?:a\s+)?)?(?:a\s+)?(?:game\s+of\s+|quick\s+game\s+of\s+|round\s+of\s+)?chess"
    r"|(?:play|start)\s+(?:a\s+)?(?:game\s+of\s+)?chess(?:\s+with\s+me)?|i\s+challenge\s+you\s+to\s+(?:a\s+game\s+of\s+)?chess"
    r"|(?:let'?s\s+)?play\s+(?:a\s+game\s+of\s+)?chess)\b",
    re.I,
)
_AGAIN = re.compile(r"\b(?:rematch|new\s+game|play\s+again|another\s+(?:game|one)|one\s+more\s+game|again\s*!?$)\b", re.I)
_SHE_WHITE = re.compile(r"\b(?:i'?ll\s+(?:be|play|take)\s+black|i\s+(?:want|wanna)\s+(?:to\s+)?(?:be|play)\s+black|you\s+(?:be|play|take|are|'re)\s+white|you\s+(?:go|move|start)\s+first|you\s+start|your\s+move\s+first)\b", re.I)
_RESIGN = re.compile(r"\b(?:i\s+resign|i\s+give\s+up|i\s+surrender|you\s+win|i\s+concede|i\s+forfeit)\b", re.I)
_TAKEBACK = re.compile(r"\b(?:take\s+(?:it|that|this|the\s+move|my\s+move)\s+back|take\s*back|takeback|undo(?:\s+(?:that|the\s+move|my\s+move))?|wait\s+no,?\s+(?:not\s+that|undo)|let\s+me\s+(?:redo|change)\s+that)\b", re.I)
_STOP = re.compile(
    r"\b(?:(?:stop|end|quit|abandon|cancel|finish)\s+(?:the\s+|this\s+|our\s+)?(?:game|chess|match|playing)|let'?s\s+stop(?:\s+playing)?|no\s+more\s+chess|"
    r"i'?m\s+done\s+(?:playing|with\s+chess|with\s+this\s+game)|enough\s+chess|stop\s+playing)\b",
    re.I,
)


_REVIEW = re.compile(
    r"\b(?:(?:review|analy[sz]e|go\s+over|go\s+through|look\s+over|break\s+down)\s+(?:the\s+|that\s+|our\s+|this\s+|my\s+)?(?:last\s+)?game"
    r"|game\s+review|post-?mortem|how\s+did\s+i\s+(?:play|do)|(?:what|where)\s+did\s+i\s+go\s+wrong|my\s+(?:worst|biggest)\s+(?:move|mistake|blunder))\b",
    re.I,
)

# his colour, before move one: what HE takes ("white", "I'll be black"), what he gives
# her ("you be white"), or hers to pick ("you choose", "surprise me")
_HER_WHITE = re.compile(r"\byou\s+(?:can\s+)?(?:be|play|take|have|get|are|'re)\s+white\b|\byou\s+(?:go|move|start)\s+first\b|\byou\s+start\b", re.I)
_HER_BLACK = re.compile(r"\byou\s+(?:can\s+)?(?:be|play|take|have|get|are|'re)\s+black\b|\bi(?:'ll|\s+will)?\s+(?:go|move|start)\s+first\b", re.I)
_RANDOM = re.compile(
    r"\b(?:you\s+(?:choose|pick|decide)|your\s+(?:choice|call|pick)|surprise\s+me|random(?:ly)?|either(?:\s+one|\s+is\s+fine)?|any(?:\s+colou?r|\s+one)|"
    r"(?:it\s+)?doesn'?t\s+matter|whatever|i\s+don'?t\s+(?:mind|care)|flip\s+a\s+coin|toss\s+a\s+coin|up\s+to\s+you|dealer'?s\s+choice|you\s+decide)\b",
    re.I,
)


def colour_choice(text: str) -> str | None:
    """His answer to "white or black?": "white" / "black" (HIS colour), "random", or None."""
    said = (text or "").strip()
    if _HER_WHITE.search(said):
        return "black"
    if _HER_BLACK.search(said):
        return "white"
    white, black = re.search(r"\bwhite\b", said, re.I), re.search(r"\bblack\b", said, re.I)
    if white and not black:
        return "white"
    if black and not white:
        return "black"
    if _RANDOM.search(said) or _SHE_WHITE.search(said):
        return "black" if _SHE_WHITE.search(said) else "random"
    return None


def command(text: str, active: bool, finished: bool = False) -> str | None:
    """His words as a chess command: "start", "resign", "takeback", "stop", "review" -
    or "move" for anything else while a game is on (the parser decides), None when
    it's not chess at all."""
    said = (text or "").strip()
    if _START.search(said) or ((active or finished) and _AGAIN.search(said) and not _STOP.search(said)):
        return "start"
    if not active:
        return "review" if finished and _REVIEW.search(said) else None
    if _STOP.search(said):
        return "stop"
    if _RESIGN.search(said):
        return "resign"
    if _TAKEBACK.search(said):
        return "takeback"
    return "move"


# ---- the game -----------------------------------------------------------------------------


@dataclass
class Beat:
    """One thing she says while playing: the line, its cue, and the board to show
    as she starts saying it (None: leave the board as it is)."""

    text: str
    cue: str | None = None
    board: dict | None = None
    sfx: str | None = None


@dataclass
class Settings:
    engine: str = r"C:\irene\stockfish\stockfish.exe"
    # her strength: Stockfish's own limiter (UCI_LimitStrength + UCI_Elo)
    elo: int = 1350
    # her search, capped both ways: whichever comes first
    think_ms: int = 300
    max_depth: int = 6
    # her opening book, in her moves (chess_book.MAX_DEPTH is the longest line)
    book_moves: int = chess_book.MAX_DEPTH
    analyse_ms: int = 250
    # the post-game review: ms per position, at full strength
    review_ms: int = 120
    # the watchdog: an engine call longer than this is a hung engine
    engine_timeout_s: float = 10.0
    hotwords: list[str] = field(default_factory=list)


def settings(path: Path = CONFIG) -> Settings:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raw = {}
    s = Settings()
    for key in ("engine", "elo", "think_ms", "max_depth", "book_moves", "analyse_ms", "review_ms", "engine_timeout_s", "hotwords"):
        if key in raw:
            setattr(s, key, raw[key])
    return s


# Stockfish 19's UCI_Elo range
ELO_MIN, ELO_MAX = 1320, 3190
# commentary and the review read the position at full strength (it must be true)
FULL = {"UCI_LimitStrength": False}


class EngineDown(Exception):
    """The engine timed out or died twice running (restarted in between)."""


# behind by this much (her side, centipawns): no move of hers repeats a position
BEHIND_CP = -100
# her unravelling, from the engine's numbers - each said once, only as it gets worse
RATTLE = {1: "crumbling", 2: "collapsing", 3: "he_has_mate", 4: "mate_close", 5: "mate_next"}


def rattle_level(her_cp: int, mate: int | None) -> int:
    """How far gone she is: 0 fine, 1 crumbling (-6 pawns), 2 collapsing (-10), 3 he has
    a mate, 4 it is two or three moves away, 5 his next move mates."""
    if mate is not None and mate < 0:
        return 5 if -mate <= 1 else 4 if -mate <= 3 else 3
    return 2 if her_cp <= -1000 else 1 if her_cp <= -600 else 0


def fresh_moves(board: chess.Board) -> list[chess.Move]:
    """Her legal moves that don't bring back a position the game has already had."""
    out = []
    for move in board.legal_moves:
        board.push(move)
        if not board.is_repetition(2):
            out.append(move)
        board.pop()
    return out


def _score(info: dict, color: chess.Color) -> int:
    """Centipawns from `color`'s side (a mate is +-10000, nearer is bigger)."""
    return info["score"].pov(color).score(mate_score=10000)


def placement(fen: str) -> str:
    """What a board SHOWS: its pieces and whose move it is (the first two FEN fields)."""
    return " ".join((fen or "").split()[:2])


# everything a move changes - put back as one when a move is cut off half-way
_STATE = ("board", "her", "active", "finished", "choosing", "her_eval", "mood", "opening_said", "pending",
          "_rattle", "_praised", "book", "unreviewed", "ending")


class ChessGame:
    """One game against him. `engine` may be injected (the tests' fake).

    ONE position: self.board. The engine is handed it for every call (python-chess
    sends the root and the move list - Stockfish keeps no game of its own), the HUD
    only draws its FEN (board_spec) and echoes back what it drew (shown()), and his
    words are checked for legality against it alone (parse()).

    Every change to the game is a transaction (_atomic): it works on the live
    position and is rolled back whole if it is cut off - his turn superseded, the
    early start retracted, the engine dead - so his move never lands without her
    answer (live 2026-10-15: a retracted early turn left Qe2 on the board, Black to
    move, and nothing ever replied)."""

    def __init__(self, cfg: Settings | None = None, engine=None, rng: random.Random | None = None):
        self.cfg = cfg or settings()
        self.rng = rng or random.Random()
        self.board = chess.Board()
        self.her = chess.BLACK
        self.engine = engine
        self._transport = None
        self._own_engine = engine is None
        self.active = False
        self.finished = False
        # asked "white or black?" and waiting for his answer
        self.choosing = False
        self.lines = talk.Lines(self.rng)
        # what the position was worth to her after her last move (centipawns)
        self.her_eval = 0
        self.mood = "even"  # even | winning | losing
        self.opening_said = False
        self.pending: list[chess.Move] = []
        # how far her position has unravelled, as she has said it (0 = not at all): she
        # never resigns - she plays on to the mate, and gets more rattled on the way
        self._rattle = 0
        # the ply of her last "nice move": praise is rationed
        self._praised = -99
        self.book = chess_book.Book(self.rng, self.cfg.book_moves)
        # her engine moves this game, and how many were not the engine's own top line
        self.engine_moves = self.limited_picks = 0
        # a finished game not yet reviewed, and how it ended
        self.unreviewed = False
        self.ending = ""
        self.last_review: chess_review.Review | None = None
        self.last_review_content: dict | None = None
        self._lock = asyncio.Lock()
        # the game as the last finished change left it (a turn's starting point)
        self._committed = self.snapshot()
        # what the HUD said it drew, per ply - and every time they disagreed
        self.divergences: list[dict] = []

    # -- one source of truth, transactions --------------------------------------------------

    def snapshot(self) -> dict:
        snap = {k: getattr(self, k) for k in _STATE}
        snap["board"] = self.board.copy()
        snap["pending"] = list(self.pending)
        snap["book"] = copy.copy(self.book)
        return snap

    def restore(self, snap: dict) -> None:
        for k in _STATE:
            setattr(self, k, snap[k])
        self.board = snap["board"].copy()
        self.pending = list(snap["pending"])
        self.book = copy.copy(snap["book"])
        self._committed = self.snapshot()

    def committed(self) -> dict:
        """The game as the last COMPLETED change left it - never a move half-made. A
        turn marks this when it starts; retracting the turn restores it."""
        return {**self._committed, "board": self._committed["board"].copy(), "pending": list(self._committed["pending"]),
                "book": copy.copy(self._committed["book"])}

    async def _atomic(self, work) -> list[Beat] | None:
        """One change to the game, all or nothing."""
        async with self._lock:
            snap = self.snapshot()
            try:
                beats = await work()
                self._committed = self.snapshot()
                return beats
            except EngineDown as error:
                self.restore(snap)
                log.error("chess: engine down (%s) - position put back to ply %d, %s to move",
                          error, len(self.board.move_stack), "white" if self.board.turn else "black")
                return [Beat(self.lines.pick("engine_down"), self.lines.cue("engine_down"), self.board_spec() if self.active else None)]
            except BaseException:
                # cut off (a newer command, a retracted early start) or broken: as if it never began
                self.restore(snap)
                log.warning("chess: move cut off half-way - position put back to ply %d (%s)",
                            len(self.board.move_stack), self.board.fen())
                raise

    def fen_at(self, ply: int) -> str | None:
        if not 0 <= ply <= len(self.board.move_stack):
            return None
        replay = self.board.root()
        for mv in self.board.move_stack[:ply]:
            replay.push(mv)
        return replay.fen()

    def _log_ply(self, who: str, san: str) -> None:
        """Every ply: the position, and the one the engine is handed (its root and the
        moves - rebuilt here exactly as python-chess sends it). Any difference is the
        bug this replaced."""
        ply = len(self.board.move_stack)
        given = self.fen_at(ply)
        same = given == self.board.fen()
        (log.info if same else log.error)("chess ply %d (%s %s): board %s | engine given %s%s",
                                          ply, who, san, self.board.fen(), "the same" if same else given, "" if same else "  DIVERGED")

    def shown(self, ply: int, fen: str, replayed: str | None = None, refused: str | None = None) -> bool:
        """The HUD's echo of a live board it drew: the pieces and turn it shows, and the
        position its move list replays to (chessboard.ts). Compared with the game's
        position at that ply - a difference is logged loud and kept."""
        want = self.fen_at(ply)
        problems = []
        if refused:
            problems.append(f"the HUD refused the board ({refused})")
        if want is None:
            problems.append(f"no ply {ply} in this game ({len(self.board.move_stack)} played)")
        else:
            if placement(fen) != placement(want):
                problems.append(f"HUD shows {placement(fen)!r}")
            if replayed is not None and placement(replayed) != placement(want):
                problems.append(f"HUD move list replays to {placement(replayed)!r}")
        if problems:
            self.divergences.append({"ply": ply, "want": want, "shown": fen, "replayed": replayed, "why": problems})
            log.error("chess ply %d DIVERGED: game %s | %s", ply, want, "; ".join(problems))
            return False
        log.info("chess ply %d shown: HUD matches the game (%s)", ply, placement(want))
        return True

    # -- engine (behind a watchdog) -----------------------------------------------------------

    async def _ensure_engine(self) -> None:
        if self.engine is None:
            self._transport, self.engine = await chess.engine.popen_uci(self.cfg.engine)
            elo = max(ELO_MIN, min(ELO_MAX, int(self.cfg.elo)))
            # her strength, Stockfish's own way: every play() uses it, every look overrides
            # it for that one call (python-chess sends it back before her next search)
            await self.engine.configure({"UCI_LimitStrength": True, "UCI_Elo": elo})
            # UCI never acknowledges a setoption; readyok says the engine has read it,
            # and the engine's own config is what goes into every later search
            await self.engine.ping()
            log.info("chess engine started: %s - sent setoption UCI_LimitStrength true, UCI_Elo %d; readyok; engine config now %s",
                     self.engine.id.get("name"), elo, {k: self.engine.config.get(k) for k in ("UCI_LimitStrength", "UCI_Elo")})

    async def _kill_engine(self) -> None:
        """A hung or dead engine: gone, so the next call starts a fresh one."""
        if not self._own_engine:
            return
        transport, self._transport, self.engine = self._transport, None, None
        if transport is not None:
            try:
                transport.kill()
            except Exception:  # noqa: BLE001 - already dead is fine
                pass

    async def close(self) -> None:
        if self.engine is not None and self._own_engine:
            try:
                await asyncio.wait_for(self.engine.quit(), 2)
            except Exception:  # noqa: BLE001 - a dead engine is closed either way
                await self._kill_engine()
            self.engine, self._transport = None, None

    async def _engine(self, what: str, call):
        """One engine call under the watchdog: a timeout or a dead engine restarts it and
        tries once more; twice is EngineDown - she says so, nothing hangs."""
        for attempt in (1, 2):
            await self._ensure_engine()
            try:
                return await asyncio.wait_for(call(self.engine), self.cfg.engine_timeout_s)
            except (asyncio.TimeoutError, chess.engine.EngineError, OSError) as error:
                log.error("chess engine %s failed (attempt %d): %s - restarting it", what, attempt, type(error).__name__ + (f": {error}" if str(error) else ""))
                await self._kill_engine()
        raise EngineDown(what)

    async def _look(self, board: chess.Board) -> dict:
        """The position at full strength: score and the best move."""
        board = board.copy()
        return await self._engine("look", lambda e: e.analyse(board, chess.engine.Limit(time=self.cfg.analyse_ms / 1000), options=FULL))

    async def _her_move(self) -> chess.Move:
        book = self.book.move(self.board, self.her)
        if book is not None:
            log.info("chess: book move %s (%s)", self.board.san(book), self.book.defence or "book")
            return book
        board = self.board.copy()
        # behind, she never shuffles into a repetition to escape: the engine searches only
        # the moves that don't bring back an earlier position (at her usual strength)
        roots = fresh_moves(board) if self.her_eval <= BEHIND_CP else None
        if roots is not None and len(roots) == board.legal_moves.count():
            roots = None  # nothing repeats anyway
        if roots:
            log.info("chess: behind (%+d) - %d of %d moves don't repeat a position", self.her_eval, len(roots), board.legal_moves.count())
        # a capped search (whichever comes first), from an EMPTY hash: the full-strength
        # look at this same position a moment ago filled the table, and a weakened search
        # reading it plays the deep search's moves (measured: scripts/chess_strength.py)
        limit = chess.engine.Limit(time=self.cfg.think_ms / 1000, depth=self.cfg.max_depth)
        info = chess.engine.INFO_PV

        async def play(e):
            await e.configure({"Clear Hash": None})
            if roots:
                return await e.play(board, limit, root_moves=roots, info=info)
            return await e.play(board, limit, info=info)

        result = await self._engine("play", play)
        # the engine's acknowledgement, move by move: under UCI_LimitStrength Stockfish
        # often plays a move other than its own top line - the limiter at work
        top = (result.info or {}).get("pv") or [None]
        self.limited_picks += top[0] is not None and top[0] != result.move
        self.engine_moves += 1
        log.info("chess: her move %s, engine's top line %s%s (%d of %d of her engine moves off its top line)",
                 result.move, top[0], " - the limiter picked another" if top[0] not in (None, result.move) else "",
                 self.limited_picks, self.engine_moves)
        # (an engine's draw offer or resignation is never taken: the game ends by the board)
        if result.move is None or result.move not in self.board.legal_moves:
            # the engine answered a different position than the game's: never played
            log.error("chess: engine move %s is not legal in %s - DIVERGED", result.move, self.board.fen())
            raise EngineDown("an illegal engine move")
        return result.move

    # -- the board she shows ----------------------------------------------------------------

    def board_spec(self, status: str = "") -> dict:
        last = self.board.peek() if self.board.move_stack else None
        spec = {
            "template": "chessboard",
            "live": True,
            "fen": self.board.fen(),
            # the ply this position is: the HUD echoes it back with what it drew
            "ply": len(self.board.move_stack),
            "flip": self.her == chess.WHITE,
            "title": "YOU VS IRENE",
            "status": status or ("WHITE OR BLACK?" if self.choosing else "YOUR MOVE" if self.board.turn != self.her else "MY MOVE"),
            # the WHOLE game: the HUD numbers it from move one (a slice of it once made
            # Black's moves look like White's: "4. Ngf6 Nc3")
            "history": self._san_history(),
        }
        if last is not None:
            spec["last"] = [chess.square_name(last.from_square), chess.square_name(last.to_square)]
        if self.board.is_check():
            king = self.board.king(self.board.turn)
            if king is not None:
                spec["highlight"] = [chess.square_name(king)]
        return spec

    def _san_history(self) -> list[str]:
        replay = self.board.root()
        out = []
        for mv in self.board.move_stack:
            out.append(replay.san(mv))
            replay.push(mv)
        return out

    # -- what he asks for ----------------------------------------------------------------------

    def _reset(self) -> None:
        self.board = chess.Board()
        self.her = chess.BLACK
        self.active, self.finished, self.choosing = True, False, False
        self.her_eval, self.mood, self.opening_said, self.pending, self._rattle, self._praised = 0, "even", False, [], 0, -99
        self.book = chess_book.Book(self.rng, self.cfg.book_moves)
        self.engine_moves = self.limited_picks = 0
        self.unreviewed, self.ending = False, ""
        self.divergences = []

    async def start(self, text: str = "", defence: str | None = None) -> list[Beat]:
        """A new game. `defence`: the book defence she plays as Black against 1.e4 -
        one she just studied (study.py) - instead of one picked at random."""
        async def work():
            await self._ensure_engine()
            self._reset()
            if defence in chess_book.DEFENCES:
                self.book.defence = defence
                log.info("chess: her defence pinned to the %s", defence)
            colour = colour_choice(text)
            if colour is None:
                # which side he wants comes first
                self.choosing = True
                log.info("chess: new game - asked him which colour")
                return [Beat(self.lines.pick("ask_colour"), self.lines.cue("ask_colour"), self.board_spec(), sfx="charge")]
            return await self._begin(colour)

        return await self._atomic(work)

    async def _begin(self, colour: str) -> list[Beat]:
        """His colour settled: said out loud before move one - then, if she's white, her move."""
        coin = colour == "random"
        if coin:
            colour = self.rng.choice(("white", "black"))
        self.her = chess.BLACK if colour == "white" else chess.WHITE
        self.choosing = False
        log.info("chess: he plays %s%s", colour, " (her coin)" if coin else "")
        kind = ("coin_" if coin else "start_") + ("he_white" if colour == "white" else "he_black")
        beats = [Beat(self.lines.pick(kind), self.lines.cue("start"), self.board_spec(), sfx=None if coin else "charge")]
        if self.her == chess.WHITE:
            beats[0].board = self.board_spec("MY MOVE")
            beats += await self._reply()
        return beats

    async def stop(self) -> list[Beat]:
        async def work():
            self.active, self.choosing = False, False
            self.finished = True
            self._end("stopped")
            return [Beat(self.lines.pick("stop"), self.lines.cue("stop"), None)]

        return await self._atomic(work)

    async def resign(self) -> list[Beat]:
        async def work():
            self.active, self.finished, self.choosing = False, True, False
            self._end("you resigned")
            return [Beat(self.lines.pick("he_resigns"), self.lines.cue("he_resigns"), self.board_spec("YOU RESIGNED"))]

        return await self._atomic(work)

    def _end(self, how: str) -> None:
        self.ending = how
        self.unreviewed = len(self.board.move_stack) >= 4

    async def takeback(self) -> list[Beat]:
        async def work():
            # his last move and her answer to it
            his = [i for i, _ in enumerate(self.board.move_stack) if (i % 2 == 0) == (self.her == chess.BLACK)]
            if not his:
                return [Beat(self.lines.pick("nothing_to_take_back"), self.lines.cue("takeback"), None)]
            undo = len(self.board.move_stack) - his[-1]
            for _ in range(undo):
                self.board.pop()
            self.pending = []
            log.info("chess: takeback (%d plies) - now ply %d: %s", undo, len(self.board.move_stack), self.board.fen())
            return [Beat(self.lines.pick("takeback"), self.lines.cue("takeback"), self.board_spec())]

        return await self._atomic(work)

    def claims(self, text: str) -> bool:
        """These words are for the board: a move (legal or not), the answer to her
        "which one?", or - before move one - his colour. Cheap - no engine."""
        if not self.active:
            return False
        if self.choosing:
            return colour_choice(text) is not None
        if self._resolve_pending(text) is not None:
            return True
        return parse(text, self.board) is not None

    async def his_move(self, text: str) -> list[Beat] | None:
        """His words, mid-game. None: they weren't a move (the model answers)."""

        async def work():
            await self._ensure_engine()
            if self.choosing:
                colour = colour_choice(text)
                return None if colour is None else await self._begin(colour)
            if self.board.turn == self.her:
                # her move is owed (it can't be, every move is atomic - but if it ever
                # is, she plays it rather than judge his against the wrong side)
                log.error("chess: my move was owed at ply %d - playing it before his", len(self.board.move_stack))
                beats = await self._reply()
                beats[0].text = f"{self.lines.pick('owed')} {beats[0].text}"
                return beats
            parsed = self._resolve_pending(text) or parse(text, self.board)
            if parsed is None:
                return None
            if parsed.options:
                self.pending = parsed.options
                return [Beat(self.lines.pick("which", options=which(self.board, parsed.options)), self.lines.cue("which"), None)]
            self.pending = []
            if parsed.illegal:
                log.info("chess: illegal %r at ply %d (%s) - %s", text, len(self.board.move_stack), self.board.fen(), parsed.illegal)
                return [Beat(self.lines.pick("illegal", reason=parsed.illegal), self.lines.cue("illegal"), None)]
            return await self._play(parsed.move)

        return await self._atomic(work)

    def _resolve_pending(self, text: str) -> Parsed | None:
        """"The one on f3" after she asked which."""
        if not self.pending:
            return None
        squares = _squares(_normalise(text))
        named = [p for _, p in _pieces(_normalise(text))]
        pick = [m for m in self.pending if (not squares or m.from_square in squares or m.to_square in squares) and (not named or self.board.piece_type_at(m.from_square) in named or m.promotion in named)]
        if len(pick) == 1:
            return Parsed(pick[0])
        return None

    async def play(self, move: chess.Move) -> list[Beat]:
        """His (legal) move, her reaction to it, and her answer - one transaction."""
        return await self._atomic(lambda: self._play(move))

    async def _play(self, move: chess.Move) -> list[Beat]:
        before = await self._look(self.board)
        his_before = _score(before, not self.her)
        best = before.get("pv", [None])[0]
        san = self.board.san(move)
        mover = self.board.piece_type_at(move.from_square)
        captured = chess.PAWN if self.board.is_en_passant(move) else self.board.piece_type_at(move.to_square)
        self.board.push(move)
        self._log_ply("he", san)
        beats: list[Beat] = []
        if self.board.is_game_over():
            return beats + self._over(his=True)
        after = await self._look(self.board)
        his_after = _score(after, not self.her)
        delta = his_after - his_before
        threat = after.get("pv", [None])[0]
        kind, extra = self._judge(move, mover, captured, best, delta, his_after, threat)
        line = self.lines.pick(kind, **extra) if kind else ""
        opening = self._opening(his=True)
        if opening:
            line = f"{line} {opening}".strip() if line else opening
        if self.board.is_check():
            line = f"{self.lines.pick('check_by_him')} {line}".strip()
            kind = kind or "check_by_him"
        log.info("chess: his %s (%+d cp for him, %s)", san, delta, kind or "plain")
        beats.append(Beat(line, self.lines.cue(kind) if line else None, self.board_spec("THINKING..."), sfx="click"))
        beats += await self._reply(hanging=extra.get("piece") if kind == "hangs" else None, threat=threat)
        return beats

    def _judge(self, move, mover, captured, best, delta: int, his_after: int, threat) -> tuple[str | None, dict]:
        """What his move deserves, from the engine's numbers."""
        # a piece he just left hanging: her best reply takes it, and it costs him
        if threat is not None and delta <= -200 and self.board.is_capture(threat):
            taken = self.board.piece_type_at(threat.to_square)
            if taken and taken != chess.PAWN:
                return "hangs", {"piece": PIECE_NAME[taken]}
        if delta <= -250:
            return "blunder", {}
        if delta <= -110:
            return "dubious", {}
        ply = len(self.board.move_stack)
        # praise is earned: not for book moves, not for the obvious recapture, and not
        # every move (then it's noise) - unless it really swung the game
        recapture = captured is not None and len(self.board.move_stack) >= 2 and self.board.move_stack[-2].to_square == move.to_square
        fresh = ply - self._praised >= 6
        if delta >= 150 or (best is not None and move == best and ply > 10 and fresh and not recapture
                            and (delta >= 40 or self.board.is_check() or self.lines.rng.random() < 0.3)):
            self._praised = ply
            return "his_good", {}
        if captured and captured != chess.PAWN:
            return "he_takes", {"piece": PIECE_NAME[captured]}
        return None, {}

    async def _reply(self, hanging: str | None = None, threat=None) -> list[Beat]:
        """Her move, and what she says about it and the position after it."""
        move = await self._her_move()
        said = spoken(self.board, move)
        captured = chess.PAWN if self.board.is_en_passant(move) else self.board.piece_type_at(move.to_square)
        san = self.board.san(move)
        self.board.push(move)
        self._log_ply("she", san)
        parts: list[str] = []
        kind = "her_move"
        if hanging and captured and PIECE_NAME.get(captured) == hanging:
            parts.append(self.lines.pick("take_hanging", piece=hanging, move=said))
            kind = "take_hanging"
        elif hanging:
            # it IS hanging - she says so, and that she's letting it go
            parts.append(self.lines.pick("spare_hanging", piece=hanging, move=said))
            kind = "spare_hanging"
        elif captured and captured != chess.PAWN:
            parts.append(self.lines.pick("she_takes", piece=PIECE_NAME[captured], move=said))
            kind = "she_takes"
        else:
            parts.append(self.lines.pick("her_move", move=said))
        opening = self._opening(his=False)
        if opening:
            parts.append(opening)
        if self.board.is_game_over():
            beats = [Beat(" ".join(parts), self.lines.cue(kind), self.board_spec())]
            return beats + self._over(his=False)
        if self.board.is_check():
            parts.append(self.lines.pick("check_by_her"))
            kind = "check_by_her"
        beats = [Beat(" ".join(parts), self.lines.cue(kind), self.board_spec("YOUR MOVE"), sfx="click")]
        # the position after her move, from her side: said when it changes hands
        look = await self._look(self.board)
        her = _score(look, self.her)
        self.her_eval = her
        mood = "winning" if her >= 250 else "losing" if her <= -250 else "even"
        mate = look["score"].pov(self.her).mate()
        # she never resigns: as it falls apart she says so, more rattled each step
        rattle = rattle_level(her, mate)
        if rattle == 0 and her > -250:
            self._rattle = 0
        elif rattle > self._rattle:
            self._rattle = rattle
            self.mood = "mated" if mate is not None and mate < 0 else "losing"
            kind = RATTLE[rattle]
            log.info("chess: unravelling (%+d cp, mate %s) - %s", her, mate, kind)
            beats.append(Beat(self.lines.pick(kind), self.lines.cue(kind), None))
            return beats
        if mate is not None and mate > 0 and self.mood != "mating":
            self.mood = "mating"
            beats.append(Beat(self.lines.pick("she_sees_mate"), self.lines.cue("winning"), None))
        elif mate is not None and mate < 0 and self.mood != "mated":
            self.mood = "mated"
            beats.append(Beat(self.lines.pick("he_has_mate"), self.lines.cue("losing"), None))
        elif mate is None and mood != self.mood and mood != "even":
            self.mood = mood
            beats.append(Beat(self.lines.pick(mood), self.lines.cue(mood), None))
        elif mate is None and mood == "even" and self.mood in ("winning", "losing"):
            self.mood = "even"
            beats.append(Beat(self.lines.pick("even_again"), self.lines.cue("even_again"), None))
        return beats

    def _over(self, his: bool) -> list[Beat]:
        """The game just ended on a move (his if `his`) - by the board alone: mate,
        stalemate, too little material, or the board's own automatic rules (fivefold
        repetition, 75 moves). A draw is never claimed or agreed."""
        self.active, self.finished = False, True
        outcome = self.board.outcome()
        if outcome is not None and outcome.winner is not None:
            kind = "she_mates" if outcome.winner == self.her else "he_mates"
            status = "MATE - I WIN!" if kind == "she_mates" else "MATE - YOU WIN"
            how = "checkmate"
        else:
            kind = "draw"
            status = "DRAW"
            how = outcome.termination.name.lower().replace("_", " ") if outcome is not None else "draw"
        log.info("chess: game over - %s (%s)", kind, how)
        self._end(how)
        return [Beat(self.lines.pick(kind), self.lines.cue(kind), self.board_spec(status), sfx="tada" if kind == "she_mates" else None)]

    def _opening(self, his: bool) -> str:
        """The opening, named once, as soon as it is recognisable."""
        if self.opening_said:
            return ""
        history = self._san_history()
        if len(history) > 10:
            self.opening_said = True
            return ""
        name, plies = talk.opening(history)
        if not name or plies != len(history):
            return ""
        self.opening_said = True
        # who played the move that made it that opening
        his_ply = (plies - 1) % 2 == (0 if self.her == chess.BLACK else 1)
        return self.lines.pick("opening_his" if his_ply else "opening_hers", name=name)

    # -- after the game: the review, from the engine ---------------------------------------------

    def _result(self) -> str:
        outcome = self.board.outcome()
        if outcome is not None:
            return outcome.result()
        if self.ending == "you resigned":
            return "0-1" if self.her == chess.BLACK else "1-0"
        if self.ending == "Irene resigned":  # (older games: she no longer resigns)
            return "1-0" if self.her == chess.BLACK else "0-1"
        return "*"

    def review_intro(self) -> Beat:
        return Beat(self.lines.pick("review_intro"), self.lines.cue("review_intro"), None)

    async def review(self) -> tuple[list[Beat], dict] | None:
        """The finished game, every position looked at by the engine at full strength:
        what she says about it and the panel. None when there is nothing to review."""
        async with self._lock:
            if not self.unreviewed:
                return None
            self.unreviewed = False
            board, he, result, ending = self.board.copy(), not self.her, self._result(), self.ending

        async def look(pos: chess.Board) -> chess_review.Look:
            pos = pos.copy()
            info = await self._engine("review", lambda e: e.analyse(pos, chess.engine.Limit(time=self.cfg.review_ms / 1000), options=FULL))
            pv = info.get("pv") or [None]
            score = info["score"].white()
            return chess_review.Look(score.score(mate_score=chess_review.MATE), pv[0], score.mate())

        started = time.perf_counter()
        try:
            rv = await chess_review.analyse(board, look, he=he, result=result, ending=ending)
        except EngineDown as error:
            log.error("chess review: engine down (%s)", error)
            return [Beat(self.lines.pick("review_failed"), self.lines.cue("engine_down"), None)], {}
        log.info("chess review: %d plies in %.1f s - he %s blunders / %s mistakes (%.0f%%), she %s / %s (%.0f%%), worst %s, turning %s",
                 len(rv.plies), time.perf_counter() - started, rv.count(he, "blunder"), rv.count(he, "mistake"), rv.accuracy[he],
                 rv.count(not he, "blunder"), rv.count(not he, "mistake"), rv.accuracy[not he],
                 rv.worst.label if rv.worst else "-", rv.turning.label if rv.turning else "-")
        self.last_review = rv
        self.last_review_content = chess_review.content(rv, time.strftime("%d %b %Y, %H:%M"))
        if not self.active:
            await self.close()
        return self.review_beats(rv), self.last_review_content

    def review_beats(self, rv: chess_review.Review) -> list[Beat]:
        """What she says about the review - every fact from it, none from the model."""
        he = rv.he

        def n(color: chess.Color) -> str:
            k = rv.count(color, "blunder")
            return "no blunders" if k == 0 else "one blunder" if k == 1 else f"{k} blunders"

        parts = [self.lines.pick("review_counts", his=n(he), hers=n(not he))]

        def said(p: chess_review.Ply, move: chess.Move | None) -> str:
            return spoken(chess.Board(p.fen_before), move) if move is not None else ""

        w = rv.worst
        if w is None:
            parts.append(self.lines.pick("review_clean"))
        else:
            fill = {"n": w.number, "move": said(w, w.move), "best": said(w, w.best) if w.best is not None and w.best != w.move else ""}
            kind = "review_worst_his" if w.color == he else "review_worst_hers"
            parts.append(self.lines.pick(kind + ("" if fill["best"] else "_plain"), **fill))
        t = rv.turning
        if t is not None:
            if w is not None and t.index == w.index:
                parts.append(self.lines.pick("review_turning_same"))
            else:
                parts.append(self.lines.pick("review_turning", n=t.number, move=said(t, t.move),
                                             who="you" if t.color == he else "I"))
        parts.append(self.lines.pick("review_panel"))
        return [Beat(" ".join(parts), self.lines.cue("review"), None)]

    # -- for the model, when he just talks mid-game ---------------------------------------

    def section(self) -> str:
        if not self.active:
            return ""
        if self.choosing:
            return ("## You're about to play chess with him\n\n"
                    "You asked which colour he wants - white, black, or you pick. The game hears his answer, not you; "
                    "never choose a colour or a move yourself.")
        history = self._san_history()
        side = "black" if self.her == chess.BLACK else "white"
        feeling = {"winning": "you are winning", "losing": "you are losing", "mating": "you can see a mate", "mated": "he has a mate on you"}.get(self.mood, "it's about even")
        return (
            "## You're playing chess with him\n\n"
            f"A game is on (you are {side}, he is {'white' if side == 'black' else 'black'}); "
            f"{len(history)} moves played, last: {' '.join(history[-4:]) or 'none yet'}; {feeling}. "
            "Your moves are played by your chess engine and announced by it - never name, suggest or "
            "judge a move yourself, never write one. If he says a move, the game hears it, not you. "
            "Banter, trash-talk lightly, answer him - then it's his move."
        )
