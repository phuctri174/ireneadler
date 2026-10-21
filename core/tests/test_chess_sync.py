"""The chess game has ONE position (irene/chess_game.py): every change is atomic, the
engine is watched, the HUD's board is checked against the game at every ply - and
around it, the colour question, her opening book and the engine's post-game review.

The bug these pin down (live 2026-10-15): an early turn played Qe2 and was retracted
while the engine thought; his move stayed on the board with no answer, the full
transcript was judged with Black to move ("illegal"), and the game hung on MY MOVE.
"""
import asyncio
import random
from pathlib import Path

import chess
import chess.engine
import pytest

from irene import chess_book, chess_review
from irene.chess_game import ChessGame, Settings, colour_choice, command, placement, settings

ENGINE = Path(settings().engine).exists()
needs_engine = pytest.mark.skipif(not ENGINE, reason="Stockfish not installed (core/scripts/setup_stockfish.ps1)")


class FakeEngine:
    """A stand-in engine: level positions, its first legal move - or hangs on demand."""

    def __init__(self):
        self.hang_play = False
        self.hang_all = False
        self.played = 0

    async def configure(self, options):
        pass

    async def analyse(self, board, limit, options=None):
        if self.hang_all:
            await asyncio.sleep(3600)
        return {"score": chess.engine.PovScore(chess.engine.Cp(0), chess.WHITE), "pv": [next(iter(board.legal_moves))]}

    async def play(self, board, limit, options=None, **kw):
        if self.hang_play or self.hang_all:
            await asyncio.sleep(3600)
        self.played += 1
        return chess.engine.PlayResult(sorted(board.legal_moves, key=lambda m: m.uci())[0], None)

    async def quit(self):
        pass


def fake_game(timeout: float = 10.0, seed: int = 1) -> tuple[ChessGame, FakeEngine]:
    engine = FakeEngine()
    game = ChessGame(Settings(engine_timeout_s=timeout, think_ms=1, analyse_ms=1), engine=engine, rng=random.Random(seed))
    return game, engine


def replay(history: list[str]) -> str:
    b = chess.Board()
    for san in history:
        b.push_san(san)
    return b.fen()


def check_spec(game: ChessGame, spec: dict) -> None:
    """What the HUD gets is one consistent position: the pieces, the move list and the
    ply agree with each other and with the game at that ply."""
    assert spec["ply"] == len(spec["history"]), spec
    assert placement(replay(spec["history"])) == placement(spec["fen"]), spec
    assert game.shown(spec["ply"], spec["fen"], replay(spec["history"])), game.divergences


# ---- the colour question ------------------------------------------------------------------


def test_colour_answers():
    for said, want in [("white", "white"), ("White please", "white"), ("I'll be black", "black"), ("black", "black"),
                       ("you be white", "black"), ("you can play black", "white"), ("you choose", "random"),
                       ("surprise me", "random"), ("I don't mind", "random"), ("flip a coin", "random"),
                       ("you go first", "black"), ("hmm let me think", None), ("what's the time", None)]:
        assert colour_choice(said) == want, said


def test_she_asks_his_colour_and_confirms_it_before_move_one():
    async def go():
        game, engine = fake_game()
        beats = await game.start("let's play chess")
        assert game.choosing and game.active and not game.board.move_stack
        assert "white" in beats[0].text.lower() and "black" in beats[0].text.lower()
        assert beats[0].board["status"] == "WHITE OR BLACK?"
        # not a colour: the model answers
        assert not game.claims("are you any good?") and await game.his_move("are you any good?") is None
        assert game.claims("black")
        beats = await game.his_move("black")
        # said out loud first, then her first move: 1.e4 from her book
        assert "black" in beats[0].text.lower() and game.her == chess.WHITE
        assert game.board.move_stack == [chess.Move.from_uci("e2e4")] and engine.played == 0
        # "you choose": her pick, said before move one
        game, _ = fake_game(seed=3)
        await game.start("let's play chess")
        beats = await game.his_move("you choose")
        side = "white" if game.her == chess.BLACK else "black"
        assert side in beats[0].text.lower()

    asyncio.run(go())


# ---- the book -------------------------------------------------------------------------------


def test_every_book_line_is_legal():
    for line in (*chess_book.AS_WHITE, *chess_book.VS_D4, *(l for ls in chess_book.DEFENCES.values() for l in ls)):
        b = chess.Board()
        for san in line.split():
            b.push_san(san)


def test_book_openings():
    seen = set()
    for seed in range(30):
        book = chess_book.Book(random.Random(seed))
        b = chess.Board()
        b.push_san("e4")
        seen.add(b.san(book.move(b, chess.BLACK)))
    assert seen == {"c5", "c6", "Nc6"}
    # as White: always 1.e4
    assert chess_book.Book().move(chess.Board(), chess.WHITE) == chess.Move.from_uci("e2e4")
    # vs 1.d4: the Nimzo-Indian when he allows it
    book, b = chess_book.Book(random.Random(0)), chess.Board()
    for his in ("d4", "c4", "Nc3"):
        b.push_san(his)
        b.push(book.move(b, chess.BLACK))
    assert b.move_stack[-1] == chess.Move.from_uci("f8b4")
    # he leaves the book: the engine plays from then on
    book, b = chess_book.Book(random.Random(0)), chess.Board()
    b.push_san("a3")
    assert book.move(b, chess.BLACK) is None and book.out


# ---- one position, atomic --------------------------------------------------------------------


def test_a_move_cut_off_mid_reply_is_rolled_back_whole():
    async def go():
        game, engine = fake_game()
        await game.start("I'll be white")
        await game.his_move("e4")  # her book answer
        await game.his_move("knight to f3")
        before = game.board.fen()
        engine.hang_play = True
        game.book.out = True
        task = asyncio.create_task(game.his_move("bishop to c4"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # his move did NOT stay on the board without her answer
        assert game.board.fen() == before and game.board.turn == chess.WHITE
        assert game.committed()["board"].fen() == before
        engine.hang_play = False
        beats = await game.his_move("bishop to c4")
        assert beats and len(game.board.move_stack) == 6 and game.board.turn == chess.WHITE

    asyncio.run(go())


def test_retracting_a_finished_turn_restores_the_committed_game():
    async def go():
        game, _ = fake_game()
        await game.start("I'll be white")
        mark = game.committed()
        await game.his_move("e4")
        assert len(game.board.move_stack) == 2
        game.restore(mark)  # what retract_turn does (app.py)
        assert not game.board.move_stack and game.board.turn == chess.WHITE
        # the full transcript, judged against the right position
        beats = await game.his_move("queen to e2")
        assert "e2" in beats[0].text.lower() and not game.board.move_stack  # illegal at move one, still his move
        await game.his_move("e4")
        await game.his_move("queen to e2")
        assert game.board.move_stack[2] == chess.Move.from_uci("d1e2")

    asyncio.run(go())


def test_a_hung_engine_is_said_and_recovered_never_a_silent_hang():
    async def go():
        game, engine = fake_game(timeout=0.2)
        await game.start("I'll be white")
        engine.hang_all = True
        beats = await asyncio.wait_for(game.his_move("e4"), 5)
        said = " ".join(b.text for b in beats).lower()
        assert "engine" in said and not game.board.move_stack and game.active
        engine.hang_all = False
        await game.his_move("e4")
        assert len(game.board.move_stack) == 2

    asyncio.run(go())


def test_the_hud_echo_is_checked():
    async def go():
        game, _ = fake_game()
        await game.start("I'll be white")
        await game.his_move("e4")
        spec = game.board_spec()
        check_spec(game, spec)
        # a HUD drawing something else is caught, loud
        assert not game.shown(1, spec["fen"])
        assert not game.shown(spec["ply"], spec["fen"], replayed=chess.STARTING_FEN)
        assert len(game.divergences) == 2

    asyncio.run(go())


def test_review_command():
    assert command("review the game", active=False, finished=True) == "review"
    assert command("how did I play?", active=False, finished=True) == "review"
    assert command("review the game", active=False, finished=False) is None


# ---- with the real engine -------------------------------------------------------------------


@needs_engine
def test_a_full_game_the_board_and_the_hud_agree_at_every_ply():
    """A whole game, his moves spoken as SAN: after every beat, the spec the HUD gets
    is the game's position at that ply, its move list replays to it, and it is always
    his move when she has finished talking."""

    async def go():
        cfg = settings()
        cfg.think_ms, cfg.analyse_ms = 60, 40
        game = ChessGame(cfg, rng=random.Random(7))
        _, him = await chess.engine.popen_uci(cfg.engine)
        checked = 0
        try:
            for b in await game.start("let's play chess, I'll be black"):
                if b.board:
                    check_spec(game, b.board)
            assert game.her == chess.WHITE and len(game.board.move_stack) == 1
            while game.active and len(game.board.move_stack) < 200:
                r = await him.play(game.board, chess.engine.Limit(time=0.02), options={"Skill Level": 3})
                beats = await game.his_move(game.board.san(r.move))
                assert beats, game.board.fen()
                for b in beats:
                    if b.board:
                        check_spec(game, b.board)
                        checked += 1
                if game.active:
                    assert game.board.turn != game.her, f"her move owed at {game.board.fen()}"
                    assert game.board_spec()["status"] == "YOUR MOVE"
            assert checked > 10 and not game.divergences
            # long games number correctly: the history is the whole game
            assert game.board_spec()["history"][0] == "e4"
        finally:
            await him.quit()
            await game.close()

    asyncio.run(go())


@needs_engine
def test_strength_is_stockfishs_own_limiter():
    """The configured Elo (1350 shipped, 1320 the floor) is what the engine holds before
    every move of hers - after the full-strength looks too."""
    assert settings().elo == 1350 and (settings().max_depth, settings().think_ms) == (6, 300)

    async def go():
        game = ChessGame()
        try:
            await game._ensure_engine()
            assert game.engine.config["UCI_LimitStrength"] is True and game.engine.config["UCI_Elo"] == 1350
            # a look runs at full strength; her next move is limited again
            await game._look(chess.Board())
            game.book.out = True
            await game._her_move()
            assert game.engine.config["UCI_LimitStrength"] is True and game.engine.config["UCI_Elo"] == 1350
            assert game.engine_moves == 1
        finally:
            await game.close()
        low = ChessGame(Settings(elo=1000))
        try:
            await low._ensure_engine()
            assert low.engine.config["UCI_Elo"] == 1320, "below Stockfish's floor is the floor"
        finally:
            await low.close()

    asyncio.run(go())


def test_her_search_is_capped_and_starts_from_an_empty_hash():
    """The look at the same position fills the hash at full strength; her weakened search
    reading it played the deep search's moves (scripts/chess_strength.py, 2026-10-19)."""
    calls = []

    class Recording(FakeEngine):
        async def configure(self, options):
            calls.append(("configure", dict(options)))

        async def play(self, board, limit, options=None, **kw):
            calls.append(("play", limit))
            return await super().play(board, limit, options)

    game = ChessGame(Settings(think_ms=300, max_depth=6), engine=Recording(), rng=random.Random(1))
    game.book.out = True
    asyncio.run(game._her_move())
    assert calls[0] == ("configure", {"Clear Hash": None}) and calls[1][0] == "play"
    assert calls[1][1].depth == 6 and calls[1][1].time == 0.3


def test_the_book_goes_as_deep_as_configured():
    assert chess_book.MAX_DEPTH == 6 and settings().book_moves == 6
    line = "d4 Nf6 c4 e6 Nc3 Bb4 Qc2 O-O a3 Bxc3+ Qxc3 b6".split()

    def book_moves(cap):
        book, b, n = chess_book.Book(random.Random(0), cap), chess.Board(), 0
        for i, san in enumerate(line):
            if i % 2 == 1:
                m = book.move(b, chess.BLACK)
                if m is None:
                    break
                n += 1
                assert b.san(m) == san
            b.push_san(san)
        return n, book.out

    assert book_moves(6) == (6, False)
    assert book_moves(2) == (2, True) and book_moves(0) == (0, True)
    game, _ = fake_game()
    assert game.book.max_moves == game.cfg.book_moves


@needs_engine
def test_the_review_is_the_engines():
    async def go():
        game = ChessGame()
        try:
            await game.start("I'll be white")
            # 1.e4 e5 2.Bc4 Nc6 3.Qh5 Nf6?? 4.Qxf7# - played straight onto the board
            for san in ("e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7#"):
                game.board.push_san(san)
            game.active, game.finished = False, True
            game._end("checkmate")
            beats, content = await game.review()
            rv = game.last_review
            nf6 = rv.plies[5]
            assert nf6.san == "Nf6" and nf6.kind == "blunder" and rv.worst is nf6 and nf6.color == chess.BLACK
            assert rv.count(chess.BLACK, "blunder") >= 1 and rv.count(chess.WHITE, "blunder") == 0
            said = beats[0].text.lower()
            assert "no blunders" in said and "knight to f6" in said and beats[0].cue == "studyBoard"
            kinds = [b["kind"] for b in content["blocks"]]
            assert kinds.count("image") >= 2 and content["title"].startswith("Game review")
            assert any("Nf6?? blunder" in b.get("text", "") for b in content["blocks"])
        finally:
            await game.close()

    asyncio.run(go())


def test_review_classes_and_turning_point_from_numbers():
    async def go():
        evals = iter([20, 30, 25, 30, 400, 390, 410])

        async def look(b):
            return chess_review.Look(next(evals))

        board = chess.Board()
        for san in ("e4", "e5", "Nf3", "Qh4", "Nxh4", "d6"):
            board.push_san(san)
        rv = await chess_review.analyse(board, look, he=chess.WHITE)
        assert [p.kind for p in rv.plies][:4] == ["best", "best", "best", "blunder"]
        assert rv.worst.san == "Qh4" and rv.turning.san == "Qh4"
        assert chess_review.graph_svg(rv).startswith("<svg")

    asyncio.run(go())
