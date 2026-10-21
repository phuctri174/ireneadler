# Irene: the documentation

These documents explain how Irene works and why it is built this way: for each part,
the problem, the mechanism, what else was considered, why this was chosen, and what it
costs. Where a bug taught something, the bug is recorded with its lesson.

## Suggested reading order

Start with the project [README](../README.md) for what Irene is and the architecture
diagram. Then:

| # | Read | You'll understand |
|---|---|---|
| 1 | [lessons.md](lessons.md) | the nine failures that shaped the project, and the rule each one left. The fastest way to see how decisions here are made |
| 2 | [evals.md](evals.md) | the method: instrument what runs, hold out whole sessions, ship only past a bar set in advance, and say so when it isn't met |
| 3 | [voice-pipeline.md](voice-pipeline.md) | one spoken turn, mic to speaker: speaker check before Whisper, the wake phrase, echo cancellation, streaming TTS |
| 4 | [modes.md](modes.md) | who answers a message, how a mode starts in code, the mode lock, his orders over it, study mode |
| 5 | [tool-protocol.md](tool-protocol.md) | how the model acts: a prompt protocol, the fast path, the router, and every check a call passes |
| 6 | [security-model.md](security-model.md) | why every defence is code, not prompt: the taint guard, the path whitelist, no delete tool, the publish scan |
| 7 | [memory-and-provenance.md](memory-and-provenance.md) | memory that can't invent, questions about the world, and teaching her facts by voice |
| 8 | [gestures.md](gestures.md) | the hand: an OS-level pointer, raw landmarks for decisions, the zoom classifier's four steps |
| 9 | [kendo.md](kendo.md) | the body: why the strike detector is a threshold, shiai's men as a sequence, why tsuki is off |
| 10 | [rps.md](rps.md) | a classifier shipped below its bar by decision, a sealed throw, and stakes where the model quotes and code decides |
| 11 | [chess.md](chess.md) | the engine as the only source of chess facts, and her strength measured |
| 12 | [lecture-capture.md](lecture-capture.md) | a second audio path that must never meet the speaker check, and map-reduce with quote checks |
| 13 | [hardware-constraints.md](hardware-constraints.md) | fitting everything into 16 GB of VRAM on one Blackwell card |

**If you have ten minutes:** the README's architecture and measured results, then
[lessons.md](lessons.md) 1, 6 and 7.

## Ideas that recur

These come up in almost every document. Knowing them first makes the rest faster.

- **Code decides, the model talks.** Chess facts come from Stockfish, rock-paper-scissors
  outcomes from a sealed throw, a bet's consequence from `rps_stakes.consequence`, mode
  entry from regexes, memory claims from a lexical guard. The model voices facts it is
  handed. Several of these moved into code after the model got them wrong: a sister it
  invented, a false lecture deadline, swapped stake labels
  ([memory-and-provenance.md](memory-and-provenance.md#provenance-memory-that-cant-make-things-up),
  [lecture-capture.md](lecture-capture.md#the-summary-map-reduce-with-quote-checks),
  [rps.md](rps.md#stakes-on-a-game)).
- **Defences in code, not in the prompt.** The model is assumed to sometimes obey what
  it reads and to sometimes invent. The taint guard, the provenance guard and the mode
  lock hold whatever the model writes ([security-model.md](security-model.md)).
- **Measure the thing that runs.** Evals go through the live turn, gesture models are
  checked against ports of the live gate, and claims are re-checked by a separate engine.
  More than once, the score of a proxy disagreed with the real thing
  ([evals.md](evals.md#the-eval-harness-measured-a-prompt-nobody-used)).
- **Hold out whole sessions, and ship past a bar or say why not.** Zoom shipped when it
  beat the incumbent at the real distance. The strike recogniser and kamae trigger are
  off. Rock-paper-scissors shipped below its bar by an explicit decision, and the model
  file says so.
- **A state must persist, not flicker.** Hold-grace on every pose trigger
  ([lessons.md](lessons.md#3-hold-grace-the-same-bug-fixed-the-same-way-five-times)).
- **His orders always win.** A lock stops *her* wandering off, never *him*
  ([modes.md](modes.md#his-orders-always-win)).

## Conventions

- **Every number cites its source**: a commit, a date with the script that produced it,
  or a live run. A number with no source is a mistake in these docs.
- **"Live"** means the running app (`start-irene.ps1 -Dev`) with real models. Live
  checks drive it through the dev socket or replays of his recorded voice, never through
  OS input.
- **"Off"** features say so in the heading or table, with the measured reason.
- **His voice and body data** (recordings, voiceprints, captures) are never in the
  repository. Tests that replay them skip on a fresh clone.

## The map: where each subsystem lives

| Subsystem | Code | Doc |
|---|---|---|
| hearing, wake, voice | `core/irene/listen.py`, `aec.py`, `speaker_id.py`, `stt.py`, `wake.py`, `voice.py`, `tts.py` | [voice-pipeline.md](voice-pipeline.md) |
| who answers | `core/irene/dispatch.py`, `modes.py`, `fast.py`, `router.py` | [modes.md](modes.md), [tool-protocol.md](tool-protocol.md) |
| the model's turn | `core/irene/brain.py`, `reply.py`, `tools/registry.py` | [tool-protocol.md](tool-protocol.md) |
| memory | `core/irene/memory.py`, `recall.py`, `provenance.py`, `taught.py` | [memory-and-provenance.md](memory-and-provenance.md) |
| guards | `core/irene/brain.py` (taint), `grounding.py`, `tools/policy.py`, `tools/sandbox.py` | [security-model.md](security-model.md) |
| hand | `hud/src/tracking/gestures.ts`, `useHandTracking.ts`, `hud/src-tauri/src/pointer.rs` | [gestures.md](gestures.md) |
| body, kendo | `hud/src/tracking/poseTracking.ts`, `strikeEvent.ts`, `strikeKind.ts`, `core/irene/shiai.py`, `keiko.py` | [kendo.md](kendo.md) |
| study mode | `core/irene/study.py`, `hud/src/led/study.ts` | [modes.md](modes.md#study-mode) |
| games | `core/irene/rps.py`, `rps_stakes.py`, `chess_game.py`, `chess_talk.py` | [rps.md](rps.md), [chess.md](chess.md) |
| lecture | `core/irene/lecture*.py` | [lecture-capture.md](lecture-capture.md) |
| her face and board | `hud/src/led/`, `hud/src/board/`, `core/irene/drawing.py` | the project [README](../README.md#features) |
| publishing | `core/scripts/publish.py` | [security-model.md](security-model.md#publishing-the-only-route-out) |
