# Kendo: keiko, strike events, shiai

Everything here reads his **body**, not his hand: MediaPipe Pose Landmarker Lite, vendored
in `hud/public/mediapipe/` like the hand model. It is armed only while a body mode
(keiko, study mode, shiai, a strike calibration) or a body capture is running, and
closed after, so the rest of the time it isn't even loaded (`hud/src/tracking/poseTracking.ts`).
It is kept out of the hand gesture engine on purpose: nothing in `gestures.ts` can see
it, so zoom, scroll and the pointer behave exactly as before.

Each section follows the same order as the rest of the docs: the problem, the mechanism,
what else was considered, why this, and what it costs.

| Part | Status | Section |
|---|---|---|
| strike recogniser (men / kote / gyaku-dou) | **off**, below its held-out bar | [Keiko](#keiko-the-strike-recogniser-and-the-kamae-trigger) |
| kamae pose trigger | **retired**, fired on everyday movement live | [Keiko](#keiko-the-strike-recogniser-and-the-kamae-trigger) |
| strike event ("he swung at her") | **on**, once he has calibrated | [Strike events](#strike-events) |
| shiai | **on**, men only | [Shiai](#shiai) |
| tsuki | **off for good** | [Tsuki](#tsuki-off-for-good) |
| study mode's hits | **on** (the strike event) | [modes.md](modes.md#study-mode) |

## Why the body, not the hand

**Problem.** Kamae and strikes aren't hand shapes. They're where the arms are relative
to the **shoulders**. The hand tracker is one hand and 21 landmarks: a men strike takes
the hand out of the frame entirely, and with no body there is no reference, so the same
strike reads differently depending on where he stands (commit `e2cd7c1`).

**Mechanism.** A second landmarker, 33 body landmarks. Positions are expressed in
**shoulder widths**, measured from the midpoint of his shoulders, so stepping or leaning
doesn't move them. A body capture is gated on the body being in view, not the hand.

**Cost.** A second model per frame: 6.0 ms (median) at the desk, 8.7 ms standing at 1 m
(`scripts/hits_diagnose.py`, 2026-10-17/18). And the body model guesses positions for
wrists it can't see; see [the framing lesson](lessons.md#4-framing-as-the-root-cause-four-times).

## Keiko: the strike recogniser and the kamae trigger

**Problem.** Keiko (kendo practice with her) wanted to name his strike: men, kote or
gyaku-dou.

**Mechanism.** A classifier over arm-from-shoulder features, with a Python trainer and a
TypeScript twin checked against it on golden windows (`hud/tests/strike.verify.mjs`).
It ships only if, held out, every confuser stays silent and at least 75% of strikes fire
the right strike.

**Result: off.** The best held-out result at build time was 2 of 3 strikes with every
confuser silent (commit `575d0cd`, 2026-10-12). Replayed 2026-10-17 with the committed
trainer it was 0 of 3, with 6/6 confusers silent. `strikeModel.ts` is `null`, and she
says so when keiko starts. More captures are needed.

**The kamae trigger: retired.** A logistic regression over 15 arm features was meant to
start keiko when he took kamae. It scored 97% held out with 0% confuser frames (commit
`bd2209b`), then fired on almost any arm movement live, because the held-out set had no
desk confusers ([evals.md](evals.md#kamae-a-held-out-pass-that-failed-live)). Keiko
starts by voice; `config/hud.json` has `kamae.enabled: false`. The committed
`kamaeModel.ts` is a draft fit with nothing held out (its `_about` field says so).

**Naming strikes in shiai was tried and taken out.** In bogu, men against kote from his
15-each calibration came out at chance (5/10, leave one out; commits `83d51c6`,
`a74bc0e`), and a coin toss between them is visibly wrong. Shiai calls every strike of
his a men (commit `e463dd1` removed the strike-type calibration).

## Strike events

`hud/src/tracking/strikeEvent.ts` runs it; `core/irene/strike_tuning.py` owns its number;
`config/strike_event.json` holds the knobs.

**Problem.** Study mode and shiai need one signal: he struck at her. Not which strike.

**Mechanism.** One wrist's **signed downward speed** (shoulder widths per second) peaks
over a threshold, followed by a **sharp stop**: the speed falls to 35% of its peak
within 160 ms.

- Signed: the raise and anything moving up never count, and the slower return to
  chudan stays under the threshold.
- The stop: an arm sinking to his lap doesn't count.
- **Two guards against landmark jumps.** A swing whose wrist the pose model was unsure
  of at its peak (visibility under 0.4) is ignored, and so is any peak over 60. In the
  first live run the camera reported peaks of 541, 154 and 104 from jumping landmarks.
  Across 248 recorded swings no real one passed 35, and every swing over 60 had
  visibility 0.24-0.33.
- **One swing is one strike.** After a strike both wrists rest for 400 ms.

That is the whole detector: no model file, no training, no held-out bar.
`hud/tests/strikeEvent.verify.mjs` checks it on made-up bodies: a strike fires once,
three strikes fire three times, and a raise, a slow return, a sinking arm, a swing with
a hole in it, a barely-seen wrist and a landmark jump never fire.

**Calibration: three swings, about 20 seconds.** "Irene, calibrate my strikes", or
automatically the first time study mode or shiai starts without one:

1. She says "hit me three times", and the detector runs for 12 s at a low floor
   (4 shoulder widths/s), reporting every swing's peak.
2. His three fastest are kept. The threshold is **0.6 × their median**, saved in
   `core/data/strike_calibration.json`.
3. Fewer than three swings, or uneven ones (the slowest under half the fastest), are
   not saved: she says the numbers and asks again. A threshold from one soft swing
   fires on everything.

To tune by feel, he nudges `"fraction"` in `config/strike_event.json` (lower = more
sensitive). It is read every time a mode switches the detector on. In `-Dev` each
strike's peak shows on her face against the threshold (`12.4/8.0`, top right, 2.5 s).

**Considered: a learned detector.** It was built first, as a five-bound gate (the arc's
apex, drop, peak speed, end position, visibility) shipped only past a held-out bar. It
could not fit its own training data: 9 of 135 training confuser descents cleared it, 4
of 17 confuser takes fired, and strike takes fired up to 5 times for 3 strikes. The
features had no direction, and the return strokes were nearly as fast as the strikes.
The full story is [lesson 1](lessons.md#1-the-strike-detector-that-could-not-fit-its-own-training-data).

**Why a rule.** Zoom, scroll and rock-paper-scissors pick his intent out of desk use,
where a false positive moves his cursor; they stay learned. Study mode and shiai are
modes he enters *to hit her*: a false positive is a funny noise. Constrained context,
cheap mistakes and scarce data (two desk sessions, 48 strikes) favour a rule he can tune.

**Cost.** No held-out number exists, because there is no model to hold anything out
from. Replayed offline on the second desk session, the rule's behaviour (not a
validation):

- A calibration on strike take 1 (swings 26.1, 22.0, 17.9) sets 13.2. At that, the 8
  strike takes (24 strikes) fire 21 times. One take with an 813 ms stall fires 0.
- Desk confusers fire too: typing 11, a stretch 4, a punch at the screen 0-3, reaching
  to the screen 1-3.
- A calibration on take 6 (19.8, 9.2, 7.0) would have set 5.5 and fired on nearly
  everything. That is why uneven calibrations are refused.

In study mode or shiai he isn't typing. If the rest bothers him, the fraction goes up.

**In bogu it fires on stillness.** 30 s still in kamae (`scripts/strike_probe.py`,
-Dev, nothing acted on), the detector as at `43182f1`: **15** strike events (peaks
10.7-18.0 against 10.44; wrist noise 17.4 shoulder widths/s), against 0-3 bare-handed
(noise 1.0-5.1). The same detector gave 24, 26 and 5 in bogu earlier (2026-10-18/19).
The kote hide his wrists, the pose model guesses them, and the guesses jump. This is
recorded, not tuned. Shiai's men needs a whole sequence instead ([below](#a-men-is-a-sequence-not-a-spike)).

## The hits capture: what the camera sees at the desk

**Problem.** The strike detector failed at the desk, and it wasn't clear whether the
cause was the detector or what the camera delivered.

**Mechanism.** A capture (Ctrl+Alt+Shift+0, 28 takes, about 3.5 minutes) in two parts.
First, seated chisai men, three per 4-second take, eight takes. Then 20 takes of fast
desk movements that are not strikes: kamae held, a men started and stopped, a punch at
the screen, reaching, the mouse, typing, a drink, a stretch, the phone, the shinai laid
down and more. Every body frame records:

- `dtMs`, and `skipped` frames (from `requestVideoFrameCallback`'s `presentedFrames`)
- `handMs` and `poseMs`
- the camera's exposure mode and time, read once per take

`core/scripts/hits_diagnose.py` turns a session into a table against four causes:
range, blur, occlusion and light.

**The framing check.** Before the first take he holds kamae, and the run records nothing
until his lower wrist has been at most **0.85** of frame height (0 = top) for a second.
The HUD shows the live number with TILT DOWN / IN FRAME (`hud/src/tracking/framing.ts`).
The 0.85 came from the first session, where a strike's lowest point sat 0.09 below
kamae.

**What it found.**

| | first desk session (diagnostic) | second (camera tilted down, framing check passed at 0.57) |
|---|---|---|
| strike frames with a wrist outside the image | **33.8%**, all off the bottom edge, down to 1.07 | **10.8%**, still off the bottom |
| wrist visibility in strikes, fast / slow frames | 0.666 / 0.669 (no blur effect) | 0.750 / 0.754 |
| wrist visibility at rest, seated / kamae | 0.706 / 0.629 | 0.981 / 0.858 |
| shoulders, worst tenth | 0.992 | 0.993 |
| frames skipped in strike takes | 1 | 49 (three takes during a HUD-wide stall) |

Blur, occlusion and light were each measured and ruled out; range was the cause
([lesson 4](lessons.md#4-framing-as-the-root-cause-four-times)). The 49 skipped frames
fell in a window where the face renderer also stalled (834 ms) and a briefing prefetch
made three gemma calls. That is a match in time, not a measured cause.

**Two measurement traps found on the way.**

- The first two hits runs (2026-10-17) recorded on the *hand* model. The capture armed
  pose only for profiles named `keiko*`; it now arms from the profile's
  `"tracks": "pose"`.
- The camera reported `continuous` exposure at 62.5 ms on every frame while delivering
  30 fps. A 62.5 ms shutter can't do that, so that field doesn't report the real
  setting.

**Cost and status.** The captures are a measurement now. Nothing trains on them.

## Shiai

`core/irene/shiai.py`, the dojo scene and `hud/src/led/score.ts`. No model in the
scoring, no capture. Its scope is exactly what he specified (2026-10-18/19); an earlier
round that added more was reverted to `43182f1` (commit `e463dd1`).

**Problem.** A sanbon shobu bout against her: first to two points, his strikes read
from the camera, hers shown on screen, with the start and reset beats of a real match.

**Mechanism.**

- **He throws men only.** Every strike of his is a men; there is no classification
  ([why](#keiko-the-strike-recogniser-and-the-kamae-trigger)).
- **She attacks with men or kote** (60 / 40) when he hasn't struck for 4-8 s: a windup
  he can see, then the impact 1.4 s later (`ATTACK_AFTER_S`, `WINDOW_S`).
- **He dodges or blocks.** A step back or aside inside the window dodges. Both hands up,
  held, block her men; against her kote, hands up leave it open.
- **Her answer to his strike is dice**, decided in code: take / parry / dodge / counter
  at 30 / 30 / 25 / 15%, or 50 / 20 / 15 / 15 when he stepped in within 1.5 s
  (`WEIGHTS`, `WEIGHTS_ADVANCED`).
- **The beats.** A 5 s countdown before the bout. After each point, the call ("Men
  ari!"), both back to the start lines, and a 5 s pause. Each ends in "Hajime!",
  shouted as a kiai (her voice processed into a shout, `sfx.shout`). Nothing counts
  between the call and hajime, refused in code (`tests/test_shiai_dead_window.py`
  fires every kind of event inside it and the score doesn't move).
  `config/shiai.json`: `startCountdownS` 5, `pauseS` 5.
- **The scoreboard**, on the left of the dojo: his row on top (**YOU**, amber), hers
  below (**IRENE**, pink). Core sends the score with the answer that calls the point,
  *before* her line, so it changes the moment the point is called. Live: 4/4 scores on
  the board 515-1234 ms before she started saying them.

What the HUD reads (thresholds in `config/strike_event.json` `"shiai"` and
`config/shiai.json`):

| His move | Read from |
|---|---|
| men | a sequence, below |
| block | both wrists over the shoulders, **held 250 ms** (a dip under 120 ms forgiven), with the strike event's visibility floor and speed ceiling |
| advance / retreat | his shoulders' width growing or shrinking 8% over 0.5 s, **held 200 ms** (dips under 60 ms forgiven), against a median baseline, **and** his face scaling the same way (4%) |
| step aside | his shoulders' midpoint moving 0.5 shoulder widths sideways over 0.5 s, held 200 ms, **and** his nose moving the same way |

The face check exists because his hands cover his shoulders in kamae: their width
jitters about 7% within a second, and once read 15% narrower for a full second.
Hold-grace alone can't outlast that, so a second signal must agree
([lesson 3](lessons.md#3-hold-grace-the-same-bug-fixed-the-same-way-five-times)).

### A men is a sequence, not a spike

**Problem.** In bogu the strike event fires 15 times in 30 s of stillness (above).

**Mechanism** (commit `874deb6`, shiai only; study mode keeps the plain strike event,
because a bonk at his desk needs no zanshin). A men must happen in order, within 2 s:

1. **furikaburi**: both wrists rise 1.8 shoulder widths above his **kamae**, the median
   wrist height over the second before (a rolling reference, because he moves about in
   a bout)
2. **the cut**: the strike event, within 0.7 s of the raise
3. **zanshin**: both wrists stay 1.1 above that kamae, held 400 ms from the cut's end
   (dips under 120 ms forgiven)

Jitter can make spikes. It can't make a raise, a cut and a hold in that order.

**Considered.**

- **Heights against the shoulder line.** Live, 30 s still: 0. Waving: 0. His men: also
  0. In bogu the pose model never sees his wrists reach his shoulders.
- **Relative to kamae at 1.0 / 0.5.** Still: 3.
- **At 1.4 / 0.8.** Still 0, and his men 0.
- **"Stays put" for zanshin, instead of "stays above".** Rejected: in kamae the jitter
  holds still for seconds, while his zanshin held steady (within 0.6) for only 192 ms.
  Height separates them, stillness doesn't.

**Why 1.8 / 1.1.** One readout in bogu: his men rose **2.34** above kamae and its cut
ended **1.62** above. 39 still-kamae jitter cuts rose at most 1.49 (most at or under
1.03) and ended at most 1.01. That leaves margins of 0.54 and 0.52 under his men.

**Cost.** **1.8 / 1.1 has not yet been run live.** It was set from the readout in the
last measurement round. The readout was a temporary probe, since removed.

**One swing, one strike.** Live in bogu, one swing came through as 2-3 events over
1.4 s, each past the detector's 400 ms rest. Shiai answers his strike once and treats
his events in the next 1.5 s (`STRIKE_GAP_S`) as the same swing.

**Starting it.** "Irene, let's do shiai", **"let's do kendo"**, **"kendo match"**, or
Ctrl+Alt+Shift+M. Whisper never writes "shiai" for his voice: live it wrote "CI" and
"Xi'an", and re-decoding his saved turns gave "xi-ai", "Si An" and "Sii". These are put
back only where a command stands ([modes.md](modes.md#entering-a-mode-matched-in-code)).
"Kendo" was transcribed right in every logged turn, so those phrasings are the reliable
ones. "Let's do kendo practice" and "let's spar" stay keiko.

**Ending it.** He says so, at any time ([modes.md](modes.md#his-orders-always-win)).
It also ends itself after 120 s with no strike of his or 15 minutes in all
(`shiai.IDLE_END_S`, `MAX_S`). The always-running mode guard is the backstop at 180 s.

**Measured live** (`scripts/shiai_live_check.py`, -Dev, dev socket, the camera's events
ignored, 2026-10-19): **10/10**.

- a 5 s countdown, with hajime 5.0 s after it
- a full bout to its result, his points all MEN ARI
- after a point, hajime 5.0 s from the call
- one swing sent as 3 events over 1.4 s, answered once
- the dashboard showed "Shiai" through the bout and "none" after
- a brush-off mid-bout said why ("Can't, we're in a bout right now")
- "stop the match" then "learn the Sicilian" started study mode at once

## Tsuki: off for good

**Problem.** A thrust to the throat moves *toward* the camera.

**What was built.** A trigger on depth: the wrists' speed toward the camera.

**Why it's off.** From one camera, depth is not a weak signal but an unusable one. With
him motionless in kamae, frame-to-frame depth speed ran 14-27 shoulder widths a second,
and the trigger fired **23 times in 30 s** (2026-10-18). Those were the phantom ippons.
His calibration "tsuki" shots had no forward travel at all. The code is gone (commit
`e463dd1`).

**The only way back** is a 2D signature: the forearms foreshortening and the elbows
extending toward the camera, measured in the image plane, never depth. It must also pass
the strike event's own guards. Don't tune a depth threshold; no number fixes this signal.
[Lesson 2](lessons.md#2-tsuki-and-depth-from-one-camera).
