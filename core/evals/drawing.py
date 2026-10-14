"""Drawing evals: the right template for a drawing request, legal chess, valid
<draw> JSON, and nothing drawn for questions that need no picture.

Chess legality is checked independently of the HUD with python-chess: a FEN must
be a valid position, moves must be legal from it, an opening must be one the
HUD's table knows (hud/src/board/templates/chessboard.ts).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import chess

from harness import conversation_for, live_turn, load, parse_reply
from irene import board, drawing, illustrate
from irene.brain import drawn_as_tool

ROOT = Path(__file__).resolve().parents[2]
def chess_problem(spec: dict) -> str | None:
    """Why a chessboard spec isn't legal chess, or None."""
    try:
        b = chess.Board(spec["fen"]) if spec.get("fen") else chess.Board()
    except ValueError as error:
        return f"bad FEN: {error}"
    if spec.get("fen") and b.status() == chess.STATUS_INVALID_EP_SQUARE:
        # the board drops an en-passant square that can't be right (it changes nothing drawn)
        b.ep_square = None
    if spec.get("fen") and not b.is_valid():
        return f"illegal position: {b.status()!r}"
    moves = spec.get("moves") or []
    if isinstance(moves, str):
        moves = [m for m in re.sub(r"\d+\.(\.\.)?", " ", moves).split() if m not in ("1-0", "0-1", "1/2-1/2", "*")]
    if spec.get("opening") and not moves and not spec.get("fen"):
        # an opening is always its moves (Round 7: no table of named openings)
        return f"opening {spec['opening']!r} without its moves"
    for m in moves:
        try:
            if isinstance(m, list) and len(m) == 2:
                move = chess.Move.from_uci(f"{m[0]}{m[1]}".lower())
                if move not in b.legal_moves:
                    move = chess.Move.from_uci(f"{m[0]}{m[1]}q".lower())
                if move not in b.legal_moves:
                    raise ValueError(m)
                b.push(move)
            else:
                b.push_san(str(m))
        except ValueError:
            return f"illegal move {m}"
    return None


@dataclass
class DrawReport:
    lines: list[str] = field(default_factory=list)
    right: int = 0
    n: int = 0
    tags: int = 0  # replies that wrote a <draw>
    valid: int = 0  # of those, drawable as far as core can tell
    chess_n: int = 0
    chess_ok: int = 0
    silent_n: int = 0  # questions that should draw nothing
    silent_ok: int = 0
    specs: list = field(default_factory=list)  # (case id, spec) core would send
    hud_ok: int = 0

    def summary(self) -> dict:
        pct = lambda a, b: f"{a}/{b} ({a / max(1, b):.0%})"  # noqa: E731
        return {
            "drawing_right_template": pct(self.right, self.n),
            "draw_json_valid": pct(self.valid, self.tags),
            "chess_legal": pct(self.chess_ok, self.chess_n),
            "non_visual_draw_nothing": pct(self.silent_ok, self.silent_n),
            "hud_draws_what_core_sends": pct(self.hud_ok, len(self.specs)),
        }

    def check_with_hud(self) -> None:
        """Run every spec core accepted through the HUD's own checks."""
        import subprocess
        import tempfile

        if not self.specs:
            return
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump([s for _, s in self.specs], f)
        hud = ROOT / "hud"
        out = subprocess.run(["node", "scripts/check_draws.mjs", f.name], cwd=hud, capture_output=True, text=True, timeout=120).stdout
        for (case, spec), verdict in zip(self.specs, json.loads(out)):
            self.hud_ok += verdict["ok"]
            if not verdict["ok"]:
                self.lines.append(f"FAIL drawing  {case:22} HUD refused: {verdict['why']}  {json.dumps(spec)[:90]}")


async def run_drawing(llm, report: DrawReport, timing=None, repeat: int = 1) -> None:
    for case in load("drawing.jsonl"):
        for _ in range(repeat):
            # the live turn, board and all: a reply with no drawing is asked once more
            conv = conversation_for(llm, case)
            asked: list = []
            ask = conv._ask_for_drawing

            async def follow_up(*args, ask=ask, asked=asked):
                spec = await ask(*args)
                asked.append(spec)
                return spec

            conv._ask_for_drawing = follow_up
            t = await live_turn(llm, case, conv, boards=True)
            if timing:
                timing(t)
            call = t.called
            reply = parse_reply(t.raw)
            meant = drawn_as_tool(t.raw)
            again = ""
            if reply.draw is None and meant is None and asked and asked[-1] is not None:
                # the follow-up drawing the app asked for: what the board got
                reply = type(reply)(reply.speak, reply.display, reply.react, reply.cues, board.Draw(asked[-1]))
                again = "  (drawn on the follow-up)"
            if reply.draw is None and meant is not None:
                # a template 'called' as a tool: the conversation draws it all the same
                why = board.check(meant)
                reply = type(reply)(reply.speak, reply.display, reply.react, reply.cues, board.Draw(None if why else meant, why))
            note = ""
            if call:
                got = f"tool:{call[0]}"
            elif reply.draw is None:
                got = None
            elif reply.draw.spec is None:
                got = "invalid"
                note = f"  INVALID {reply.draw.error}"
            elif drawing.is_spec(reply.draw.spec) and illustrate.for_question(case["say"]) is None and board.wanted(case["say"]) is None:
                # chat: the conversation drops a drawing she composed unasked
                got, note = None, "  (drew unasked: dropped)"
            elif drawing.is_spec(reply.draw.spec):
                # one she composed (Round 8): what it becomes on the board
                try:
                    shown, _ = illustrate.board_for(reply.draw.spec, case["say"], None)
                except drawing.SpecError as error:
                    got, note = "invalid", f"  INVALID {error}"
                else:
                    got = "chessboard" if isinstance(shown, (illustrate.Chess, illustrate.Position)) else f"spec:{shown.kind}"
                    report.specs.append((case["id"], shown.snapshot()["spec"]))
                    if isinstance(shown, (illustrate.Chess, illustrate.Position)):
                        report.chess_n += 1
                        report.chess_ok += 1  # its moves are legal: board_for keeps only those
            else:
                got = reply.draw.spec.get("template", "shapes")
                report.specs.append((case["id"], reply.draw.spec))
            note += again
            if "<draw" in t.raw.lower():
                report.tags += 1
                report.valid += bool(reply.draw and reply.draw.spec)
            # "composed": any picture she composed herself - not her outline of words
            ok = got in case["expect"] or ("composed" in case["expect"] and str(got).startswith("spec:") and got not in ("spec:outline", "spec:keywords"))
            if got == "chessboard" and not drawing.is_spec(reply.draw.spec):
                report.chess_n += 1
                problem = chess_problem(reply.draw.spec)
                report.chess_ok += problem is None
                if problem:
                    ok = False
                    note += f"  CHESS {problem}"
            if case.get("forbid_label") and reply.draw and case["forbid_label"] in json.dumps(reply.draw.spec or {}).lower():
                ok = False
                note += f"  DREW {case['forbid_label']!r}"
            if case["expect"] == [None]:
                report.silent_n += 1
                report.silent_ok += got is None
            report.n += 1
            report.right += ok
            report.lines.append(f"{'PASS' if ok else 'FAIL'} drawing  {case['id']:22} got {str(got):16} want {'/'.join(map(str, case['expect']))}{note}")
