# Rock-paper-scissors

`core/irene/rps.py` (the round), `core/irene/rps_stakes.py` (bets), `core/irene/rps_model.json`
(the classifier), `hud/src/led/gameHand.ts` (her hand), `config/rps.yaml`.

**Status: on, below its accuracy bar, by decision.** It scored 83.3% held out against a
95% bar, and he shipped it anyway for a casual game.

Like [chess](chess.md), the rule is that **the code decides and the model talks**. Who
won, and what that means for a bet, is never the model's call.

## Reading his throw

**Problem.** His hand has to be read at the "shoot" instant, from a webcam, as rock,
paper or scissors.

**Mechanism.**

- The HUD sends the hand landmarks from a fixed window around "shoot": 600 ms before
  to 1400 ms after (`SEND_BEFORE_MS`, `SEND_AFTER_MS`). The trainer chose which frames
  in that window to read, on training sessions only.
- Features describe the hand's shape independent of where it is, how big it looks and
  how it's turned (`rps.features`):
  - per finger: tip distance over palm size, and two joint angles
  - fingertip-to-fingertip gaps
  - the angle between index and middle
  The classifier is softmax regression with per-feature scaling, small enough to ship
  as JSON.
- **Below its confidence floor, she asks for a redo** rather than guess. The floor is
  0.60 for the shipped model: the 5th percentile of its correct cross-validated reads.
- While a game runs, the HUD's game mode suspends the normal gestures, so a fist
  doesn't click and an open hand doesn't zoom. `hud/tests/gameMode.verify.mjs`: 3
  scripted and 11 real takes silent in game mode.

**Considered: a finger-count rule** (`rps.baseline`). It counts fingers whose tip is
farther from the wrist than their middle joint: 0-1 is rock, 2 scissors, 3-4 paper.
It's the baseline the model must beat, and it scored 55.6% held out, with scissors at
0%.

**The bar** (`core/scripts/rps_train.py`). On a whole session the model never saw: at
least 95% of throws right, every class at least 90%, and no worse than the baseline.

**Result.** Held out session `2026-10-16T06-28-48`, 36 throws, replayed 2026-10-17 and
identical to the report stored in `rps_model.json`:

| | accuracy | rock | paper | scissors |
|---|---|---|---|---|
| classifier | **83.3%** (30/36; 3 asked for a redo) | 83% | 75% | 92% |
| finger-count baseline | 55.6% | 75% | 92% | 0% |

**Why it shipped anyway** (`--ship-anyway`, his call; the model file records
`"shipped_below_bar": true`). It's a casual game: a misread costs a redo, not a wrong
action on his PC. The shipped model was then refit on both sessions.

**Cost.** One person's hands, two sessions (72 throws). For anyone else, accuracy is
unmeasured and expected to be lower ([gestures.md](gestures.md#the-model-files-that-ship-and-their-limitation)).

## Fairness: her throw can't depend on his

**Problem.** If she chose after seeing his hand, or could be shown to, the game is
rigged.

**Mechanism.**

- **Sealed before the count.** Her throw is drawn, and its SHA-256 commitment is logged
  **before** his hand is read. The panel shows the hash during the count, and both
  throws are revealed together. Every game is logged in `core/data/games/`.
- **Her LED hand can't leak it** (commit `e16fabd`). Her side is pixel glyphs on her
  face: a side-on fist that pumps on each counted word, then her throw. Her throw
  arrives only inside the `game_shoot` message, the same message that starts reading
  his hand, so it can't appear before his is read. `led/gameHand.ts` is pure (message
  → state, state → pixels), and `hud/tests/gameHand.verify.mjs` checks that the count
  renders identically whatever she has sealed.
- Each result has its own face: triumphant, outplayed, standoff, oops.

## Stakes on a game

**Problem.** He bets: "if I win you sing, if I lose I do the dishes", "loser buys tea",
"best of three". A wrong reading of a bet, or the model deciding who owes what, would
be worse than no feature.

**Mechanism** (commit `a65551b`). The model does exactly two things, and both are
checked:

1. **It finds the stakes, as quotes.** Asked for JSON with the stakes **copied word for
   word** from his message (`parse_messages`, temperature 0, JSON mode). Then
   `rps_stakes.check`:
   - **every quote must be found in his words**, or she asks
   - **which outcome a quote belongs to is read by code**, from the clause it sits in
     ("if I win ...", "if you win ...") or the word before it ("loser ...", "for who
     ..."). The model's own labels are ignored.
   - both a win and a loss must be there; if one is missing she asks for it ("And if
     you lose? I need both sides before I seal anything.")
   - win and lose can't come out the same
2. **It writes her reaction**, ahead of time, while he gets ready. The reaction is
   checked: short, no consequence of either side, no throw, never the opposite result.
   One that fails is replaced by a template.

Then:

- She reads the stakes back in her own voice (his "I" becomes her "you"), with a
  `shakeOnIt` gesture. Nothing is counted until his yes.
- The outcome is the sealed-throw result. `consequence(stakes, outcome)` is **the only
  place an outcome becomes a consequence**, and the consequence sentence is always the
  code's.
- **A staked game reads his hand against a higher bar**: `min_confidence_staked: 0.85`,
  or the model's own floor if that is higher. A wrong call on a bet costs more than a
  redo.
- Best of three: first to two counted rounds, draws replayed.
- Every stakes event (parse, ask, confirm, settle) goes into the game log beside the
  sealed throws that led to it.

**Considered: trusting the model's labels.** The JSON still has labelled fields
(`he_wins`, `he_loses`), but `check` doesn't trust them. The code comment says why:
"never taken from the model's labels, which a 12B model swaps often enough to matter".
The swap rate itself was not recorded.

**Why.** Finding a phrase in a sentence is easy for a model to do and easy for code to
check: the quote is either in his words or it isn't. Deciding who it applies to is easy
for a model to get backwards and hard to check after the fact. So the model does the
first, and code does the second.

**Cost.** Phrasings the clause reader doesn't know get a question instead of a game.
Unit-tested (`tests/test_rps_stakes.py`); **no live measurement of stakes parsing is
recorded.**

## Ending a game

It ends when he says so, after 90 s with no round (`rps.IDLE_END_S`), or through the
mode guard at 2 minutes ([modes.md](modes.md#no-mode-can-get-stuck)).
