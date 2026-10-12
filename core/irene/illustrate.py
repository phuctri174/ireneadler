"""The board illustrates what she is saying - with the drawing she composes herself.

Round 8: no topic is anticipated. She writes her drawing as a spec after </speak>
(drawing.py lays it out); this module turns it into the board he watches:

  chess      any line of moves - hers, or the line in the pages she just read -
             checked legal (python-chess), each move played as she says it.
             There is no table of named openings, and no opening is special.
  the rest   drawing.SpecBoard: each element appears as she names it, the rest as
             the answer ends.
  fallback   a spec that can't be drawn (logged in logs/draw-specs.jsonl) - or
             no spec at all - leaves her keywords on the board, never a crash.

The board follows what he HEARS: the app calls Live.hear() as each sentence starts
playing, so a drawing that arrives mid-answer (the spec comes after the speech
text) shows at once what she already said and the rest as she says it. A new
answer always starts a new board.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from . import compose, drawing

# ---- chess: a line of moves, always checked legal ------------------------------------------

# a move as she (or a page) writes it: "d4", "Nf3", "cxd4", "O-O", "e8=Q+"
_SAN = re.compile(r"(?<![A-Za-z0-9])(O-O(?:-O)?|[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?)(?![A-Za-z0-9])")
# between two moves of one line: move numbers, dots, commas, "and", "then"
_BETWEEN = re.compile(r"^[\s,;]*(?:\d+\s*\.{1,3}\s*|\.{3}\s*|(?:and|then|followed by|with|replies?|answers?|plays?|by)\s+|[\s,;])*$", re.I)
MAX_PLIES = 12
# "White: e4", "Black - c5": a move label's side
_SIDE = re.compile(r"\b(?:white|black)\s*[:\-]\s*", re.I)
CHESSISH = re.compile(r"\bchess\w*|\bopening\b|\bgambit\b|\bdefen[cs]e\b|\bsystem\b|\battack\b|\bvariation\b|\bindian\b|\bgame\b", re.I)
# a question about chess itself, not "the immune system" or "a board game"
_CHESS = re.compile(r"\bchess\b|\bopening\b|\bgambit\b|\bvariation\b|\b(?:sicilian|french|caro|slav|indian|dutch|english|scandinavian|pirc|grunfeld|gr[uü]nfeld|nimzo|catalan|benoni|alekhine)\b", re.I)


def legal_line(text: str, start: int = 0, max_plies: int = MAX_PLIES) -> list[str]:
    """The longest line of moves written in `text` that is legal from the initial
    position - "1.e4 e5 2.Nf3 Nc6 3.Bc4", "d4, d5, then c4". [] if none."""
    import chess

    moves = list(_SAN.finditer(text, start))
    best: list[str] = []
    for i in range(len(moves)):
        board = chess.Board()
        line: list[str] = []
        prev_end = None
        for m in moves[i:]:
            if prev_end is not None and not _BETWEEN.match(text[prev_end : m.start()]):
                break
            try:
                move = board.parse_san(m.group(1))
            except ValueError:
                break
            line.append(board.san(move))
            board.push(move)
            prev_end = m.end()
            if len(line) >= max_plies:
                break
        if len(line) > len(best):
            best = line
    return best if len(best) >= 2 else []


def legal_prefix(moves: list[str], max_plies: int = MAX_PLIES) -> list[str]:
    """Her moves as far as they are legal from the start: ["e4", "e5", "Nf3", ...]."""
    import chess

    board = chess.Board()
    out: list[str] = []
    for raw in moves:
        san = re.sub(r"^\d+\s*\.+\s*|[!?]+$", "", str(raw).strip())
        if not san or san in ("1-0", "0-1", "1/2-1/2", "*"):
            continue
        try:
            move = board.parse_san(san.replace("0-0-0", "O-O-O").replace("0-0", "O-O"))
        except ValueError:
            break
        out.append(board.san(move))
        board.push(move)
        if len(out) >= max_plies:
            break
    return out


def line_from_sources(name: str, text: str) -> list[str]:
    """The opening's moves from what she fetched: the longest legal line near where
    the pages name it, else anywhere in them."""
    if not text:
        return []
    key = re.escape(re.sub(r"\s+", " ", name.strip()))
    best: list[str] = []
    for m in re.finditer(key, text, re.I) if key else []:
        line = legal_line(text[m.start() : m.start() + 600])
        if len(line) > len(best):
            best = line
    return best or legal_line(text[:20000])


@dataclass
class Chess:
    """A chessboard whose moves play as she says them. `moves` is the line known so
    far (from her drawing, her sources or her words, each checked legal)."""

    name: str
    moves: list[str] = field(default_factory=list)
    started: bool = False
    ply: int = 0
    notes_shown: set[str] = field(default_factory=set)
    kind: str = "chess"

    def spec(self) -> dict:
        return {"template": "chessboard", "moves": list(self.moves), "title": compose.caps(self.name, 95), "sync": True}

    def _said(self, sentence: str) -> tuple[int, bool]:
        """(the ply her sentence reaches, whether the line itself grew)."""
        import chess

        reached, grew = self.ply, False
        for m in _SAN.finditer(sentence):
            san = m.group(1).rstrip("+#")
            for i in range(self.ply, len(self.moves)):
                if self.moves[i].rstrip("+#").lower() == san.lower():
                    reached = max(reached, i + 1)
                    break
            else:
                # a move past the known line: kept if it is legal right there
                board = chess.Board()
                for known in self.moves:
                    board.push_san(known)
                try:
                    move = board.parse_san(m.group(1))
                except ValueError:
                    continue
                if len(self.moves) < MAX_PLIES:
                    self.moves.append(board.san(move))
                    reached, grew = len(self.moves), True
        return reached, grew

    def step(self, sentence: str, terms=()) -> dict | None:
        spoken = legal_line(sentence)
        if spoken and not self.moves:
            self.moves = spoken
        reached, grew = self._said(sentence)
        message: dict = {"type": "board_sync"}
        if not self.started:
            self.started = True
            message["spec"] = self.spec()
        elif grew:
            message["set"] = {"moves": list(self.moves)}
        add: dict[str, list[dict]] = {}
        if reached > self.ply:
            self.ply = reached
            add["reveal"] = [{"key": f"ply:{reached}"}]
        # the board's font is plain capitals: "Ruy López", "Black’s" as it can draw them
        terms = [unicodedata.normalize("NFKD", t.replace("’", "'")).encode("ascii", "ignore").decode() for t in terms]
        notes = [t for t in terms if t and not _SAN.fullmatch(t) and t.lower() not in self.notes_shown and len(t) > 3]
        if notes:
            self.notes_shown.update(t.lower() for t in notes)
            add["notes"] = [{"text": t[:30]} for t in notes]
        if add:
            message["add"] = add
        return message if len(message) > 1 else None

    def snapshot(self) -> dict:
        """The board as it stands, as a new board: played to where she has got."""
        self.started = True
        spec = {**self.spec(), "reveal": [{"key": f"ply:{self.ply}", "at": 0}] if self.ply else []}
        if self.notes_shown:
            spec["notes"] = [{"text": t.upper()[:30], "at": 0} for t in sorted(self.notes_shown)]
        return {"type": "board_sync", "spec": spec}

    def finish(self) -> dict | None:
        if self.started and self.ply >= len(self.moves):
            return None
        message: dict = {"type": "board_sync"}
        if not self.started:
            self.started = True
            message["spec"] = self.spec()
        if self.ply < len(self.moves):
            self.ply = len(self.moves)
            message["add"] = {"reveal": [{"key": f"ply:{self.ply}"}]}
        return message


def _opening_name(text: str) -> str:
    """"the Italian Game opening in chess" -> "Italian Game"."""
    m = re.search(r"((?:[A-Z][\w'’]+\s+){0,3}(?:Opening|Gambit|Defen[cs]e|System|Attack|Variation|Indian|Game)\b(?:\s+(?:Accepted|Declined))?)", text)
    if m:
        return m.group(1).strip()
    t = re.sub(r"\b(?:research|explain|tell me about|what is|what's|the|chess|opening|in|how does|work|please)\b", " ", text, flags=re.I)
    return " ".join(t.split()).strip(" ?.!") or text


@dataclass
class Position:
    """A chess position given as a FEN: shown as it is (checked legal first)."""

    name: str
    fen: str
    started: bool = False
    kind: str = "chess"

    def snapshot(self) -> dict:
        self.started = True
        return {"type": "board_sync", "spec": {"template": "chessboard", "fen": self.fen, "title": compose.caps(self.name, 95)}}

    def step(self, sentence: str, terms=()) -> dict | None:
        return None if self.started else self.snapshot()

    def finish(self) -> dict | None:
        return None if self.started else self.snapshot()


def chess_board(spec: drawing.Spec, question: str, sources: str | None) -> Chess | Position | None:
    """A chess drawing: her moves as far as they are legal - or, when the pages she
    just read give the line and hers disagrees or is short, theirs; or the moves
    he gave himself; or a position she wrote as a FEN."""
    import chess

    name = spec.title or _opening_name(question)
    if spec.fen and not spec.moves:
        try:
            board = chess.Board(spec.fen)
        except ValueError:
            return None
        return Position(name, board.fen()) if board.is_valid() else None
    his = legal_line(question)
    if len(his) >= 2 and len(legal_prefix(spec.moves)) < len(his):
        return Chess(name, his)
    hers = legal_prefix(spec.moves)
    theirs = line_from_sources(_opening_name(question), sources) if sources else []
    if theirs and (len(hers) < 2 or hers[: len(theirs)] != theirs[: len(hers)]):
        return Chess(name, theirs)
    if len(hers) >= 2:
        return Chess(name, hers if len(hers) >= len(theirs) else theirs)
    return None


# a FEN in his words: eight ranks, side to move
_FEN = re.compile(r"[rnbqkpRNBQKP1-8]{1,8}(?:/[rnbqkpRNBQKP1-8]{1,8}){7}(?:\s+[wb](?:\s+[KQkq-]{1,4}(?:\s+[a-h1-8-]{1,2}(?:\s+\d+\s+\d+)?)?)?)?")


class LiveDataError(drawing.SpecError):
    """A chart of numbers that change, without real numbers behind it."""


def board_for(raw: dict, question: str, sources: str | None, title: str = "", series: str | None = None):
    """Her spec -> (the board: Chess or drawing.SpecBoard, the spec as read);
    SpecError if it can't be drawn, LiveDataError if its numbers aren't real."""
    spec = drawing.read(raw, title=title or compose.board_title(question))
    if spec.layout == "chess":
        board = chess_board(spec, question, sources)
        if board is None:
            raise drawing.SpecError("no legal line of moves")
        return board, spec
    fen = _FEN.search(question)
    if fen:
        # a position he pasted: that position, whatever she drew
        shown = chess_board(drawing.Spec("chess", spec.title or "Position", fen=fen.group(0)), question, None)
        if shown is not None:
            return shown, spec
    his = legal_line(question)
    # the moves written as labels ("1. e4", "White: Nf3"), in any layout
    labels = [_SIDE.sub("", label) for label in _labels(spec.items)]
    hers = legal_line(" ".join(labels))
    chessy = bool(CHESSISH.search(question) or _CHESS.search(question))
    if chessy or his or (len(hers) >= 4 and len(hers) >= 0.6 * len(labels)):
        # ...or given by him ("draw the board after 1. e4 e5 2. Nf3"): still a line of moves
        line = his or hers or (line_from_sources(_opening_name(question), sources) if sources and chessy else [])
        if line:
            spec.fixed.append("moves written as labels -> chess")
            return Chess(spec.title or _opening_name(question), line), spec
    why = drawing.numbers(spec, question, sources, series)
    if why:
        raise LiveDataError(why)
    return drawing.SpecBoard(drawing.compile(spec)), spec


def _labels(items) -> list[str]:
    out = []
    for i in items:
        out.append(i.label)
        out += _labels(i.items)
    return out


# ---- one answer's board, as he hears it --------------------------------------------------------


class Live:
    """The board for one answer. It starts empty (or on the chess line her pages
    give); her drawing is adopted when it arrives; hear() moves it on with every
    sentence he hears; finish() puts up whatever she never named."""

    def __init__(self, question: str, title: str = "", sources: str | None = None, wanted: bool = True):
        self.question = " ".join((question or "").split())
        self.title = title or compose.board_title(self.question)
        # what she read for this answer (None: no research) - live numbers must be in it
        self.sources = sources
        # an explanation: a drawing is expected (else only one she writes unasked)
        self.wanted = wanted
        self.inner = None
        self.heard: list[tuple[str, tuple]] = []
        self.adopted = False
        self.fallback = False
        # why her drawing couldn't be drawn (asked for once more with it)
        self.invalid: str | None = None
        # a chart of live numbers with none from research behind it
        self.no_numbers = False
        # the real series research fetched for it (tools/series.py), if any
        self.series: str | None = None
        # "the London System", "the Italian Game": chess only once moves show it
        self._chess_topic = bool(_CHESS.search(self.question) or CHESSISH.search(self.question) or legal_line(self.question))
        if self._chess_topic and sources and (_CHESS.search(self.question) or re.search(r"\bchess\b", sources[:4000], re.I)):
            line = line_from_sources(_opening_name(self.question), sources)
            if line:
                self.inner = Chess(_opening_name(self.question), line)

    @property
    def kind(self) -> str:
        return getattr(self.inner, "kind", "")

    def hear(self, text: str, terms=()) -> list[dict]:
        """He is hearing this sentence now: what it puts on the board."""
        self.heard.append((text, tuple(terms)))
        if self.inner is None and self._chess_topic and len(self.heard) <= 3:
            line = legal_line(text)
            if line:
                self.inner = Chess(_opening_name(self.question), line)
        if self.inner is None:
            return []
        message = self.inner.step(text, terms)
        return [message] if message else []

    def adopt(self, board) -> dict | None:
        """Her drawing arrived: it replaces what is up (unless it is the same chess
        line), shown as far as she has already got."""
        if isinstance(self.inner, Chess) and isinstance(board, Chess):
            if board.moves[: len(self.inner.moves)] == self.inner.moves and len(board.moves) > len(self.inner.moves):
                self.inner.moves = list(board.moves)
                self.adopted = True
                return {"type": "board_sync", "set": {"moves": list(self.inner.moves)}} if self.inner.started else None
            self.adopted = True
            return None
        if isinstance(self.inner, Chess) and self.inner.started and not isinstance(board, Chess):
            # a chess answer keeps its board: an outline of it is no better
            self.adopted = True
            return None
        self.inner = board
        self.adopted = True
        for text, terms in self.heard:
            board.step(text, terms)
        return board.snapshot()

    def finish(self) -> dict | None:
        return self.inner.finish() if self.inner is not None else None

    def said(self) -> list[str]:
        return [t for t, _ in self.heard]


_ASKS = re.compile(
    r"\?\s*$|^\W*(?:(?:hey |ok |okay )?(?:irene,? )?(?:can you |could you |please )?)?"
    r"(?:what|how|why|who|when|where|which|explain|tell me|describe|show me|teach me|walk me through|draw|sketch|compare|"
    r"give me|list|summari[sz]e|research|look up|break down|go over|outline)\b",
    re.I,
)
_CHAT = re.compile(r"\b(?:you|your|yourself|u)\b|\bhow are\b|\bwhat'?s up\b|\bjoke\b|\bfeel|\bthink\b|\bopinion\b|\b(?:should|shall) i\b", re.I)


# how he asks, not what about: "can you tell me about X" is a question about X,
# not chat about her (the bare "you" in it used to cost every such answer its board)
_FRAME = re.compile(
    r"\b(?:(?:can|could|would|will) (?:you|u)(?: please)?(?: (?:help|give) me(?: to)?)?|do (?:you|u) (?:know|remember)(?: about| of)?"
    r"|have (?:you|u) heard(?: of| about)?|(?:i want|i'd like|i need) (?:you )?to)\b",
    re.I,
)


# "can you open the panel?" asks her to do something, not to explain it
_DOES = re.compile(
    r"^\W*(?:(?:hey|ok|okay|so|wait|and|but|irene)\W+)*(?:please\s+)?"
    r"(?:open|close|play|pause|resume|stop|skip|set|start|turn|save|take|mute|unmute|launch|put|move|quarantine|hide)\b",
    re.I,
)


def _asks_knowledge(text: str) -> bool:
    """Any sentence of his that asks about something other than her or him."""
    for sentence in re.findall(r"[^.?!]+[.?!]*", text):
        s = _FRAME.sub(" ", sentence)
        if _DOES.match(s):
            continue
        if _ASKS.search(s.strip()) and (not _CHAT.search(s) or _CHESS.search(s)):
            return True
    return False


def for_question(text: str) -> Live | None:
    """A knowledge question gets the board ("explain the Queen's Gambit", "can you
    tell me how a transformer works?") - not chat about her or him ("how are you",
    "what do you think")."""
    text = text or ""
    if not _asks_knowledge(text):
        return None
    return Live(text, compose.board_title(text))


def prompt_hint(shown: Live) -> str:
    """The Now-section line for a question the board will illustrate."""
    what = (
        'a chess line: {"chess": [its moves in order]}' if shown._chess_topic
        else "its form picked from the content (see Your drawing board)"
    )
    return (
        "Explain it OUT LOUD in <speak>: three to five sentences, naming the things you "
        f"draw as you go. Then, after </speak>, draw it: one <draw>{{...}}</draw> - {what}."
    )


class BoardFeed:
    """A reply's board messages in the order he hears them: line() as a sentence is
    queued, heard() as it starts playing, adopt() when her drawing arrives, close()
    once the answer has no more sentences - whatever she never named goes up as
    the last one starts. `send` gets each board_sync message."""

    def __init__(self, send):
        self.send = send
        self.plan: Live | None = None
        self.fed = 0
        self.heard_n = 0
        self.closed = False
        self._finished = False

    @property
    def drew(self) -> bool:
        return self.plan is not None and self.plan.inner is not None

    def start(self, plan: Live | None) -> None:
        self.plan = plan

    def line(self) -> None:
        self.fed += 1

    def heard(self, text: str, terms=()) -> None:
        self.heard_n += 1
        if self.plan is None:
            return
        for message in self.plan.hear(text, terms):
            self.send(message)
        self._maybe_finish()

    def adopt(self, board) -> None:
        if self.plan is None:
            return
        message = self.plan.adopt(board)
        if message:
            self.send(message)
        self._maybe_finish()

    def close(self) -> None:
        self.closed = True
        self._maybe_finish()

    def _maybe_finish(self) -> None:
        if self.closed and not self._finished and self.drew and self.heard_n >= self.fed:
            self._finished = True
            message = self.plan.finish()
            if message:
                self.send(message)


def briefing_board(expand: str = ""):
    """The daily briefing's board (tools/briefing.LAST): one section per item it
    spoke, each drawn as she reaches its sentence - or, going into one item
    (`expand`), that item alone across the board. None: nothing to draw."""
    from tools import briefing

    b = briefing.LAST
    if b is None or not b.items:
        return None
    items = b.items
    if expand:
        picked = briefing._which(expand, b)
        if picked is None:
            return None
        items = [picked[1]]
    parts = []
    for item in items:
        d = item.board
        if d.get("kind") == "chart":
            parts.append(drawing.Section(item.header, "chart", points=list(d.get("points") or []), up=d.get("up"), change=d.get("change", ""), value=d.get("value", "")))
        elif d.get("kind") == "sky":
            parts.append(drawing.Section(item.header, "sky", icon=d.get("icon", "cloud"), lines=list(d.get("lines") or [])))
        else:
            parts.append(drawing.Section(item.header, "story", icon=d.get("icon", "star"), lines=list(d.get("words") or [])))
    return drawing.SectionBoard(drawing.sections(parts, "TODAY"))
