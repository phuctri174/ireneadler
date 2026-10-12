"""Chess with Irene: a real engine plays her moves, he plays his by voice.

The language model never chooses a move and never judges one. Here:

  parse()     his words -> a legal move: "e4", "knight to f3", "castle kingside",
              "take the bishop", "e takes d5", "g1 f3", "e8 queen" - with what
              Whisper makes of them ("night to F3", "e four"). A move that isn't
              legal is refused with the reason; one that could be two moves asks
              which ("the knight on b1 or the one on f3?")
  ChessGame   the game: Stockfish (config/chess.yaml) at a modest Skill Level
              picks her moves; a full-strength look at the position after every
              move decides what she says about it, so what she says is true -
              "that hangs your knight" only when the engine's best reply takes it
  Beat        what she says and shows, in order: a line, its cue, and the board
              as it should look when she starts saying it

His commands are matched in code (command()): start, resign, takeback, stop.
Everything else he says mid-game goes to the model as usual, with the game in
her context (section()) - she can banter, but she never picks or rates a move.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

import chess
import chess.engine
import yaml

from . import chess_talk as talk

log = logging.getLogger("irene.chess")

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "chess.yaml"

PIECE_WORDS = {
    "pawn": chess.PAWN, "pawns": chess.PAWN, "porn": chess.PAWN, "pond": chess.PAWN,
    "knight": chess.KNIGHT, "knights": chess.KNIGHT, "night": chess.KNIGHT, "nite": chess.KNIGHT, "horse": chess.KNIGHT,
    "bishop": chess.BISHOP, "bishops": chess.BISHOP,
    "rook": chess.ROOK, "rooks": chess.ROOK, "rock": chess.ROOK, "brook": chess.ROOK, "rookie": chess.ROOK,
    "queen": chess.QUEEN, "queens": chess.QUEEN, "queenie": chess.QUEEN,
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
    r"how\s+about|fancy|you\s+up\s+for|up\s+for|time\s+for)\s+(?:a\s+)?(?:play\s+)?(?:a\s+)?(?:game\s+of\s+|quick\s+game\s+of\s+|round\s+of\s+)?chess"
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


def command(text: str, active: bool, finished: bool = False) -> str | None:
    """His words as a chess command: "start", "resign", "takeback", "stop" - or
    "move" for anything else while a game is on (the parser decides), None when
    it's not chess at all."""
    said = (text or "").strip()
    if _START.search(said) or ((active or finished) and _AGAIN.search(said) and not _STOP.search(said)):
        return "start"
    if not active:
        return None
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
    skill: int = 4
    think_ms: int = 500
    analyse_ms: int = 250
    hotwords: list[str] = field(default_factory=list)


def settings(path: Path = CONFIG) -> Settings:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raw = {}
    s = Settings()
    for key in ("engine", "skill", "think_ms", "analyse_ms", "hotwords"):
        if key in raw:
            setattr(s, key, raw[key])
    return s


def _score(info: dict, color: chess.Color) -> int:
    """Centipawns from `color`'s side (a mate is +-10000, nearer is bigger)."""
    return info["score"].pov(color).score(mate_score=10000)


class ChessGame:
    """One game against him. `engine` may be injected (the tests' fake)."""

    def __init__(self, cfg: Settings | None = None, engine=None, rng: random.Random | None = None):
        self.cfg = cfg or settings()
        self.board = chess.Board()
        self.her = chess.BLACK
        self.engine = engine
        self._own_engine = engine is None
        self.active = False
        self.finished = False
        self.lines = talk.Lines(rng or random.Random())
        # what the position was worth to her after her last move (centipawns)
        self.her_eval = 0
        self.mood = "even"  # even | winning | losing
        self.opening_said = False
        self.pending: list[chess.Move] = []
        # her bad moves in a row (resigns when it's hopeless and stays so)
        self._hopeless = 0
        # the ply of her last "nice move": praise is rationed
        self._praised = -99

    # -- engine --------------------------------------------------------------------------

    async def _ensure_engine(self) -> None:
        if self.engine is None:
            _, self.engine = await chess.engine.popen_uci(self.cfg.engine)
            log.info("chess engine started: %s (skill %s)", self.engine.id.get("name"), self.cfg.skill)

    async def close(self) -> None:
        if self.engine is not None and self._own_engine:
            try:
                await asyncio.wait_for(self.engine.quit(), 2)
            except Exception:  # noqa: BLE001 - a dead engine is closed either way
                pass
            self.engine = None

    async def _look(self, board: chess.Board) -> dict:
        """The position at full strength: score and the best move."""
        info = await self.engine.analyse(board, chess.engine.Limit(time=self.cfg.analyse_ms / 1000), options={"Skill Level": 20})
        return info

    async def _her_move(self) -> chess.Move:
        result = await self.engine.play(self.board, chess.engine.Limit(time=self.cfg.think_ms / 1000), options={"Skill Level": int(self.cfg.skill)})
        return result.move

    # -- the board she shows ----------------------------------------------------------------

    def board_spec(self, status: str = "") -> dict:
        last = self.board.peek() if self.board.move_stack else None
        spec = {
            "template": "chessboard",
            "live": True,
            "fen": self.board.fen(),
            "flip": self.her == chess.WHITE,
            "title": "YOU VS IRENE",
            "status": status or ("YOUR MOVE" if self.board.turn != self.her else "MY MOVE"),
            "history": [m for m in self._san_history()][-16:],
        }
        if last is not None:
            spec["last"] = [chess.square_name(last.from_square), chess.square_name(last.to_square)]
        if self.board.is_check():
            king = self.board.king(self.board.turn)
            if king is not None:
                spec["highlight"] = [chess.square_name(king)]
        return spec

    def _san_history(self) -> list[str]:
        replay = chess.Board()
        out = []
        for mv in self.board.move_stack:
            out.append(replay.san(mv))
            replay.push(mv)
        return out

    # -- what he asks for ----------------------------------------------------------------------

    async def start(self, text: str = "") -> list[Beat]:
        await self._ensure_engine()
        self.board = chess.Board()
        self.her = chess.WHITE if _SHE_WHITE.search(text or "") else chess.BLACK
        self.active, self.finished = True, False
        self.her_eval, self.mood, self.opening_said, self.pending, self._hopeless, self._praised = 0, "even", False, [], 0, -99
        log.info("chess: new game, he plays %s", "black" if self.her == chess.WHITE else "white")
        if self.her == chess.BLACK:
            return [Beat(self.lines.pick("start_he_white"), self.lines.cue("start"), self.board_spec(), sfx="charge")]
        beats = [Beat(self.lines.pick("start_she_white"), self.lines.cue("start"), self.board_spec("MY MOVE"), sfx="charge")]
        beats += await self._reply()
        return beats

    async def stop(self) -> list[Beat]:
        self.active = False
        self.finished = True
        await self.close()
        return [Beat(self.lines.pick("stop"), self.lines.cue("stop"), None)]

    async def resign(self) -> list[Beat]:
        self.active, self.finished = False, True
        await self.close()
        return [Beat(self.lines.pick("he_resigns"), self.lines.cue("he_resigns"), self.board_spec("YOU RESIGNED"))]

    async def takeback(self) -> list[Beat]:
        # his last move and her answer to it
        his = [i for i, _ in enumerate(self.board.move_stack) if (i % 2 == 0) == (self.her == chess.BLACK)]
        if not his:
            return [Beat(self.lines.pick("nothing_to_take_back"), self.lines.cue("takeback"), None)]
        undo = len(self.board.move_stack) - his[-1]
        for _ in range(undo):
            self.board.pop()
        self.pending = []
        log.info("chess: takeback (%d plies)", undo)
        return [Beat(self.lines.pick("takeback"), self.lines.cue("takeback"), self.board_spec())]

    def claims(self, text: str) -> bool:
        """These words are for the board: a move (legal or not), or the answer to her
        "which one?". Cheap - no engine."""
        if not self.active:
            return False
        if self._resolve_pending(text) is not None:
            return True
        return parse(text, self.board) is not None

    async def his_move(self, text: str) -> list[Beat] | None:
        """His words, mid-game. None: they weren't a move (the model answers)."""
        await self._ensure_engine()
        parsed = self._resolve_pending(text) or parse(text, self.board)
        if parsed is None:
            return None
        if parsed.options:
            self.pending = parsed.options
            return [Beat(self.lines.pick("which", options=which(self.board, parsed.options)), self.lines.cue("which"), None)]
        self.pending = []
        if parsed.illegal:
            log.info("chess: illegal %r - %s", text, parsed.illegal)
            return [Beat(self.lines.pick("illegal", reason=parsed.illegal), self.lines.cue("illegal"), None)]
        return await self.play(parsed.move)

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
        """His (legal) move, her reaction to it, and her answer."""
        before = await self._look(self.board)
        his_before = _score(before, not self.her)
        best = before.get("pv", [None])[0]
        san = self.board.san(move)
        mover = self.board.piece_type_at(move.from_square)
        captured = chess.PAWN if self.board.is_en_passant(move) else self.board.piece_type_at(move.to_square)
        self.board.push(move)
        log.info("chess: he played %s", san)
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
        log.info("chess: she played %s", san)
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
        if her <= -900:
            self._hopeless += 1
        else:
            self._hopeless = 0
        if self._hopeless >= 2 and len(self.board.move_stack) > 20:
            # hopeless and staying so: she bows out
            self.active, self.finished = False, True
            await self.close()
            return beats + [Beat(self.lines.pick("she_resigns"), self.lines.cue("she_resigns"), self.board_spec("I RESIGN"))]
        mate = look["score"].pov(self.her).mate()
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
        """The game just ended on a move (his if `his`)."""
        self.active, self.finished = False, True
        outcome = self.board.outcome()
        if outcome is not None and outcome.winner is not None:
            kind = "she_mates" if outcome.winner == self.her else "he_mates"
            status = "MATE - I WIN!" if kind == "she_mates" else "MATE - YOU WIN"
        else:
            kind = "draw"
            status = "DRAW"
        log.info("chess: game over - %s", kind)
        asyncio.ensure_future(self.close())
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

    # -- for the model, when he just talks mid-game ---------------------------------------

    def section(self) -> str:
        if not self.active:
            return ""
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
