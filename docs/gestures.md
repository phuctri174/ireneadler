# Gestures: the hand

All vision runs in the HUD (`hud/`), not in Python. MediaPipe Hand Landmarker runs from
WASM and model files vendored in `hud/public/mediapipe/`, and nothing is fetched from a
CDN. The video feed is **mirrored**, and the open-palm detection depends on it.

This document is the hand. The body (keiko, strike events, shiai) is in
[kendo.md](kendo.md), and the rock-paper-scissors classifier in [rps.md](rps.md).

**In the HUD, not Python**, is a project rule (CLAUDE.md); the reason was never written
down. What it means in practice: the camera frames never leave the webview, and the
gesture engine sits next to what it drives (the pointer, the face). Core receives
gesture events, not video.

## What the hand does

| Gesture | Effect | How it's decided |
|---|---|---|
| point (index out) | moves the **real** Windows cursor, relatively, like a mouse, across both monitors | finger extension ratios with hysteresis (`gestures.ts`) |
| dwell (hold still while pointing) | left click | the cursor stays within `DWELL_RADIUS` 0.035 for `DWELL_HOLD_MS` 650 ms |
| pinch (after pointing) | instant left click | thumb tip onto index tip, on **raw** landmarks, only within 1.5 s of pointing (`PINCH_AFTER_POINT_MS`) |
| two fingers | mouse wheel | thresholds, latched for 80 ms with hysteresis; One Euro on the scroll signal |
| five-finger spread / close | zooms the panel's centre card | a learned classifier ([below](#the-zoom-classifier)) |
| crossed index and middle | summon | a bone-distance gate, held 600 ms ([below](#the-summon-pose)) |

## The OS-level pointer

**Problem.** The long-term goal is full gesture control of Windows: his hand should work
everywhere a mouse does.

**Mechanism.** `hud/src-tauri/src/pointer.rs` moves the real cursor with Win32
`SendInput`, **relatively**, like a mouse, across both monitors. Dwell is a left click and
two fingers is the wheel. The mouse keeps working alongside it. Ctrl+Alt+H turns hand
control off. Tracking runs whenever Irene runs: her main window stays up, transparent
and click-through, while she sleeps.

**Ruled out: per-window control** (gestures handled only inside her own windows). The
project rule is "built at OS level, never per window": a pointer that works only in her
windows isn't control of Windows.

**Relative, not absolute**, is also a project rule ("moves the REAL cursor relatively,
like a mouse"); no comparison with an absolute mapping is recorded. A mouse works the
same way: the cursor moves by how far the hand moves, not to where it is.

**Cost.**

- Windows-only.
- It can't be tested by driving it. Real OS input reaches whatever app owns the cursor;
  a test once typed into another app. So **only the camera's hand drives it**: the dev
  synthetic hand is refused, and `core/tests/test_no_os_input.py` fails the suite if a
  test, eval or script uses `SendInput`, `keybd_event`, `pyautogui` or similar.

## Filtering: smooth the outputs, never the decisions

**Problem.** Landmarks jitter. A smoothed cursor feels steadier, but every smoothing
filter **delays** the signal it smooths.

**Mechanism.**

- **Clicks and gesture classification read raw landmarks.** A click decided on a
  filtered fingertip lands late.
- **One Euro is applied to continuous outputs only**: the cursor position
  (`useHandTracking.ts`, `DEFAULT_CURSOR_FILTER`), the scroll signal and the zoom factor
  (`gestures.ts`, `SCROLL_FILTER`, `ZOOM_FILTER`).

One Euro is a low-pass filter whose cutoff rises with speed. When the hand is slow it
smooths hard, which removes jitter. When the hand is fast it barely smooths, which
removes lag.

**Cost.** A raw-landmark click is noisier. The dwell radius went from 0.02 to 0.035 after
live observation, because a still hand's tremor kept restarting it
([evals.md](evals.md#where-the-method-has-not-been-applied)). The pointing, scroll and
pinch thresholds have not been calibrated against held-out captures the way zoom was.

**Deferred.** The pinch anchor is captured at latch, not at pinch onset, so a pinch click
lands about 2-4 frames of fingertip drift late. Deferred until there are real targets to
measure against.

## The zoom classifier

**Problem.** Zoom (spread all five fingers, or close them) has to be told apart from a
wave, a relaxed hand and a held fist, which are all open or closed hands.

**First version: a rule.** "All five fingers agree". It couldn't separate a deliberate
spread from a wave or a relaxed hand.

**Step 1: make the measurement trustworthy.** `core/scripts/zoom_replay.py` ports the
live gate to Python. It reproduced the engine's recorded decisions on 99.66% of frames
(commit `50a3a33`), so offline numbers describe the real gate. Measured that way, the
rule latched on 95% of waving frames and 34% of held-fist frames.

**Step 2: compare candidates on a held-out session.** One whole capture session was held
out (commit `50a3a33`, `zoom_near` 23-25-12, 26 takes):

| | overall | holds | motions | confusers | false zooms |
|---|---|---|---|---|---|
| live rule | 63.07% | 58.10% | 77.90% | 9.21% | 4/4 takes |
| retuned thresholds | 70.20% | 77.65% | 86.14% | 7.53% | 4/4 takes |
| gradient-boosted classifier | 97.06% | 100.00% | 98.22% | 91.63% | 1/4 takes |

The classifier won on all three choices of held-out session (mean 90.9% against 66.4%).
It was **not switched on**: the captures had no two-finger scroll pose, and wiring it in
broke the scroll, summon and peace tests.

**Step 3: a feature bug found by measuring.** The motion features read the *cursor*,
which moves only while a pointing pose is live, so during a wave it sat still: median
travel while waving was 0.000. The classifier had been learning which gesture the old
engine happened to be tracking. Reading the wrist instead gave waving 0.518 against
0.03-0.05 for still poses. Retrained with `scroll_pose` captured (commit `8333bd4`,
held out `zoom_near` 03-19-12):

| | overall | holds | motions | confusers | false zooms | zoom factor tracked |
|---|---|---|---|---|---|---|
| live rule | 56.51% | 50.00% | 65.63% | 30.48% | 4/5 takes | 16/20 |
| retuned | 44.16% | 50.00% | 46.85% | 34.08% | 4/5 takes | 10/20 |
| classifier | 95.15% | 95.56% | 94.54% | 96.92% | 0/5 takes | 20/20 |

**Step 4: the panel distance** ([lesson 4](lessons.md#4-framing-as-the-root-cause-four-times)).
He sits closer to the panel than in any training capture (palm 0.16-0.18 of the frame,
against a training median of 0.10), and a still open hand scored as a zoom. A
`zoom_panel` session was captured and split by take. Held out, with a stricter entry
gate: the live forest had 1/7 confuser takes fire and caught 7/8 zooms; the retrained
one 0/7 and 8/8 (commit `64a0050`). It shipped because it beat the incumbent there.

**The gate it runs now** ([hold-grace](lessons.md#3-hold-grace-the-same-bug-fixed-the-same-way-five-times)):
the pose must score at least 2.0 on every frame of a **700 ms** hold to latch, and
dropouts under 60 ms are forgiven. Replayed 2026-10-17 over the whole panel session
(training and held-out takes together, so not a held-out number): 0/9 confuser takes
fired, 18/18 zoom takes latched.

**Why a classifier here.** Zoom is used during ordinary desk work, where a false zoom
changes what he's looking at. The rule failed in a way tuning couldn't fix (retuned
thresholds were *worse* on one held-out session), and the captures gave enough data to
learn from.

**Cost.**

- The model fits one person's hands.
- It needs captures at every distance he uses.
- The test fixtures had to change. The hand-built synthetic poses put every landmark
  at z = 0 with straight fingers: geometry real tracking never produces, and the
  classifier reads 3D distances. They were replaced with replays of real takes.

The export is checked twice. `zoom_train.py` compares its own tree walk to
scikit-learn's predictions before writing, and `hud/tests/zoom.verify.mjs` checks the
TypeScript features against frames Python scored (390 frames, drift 6.1e-7, 2026-10-21).

## The summon pose

**Problem.** Crossed index and middle fingers must summon her, and two parallel fingers
(the scroll pose, a peace sign) must not.

**Considered: the tip-to-knuckle ratio.** The first gate used it. It overlapped the
crossed and parallel poses and never latched on a real crossed hand.

**Mechanism.** The shortest distance between the two fingertip bones, in palm spans,
calibrated on 90 frames per pose (2026-09-21, recorded in `gestures.ts`): crossed at
most 0.023, parallel at least 0.237. Latch is a quarter into that gap (0.08), release at
its midpoint (0.13). The pose must hold 600 ms, and dropouts under 120 ms are forgiven
(`SUMMON_HOLD_MS`, `SUMMON_GRACE_MS`).

## The model files that ship, and their limitation

Trained models are committed so a fresh clone works. They are small derived
classifiers: no frame of video and no landmark sequence is in them.

| File | Contains | Trained on | Used |
|---|---|---|---|
| `hud/src/tracking/zoomModel.ts` | a gradient-boosted forest: 60 trees, depth 3, over 24 hand-shape and motion features (41 KB) | the owner's `zoom_near`, `zoom_mid` and `zoom_panel` captures | **on** |
| `core/irene/rps_model.json` | per-feature mean and scale, softmax weights and bias, the read window and the confidence floor | the owner's two RPS sessions (72 throws) | **on, below its bar** ([rps.md](rps.md)) |
| `hud/src/tracking/kamaeModel.ts` | logistic-regression weights over 15 arm features, plus the watcher's gate | the owner's `keiko_near` capture | **off** ([kendo.md](kendo.md#keiko-the-strike-recogniser-and-the-kamae-trigger)) |
| `hud/src/tracking/strikeModel.ts` | `null`: no strike model has passed | - | **off** |

**These models fit one person.** All training data is one user, one camera, one room.
Someone else will get lower accuracy: hand proportions, how a person makes a fist,
camera height and distance all shift the features. How much lower hasn't been measured.
The capture profiles (`config/capture_profiles.json`, hotkeys in `hud/HOTKEYS.md`) and
the trainers are in the repo, so a new user can record their own sessions and retrain.
Each trainer ships a model only if it passes its held-out bar.

The raw captures (`core/calibration/`) and the golden frames the parity tests replay are
personal and are never published (the publish scan blocks the folder). On a fresh clone
those parity checks skip.
