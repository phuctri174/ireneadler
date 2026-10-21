# Lessons: the bugs that taught something

Each entry is a real failure: what was seen, what the cause turned out to be, what
changed, and the rule taken from it. Every claim cites the commit or document that
recorded it. Where the record doesn't settle a detail, that's stated.

Most of these share one shape: **the first explanation was wrong, and a measurement of the
thing that actually runs found the real one.** That is also the method in
[evals.md](evals.md#the-rule).

| # | Lesson | Area |
|---|---|---|
| 1 | [If a model can't fit its own training data, the features are missing the information](#1-the-strike-detector-that-could-not-fit-its-own-training-data) | kendo |
| 2 | [Some signals are unusable, not mistuned](#2-tsuki-and-depth-from-one-camera) | kendo |
| 3 | [A state must persist, not flicker: hold-grace](#3-hold-grace-the-same-bug-fixed-the-same-way-five-times) | gestures, kendo |
| 4 | [Check the framing before the model](#4-framing-as-the-root-cause-four-times) | vision |
| 5 | [A test runner has to be shown failing](#5-the-hud-test-runner-that-could-not-report-a-failure) | testing |
| 6 | [Before blaming the model, check whether it was called](#6-the-model-misroute-that-was-a-regex) | routing |
| 7 | [A memory that keeps the model's answers feeds them back as facts](#7-memory-echoing-her-own-invented-answers-back-as-fact) | memory |
| 8 | [A filter on format can't protect content](#8-a-filter-on-file-type-cant-protect-a-recording) | publishing |
| 9 | [A setting the engine accepts is not a setting that takes effect](#9-the-chess-strength-that-was-applied-and-still-didnt-hold) | chess |
| - | [Earlier lessons](#earlier-lessons-recorded-in-evalsmd) | evals |

---

## 1. The strike detector that could not fit its own training data

**Seen.** Study mode and shiai needed one binary signal: did he swing at her. The first
version was learned: a five-bound gate (the arc's apex, its drop, peak speed, end
position, wrist visibility), fitted on his "hits" desk captures and shipped only past a
held-out bar set in advance.

**Cause.** It never reached the held-out test. On the second desk session, its own
training data, 9 of 135 confuser descents still cleared the gate, 4 of 17 confuser takes
fired, and strike takes fired up to 5 times for 3 strikes (commit `be1211f`). The return
stroke to chudan was nearly as fast as the strike, and none of the five features said
which **direction** the wrist was moving. A model that can't separate its training data
can't be saved by more data or a better bar: the information isn't in the features.

**Changed** (commit `7f60b60`). A rule replaced the model. It looks for one wrist's
**signed** downward speed (in shoulder widths per second, measured from the shoulder
midpoint) going over a threshold, followed by a sharp stop. Because the speed is signed,
the raise never counts and the slower return stays under the threshold. Because it
needs a stop, an arm sinking to his lap doesn't count. The threshold comes from three
calibration swings, and he can nudge one number by feel. The trainer, its Python twin
and the model file were deleted.

**Why a rule here and learned models elsewhere.** Zoom, scroll and rock-paper-scissors
pick his intent out of ordinary desk use. There, a false positive moves his cursor or
throws for him, so they stay learned and held to their bars. Study mode and shiai are
modes he enters *to hit her*. A false positive there is a funny noise, and the data is
scarce (two desk sessions, 48 strikes). Constrained context, cheap mistakes and little
data is the case where a rule he can tune beats learning.

**Rule.** When a model fails on its training set, look at what the features can't
express before reaching for more data. Then ask whether the problem needs a model at
all.

Details: [kendo.md](kendo.md#strike-events).

## 2. Tsuki and depth from one camera

**Seen.** Shiai scored ippons with him sitting still (commit `83d51c6`).

**Cause.** The tsuki (thrust) trigger read **depth**: the wrists' speed toward the
camera. MediaPipe's z from a single camera is an estimate. With him motionless in kamae,
the depth speed ran 14-27 shoulder widths a second, and the trigger fired **23 times in
30 s**. His calibration "tsuki" shots had no forward travel at all, so the threshold
(4.6) had been set from pure noise.

**Changed.** Tsuki is off for good. The commit and [kendo.md](kendo.md#tsuki-off-for-good)
both say not to tune its threshold, because no number fixes the signal. The only path
back is a **2D signature**: the forearms foreshortening and the elbows extending toward
the camera, measured in the image plane, and it would have to pass the strike event's
own guards. The tsuki code was later removed entirely (commit `e463dd1`); the
documentation of why stays.

**Rule.** Before tuning a threshold, record the signal with the subject **still**. If
the noise floor overlaps the real movement, the signal is unusable, not mistuned. That
measurement (`scripts/strike_probe.py`: detectors armed, nothing acted on) took 30
seconds and settled the question.

## 3. Hold-grace: the same bug, fixed the same way five times

**Seen.** A gesture fires because one frame, or a short burst of frames, crosses a line
while he is doing nothing. Each case below was a separate bug, found separately:

| Where | What flickered | The fix in code |
|---|---|---|
| zoom (`gestures.ts`) | a still open hand at panel distance scored as a zoom | score at least 2.0 on every frame of a **700 ms** hold; dropouts under 60 ms forgiven (commit `6a6ca6f`) |
| kamae watcher (`kamaeModel.ts`) | the frame-level kamae detector fired on everyday arm movement | a steady stance **held 1500 ms**, release with hysteresis (commit `6698b21`); the trigger was later retired anyway (lesson in [evals.md](evals.md#kamae-a-held-out-pass-that-failed-live)) |
| shiai footwork (`strikeEvent.ts`, `config/strike_event.json`) | in kamae his hands cover his shoulders and their width jitters ~7% within a second, against an 8% step | the new width must hold **200 ms**, dips under 60 ms forgiven, against a **median** baseline (commit `83d51c6`) |
| shiai block (`strikeKind.ts`) | a men passes through "both wrists up" on its way up | both wrists up **held 250 ms**, dips under 120 ms forgiven |
| shiai men zanshin (`shiai.py` `MEN`) | jitter in bogu made strike-like spikes | the wrists must **stay** above a line for 400 ms after the cut, dips under 120 ms forgiven (commit `874deb6`) |

The summon pose uses the same shape (held 600 ms, dropouts under 120 ms forgiven,
`gestures.ts`), though no bug report is attached to it.

Scroll, often counted with these, is related but not the same: its `Latch` in
`gestures.ts` requires the pose for 80 ms with separate enter and exit thresholds
(hysteresis), but a dip during the hold resets it. There is no grace.

**The pattern** (written down as a project principle in commit `83d51c6`):

- **hold**: the state must stay past its line for a set time before it counts
- **grace**: a dip back under it shorter than a set time is forgiven, so one lost frame
  is not a lost pose; a longer dip starts the hold over
- **a steady baseline**: "where he was" is the median of a stretch, never one frame,
  so a flicker can't become the place he moved from

**When hold-grace is not enough.** His shoulders read 15% narrower for a whole second
with his hands over them. No reasonable hold outlasts that. The footwork trigger now
needs a second, independent signal to agree: his face must scale or move the same way
as his shoulders, and his hands never cover his face.

**Rule.** A new trigger built on a pose landmark starts with hold-grace. A frame is not
an event.

## 4. Framing as the root cause, four times

Four times, a vision feature that looked like a model problem was a camera problem: the
body part wasn't in the picture, or was at a size training never saw.

| When | Looked like | Was | Fix | Source |
|---|---|---|---|---|
| 2026-09-27 | nothing to train strikes on | the hand tracker can't see a men strike: the hand leaves the frame, and with no body model there was no reference for "where his arms are" | pose landmarker vendored; keiko takes are gated on the **body** being in view, not the hand | commit `e2cd7c1` |
| 2026-10-04 | the zoom classifier firing on a still open hand | he sits closer to the panel than in any training capture: palm 0.16-0.18 of the frame against a training median of 0.10 | a `zoom_panel` capture at the real distance, retrained; held out, 0/7 false zooms against 1/7 | commits `6a6ca6f`, `64a0050` |
| 2026-10-17 | strike recognition failing on keiko_near | range: the wrist outside the image on 48% of fast men frames (60-76% for kote and do) | diagnosis by cause (below) | [kendo.md](kendo.md#the-hits-capture-what-the-camera-sees-at-the-desk) |
| 2026-10-18 | the desk strike detector failing | range again: a wrist below the bottom edge in **33.8%** of strike frames. Blur (visibility 0.666 fast vs 0.669 slow), occlusion (shoulders 0.992) and light (0.97 with hands up under the same lamp) were each measured and ruled out | a **framing check** before any capture: his lower wrist at most 0.85 of frame height in kamae for a second; camera tilted down → 10.8% | commits `3691172`, `be1211f` |

**The method that found it.** `scripts/hits_diagnose.py` reports a session against four
causes, each with its own measure:

- range: the wrist is outside the image
- blur: in-frame visibility on fast frames against slow ones
- occlusion: shoulder visibility
- light: visibility of a raised hand

Pose models keep reporting a position for a wrist outside the image, a guess at about
0.60 visibility. So the failure doesn't show up as missing data; it shows up as wrong
data.

**Rule.** Before a vision feature's model is blamed, measure whether the thing it reads
is in the frame, at the size it was trained on. Make the capture refuse to start until
it is.

## 5. The HUD test runner that could not report a failure

**Seen.** A new framing test failed. The run reported success (commit `38d0baf`).

**Cause.** `hud/tests/run.mjs` runs each `*.verify.mjs`. Several of them set
`process.exitCode = 1` on failure and keep going. `gestures.verify.mjs` ran last and
ended with `process.exit(0)` when its own checks passed. That threw away the failure
code set by `strikeEvent`, `framing` and two other verify files. Their FAIL lines were
printed, and `node tests/run.mjs` still exited 0.

**Changed.** It keeps an earlier failure. With the masking removed, nothing that had
been hidden was failing. That was luck, not design.

**Rule.** A test runner is code too, and untested until it has been seen to fail.
Break a test on purpose and check the **exit code**, not the printed output, because
the exit code is what everything downstream reads.

## 6. The "model misroute" that was a regex

**Seen.** In the routing evals, "I studied the Sicilian all weekend" was sent to
research. The write-ups put it down to gemma over-eagerly reaching for a tool. Then, in
his first live test of study mode, "Learn Sicilian" also went to research.

**Cause** (commit `a909ea3`). The model never saw those sentences. The fast path
(`fast.py`) answers some messages before the model, and its chess-opening rule tested
`text + "?"` against its question pattern. Appending a question mark made every sentence
that named an opening count as a question, so it was researched in code.

**Changed.** The opening rule fires only on a real question, or on "explain / tell me
about". More structurally, mode entry (shiai, study, chess and the rest) is now matched
in code **before** the fast path and the model, so neither can send "learn the
Sicilian" anywhere else. Measured: his seven saved turns from that test, replayed
through the live mic pipeline, 7/7 to the right mode, none researched. Of four
mode-entry eval cases that had failed, all four were the opening rule, not the model.

**Rule.** "The model did X" is a hypothesis. First establish *who answered the turn*:
the eval harness records `who` (a mode, the fast path, a quick reply, the model), and
the live turn is the only thing worth measuring
([evals.md](evals.md#the-eval-harness-measured-a-prompt-nobody-used)).

## 7. Memory echoing her own invented answers back as fact

**Seen** (commit `92c82b0`). He asked her to name a song from its lyrics, several times
across sessions. She answered "Oh, you remembered that one!", then "Oh, Mister Tri." five
turns running.

**Cause.** Long-term memory stored every exchange, his words **and her reply**. Asked
the same lyrics again, recall found her earlier answers to the same question and put
them in front of the model as context. The model treated its own past guesses as
something it had been told. Separately, `read_page_text` read his own Google search
for one song, then gave that stale page's answer for a different song.

**Changed.**

- **A question about the world skips memory** (naming a song from lyrics, a film, book
  or person from a description; `recall.world_knowledge`). His own things ("the song I
  sent you") still go to memory.
- **Every memory item records its source** at write time: `him` (a fact he stated),
  `her` (a turn or research note), `lecture`. Only `him` may answer a question about the
  world. Her answers to such questions are no longer stored at all.
- The 23 stored song exchanges were deleted from his store.
- **Teaching** became the way in. He states the fact ("that song is Blue by yung kai,
  the one that goes..."), it is kept in his words, tagged as his, and found later by
  matching his lyrics against his lyrics ([memory-and-provenance.md](memory-and-provenance.md#teaching-and-recall-his-facts-answer-the-world)).

**Rule.** A store that keeps the model's output and feeds it back as context is a
feedback loop: one wrong answer becomes a remembered fact. Record **who said it** at
write time. You can't recover it later from the text.

## 8. A filter on file type can't protect a recording

**Seen** (2026-10-21, while checking that no voice data was published). The publish
scan (`core/scripts/publish.py`) blocked voiceprints by file type (`.npz`, `.npy`). His
raw recordings are `.wav`, and so are her pre-rendered voice lines, which are meant to
be published. A blocklist on `.wav` would block her; leaving `.wav` open meant nothing
would stop a recording of him that ended up in a tracked folder.

Nothing had leaked: his recordings (`core/voice_data/`) and voiceprints were never in
any commit, local or public. Her own voice is cloned at startup from a clip of Kokoro's
stock `af_bella` voice, byte-identical to that render, and never saved.

**Changed** (commit `6c1ce61`). A **path** rule: anything under a `voice_data/` or
`calibration/` folder, at any depth, stops the publish. It matches whole folder names,
so the `voice_data.py` module still publishes. `.pt` and `.safetensors` were added to
the blocked types, the formats a saved voice clone or any weights would use.

**Rule.** Format says what a file is, not whose it is. Protect content by where it
comes from (the folders the app writes personal data to), and keep the type rules for
formats that are never legitimate in the repo.

## 9. The chess strength that was applied and still didn't hold

**Seen.** Her strength was set in `config/chess.yaml` (`UCI_Elo` 1450), and it still had
to be measured and lowered (commit `a87b851`).

**What it was not.** The obvious suspect was the engine ignoring the setting. It
wasn't.
Traced with python-chess's UCI log (commit `a87b851`):

- `UCI_LimitStrength true` and `UCI_Elo` were sent at engine start, and again before
  every move of hers, on the same process.
- The engine answered `readyok`.

**Cause.** The hash table. After every move, a full-strength look at the position
(which picks her commentary) ran on the same engine, immediately before her own
weakened search of that position. Her search read the deep result out of the shared
hash table. The limiter was configured, accepted and active, and its effect was being
undone by state another search had left behind.

**Changed.**

- Her search clears the hash first and is capped at depth 6 or 300 ms.
- The Elo went from 1450 to 1350; Stockfish's floor is 1320.
- The **effect** is now logged, not just the setting: the engine's `readyok` and config
  at start, and every engine move of hers next to the engine's own top line. A
  different move means the limiter chose it. Live, 2 of her first 4 engine moves
  differed.

Measured with `scripts/chess_strength.py`. Each setting played 10 games, and every
engine move was scored by a separate depth-12 Stockfish:

| | average centipawn loss | blunders per game | median loss |
|---|---|---|---|
| before (1450, look's hash kept) | 42.3 | 0.5 | 7 |
| after (1350, empty hash, depth 6) | 51.5 | 1.0 | 16 |

**Rule.** Configuration is a claim about behaviour, and only the behaviour can confirm
it. Seeing a setting in the config, or even the engine acknowledging it, doesn't show
it takes effect. Log what the configured thing actually did (here, its move against
its own unrestricted choice), and measure the outcome you configured for.

---

## Earlier lessons, recorded in evals.md

- [**A held-out pass that failed live**](evals.md#kamae-a-held-out-pass-that-failed-live).
  Kamae scored 97% held out, then fired on everyday arm movement. The held-out set
  contained no desk confusers, and a held-out split only measures the conditions it
  contains.
- [**The eval harness measured a prompt nobody used**](evals.md#the-eval-harness-measured-a-prompt-nobody-used).
  The evals built their own prompt. Moving every case onto the live turn made the
  scores go **down**, because the old ones were measuring the wrong thing.
- [**The score would have picked the wrong model**](evals.md#gemma3-over-gemma4-the-numbers-and-the-transcripts-disagreed).
  gemma4 scored higher and claimed actions it never took. Read the transcripts, not
  just the scores.
- [**A feature that watched the wrong thing**](gestures.md#the-zoom-classifier).
  The zoom motion features read the cursor, which stands still during a wave. The
  classifier was learning which gesture the old engine happened to be tracking.
