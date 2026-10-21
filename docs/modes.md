# Modes: entering, holding, leaving

A **mode** is an activity that takes over her: chess, shiai, study mode, keiko,
rock-paper-scissors, a strike calibration, lecture capture. This document covers how
one starts, how it holds the screen while it runs, how he gets out of it, and study
mode itself. Shiai is in [kendo.md](kendo.md#shiai), chess in [chess.md](chess.md),
rock-paper-scissors in [rps.md](rps.md), lecture capture in
[lecture-capture.md](lecture-capture.md).

Code: `core/irene/modes.py` (entry words, the lock, the gate), `core/irene/dispatch.py`
(who answers a message), `core/irene/app.py` (`_mode_guard`).

## Who answers a message

`dispatch.route` decides, in one order shared by the app and the evals:

1. **With a mode on, his orders about modes**: an exit, or an exit plus something else
   ([below](#his-orders-always-win)).
2. **The mode claims**, in a fixed order (strike calibration, shiai, keiko, study,
   rock-paper-scissors, chess). Each is asked whether it takes the words: the active
   mode's own commands (a chess move, "resign", "yame") or any mode's start phrase.
   Another mode's start, said while one is on, is a switch.
3. **With a mode on, the lock**: an explicit request it refuses gets her brush-off
   ([below](#the-mode-lock)).
4. **A pre-rendered quick reply** (hello, thanks), which needs the whole message to
   match.
5. **The model path** (`Conversation.respond`). Its first stop is the fast path
   (`fast.py`): unmistakable commands answered by a tool and a template, with no model
   call ([tool-protocol.md](tool-protocol.md#before-the-model-the-fast-path-and-the-router)).

The evals record which of these answered each case (`who`), so a failure can be pinned
on the right layer ([lesson 6](lessons.md#6-the-model-misroute-that-was-a-regex)).

## Entering a mode: matched in code

**Problem.** His first live test of shiai and study mode failed on the words, not the
modes (commit `a909ea3`). Whisper wrote "shiai" as "CI" and "Xi'an", and "Learn
Sicilian" went to research.

**Mechanism.**

- **Modes are a closed set**, and each one's start phrases are regexes matched before
  the fast path and the model. Neither can send "learn the Sicilian" anywhere else.
  Lecture capture is a tool, but its start is matched in code too (`fast.py`).
- **Whisper's mishearings are put back** by `modes.heard()`, only where a command stands:
  "let's do CI" is shiai, "our CI pipeline" is not. Every alias came from his own voice,
  either logged live or re-decoded from his saved turns: CI, Xi'an, xi-ai, Si An, Sii;
  "Go La Sicilia"; "stripe" and "Mindstrike" for strike.
- **Hotkeys** need no voice at all: Ctrl+Alt+Shift+S toggles study mode and
  Ctrl+Alt+Shift+M toggles shiai. A global shortcut sends `irene://mode`, and the HUD
  tells core. No keystroke is ever sent.

**Considered: more Whisper hotwords.** Hotwords bias decoding toward listed words. The
budget is full (223 tokens of his vocabulary), so the fix had to come after
transcription.

**Why code, not the model.** A mode is a closed set of known commands, so a regex is
exact and costs nothing. Every case the model would decide is a case it can get wrong.

**Cost.** A regex knows only the phrasings it has. Each new mishearing has to be found
and added; `tests/test_modes.py` holds every mode's entry phrases, the mishearings, and
the talk about the same things that must still reach the model ("I studied the
Sicilian all weekend", "I need to go study for my exam").

**Measured.** His seven saved turns from that test, replayed through the live mic
pipeline (-Dev): **7/7** to the right mode, none researched.

### The verb decides: study mode or research

"Learn X", "go learn X", "study X" and "learn about X" start **study mode**, for any
subject: tenouchi, suriage waza, black holes. "Research X", "look up X" and "search
(for) X" are the **research tool** (`fast._RESEARCH`, `fast._SEARCH`). Searching his
files or YouTube stays with their own tools. They may look up the same thing; the
difference is the experience. Study mode is the progress bar and him hitting her;
research is the dashboard and the PDF.

## The mode lock

**Problem.** Filming, he trash-talked mid-game ("You can even play Sicilian?"), and she
replaced the chess board with a drawing (commit `746385f`). Two things went wrong at
once: the opening rule sent the message to research, and the reply's `<draw>` took over
the board.

**Mechanism.** While a mode is on, it owns the display until he ends it. He can still
talk to her, and trash talk is answered in character. Everything that would repaint the
display is blocked in three independent ways, none of them an instruction the model
could be talked out of:

1. **The tools aren't there.** For that turn, the model is offered only the tools that
   change nothing on screen (`modes.QUIET_TOOLS`): time, timers, volume, media, PC
   status. Lecture capture adds its own stop and questions. A call to any other is not
   run and not kept; she says a brush-off instead.
2. **The turn has no board.** No illustration plan, her `<draw>` is dropped, and no
   answer is kept for the panel.
3. **The display is gated.** A locked turn's task carries `modes.HOLD`. `Bridge.send`
   drops anything from it that repaints (`modes.REPAINTS`: a draw, a board term, the
   panel, a scene, an entrance, a summon, a URL). The mode's own handlers never run
   under the hold, so a chess move still redraws its board.

**Considered: telling the model in the prompt.** No prompt-only version is recorded.
The design follows the [taint guard](security-model.md#taint-guard): anything the model
can be talked into, it eventually will be, so the rule lives where it can't be.

**Why three layers.** Each one covers a different way through. A refused tool covers a
call. No board covers a drawing written in the reply. The gate at the socket covers
anything that reaches the HUD by a route nobody thought of.

**Cost.** A request he means is refused too. An explicit request for something that
isn't a mode ("research X", "draw me X", the panel, screens off) is decided in code
(`dispatch.BLOCKED`) and gets a short in-character line that always says why ("Not now
- we're in the middle of a chess game. Your move."). A refusal must never pass for a
bug. The request is dropped, not queued (roadmap).

**A bug the first live run found.** The gate first listed the dashboard. The live check
counted the dashboard's CPU readout, which is sent every few seconds, as a repaint, and
that showed a real flaw: a timer set mid-game (an allowed tool) would never have reached
its card. The dashboard came off the list.

**Measured.**

| What | Result | Source |
|---|---|---|
| every blocked tool during every mode, the call written as the model writes it, through the app's turn and the real `Bridge` | 28 tools × 7 modes: **0** ran, **0** repaints at the HUD socket; with the lock off the same cases fail (35/35) | `tests/test_mode_lock.py`, 2026-10-18 |
| lock and verb routing cases | **78/78** (26 × 3) | `evals/routing_subset.py --repeat 3`, 2026-10-18 |
| in the running app | trash talk mid-chess answered with the board untouched; 9/9 blocked requests refused in code, none repainted. 2 of 15 driver checks lost her spoken line to real camera strikes, after the refusal was logged | `scripts/mode_lock_live_check.py`, 2026-10-18 |

## His orders always win

**Problem.** The first lock refused "cancel the chess match then learn tenouchi",
because it blocked any other mode's start. The lock is there to stop *her* wandering
off, never to stop *him* giving an order.

**Mechanism.** Before the lock, in code (`modes.order`, `dispatch.route`):

- **An exit** ("cancel", "quit this", "stop the match", "forget the chess", "never mind
  the game", "put the book down", "I'm done") ends whatever mode is on, with its own
  goodbye (`dispatch.EXIT`).
- **A switch**: another mode's start said outright, or its hotkey, ends this one quietly
  and starts that one (`dispatch.SWITCH`).
- **A compound**: an exit, then something else, in one breath. "Cancel the chess match
  then learn tenouchi" is chess off and study mode on tenouchi, in one turn.
  - An exit that names the mode ("stop the game, what time is it?") takes anything
    after it.
  - A bare verb ("stop and ...") takes only another mode, so "stop and think about it"
    is talk.

What stays blocked is *her* unrequested takeover. Trash talk that names a game ("I'd
beat you at rock paper scissors too") is answered in words.

**Measured.** `tests/test_mode_switch.py`, every mode into every other through the app's
real turn, said outright and as exit + start with four joints ("then", ",", "and then",
"."), 12 exit phrasings × 7 modes, 9 trash-talk lines × 7 modes that must never leave:
**372/372**. Routing cases for the same: **222/222** over 3 runs (2026-10-18).

The eval run found one real bug before any live run. `modes.heard` put Whisper's
"calibrate my stripe" back as "calibrate my strikes", which turned "calibrate my strike
types" into "strikes types". Fixed that day; the strike-type calibration itself was
removed on 10-19.

## No mode can get stuck

**Problem.** After a bout, "learn the Sicilian" seemed to do nothing, and it looked like
a stuck mode. It wasn't: Whisper heard "Hey learn Sicilian please", the "hey" kept and
her name dropped, so it fell through to chat. "Hey ...", "you learn X" and "let's learn
X" now start study mode. But the investigation showed chess and lecture capture had no
idle limit at all (commit `e463dd1`).

**Mechanism.** Two layers:

- **Each mode's own watchdog.** Shiai ends after 120 s with no strike or 15 min in all;
  study mode at 10 min; keiko and rock-paper-scissors on their own idle limits.
- **One guard, always running** (`app.Core._mode_guard`). It ends any mode with nothing
  happening in it past `modes.IDLE_LIMIT_S`, even one whose own watchdog has died, and
  says so: strike calibration 1 min, rock-paper-scissors 2, shiai and keiko 3, study 11,
  chess 20, lecture capture 30 (with no new words).

It also writes the mode she thinks she's in on the dashboard header ("Mode: Shiai",
"Mode: none"), and a mode hotkey clears whatever mode is on.

**Why both.** The watchdogs know what "nothing happening" means for their mode. The
guard knows nothing about any mode, which is exactly why a bug inside one can't
disable it.

## Study mode

`core/irene/study.py`, the LED scene `hud/src/led/study.ts`.

**Problem.** A gag for his videos: she studies something, and he hits her to make her go
faster.

**Mechanism.**

- **The scene.** Her face goes compact and head-down over an open book, with a pen hand
  writing along the line it has reached. The written lines are the progress. The
  subject runs along the top, the bar along the bottom. Unhit, the bar fills in 90 s
  (`BASE_S`).
- **Muttering.** She mutters lines the model writes for the subject now and then, never
  within 4 s of her last words or 5 s of a hit.
- **Hits.** Each [strike event](kendo.md#strike-events) is a hit. The bar jumps 6%
  (`HIT_JUMP`; the segment flashes white and sparks fly) and fills 25% faster per hit
  from then on (`SPEEDUP`). Hitting every 4 s fills it in about 7 hits.
- **Her reaction escalates.** Each tier has its own art, motion and full-face theatre:

  | Hits | Line | Face |
  |---|---|---|
  | 1-2 | "Ow!" | `bonked`: one eye winced shut, stars circling |
  | 3-4 | "I AM studying!" | `indignant`: brows in a V, an anger mark |
  | 5+ | "Okay okay okay okay!" | `surrender`: T_T, waterfall tears, a white flag |

- **When the bar fills**, she says what she learned. A chess opening she has a book line
  for (the Sicilian, the Caro-Kann, the Nimzowitsch) goes straight into a game, with
  her book **pinned** to that defence. Another chess subject starts an ordinary game.
  Anything else, she only summarises.
- **Eight hits or more** (`TOO_FAST`) and she finishes "too fast": she gets a detail
  wrong and corrects herself out loud. For a book defence the fumble is built from the
  real lines ("The Caro-Kann starts 1.e4 c5. Wait. No. That's the Sicilian."), never the
  model's.
- The first time, with no strike calibration, she asks for three swings first.

**Cost.** The hits are the strike event, with its desk false positives: typing fires it
([kendo.md](kendo.md#strike-events)). In study mode he's holding a shinai, not typing.

**Measured live** (`scripts/study_live_check.py`, swings sent as the HUD sends them,
2026-10-17):

- 9/9 checks: 6 swings at 4 s took the bar from 0.27 to 0.95 through the tiers ow, ow,
  indignant, indignant, uncle, uncle. She then played 1...c5.
- 10/10 rushed: 9 swings at 1.2 s; she fumbled, caught it, and played 1...c6.
- A plain subject was only summarised.

Routing: study routes 6/6, and his own studying never taken as study mode 9/9.
