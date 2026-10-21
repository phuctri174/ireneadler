# Gestures

All vision runs in the HUD (`hud/`), not in Python: MediaPipe Hand Landmarker (and,
for keiko only, Pose Landmarker Lite) from WASM and model files vendored in
`hud/public/mediapipe/`. Nothing is fetched from a CDN. The video feed is mirrored;
the open-palm detection depends on it.

## What the hand does

| Gesture | Effect | How it is decided |
|---|---|---|
| point (index out) | moves the real Windows cursor, relatively, like a mouse, across both monitors | thresholds on finger extension ratios, with hysteresis (`gestures.ts`) |
| dwell (hold still while pointing) | left click | the cursor stays within `DWELL_RADIUS` 0.035 for `DWELL_HOLD_MS` 650 ms |
| pinch (after pointing) | instant left click | thumb tip onto index tip on **raw** landmarks, only within 1.5 s of pointing |
| two fingers | mouse wheel | thresholds, then One Euro on the scroll signal |
| five-finger spread / close | zooms the panel's centre card | a learned classifier, see below |
| crossed index and middle | summon | a bone-distance gate calibrated on captures, see below |

The pointer is built at OS level (`hud/src-tauri/src/pointer.rs`, Win32 `SendInput`),
never per window, so it works in Chrome, Explorer, anywhere. The mouse keeps
working alongside it. Ctrl+Alt+H turns hand control off. Only the camera's hand
drives it: the dev synthetic hand is refused, and no test reaches it
(`core/tests/test_no_os_input.py` fails the suite if a test, eval or script uses
`SendInput`, `keybd_event`, `pyautogui` and similar).

Tracking runs whenever Irene runs; her main window stays up, transparent and
click-through, while she sleeps.

### Filtering rules

- **Clicks and gesture classification use raw landmarks.** A smoothing filter
  delays the signal it smooths; a click decided on a filtered fingertip lands late.
- **One Euro is applied to continuous outputs only**: the cursor position
  (`useHandTracking.ts`, `DEFAULT_CURSOR_FILTER`), the scroll signal and the zoom
  factor (`gestures.ts`, `SCROLL_FILTER`, `ZOOM_FILTER`).

## The zoom classifier: a measured replacement for a hand-tuned rule

The first zoom gate was a rule: "all five fingers agree" (all extended or all
curled). It could not separate a deliberate spread from a wave or a relaxed hand,
because all three are open hands.

**Step 1, make the measurement trustworthy.** `core/scripts/zoom_replay.py` ports
the live gate to Python. It reproduced the engine's own recorded decisions on
99.66% of frames (commit `50a3a33`, 2026-09-27), so offline numbers describe the
real gate. Measured that way, the live rule latched on 95% of waving frames and
34% of held-fist frames.

**Step 2, compare candidates on a held-out session.** One whole capture session
was held out of training. From commit `50a3a33` (held out: `zoom_near` 23-25-12,
26 takes):

| | overall | holds | motions | confusers | false zooms |
|---|---|---|---|---|---|
| live rule | 63.07% | 58.10% | 77.90% | 9.21% | 4/4 takes |
| retuned thresholds | 70.20% | 77.65% | 86.14% | 7.53% | 4/4 takes |
| gradient-boosted classifier | 97.06% | 100.00% | 98.22% | 91.63% | 1/4 takes |

The classifier won on all three choices of held-out session (mean 90.9% against
66.4%). It was **not switched on** at that point: the captures had never included a
two-finger scroll pose, and wiring it in broke the scroll, summon and peace tests.

**Step 3, a feature bug found by measuring.** The motion features read the
*cursor*, which only moves while a pointing pose is live, so during a wave it sat
still: median travel while waving was 0.000. The classifier had been learning which
gesture the old engine happened to be tracking. Reading the wrist instead gave
waving 0.518 against 0.03-0.05 for still poses. Retrained, with `scroll_pose`
captured (commit `8333bd4`, held out `zoom_near` 03-19-12):

| | overall | holds | motions | confusers | false zooms | zoom factor tracked |
|---|---|---|---|---|---|---|
| live rule | 56.51% | 50.00% | 65.63% | 30.48% | 4/5 takes | 16/20 |
| retuned | 44.16% | 50.00% | 46.85% | 34.08% | 4/5 takes | 10/20 |
| classifier | 95.15% | 95.56% | 94.54% | 96.92% | 0/5 takes | 20/20 |

Holding out the other scroll-bearing session instead: 94.6%, confusers 100%.

**Step 4, the panel distance.** He sits closer to the panel than any training
capture (palm 0.16-0.18 of the frame against a training median of 0.10), and a still
open hand scored as a zoom. A `zoom_panel` session was captured and split by take.
Held out, with the stricter entry gate: the live forest had 1/7 confuser takes
false (4.4% of frames) and 7/8 zooms; the retrained one 0/7 (0.0%) and 8/8
(commit `64a0050`, 2026-10-04). It shipped because it beat the incumbent there.

The strict gate is what `gestures.ts` runs now: the pose must score at least 2.0 on
every frame of a 700 ms hold to latch. Replayed today (2026-10-17,
`scripts/zoom_eval.py --sessions zoom_panel --model HEAD`) over the **whole**
panel session (training and held-out takes together, so not a held-out number):
0/9 confuser takes false, 18/18 zoom takes latched.

**The test fixtures had to change too.** The hand-built synthetic poses in
`gestures.verify.mjs` put every landmark at z = 0 with straight fingers; the
classifier reads 3D distances, so those poses are geometry real tracking never
produces. They were replaced with replays of real captured takes.

The export is checked twice: `zoom_train.py` compares its own tree walk to
scikit-learn's predictions before writing, and `hud/tests/zoom.verify.mjs` checks the
TypeScript features against frames Python scored.

## The summon pose

Crossed index and middle fingers. The old tip/knuckle ratio overlapped the crossed
and parallel poses and never latched on a real crossed hand. The gate now measures
the shortest distance between the two tip bones in palm spans, calibrated on 90
frames per pose (2026-09-21, recorded in `gestures.ts`): crossed at most 0.023,
parallel at least 0.237. Latch is set a quarter into that gap (0.08), release at its
midpoint (0.13).

## The model files that ship, and their limitation

Three trained models are committed so a fresh clone works. They are small,
derived classifiers, not recordings: no frame of video and no landmark sequence is
in them.

| File | Contains | Trained on | Used |
|---|---|---|---|
| `hud/src/tracking/zoomModel.ts` | a gradient-boosted forest: 60 trees, depth 3, over 24 hand-shape and motion features (41 KB) | the owner's `zoom_near`, `zoom_mid` and `zoom_panel` captures | **on** |
| `core/irene/rps_model.json` | per-feature mean and scale, softmax weights and bias for rock / paper / scissors, the read window and the confidence floor | the owner's two RPS sessions (72 throws) | **on**, below its bar (see [rock-paper-scissors](#rock-paper-scissors)) |
| `hud/src/tracking/kamaeModel.ts` | logistic-regression weights over 15 arm-from-shoulder features, plus the watcher's gate | the owner's `keiko_near` capture | **off** (see [keiko](#keiko-kamae-and-strikes)) |
| `hud/src/tracking/strikeModel.ts` | `null`: no strike model has passed | - | **off** |

**These models are fit to one person's hands and body.** All training data is one
user, one camera, one room. Someone else cloning the repo will get lower accuracy:
hand proportions, how a person makes a fist or a spread, camera height and distance
all shift the features. How much lower has not been measured. The capture profiles
(`config/capture_profiles.json`, hotkeys in `hud/HOTKEYS.md`) and the trainers are
in the repo so a new user can record their own sessions and retrain; each trainer
ships a model only if it passes its held-out bar.

The raw captures themselves (`core/calibration/`) and the golden frames the parity
tests replay are personal and not published. On a fresh clone those parity checks
are skipped.

## Rock-paper-scissors

His throw is read from a fixed window of camera frames after the "shoot" instant
(the window is chosen by the trainer on training sessions only). Her throw is
drawn and its SHA-256 commitment logged **before** his hand is read; the panel shows
the hash during the count, and both throws are revealed together.

The bar to ship (`core/scripts/rps_train.py`): on a whole session the model never
saw, at least 95% of throws right, every class at least 90%, and no worse than a
finger-counting baseline. Replayed 2026-10-17 (`rps_train.py --report-only`, held
out session 2026-10-16T06-28-48, 36 throws), identical to the report stored in
`rps_model.json`:

| | accuracy | rock | paper | scissors |
|---|---|---|---|---|
| classifier | **83.3%** (30/36, 3 asked for a redo) | 83% | 75% | 92% |
| finger-count baseline | 55.6% | 75% | 92% | 0% |

**It missed the 95% bar and shipped anyway, as a deliberate call** (`--ship-anyway`):
a casual game, where a misread costs a redo, not a wrong action. The shipped model
was then refit on both sessions. Below its confidence floor it asks for a redo
rather than guess. A game with stakes on it (`core/irene/rps_stakes.py`) raises that
floor to 0.85 (`config/rps.yaml`), since a wrong call on a bet costs more than a redo.

## Keiko: kamae and strikes

Keiko (kendo practice with her) uses the pose landmarker, which runs only while keiko
or a keiko capture is on.

- **Kamae as a trigger: retired.** Live, the frame-level kamae detector fired on
  everyday arm movements. Keiko now starts by voice only, and `config/hud.json` has
  `kamae.enabled: false`. The committed `kamaeModel.ts` is a DRAFT fit with nothing
  held out (its own `_about` field says so). Replayed 2026-10-17 on the one keiko
  capture on disk, with its built-in split: 0/1 held-out kamae takes caught, 0/5
  confusers fired, below the bar.
- **Strike recogniser (men, kote, gyaku-dou): built, switched off.** It ships only
  if, held out, every confuser stays silent and at least 75% of strikes fire the
  right strike. Recorded at build time (commit `575d0cd`, 2026-10-12): the best
  held-out result on the one session was **2 of 3 strikes** with every confuser
  silent, under the bar. Replayed 2026-10-17 with the trainer as committed: 0 of 3
  strikes, 6/6 confusers silent. `strikeModel.ts` is `null`, and she says so when
  keiko starts. More captures are needed (`keiko_strikes`, recorded twice on
  different days). The TypeScript twin matches the Python trainer on golden windows
  (`hud/tests/strike.verify.mjs`).

## Strike events: a tuned threshold, not a learned classifier

That he struck at her, nothing more - never which strike (that is the keiko recogniser
above, untouched). Study mode counts hits with it; shiai reads his strikes with it.
`hud/src/tracking/strikeEvent.ts` runs it; `core/irene/strike_tuning.py` owns its number;
`config/strike_event.json` holds the knobs.

**A strike** is one wrist's *signed* downward speed - shoulder-widths per second,
measured from the midpoint of his shoulders, so leaning or stepping doesn't move it -
peaking over the threshold, followed by a sharp stop: the speed falls to 35% of its
peak within 160 ms. Signed, so the raise and anything moving up never count, and the
slower return to chudan stays under the threshold; the stop, so an arm sinking to his
lap doesn't count either. A swing is not an arm at all if the pose model was unsure of
the wrist at its peak (visibility under 0.4) or the peak is over 60: in the first live
run the camera reported peaks of 541, 154 and 104 from jumping landmarks, while across
248 swings in his two desk sessions no real one passed 35 and every one over 60 had
visibility 0.24-0.33. After a strike both wrists rest for 400 ms, so a two-handed
swing is one strike. That is the whole detector: no model file, no training, no
held-out bar. `hud/tests/strikeEvent.verify.mjs` checks it on made-up bodies (a strike
fires once, three strikes three times, a raise, a slow return, a sinking arm, a
swing with a hole in it, a barely-seen wrist and a landmark jump never).

**Why a threshold here, when the gesture controls are learned.** Zoom, scroll, kamae
and rock-paper-scissors must pick his intent out of ordinary desktop activity,
where a false positive moves his cursor or throws for him; those stay trained
classifiers with their held-out bars, and their results above are unchanged. Study mode
and shiai are different: he is in a mode, holding a shinai, specifically to hit her. A
false positive is a funny noise, not a failure. The context is constrained, false
positives are cheap and the data is scarce (two desk sessions, 48 strikes) - the case
where a rule he can tune beats learning.

**What it replaced.** The learned approach - a five-bound gate (the arc's apex, drop,
peak speed, end position, visibility) fitted on his hits captures, shipped only past a
held-out bar - failed to fit even its own training data with that feature set. On the
second desk session alone, 9 of 135 training confuser descents still cleared the gate,
4 of 17 confuser takes fired, and strike takes fired up to 5 times for 3 strikes: the
return strokes were nearly as fast as the strikes and the features had no direction.
The trainer, its Python twin of the detector and the model file are gone; the captures
stay on disk as a record, and nothing trains on them.

**Calibration: three swings, about 20 seconds.** "Irene, calibrate my strikes" - or the
first time study mode or shiai starts without one. She says "hit me three times"; the
detector runs for 12 s at a floor of 4 shoulder-widths/s, every swing reporting its
peak; his three fastest are kept, and the threshold is 0.6 x their median, saved in
`core/data/strike_calibration.json`. Fewer than three, or uneven ones (the slowest under
half the fastest), are not saved - she says the numbers and asks again: a threshold
from one soft swing fires on everything. No takes, no confusers, no capture. To tune by
feel, nudge `"fraction"` in `config/strike_event.json` (lower = more sensitive); it is
read every time a mode switches the detector on, so starting study mode or shiai again
picks it up. In -Dev each strike's peak shows on her face against the threshold
(`12.4/8.0`, top right, 2.5 s), so he can see the number he is producing.

**Replayed offline on the second desk session** (how the rule behaves, not a
validation: one session, no held-out number). A calibration on strike take 1 (swings
26.1, 22.0, 17.9) sets 13.2; at that, the eight strike takes (24 strikes) fire 21 times
(per take 2, 4, 2, 3, 0, 4, 3, 3 - the 0 is the take with the 813 ms stall), and
desk confusers fire too: typing 11, a stretch 4, a punch at the screen 0-3, reaching
to the screen 1-3, a men started and stopped 1-2, the mouse, the phone and the shinai
laid down once each (without the two guards above: the shinai 5, the mouse 4, a
stretch 6). In study mode or shiai he isn't typing;
if the others bother him, the fraction goes up. A calibration on take 6 (19.8, 9.2,
7.0) would have set 5.5 and fired on nearly everything - which is why uneven
calibrations are refused.

**Status: on**, once he has calibrated. Not yet measured live: the number is his to
tune by feel.

### The hits capture: what the camera sees at the desk

The `hits` capture (Ctrl+Alt+Shift+0, 28 takes, about 3.5 minutes) is a measurement now,
not training data. Seated at the desk where he hits her, one style - chisai men, three
per 4-second take, eight takes - then 20 takes of fast desk movements that are not
strikes: kamae held, a men started and stopped, a punch at the screen, reaching to the
screen, leaning in, the mouse, typing, a drink, talking with his hands, a stretch,
scratching his head, a wave, pointing, the phone, the shinai laid down and picked up.

**The framing check.** Before the first step he takes kamae and the run waits,
recording nothing, until the lower of his wrists has been at most 0.85 of the frame
height (0 top, 1 the bottom edge) for a second: the HUD shows the live number and
TILT DOWN / IN FRAME (`hud/src/tracking/framing.ts`, the profile's `"framing"`). 0.85
comes from the first desk session: a strike's lowest point sat 0.09 below his kamae
(kamae median 0.98, strikes up to 1.07), so 0.85 in kamae keeps a strike's lowest
point near 0.94, inside the image. The pass or a two-minute give-up goes to core.log
(`hud capture hits framing ...`).

Every body frame of a capture records how it went: `dtMs` (ms since the last processed
frame), `skipped` (camera frames presented that the loop never saw, from
`requestVideoFrameCallback`'s `presentedFrames`), `handMs` and `poseMs` (each model's
cost), and the camera's `exposureMode` / `exposureTime` (100 µs units) with its size and
frame rate, read once per take. `core/scripts/hits_diagnose.py` turns a session into
the strike-vs-rest table: frames with no body, wrists out of frame (range), in-frame
wrist visibility on fast vs slow frames (blur), shoulder visibility (occlusion), frame
drops, inference cost and exposure (lighting).

**What the first diagnosis found (2026-10-17).** The two hits runs recorded that day
ran on the *hand* model: the capture armed pose only for profiles named `keiko*`, so
the HUD perf log shows `poseHz: 0`, and each run saved only its 5-second standing take
(the strike step waited for a hand that the tsuba hid). Both are in
`core/calibration/archive/`. The capture now arms pose from the profile's `"tracks":
"pose"`, and disarms it when the run ends, done or failed (it used to keep running at
30 Hz after a failed run). On the only pose capture there was (keiko_near, 1 m,
standing, a different style), the body was missing on 27/2518 frames; the biggest loss
was range (the wrist outside the image on 48% of fast men frames, 60-76% for kote/do);
blur second (in-frame wrist visibility 0.54 fast vs 0.84 slow on men); frames came
every 30.1 ms (median), 2-4% of gaps over 50 ms; the body model cost 8.7 ms (median).
The webcam (Logitech Brio 101, 30 fps max) supports manual exposure, range -11 to -2
(1/2048 s to 1/4 s); on auto it was choosing -5, about 1/32 s.

**The first desk session (2026-10-18, `hits-2026-10-17T23-21-11`, auto exposure, a
lamp on him).** All 28 takes, 3405 frames; a body in 3346 (98.3%), in every one of the
959 strike frames (the 59 misses were talking, the shinai on the desk, a drink, the
stretch). Frames every 33.3 ms (median; 95th percentile 46-50 ms), 1 skipped in the
strike takes, the body model 6.0 ms. Measured against the four causes:

| cause | measure | strikes (men) | at rest (seated / kamae) |
|---|---|---|---|
| range | wrist outside the image | **33.8%**, all of it off the bottom edge, down to 1.07 of frame height | 0.0% / 2.5% |
| blur | in-frame wrist visibility, fast vs slow frames | 0.666 vs 0.669 - no drop | 0.636 vs 0.706 / 0.599 vs 0.629 |
| occlusion | shoulder visibility, worst tenth | 0.992 | 0.992 / 0.992 |
| light | wrist visibility under the same lamp, hands up (point, wave) | 0.972, 0.970 (slow frames) | - |

Range: the wrists leave the bottom of the image at the slow ends of each swing (only
3.6% of fast frames are out), and pose still reports a position there, a guess at
~0.60 visibility; the session is marked diagnostic in the profile. The camera reported
`continuous` exposure at 625 (62.5 ms) on every frame while delivering 30 fps, which a
62.5 ms shutter cannot do, so that field is not the camera's real setting. The second
session that day (exposure locked at -8) was never saved: the HUD's console window was
closed two minutes after the first one ended.

**The second desk session (2026-10-18, `hits-2026-10-18T00-42-37`, camera tilted
down, through the framing check).** The check passed at a lowest wrist of 0.57. All 28
takes; a body in every strike frame. Against the first session:

| | first (diagnostic) | second (tilted down) |
|---|---|---|
| strike frames with a wrist outside the image | 33.8% | **10.8%** (still all off the bottom edge; lowest 1.07) |
| wrist visibility in strikes, fast / slow | 0.666 / 0.669 | 0.750 / 0.754 |
| wrist visibility at rest, seated / kamae | 0.706 / 0.629 | 0.981 / 0.858 |
| shoulders, worst tenth | 0.992 | 0.993 |
| frames skipped in strike takes | 1 | **49** |

The skips are three takes in a row (men reps 3-5: 10, 26 and 12 skipped; rep 4 has
72 frames for 4 s, one 813 ms gap, a 784 ms pose frame). The face renderer stalled
with it (834 ms), so the whole HUD was held up, not the pose model alone - and the
window is the one in which a briefing prefetch made three gemma calls (07:43:24-43).
That is a match in time, not a measured cause.

## Study mode

"Irene, go study X" (`core/irene/study.py`, the LED scene `hud/src/led/study.ts`), or
**Ctrl+Alt+Shift+S** with no voice at all (the last subject, or the Sicilian the first
time; again to stop). Matched in code, never by the model: "go study / learn X",
"Irene, study X", "I think you should go learn X", "I want you to study X", and a bare
order with nothing after it ("Learn Sicilian", "learn tenouchi", "learn about black
holes"); Whisper's "Go La Sicilia" is put back (`core/irene/modes.py`). Any subject in
the world, not a list: the verb decides, and "research / look up / search X" is the
research feature instead ([tool-protocol.md](tool-protocol.md#what-runs-before-the-model)).
Talk stays talk: "I studied the Sicilian all weekend", "I need to go study for my
exam", "study the Sicilian, they said, it's easy". Her
face goes compact and head-down over an open book, a pen hand writing along the line it
has reached: the book's written lines *are* the progress, page by page. The subject
runs along the top, the bar along the bottom. Unhit, the bar fills in 90 s. She mutters
now and then (lines the model writes for the subject while she works, never within 4 s
of her last words or 5 s of a hit).

Each strike event is a hit, and the hits are the point: the bar jumps 6% (the jumped
segment flashes white, sparks fly off its end) and fills 25% faster per hit from then
on. Hitting every 4 s fills it in about 7 hits. Her reaction escalates with the count,
with three new expressions (each with its own art, motion and full-face theatre):

| Hits | Reaction | Face |
|---|---|---|
| 1-2 | "Ow!", startled | `bonked`: one eye winced shut, one wide; a burst, stars circling her head |
| 3-4 | "I AM studying!" | `indignant`: brows in a V, an anger mark throbbing, head snapped up off the book |
| 5+ | "Okay okay okay okay!" | `surrender`: T_T, waterfall tears onto the page, a white flag where the pen was |

When the bar fills she looks up and says what she learned. A chess opening she has a
book line for (the Sicilian, the Caro-Kann, the Nimzowitsch) goes straight into a game:
the board goes up with her challenge, his colour first, and her book is pinned to that
defence, so as Black she answers 1.e4 with what she studied. Another chess subject
starts an ordinary game. Anything else she only summarises. Eight hits or more and she
finishes "too fast": she gets a detail wrong and corrects herself out loud. For a book
defence the fumble is built from the real lines ("The Caro-Kann starts 1.e4 c5. Wait.
No. That's the Sicilian. The Caro-Kann is 1.e4 c6."), never the model's.

The hits are [strike events](#strike-events-a-tuned-threshold-not-a-learned-classifier):
the first time study mode starts with no calibration, she asks for three swings first,
then opens the book.

## The hold-grace pattern: a state must persist, not flicker

The same bug has now been fixed the same way four times: a gesture fired on one frame,
or a burst of frames, that happened to cross a line. Scroll, the kamae trigger, zoom,
and shiai's footwork (2026-10-18: in kamae his shoulders' width jitters ~7% within a
second, against an 8% step) all flickered across their thresholds with him doing
nothing. The fix each time:

- **hold** - the pose or state must stay past its line for a set time (zoom 700 ms,
  the block 250 ms, footwork 200 ms) before it counts
- **grace** - a dip back under it shorter than a set time (60-120 ms) is forgiven,
  so one lost frame is not a lost pose; a longer one starts the hold over
- **against a steady baseline** - "where he was" is the median of a stretch, never one
  frame, so a flicker can't become the place he moved from

A new trigger built on a pose landmark starts with hold-grace, not without it.
When the noise lasts longer than any reasonable hold - his shoulders reading 15%
narrower for a full second with his hands over them - hold-grace is not enough: the
trigger needs a second, independent signal that must agree (footwork: his face has to
scale and move with his shoulders, and his hands never cover it).

## Shiai

"Irene, let's do shiai" (`core/irene/shiai.py`): the keiko dojo, her in bogu facing him,
sanbon shobu. Rules and dice in code - no model, no capture. **The whole feature**, as
he set it (2026-10-18), and nothing beyond it:

- **He throws men only.** Every strike of his is a men - there is no classification.
  (Strike types were built, measured and taken out: in bogu, men vs kote came out at
  chance, 5/10 leave one out, and a coin toss between them is visibly wrong.)
- **She attacks with men or kote** (60 / 40), when he hasn't struck for 4-8 s: a windup
  he can see coming, then impact 1.4 s later.
- **He can dodge** - a step back or aside inside that window - **and block**: both
  hands up, held, against her men (against her kote, hands up leave it open).
- **She can dodge, parry and counter** his strike: weights take / parry / dodge /
  counter 30 / 30 / 25 / 15%, and 50 / 20 / 15 / 15 when he stepped in within 1.5 s.
- **A 5 s countdown before the bout**, on screen, then "Hajime!" shouted as a kiai
  (her own voice made a shout, `sfx.shout`).
- **A 5 s pause after each point**: the call ("Men ari!"), both back to the start
  lines with the rest of the pause counted down, then the shout again. Nothing counts
  between the call and hajime - refused in code (`tests/test_shiai_dead_window.py`).
- **The running score on screen.**
- **First to two.**

`config/shiai.json`: `startCountdownS` (5), `pauseS` (5). The HUD reads, with the
strike event's tuned threshold (above) and thresholds he tunes in
`config/strike_event.json` (`"shiai"`):

| His move | Read from | Threshold |
|---|---|---|
| strike (a men) | a SEQUENCE: furikaburi - both wrists 1.8 shoulder widths above his kamae (the median wrist height over the second before, rolling); the cut - the strike event above, within 0.7 s; zanshin - both wrists still 1.1 above that kamae, held 400 ms (a dip under 120 ms forgiven), from the cut's end; all within 2 s | the calibrated threshold, and `menRaiseAboveKamae` / `menZanshinAboveKamae` in `config/shiai.json` |
| block | both wrists over the shoulders, held 250 ms (a dip under 120 ms forgiven), with the strike event's own visibility floor and speed ceiling | the shoulder line |
| advance / retreat | his shoulders' width growing / shrinking over 0.5 s, held 200 ms, and his face scaling the same way | 8% (face 4%) |
| step aside | his shoulders' midpoint moving sideways over 0.5 s, held 200 ms, and his nose moving the same way | 0.5 shoulder widths |

**A men is a sequence, not a spike** (2026-10-19, shiai only - study mode keeps the plain
strike event: a bonk at his desk needs no zanshin). Jitter makes spikes; it can't make a
raise, a cut and a hold in order. Heights are against his own kamae, not his shoulders: in
bogu the pose model never sees his wrists reach his shoulders, and he moves about in a bout,
so the reference rolls. The numbers came from one readout in bogu: his men rose **2.34**
above kamae and its cut ended **1.62** above; 39 still-kamae jitter cuts rose at most 1.49
(most at or under 1.03) and ended at most 1.01 (held 67 ms; at most 0.88 among those that
held 400 ms). So 1.8 and 1.1 - margins 0.54 and 0.52 under his men. Height separates them
and stillness does not: in kamae the jitter holds still for seconds, while his zanshin held
steady (within 0.6) only 192 ms - so the hold is "stays above the line", not "stays put".
Live, at the shoulder line first: 30 s still 0, waving 0, but his men 0 (it never reaches
his shoulders); relative at 1.0 / 0.5: still 3; at 1.4 / 0.8: still 0 and his men 0.

**One swing is one strike.** The strike event's own 400 ms rest is unchanged, and
`hud/tests/strikeEvent.verify.mjs` holds it: a men whose wrists rebound inside it is
one event (with the rest off, the same swing is two). But live in bogu one swing came
through as 2-3 events over 1.4 s, each past the 400 ms - so shiai answers his strike
once and takes his events in the next 1.5 s (`STRIKE_GAP_S`) as the same swing.

**Sitting still in bogu, the strike event fires.** Measured (`scripts/strike_probe.py`,
-Dev, nothing acted on), 30 s still in kamae, the detector as it was at `43182f1`
(reverted to it 2026-10-19): **15** strike events in bogu, peaks 10.7-18.0 against
10.44, wrist noise 17.4 shoulder widths a second (the median of each second's fastest
downward wrist); the same detector earlier gave 24, 26 and 5 in bogu and 0-3
bare-handed (noise 1.0-5.1). The kote hide his wrists: the pose model guesses them,
and the guesses jump. The threshold, its calibration and its guards are as he filmed
with; this is recorded, not tuned.

**Tsuki is off, for good.** Its trigger used depth - the wrists' speed toward the
camera - and from one camera that is not a weak signal but an unusable one: with him
motionless in kamae, frame-to-frame depth speed ran 14-27 shoulder widths a second,
and the trigger fired 23 times in 30 s (2026-10-18). Those were the phantom ippons. His
calibration's "tsuki" shots had no forward travel at all and set a threshold of 4.6
from pure noise. Do not tune its threshold: no number fixes this signal. If tsuki ever
comes back, the only viable path is a 2D signature - the forearms foreshortening and
the elbows extending toward the camera - never depth, and it must pass the strike
event's own guards.

**The scoreboard.** The running score stands on the left of the dojo, where the scene
leaves the wall bare (`hud/src/led/score.ts`): his row on top, **YOU** in amber, hers
below, **IRENE** in pink, each count a big digit - 0-0, 1-0, 1-1. Core sends the score
with the answer that calls the point and before her line (`app.Core._shiai_answer`),
so it changes the moment the point is called; the side that just scored flashes white.

**Starting it.** Whisper never writes "shiai" for his voice: live it wrote "CI" and
"Xi'an", and re-decoding his saved turns gave "xi-ai", "Si An" and "Sii". Those are
put back where a command stands (`core/irene/modes.py`), and two phrasings that always
transcribe start it too: **"let's do kendo"** and **"kendo match"** ("kendo" was
written right in every one of his logged turns). "Let's do kendo practice" and "let's
spar" stay keiko. **Ctrl+Alt+Shift+M** starts it with no voice at all, and again stops it.

## Known deferred

The pinch anchor is captured at latch, not at pinch onset, so a pinch click lands
about 2-4 frames of fingertip drift late. Deferred until there are real targets to
measure against.
