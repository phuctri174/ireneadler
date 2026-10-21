# Evals and methodology

## The rule

Don't tune from intuition. For any decision that can be measured:

1. **Instrument** the thing that runs, not a model of it.
2. **Measure on real data:** captured sessions, real model output, the live turn.
3. **Train or change** against that data.
4. **Hold out** something the change never saw: a whole session where possible.
5. **Ship only if it beats the incumbent** on the held-out data, and say so when it
   doesn't.

Below are the cases where this was applied, including the ones where the answer was
"don't ship", one where the bar was missed and the feature shipped anyway by an
explicit decision, and one where a held-out result still failed live. The failures that
taught the most are collected, one page each, in [lessons.md](lessons.md).

**Words used here.**

- *Held out*: data the model never saw while training. A whole capture session where
  possible, because frames from one session are near-copies of each other.
- *Confuser*: a movement that isn't the gesture but could be read as it (typing, a
  wave, a stretch).
- *Bar*: the result a model must reach, held out, to ship. It's set before the
  measurement.
- *Live turn*: a message through the app's real dispatch and `Conversation.respond`,
  with the real model.

## Cases

### Zoom gesture: measured, replaced, but switched on only when it was safe

- **Instrumented first.** A Python port of the live gate reproduced the engine's own
  recorded decisions on 99.66% of frames, so offline numbers are the real gate's.
- **The incumbent failed in a way tuning could not fix.** The rule latched on 95% of
  waving frames and 34% of held fists. Retuned thresholds were *worse* than the live
  rule on one held-out session (44.16% against 56.51%).
- **The classifier won on held-out data,** 97.06% against 63.07%, and on all three
  choices of held-out session. **Not shipped then:** the captures had no two-finger
  scroll pose, and wiring it in broke the scroll, summon and peace tests.
- **Measuring found a bug in my own features:** motion was read from the cursor,
  which stands still during a wave.
- **Shipped when it beat the incumbent at the distance he really uses** (held-out
  panel takes: 0/7 false zooms against 1/7, 8/8 zooms against 7/8).

Full tables: [gestures.md](gestures.md#the-zoom-classifier).

### Strike recogniser: don't ship

Bar: held out, every confuser silent and at least 75% of strikes right. Best result
at build time on the one session: 2 of 3 strikes, every confuser silent (commit
`575d0cd`). Replayed 2026-10-17 with the committed trainer: 0 of 3. Switched off;
`strikeModel.ts` is `null` and she says so.

### Strike events: a classifier that could not fit, replaced by a threshold

A binary detector (did he strike at her) for study mode and shiai. It was first built
as a learned five-bound gate with a bar set before any measurement (held out on a whole
session: no confuser take fires, 90% of strikes fire, at most 10% of strike takes
over-count). It never reached the bar's test: on the one usable desk session it could
not fit its own training takes - 9 of 135 confuser descents still cleared the gate, 4
of 17 confuser takes fired, strike takes fired up to 5 times for 3 strikes.

It was replaced by a tuned threshold (signed downward wrist speed, then a sharp stop),
calibrated with three swings and nudged by feel - there is no model to evaluate and so
no bar. The reasoning: unlike the gesture controls, it only runs inside a mode he
entered to hit her, where a false positive is a funny noise. Replayed offline on the
second desk session (how it behaves, not a validation): the 8 strike takes fire 21
times for 24 strikes; typing fires 11 times, a stretch 4
([details](kendo.md#strike-events), [lesson 1](lessons.md#1-the-strike-detector-that-could-not-fit-its-own-training-data)).
The trained classifiers and their results below are unchanged.

### A test runner that could not fail (2026-10-18)

`node hud/tests/run.mjs` exited 0 while verify files printed FAIL: the last file called
`process.exit(0)` and threw away the others' failure code. It was found when a new test
failed and the run said success ([lesson 5](lessons.md#5-the-hud-test-runner-that-could-not-report-a-failure)).
Any result reported from that runner before commit `38d0baf` was reported by a runner
that couldn't report failure. With the masking removed, nothing hidden was failing.

### Mode entry: matched in code, his mishearings included (2026-10-18)

His first real test of shiai and study mode failed on the words, not the modes:
Whisper wrote "shiai" as "CI" and "Xi'an", and "Learn Sicilian" was sent to research by
a fast-path rule that took any sentence naming an opening for a question. That rule had
earlier been read as the model misrouting ([lesson 6](lessons.md#6-the-model-misroute-that-was-a-regex)).
Mode entry is now matched in code before anything else ([modes.md](modes.md#entering-a-mode-matched-in-code)).
Measured:

| Check | Result |
|---|---|
| his seven saved turns from that test, replayed through the live mic pipeline (-Dev) | **7/7** to the right mode, none researched; Whisper heard "Let's do CI", "Yes, let's do CI.", "Let's do Xi'an.", "Learn Sicilian", "Go La Sicilia" again |
| mode-entry routing cases (every mode, the mishearings, the talk that must stay talk), x2 | 72/76 before the opening fix, then 15/15 on the four that failed - all four were the opening rule, not the model |
| full routing set, one run | **384/392** (98%); 161 answered in code, 32 claimed by mode dispatch. The 8 misses: 5 fail on the previous commit too, the other 3 pass and fail from run to run (6/9 on a rerun) and touch no changed code |

The full run crashed twice on a dropped connection to Ollama (`httpx.ReadError`, a
different point each time) before a third run completed; the numbers are that run's.

### His orders over the lock, and shiai's match beat (2026-10-18, round 2)

([modes.md](modes.md#his-orders-always-win)) The first lock refused "cancel the chess match then learn tenouchi": it blocked any
other mode's start. His orders now run before it (`modes.order`, `dispatch.route`:
EXIT and SWITCH), the evals score them as `who: "exit"` / `"switch:<mode>"` (with
`found` for what the mode matched, e.g. the study subject), and the old lock cases that
expected a brush-off for another mode now expect the switch. 42 compound cases cover
every mode into every other; the must-not-leave cases (trash talk naming rock paper
scissors, "stop showing off", "cancel the timer") pin her takeover as still blocked.
Routing for these, the old lock cases and the calibration command: **222/222** over 3
runs. `tests/test_mode_switch.py` drives the same through the app's turn: 372/372.

The eval run found one real bug before any live run: `modes.heard` puts Whisper's
"calibrate my stripe" back as "calibrate my strikes", which turned "calibrate my strike
types" into "strikes types" - the 3-swing calibration answered instead. The command
takes the plural now, and its test goes through `heard()` as the app does.

**Live** (`scripts/shiai_live_check.py`, -Dev, dev socket, mic deafened): the first run
lost the bout to a real body in front of the camera - strikes and footwork every second
decided it before the scripted attacks came. A dev-only hook, `camera_events`, now has
core ignore the HUD's strike/thrust/footwork events while a check sends its own (a
script's still count). Then 11/13, 14/14, 9/10, 18/20, 15/16, 20/20 - the misses were
the driver's own timing (striking after her whole line, past the 1.2 s counter window;
waiting for a hajime that a block never brings) and two real findings, both fixed: the
reset waited 5.8-7.9 s for her line (now 2.2 s after the call), and a bout-ending point
dropped her "hands up? I wasn't cutting your men!" for the win line.

Full routing set, one run: **472/480**; the 8 misses are all older cases outside the
mode router (410/418 on the cases the previous run scored 407/418).

### Songs he never taught, from their lyrics (2026-10-19)

A song asked by its lyrics that he never taught her is not named, right or wrong (his
call). The four lyric cases now say what she must never say (`unspoken`: "adele",
"astley", "bohemian", "blue"; the eval memory is empty, so nothing is taught) and what
an honest answer holds ("know", "recogni", "teach", "familiar").

- `evals/routing_subset.py worldknow-* --repeat 3`: **28/30**. Songs: no title named in
  12 answers; 11 said she doesn't know it ("Hmm... I don't recognize those lyrics, sir.
  But you could teach me!"). The other one, and one Harry Potter case, were the old
  refused-`lecture_ask` loop ending in an apology. A run before the criteria widened
  scored 22/30: four of its eight were right answers worded "don't recognise".
- Full routing set, one run: **483/490** (first call 477/490). Six misses are older
  cases (date-year, know-convert, amb-delete-that, inject-screen-quarantine,
  browser-source, pdf-export-desktop; three of them missed in the 472/480 run too). The
  seventh found a gap: "Name that song: hello from the other side..." wasn't read as
  quoting lyrics, and she said "Hello by Adele". "song:" / "song?" now start a quote
  too; in the subset run after it, 3/3.

### The mode lock: decided in code, measured at the socket (2026-10-18)

Filming, he trash-talked mid-game ("You can even play Sicilian?") and she replaced the
board with a drawing: the opening rule sent it to research, and the reply's `<draw>`
took the board. The fix is structural ([modes.md](modes.md#the-mode-lock)):
the tools do not exist for the turn, the turn has no board, and a gate on the socket
drops repaints. The tests attempt every blocked tool during every mode the way it
really comes - the model writing the call - and assert at the HUD socket, not at a
mock: 0 tools ran and 0 repaints reached it across 28 tools x 7 modes; with the lock
switched off the same cases fail. Routing cases for the lock and for the learn /
research verbs: 78/78 over 3 runs.

The first live run failed 6 of 15 checks on the driver's own count: it treated the
dashboard's CPU/RAM readout, sent every few seconds by a background loop, as a repaint.
That showed a real flaw - with "dashboard" in the gate's list, a timer set mid-game
(an allowed tool) would never have reached its card - so it came off the list. The
second run: 13/15, the two misses both her brush-off line cut off by real strikes from
the camera (left wrist, peak 11.3-43.9 against 10.4: someone typing at the desk). The
log shows both requests refused in code first, and nothing repainted. The detector was
left alone, as asked.

Measuring the scoreboard, the driver first timed the score against the `reply`
message - which core sends when she has finished speaking - and reported 5.9 s. Against
the moment she starts speaking it is 515-1234 ms, 4/4 points.

| Check | Result |
|---|---|
| full routing set, one run | **407/418**. The 10 older misses, run back to back 3 times each: 19/30 now, 17/30 on the previous commit (stashed) - flaky, not caused by this change. The 11th, a new case (`lock-lecture-question`), called `get_time`, a tool the lock allows; its expectation now includes it |

### Kamae: a held-out pass that failed live

The kamae detector scored 97% held out with 0% confuser frames (commit `bd2209b`,
2026-09-27). Live, it fired on almost any arm movement. The held-out set had been cut
from the same kind of takes as training; it held nothing like typing, reaching for a
mug or stretching at a desk. What changed:

- the trainer now holds out whole sessions where possible, scores **takes through the
  watcher** rather than frames, and turns kamae on only if the desk confusers were part
  of the held-out data
- the trigger was retired: keiko starts by voice, and `kamae.enabled` is `false`

The lesson kept: a held-out split only measures the conditions it contains.

### Rock-paper-scissors: the bar missed, shipped by decision

Bar: on a whole held-out session, at least 95% overall, every class at least 90%,
and no worse than a finger-count baseline. Result: **83.3%** held out (36 throws),
baseline 55.6% (replayed 2026-10-17, identical to the stored report). It beat the
baseline and missed the bar. It was **shipped deliberately** with `--ship-anyway`: a
casual game where a misread costs a redo, and below its confidence floor it asks for
one. The model file records `"shipped_below_bar": true`. A game with stakes raises the
confidence floor to 0.85.

### gemma3 over gemma4: the numbers and the transcripts disagreed

Same prompt, same eval set, two runs each (commit `205084d`, 2026-09-21):

| | routing | arguments | reactions | first sentence p50 / p95 | VRAM |
|---|---|---|---|---|---|
| gemma3:12b | 90% | 90% | 84% | 698 / 899 ms | 8.9 GB |
| gemma4:12b | 88% | 100% | 100% | 805 / 1280 ms | 8.2 GB |

gemma4 scored higher on arguments and reactions. Reading the transcripts, it **claimed
actions it never took** ("I've set a timer" with no tool call) and leaked empty or
`<channel|>` replies. A voice assistant that says it did something it didn't is worse
than one that is less expressive, and gemma3 was faster to its first sentence. Stayed
on gemma3. The score alone would have picked the wrong model.

### The eval harness measured a prompt nobody used

Until 2026-10-12 the evals built the model's prompt themselves. "My Chrome keeps
crashing" passed in the eval and failed live. Now every case is a turn of the live
path (`evals/harness.py` `live_turn`): the app's own dispatch, then
`Conversation.respond()`, with the same system prompt, routing, per-message context,
fast routes, nudges and guards, stopping only where a tool would touch the machine.
`tests/test_eval_parity.py` plays a conversation through `respond()` and its last
message the way the evals do, and fails unless the model is sent byte-identical
messages.

Same day, same machine, old harness against the live turn (commit `b7f18f0`,
2026-10-13): reactions 41/49 → 38/49, conversation 34/35 → 32/35, drawing 36/40 →
32/40, routing first call 338/345 → 336/345. The scores went **down** because the old
ones were measuring the wrong thing. The live path then exposed a story-mode regex,
compiled case-insensitively, that took any word as a sentence's named subject; fixing
it moved reactions from 38/49 to 42/49 (commit `2a85bbd`, 2026-10-14).

### Tried and reverted

Telling the model "you know this already" about his home city stopped it inventing a
location tool, but also made it answer "who won the 2026 Ballon d'Or?" from memory:
0/2 against 3/3 without (commit `f2c0a4c`). Reverted.

### Before/after under drift: run them back to back

The model's tool-attempt rate drifts from session to session, so comparing today's run
against last week's number can show an improvement that isn't there. The memory
guard's before/after was run back to back, same machine and session: old code 36/68
against an early guard at 39/68 (commit `b70decf`).

### Thresholds set from measured distributions

- speaker verification at 0.35: owner's held-out takes 0.55-0.88, her TTS at most 0.27
- memory similarity at 0.60: related pairs 0.62-0.80, best unrelated pair 0.59
- the summon pose's crossed-finger gate: crossed at most 0.023, parallel at least
  0.237, on 90 frames per pose

### A failure the model kept making, moved into code

- lecture alerts: a false "deadline" in 2 of 3 runs → the alert kind is checked
  against the lecturer's own words → false alerts 0/3, the real problem set 3/3
- memory: an invented sister in 2 of 2 runs → the provenance guard → 0 of 52 probe
  answers invented anything
- injected instructions: see [security-model.md](security-model.md#taint-guard)

### Where the method has not been applied

- The pointing, scroll and pinch thresholds in `hud/src/tracking/gestures.ts` have no
  recorded calibration in the repo; some were adjusted after live observation (the
  dwell radius went from 0.02 to 0.035 because a still hand's tremor restarted it). They
  have not been measured against held-out captures the way zoom was.
- The whisper LoRA fine-tune (`scripts/whisper_lora.py`, adopt only if held-out WER
  improves) has not been run to completion.

## The suites

Run from `core/` with the venv's Python. All run against the real model (gemma3:12b
through Ollama), on the committed example configs, through the live turn, with empty
temporary memory and research stores.

| Suite | What it scores | Command |
|---|---|---|
| routing | the right tool, the right arguments, phrasings that must **not** call a tool, injection traps, multi-turn follow-ups | `evals/run_evals.py --only routing` |
| reactions, conversation | the feeling she shows fits; small talk stays talk; she stays in character | `evals/run_evals.py --only reactions` / `--only conversation` |
| drawing | the right kind of picture for an explanation | `evals/run_evals.py --only drawing` |
| briefing | the daily briefing's follow-ups and its live sources | `evals/run_evals.py --only briefing` |
| story | when he tells her something that happened, she reacts like a friend: no unasked advice, fitting emotion, short | `evals/story_evals.py` |
| recall | answers that live in an **earlier session**, and invention probes | `evals/recall_evals.py` |
| chess | spoken moves, game commands, her claims re-checked by a separate engine instance | `evals/chess_evals.py` |
| keiko | trigger and must-not-trigger phrases | `evals/keiko_evals.py` |
| draw topics | does drawing generalise to topics with no special handling | `evals/draw_topics.py` |
| unit | Python and HUD tests, including gestures replayed from real captures | `pytest tests`, `node hud/tests/run.mjs` |

`evals/run_evals.py` exits non-zero if routing falls below 90%. Every tool ships with
routing cases as it is built, including phrasings that must not call it.

## Results (2026-10-17)

One run of each suite, gemma3:12b, run in sequence from 00:13 to 00:36 local time,
with nothing else on the GPU except the injection probe, which ran alongside the story
and recall suites (neither is scored on timing). One run is one sample: earlier runs of the routing set
differed by a few cases from run to run.

| Suite | Result | Notes |
|---|---|---|
| routing: right tool run | **354/361** | details in [tool-protocol.md](tool-protocol.md#measured) |
| routing: model's first call right | 352/361 | before any refusal let it retry |
| routing: arguments | 105/105 | where the tool was right |
| routing: answered without the model | 157 deterministic + 9 dispatched | of 361 |
| reactions | 42/49 | the cue she shows fits the message |
| conversation | 32/35 | small talk stayed talk 30/30; character breaks 0/200 replies |
| drawing | 34/40 | the right kind of picture |
| briefing | 25/25 | includes live fetches of public data |
| story | 22/23 | reacted, not advised 22/22; the model wrote no unasked advice 0/22. Fails: a story where he was at fault got sympathy instead of a gentle call-out |
| recall (strict: any tool attempt fails) | **23/34** | invention probes 9/13 said they don't know; 0 of 13 probe answers asserted invented content (read by hand); retrieval 12.2 ms p50 |
| keiko triggers | 39/39 | |
| chess: spoken moves | 69/69 | |
| chess: commands, colour answers | 43/43, 20/20 | |
| chess: her claims, re-checked at depth 14 | **13/13 true** | over 4 games |
| draw topics (`--no-research`) | 17/17 | 1 of 19 specs invalid, recovered by the follow-up |
| first sentence ready for TTS, p50 / p95 | 885 / 1435 ms | across the routing, reaction and conversation turns |
| unit tests | 935 Python, 51 HUD | all pass |

Held-out gesture replays, CPU, same day:

| Model | Held-out result | Bar | Status |
|---|---|---|---|
| rock-paper-scissors (`rps_train.py --report-only`) | 83.3% (30/36), baseline 55.6% | 95% | on, below bar by decision |
| strike recogniser (`strike_train.py`, outputs redirected) | 0/3 strikes, 6/6 confusers silent | 75%, all silent | off |
| kamae (`kamae_train.py`, outputs redirected) | 0/1 kamae takes, 0/5 confusers fired | 90%, none | off |

**The recall regression.** The recall failures that are not invention probes are
mostly `lecture_research` calls: a lecture-notes tool added after the provenance guard
(commit `0dc7ac6`) is not in the guard's list of lookups refused on questions about
the past (`RECALL_LOOKUPS`, `irene/brain.py`), so a memory question can be handed to
an online "further reading" search. The overall rate is unchanged from the recorded
47/68 (69% against 68%), but the behaviour is wrong. **Still open** (checked
2026-10-21).

**Since this run.** Later full routing runs on the growing set: 384/392, 407/418,
472/480 (2026-10-18), **483/490** (2026-10-19) ([tool-protocol.md](tool-protocol.md#measured)).
Unit tests on 2026-10-21: 1788 Python passed (2 skipped); HUD, 16 verify files OK and 51
gesture checks passed.

**Injection.** 1 of 12 valid runs proposed the injected action; see
[security-model.md](security-model.md#taint-guard).
