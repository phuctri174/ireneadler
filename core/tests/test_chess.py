"""Chess with Irene (irene/chess_game.py): his moves by voice, hers by the engine,
what she says true to the engine's numbers."""
import asyncio
from pathlib import Path

import chess
import pytest

from irene import chess_talk
from irene.chess_game import ChessGame, command, parse, settings, spoken, which

ENGINE = Path(settings().engine).exists()


def san(text: str, board: chess.Board) -> str:
    p = parse(text, board)
    assert p is not None and p.move is not None, (text, p)
    return board.san(p.move)


def test_moves_said_aloud():
    b = chess.Board()
    for said in ("e4", "E4.", "e four", "pawn to e4", "I'll play e4", "Irene, e4 please"):
        assert san(said, b) == "e4", said
    for said in ("knight to f3", "Knight to F3", "night to f3", "knight f3", "Nf3", "g1 f3", "g1 to f3"):
        assert san(said, b) == "Nf3", said


def test_captures_and_castling():
    b = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p3/3PP3/5N2/PPP2PPP/RNBQKB1R b KQkq - 0 3")
    assert san("e takes d4", b) == "exd4"
    assert san("knight takes d4", b) == "Nxd4"
    assert san("knight takes the pawn", b) == "Nxd4"
    b = chess.Board("r3k2r/pppq1ppp/2npbn2/2b1p3/2B1P3/2NPBN2/PPPQ1PPP/R3K2R w KQkq - 4 8")
    assert san("castle kingside", b) == "O-O"
    assert san("castles queenside", b) == "O-O-O"
    assert san("castle short", b) == "O-O"
    assert san("bishop takes c5", b) == "Bxc5"


def test_promotion():
    b = chess.Board("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
    assert san("a8", b) == "a8=Q+"
    assert san("a8 queen", b) == "a8=Q+"
    assert san("a8 knight", b) == "a8=N"
    assert san("promote to a knight", b) == "a8=N"


def test_ambiguity_asks_which():
    b = chess.Board("r3k2r/pppq1ppp/2npbn2/2b1p3/2B1P3/2NPBN2/PPPQ1PPP/R3K2R w KQkq - 4 8")
    p = parse("take the bishop", b)
    assert len(p.options) == 2 and which(b, p.options) == "the bishop on c4 or the one on e3"
    assert which(b, parse("castle", b).options) == "kingside or queenside"


def test_illegal_moves_are_refused_with_the_reason():
    b = chess.Board()
    assert parse("knight to f4", b).illegal == "no knight of yours can get to f4 from there"
    assert parse("king e2", b).illegal == "you've already got your own pawn on e2"
    assert "castle" in parse("castle kingside", b).illegal
    pinned = chess.Board("4k3/4r3/8/8/8/8/4N3/4K3 w - - 0 1")
    assert parse("knight to c3", pinned).illegal == "that would leave your king in check"


def test_talk_is_not_a_move():
    b = chess.Board()
    for said in ("what a great game", "are you winning?", "hmm let me think", "the bishop is annoying", "you're good at this"):
        assert parse(said, b) is None, said


def test_commands():
    assert command("Let's play chess!", active=False) == "start"
    assert command("Wanna play a game of chess?", active=False) == "start"
    assert command("I challenge you to chess", active=False) == "start"
    assert command("I played chess with my dad yesterday", active=False) is None
    assert command("What's the Sicilian Defence?", active=False) is None
    assert command("rematch!", active=False, finished=True) == "start"
    assert command("I resign", active=True) == "resign"
    assert command("take that back", active=True) == "takeback"
    assert command("let's stop the game", active=True) == "stop"
    assert command("e4", active=True) == "move"
    assert command("I resign", active=False) is None


def test_spoken_moves():
    b = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p3/3PP3/5N2/PPP2PPP/RNBQKB1R b KQkq - 0 3")
    assert spoken(b, b.parse_san("exd4")) == "pawn takes pawn on d4"
    assert spoken(chess.Board(), chess.Move.from_uci("g1f3")) == "knight to f3"


def test_openings_are_named_by_their_moves():
    assert chess_talk.opening(["e4", "c5"]) == ("Sicilian", 2)
    assert chess_talk.opening(["e4", "e5", "Nf3", "Nc6", "Bb5"]) == ("Ruy Lopez", 5)
    assert chess_talk.opening(["d4", "d5", "c4", "e6"]) == ("Queen's Gambit Declined", 4)


def test_lines_never_repeat_back_to_back():
    lines = chess_talk.Lines()
    said = [lines.pick("his_good") for _ in range(12)]
    assert all(a != b for a, b in zip(said, said[1:]))
    cues = [lines.cue("winning") for _ in range(6)]
    assert all(a != b for a, b in zip(cues, cues[1:]))


def test_every_chess_cue_exists():
    from irene import react

    for kind, family in chess_talk.CUES.items():
        for name in family:
            assert react.resolve(name) is not None, (kind, name)


@pytest.mark.skipif(not ENGINE, reason="Stockfish not installed (core/scripts/setup_stockfish.ps1)")
def test_a_game_with_the_real_engine():
    async def go():
        game = ChessGame()
        try:
            beats = await game.start("let's play chess")
            assert game.active and game.her == chess.BLACK and beats[0].board["status"] == "YOUR MOVE"
            beats = await game.his_move("e4")
            # her answer is a legal move the engine made, announced and shown
            assert len(game.board.move_stack) == 2
            assert any(b.board and b.board["status"] == "YOUR MOVE" for b in beats)
            assert await game.his_move("you're good at this") is None
            refused = await game.his_move("queen to h7")
            assert len(game.board.move_stack) == 2 and "queen" in refused[0].text.lower()
            await game.takeback()
            assert len(game.board.move_stack) == 0
            await game.resign()
            assert not game.active
        finally:
            await game.close()

    asyncio.run(go())


@pytest.mark.skipif(not ENGINE, reason="Stockfish not installed (core/scripts/setup_stockfish.ps1)")
def test_hanging_is_only_said_when_true():
    async def go():
        game = ChessGame()
        try:
            await game.start("")
            # 1. e4 d5 2. Qg4?? - the bishop on c8 takes the queen
            game.board = chess.Board("rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
            beats = await game.play(chess.Move.from_uci("d1g4"))
            said = " ".join(b.text for b in beats).lower()
            assert "queen" in said and any(w in said for w in ("hang", "sitting there", "poor", "leave", "free")), said
            # a sound move is never called a hang
            game.board = chess.Board()
            beats = await game.play(chess.Move.from_uci("e2e4"))
            assert "hang" not in " ".join(b.text for b in beats).lower()
        finally:
            await game.close()

    asyncio.run(go())
