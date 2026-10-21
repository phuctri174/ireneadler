# Chess

He plays by voice; Stockfish plays her moves; the language model never chooses,
names or judges a move.

## The split

| Who | Does |
|---|---|
| code (`chess_game.parse`) | his words to a legal move: "e4", "knight to f3", "castle kingside", "take the bishop", "e takes d5", and what Whisper makes of them ("night to F3", "e four"). An illegal move is refused with the reason; an ambiguous one asks which |
| code (`chess_game.command`) | start, resign, takeback, stop, review, matched before the model |
| opening book (`chess_book.py`) | her first moves: 1.e4 as White; as Black the Sicilian, Caro-Kann or Nimzowitsch against 1.e4 (picked at random, or pinned to the one she just studied - study mode, `study.py`), the Nimzo-Indian against 1.d4 when allowed. At most 6 of her moves deep (`book_moves`); once he leaves the book the engine takes over |
| Stockfish, strength-limited | her moves after the book: `UCI_LimitStrength` with `UCI_Elo` 1350, from an empty hash, depth 6 or 300 ms, whichever comes first (`config/chess.yaml`) |
| Stockfish, full strength | a look at the position after every move (250 ms), which selects what she says |
| the model | her voice around facts it was handed; mid-game banter with the game in context |

**Commentary is selected, not generated** (`chess_talk.py`). "That hangs your knight"
is said only when the engine's best reply takes the knight; "nice one" only for a
move the engine rates; "I think I'm losing" only when the full-strength score crosses
a threshold against her. Several lines per moment, never the same twice running.

**She never resigns** (2026-10-19). She plays on to checkmate or stalemate. Nothing
claims or agrees a draw: only the board ends a game (mate, stalemate, too little
material, and its own automatic fivefold-repetition and 75-move rules); threefold is a
claim, and nothing claims it. Behind (her score -1 pawn or worse) she never shuffles into
a repetition to escape: the engine searches only the moves that don't bring back a
position the game has had (`fresh_moves`, the engine's own `root_moves`, at her usual
strength), so he actually gets to deliver mate.

**She feels it coming.** As the engine's numbers collapse she says so, each step once and
only as it gets worse (`rattle_level`): crumbling (-6 pawns), collapsing (-10), "you have
a mate, don't you", the mate two or three moves away, mate next move. Checkmate gets its
own lines, several, written to land - that is the moment he films for. The outcome is
always the board's; she only narrates. In a lost king-and-queen ending played to mate
with the real engine (`tests/test_chess.py`) she said: "Wait. Wait wait wait. Is that
mate coming?" - "No no no no. My king has nowhere to go. Nowhere!" - "...It's mate next
move. I can see it. Please don't see it." - and at mate: "Checkmate. Okay. Okay. I'm
fine. I'm completely fine. Set them up again. Right now."

**Her strength** (2026-10-19). Everything is in `config/chess.yaml`:

- `elo` (1350; Stockfish's floor is 1320, and anything lower is clamped up)
- `think_ms` (300) and `max_depth` (6): her search stops at whichever comes first
- `book_moves` (6): her opening book, counted in her moves

How the options reach the engine (traced with python-chess's UCI log):

- At engine start: `setoption UCI_LimitStrength true` and `setoption UCI_Elo 1350`, then `isready`. The engine answers `readyok`, and core.log records it with the engine's config.
- Before every move of hers, on the same engine process: `setoption Clear Hash`, `setoption UCI_LimitStrength true`, `go depth 6 movetime 300`.
- The full-strength looks set `UCI_LimitStrength false` for that one search only.

UCI has no per-option acknowledgement, so each of her moves logs the engine's own top line next to the move it played. A different move means the limiter chose it. Live, 2 of her first 4 engine moves differed.

**The hash leak.** The full-strength look at a position ran just before her search of that same position. Her weakened search then read the deep analysis out of the hash table. Her search now starts from an empty hash.

**The book is perfect theory** whatever the Elo, so she plays best in the opening:

- As Black: up to 6 of her moves (the Nimzo-Indian's ...b6 is the deepest line).
- As White: only 1.e4.
- The book stops the moment he leaves its lines.
- `book_moves` cuts it shorter.

**Measured** (`scripts/chess_strength.py`):

- The setup: 10 whole games per setting through the real `ChessGame`, looks included, against a fixed opponent (Stockfish Skill Level 8 at 100 ms). The opponent won all 40 games.
- Scoring: every one of her engine moves is scored by a separate full-strength Stockfish at depth 12. The scores are taken from her side and clamped to ±1000 centipawns.
- A blunder loses 300 centipawns or more.

| setting | average centipawn loss (± standard error) | median loss | blunders per game | her time per move |
|---|---|---|---|---|
| before: 1450, 500 ms, the look's hash kept | 42.3 ± 3.7 (419 moves) | 7 | 0.5 | 434 ms |
| 1450, empty hash, depth 6 | 47.4 ± 4.6 (353) | 8 | 0.8 | 7 ms |
| **shipped: 1350, empty hash, depth 6** | **51.5 ± 5.3 (331)** | **16** | **1.0** | 7 ms |
| the floor: 1320 | 53.7 ± 5.8 (317) | 14 | 1.3 | 8 ms |

Every step makes her weaker: blunders doubled and the median loss doubled. The average loss moved by less than its noise, though. Even at the floor, Stockfish's limiter makes small slips more than real blunders. That is cleaner than a typical 1400-1500 player, who hangs pieces, so 1320 is as low as `UCI_Elo` goes.

**The review** after a game (`chess_review.py`) analyses every position at full
strength: centipawn loss per move, classified best / good / inaccuracy / mistake /
blunder, and an accuracy per side using lichess's win-percentage formula. She narrates
what it found; the panel shows the evaluation graph and key positions, and saves as a
PDF.

## Why this design

An LLM narrating chess will say a piece is hanging when it isn't, and a 12B model
cannot reliably track a position. Making the engine the only source of chess facts
turns "is her commentary true?" into something that can be checked.

## Measured

`evals/chess_evals.py` has three parts:

- **moves:** spoken moves, written the way Whisper writes them, must parse to the
  right legal move; illegal ones must be refused; talk must never be taken for a move.
- **commands:** start / resign / takeback / stop / review, and phrasings that must not
  trigger them.
- **truth:** whole games against a sparring Stockfish at varying skill. Every time
  she says a piece hangs, or that she is winning or losing, a **separate Stockfish
  instance at fixed depth 14** re-scores the same position and must agree. This is
  independent of her own 250 ms look, but it is the same engine program, not a second
  engine.

| Part | 2026-10-17 | Recorded at build (commit `811e1dc`, 2026-10-12) |
|---|---|---|
| spoken moves | 69/69 | 69/69 |
| commands | 43/43 | 34/34 (the set has grown since) |
| colour answers | 20/20 | - |
| her claims confirmed by the depth-14 check | **13/13** over 4 games | 7/7 over 4 games |
| her strength, 1350 vs the old 1450 (2026-10-19, `scripts/chess_strength.py`, 10 games each) | average centipawn loss 51.5 vs 42.3; 1.0 vs 0.5 blunders a game | - |

Live at build time (`start-irene.ps1 -Dev`, `scripts/chess_live_check.py`): 12/12
steps: board up, two moves, an illegal one refused, talk with the board kept,
takeback, resign.
