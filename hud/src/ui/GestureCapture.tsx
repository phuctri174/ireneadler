// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { onFrame } from "../tracking/frameLoop";
import type { GestureInput, GestureState } from "../tracking/gestures";
import type { CoreSocket } from "../link/coreSocket";
import { FramingCheck } from "../tracking/framing";
import { flatten } from "../tracking/poseTracking";
import type { PoseSample } from "../tracking/poseTracking";
import type { CameraInfo, FrameTiming } from "../tracking/useHandTracking";
import captureConfig from "../../../config/capture_profiles.json";
import "./GestureCapture.css";

// Guided capture for recalibrating a gesture, driven by a profile in
// config/capture_profiles.json (summon: ctrl+alt+shift+c, the others ctrl+alt+shift+1..5). Each step -
// a held pose, or a motion done once per rep - is announced in Irene's voice, then
// waits for a hand, counts down, and records. Every camera frame's metrics AND the
// engine's raw input (landmarks, handedness, cursor) go to core with the step label,
// which writes them to core/calibration/<profile>-<session>.jsonl - enough to replay
// the gesture engine offline with new thresholds. A take with a hand in under
// minHandShare of its frames is redone; a dead camera is said out loud, so a run
// can't silently produce an empty file.

interface CaptureStep {
  label: string;
  kind: "hold" | "motion";
  seconds: number;
  prompt: string;
  spoken: string;
  reps?: number;
  repSpoken?: string;
  /** "natural": a real-speed movement (a kendo strike) - "GO", never "SLOWLY". */
  pace?: "slow" | "natural";
}

interface CaptureProfile {
  hotkey: string;
  /** "pose": the run reads the upper body, so the pose model is armed for it */
  tracks?: "pose";
  steps: CaptureStep[];
  done: string;
  /** a body run starts with his hands checked in frame, in kamae (src/tracking/framing.ts) */
  framing?: { wristMaxY: number; prompt: string; spoken: string };
}

const CONFIG = captureConfig as unknown as {
  minHandShare: number;
  countdownSeconds: number;
  profiles: Record<string, CaptureProfile>;
};

// a profile core runs itself (rock-paper-scissors: captured as the game's own rounds)
// is not one this component can run
export const CAPTURE_PROFILES = Object.keys(CONFIG.profiles).filter((name) => !(CONFIG.profiles[name] as { driver?: string }).driver);

/** Hand must be seen this long before the countdown starts. */
const HAND_SETTLE_MS = 400;
const WAIT_HAND_MS = 20000;
/** No new camera sample for this long means the feed is dead, not the hand missing. */
const NO_CAMERA_MS = 2500;
const MAX_TRIES = 3;
/** Long enough to tilt the camera and sit back down; nothing is recorded meanwhile. */
const FRAMING_WAIT_MS = 120000;

export interface CaptureFrame {
  [key: string]: number | boolean | string | number[];
}

function round(value: number, places = 5): number {
  const k = 10 ** places;
  return Math.round(value * k) / k;
}

/** A body capture's frame also says how the frame went: its timing (dropped frames,
 *  inference cost) and the camera's exposure - the strike diagnosis needs both. */
interface FrameNotes {
  timing: FrameTiming | null;
  camera: CameraInfo | null;
}

function snapshot(
  g: GestureState,
  input: GestureInput | null,
  t: number,
  body: PoseSample | null,
  notes: FrameNotes | null,
): CaptureFrame {
  const d = g.diag;
  const frame: CaptureFrame = {
    t: Math.round(t),
    hand: g.handPresent,
    mode: g.mode,
    summon: g.summon,
    zoom: g.zoom,
    pointing: g.pointing,
    scroll: g.scroll,
    zoomFactor: g.zoomFactor,
    zoomDelta: d.zoomDelta,
    zoomState: d.zoom.slice(0, 160),
    spread: g.spread,
    allFiveOpen: d.allFiveOpen,
    allFiveClosed: d.allFiveClosed,
    classes: d.classes,
    thumb: d.thumb,
    index: d.index,
    middle: d.middle,
    ring: d.ring,
    pinky: d.pinky,
    cross: g.crossing,
    tipGap: d.crossTipGap,
    knuckleGap: d.crossKnuckleGap,
    ratio: d.crossRatio,
    tipGapPalm: d.crossTipGapPalm,
    knuckleGapPalm: d.crossKnuckleGapPalm,
    palmSpan: d.palmSpan,
    boneTipCross: d.boneTipHit,
    boneTipT: d.boneTipT,
    boneTipU: d.boneTipU,
    boneTipGap: d.boneTipGap,
    boneDipCross: d.boneDipHit,
    boneDipT: d.boneDipT,
    boneDipU: d.boneDipU,
    boneDipGap: d.boneDipGap,
  };
  // the upper body, for keiko - 33 landmarks as [x, y, z, visibility, ...].
  // Absent for every other profile, so a zoom capture is byte-for-byte as before.
  if (body) {
    frame.pose = flatten(body);
  }
  if (notes?.timing) {
    frame.dtMs = round(notes.timing.dtMs, 1);
    frame.skipped = notes.timing.skipped;
    frame.handMs = round(notes.timing.handMs, 1);
    frame.poseMs = round(notes.timing.poseMs, 1);
  }
  if (notes?.camera) {
    frame.exposureMode = notes.camera.exposureMode;
    frame.exposureTime = notes.camera.exposureTime;
    frame.camW = notes.camera.width;
    frame.camH = notes.camera.height;
    frame.camFps = notes.camera.frameRate;
  }
  // the engine's exact input, for offline replay
  if (input) {
    frame.ts = round(input.timestamp, 3);
    frame.tracking = input.tracking;
    frame.cx = round(input.cursor.x);
    frame.cy = round(input.cursor.y);
    if (input.hand) {
      frame.handed = input.hand.handedness;
      frame.lm = input.hand.landmarks.flatMap((p) => [round(p.x), round(p.y), round(p.z)]);
    }
  }
  return frame;
}

export interface CaptureRun {
  profile: string;
  n: number;
}

interface Props {
  /** A new object starts a run of that profile (hotkey or dev hook). */
  run: CaptureRun | null;
  gestures: RefObject<GestureState>;
  input: RefObject<GestureInput | null>;
  /** The upper body, for keiko profiles; null unless the tracker is armed. */
  pose: RefObject<PoseSample | null>;
  /** Loads the pose model for a body run and tears it down afterwards. */
  armPose: (on: boolean) => void;
  timing: RefObject<FrameTiming | null>;
  camera: () => CameraInfo | null;
  core: CoreSocket;
}

type Phase = "framing" | "waiting" | "countdown" | "recording" | "done" | "failed";

interface View {
  prompt: string;
  phase: Phase;
  big: string;
  meta: string;
  hand: boolean;
}

export function GestureCapture({ run, gestures, input, pose, armPose, timing, camera, core }: Props) {
  const [view, setView] = useState<View | null>(null);
  const running = useRef(false);

  useEffect(() => {
    if (!run || running.current) return;
    const profile = CONFIG.profiles[run.profile];
    if (!profile) {
      console.error(`[irene] no capture profile ${run.profile}`);
      return;
    }
    running.current = true;
    // a "tracks": "pose" profile (keiko, hits) is read from the upper body; nothing
    // else needs the pose model, so it is loaded for this run only and closed again
    // on the way out. Keyed on the profile's field, never its name: a name check
    // once ran the hits capture on the hand model and saved no strike at all.
    const needsBody = profile.tracks === "pose";
    armPose(needsBody);
    const steps = profile.steps;
    const session = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    const say = (text: string): void => {
      core.send({ type: "speak", text, source: "calibration" });
    };
    const countdownMs = CONFIG.countdownSeconds * 1000;

    let step = 0;
    let rep = 0;
    let tries = 0;
    // a body run with a framing line checks his hands are in the picture first
    const framing = needsBody && profile.framing ? new FramingCheck(profile.framing.wristMaxY) : null;
    let phase: Phase = framing ? "framing" : "waiting";
    let phaseStart = performance.now();
    let handSince = 0;
    let frames: CaptureFrame[] = [];
    let cameraNow: CameraInfo | null = null;
    let lastSample = gestures.current.samples;
    let lastSampleAt = performance.now();
    let warnedCamera = false;
    let finished = false;

    const reps = (s: CaptureStep): number => (s.kind === "motion" ? (s.reps ?? 1) : 1);
    const title = (s: CaptureStep): string => (reps(s) > 1 ? `${s.prompt}  ${rep + 1}/${reps(s)}` : s.prompt);
    const show = (next: View): void => {
      setView((v) =>
        v && v.prompt === next.prompt && v.phase === next.phase && v.big === next.big && v.meta === next.meta && v.hand === next.hand
          ? v
          : next,
      );
    };
    const enter = (next: Phase, now: number): void => {
      phase = next;
      phaseStart = now;
    };
    const end = (outcome: "done" | "failed", prompt: string, meta: string): void => {
      finished = true;
      running.current = false;
      show({ prompt, phase: outcome, big: "", meta, hand: false });
      window.setTimeout(() => setView(null), outcome === "done" ? 2500 : 6000);
      stop();
      // the run is over, done or failed: the body model goes with it, not at the
      // next run (it kept running at 30 Hz after a failed hits run)
      armPose(false);
    };

    say(framing && profile.framing ? profile.framing.spoken : steps[0].spoken);
    console.log(`[irene] ${run.profile} capture ${session} started`);

    const stop = onFrame((now) => {
      if (finished) return;
      const g = gestures.current;
      // keiko reads the upper body, so that is what must be in view and what a
      // take is judged on - a men strike takes the hand out of frame entirely,
      // which would fail every take if the hand were still the gate
      const seen = needsBody ? pose.current !== null : g.handPresent;
      const subject = needsBody ? "body" : "hand";
      const current = steps[step];
      const elapsed = now - phaseStart;
      const recordMs = current.seconds * 1000;

      const fresh = g.samples !== lastSample;
      if (fresh) {
        lastSample = g.samples;
        lastSampleAt = now;
      }
      const cameraDead = now - lastSampleAt > NO_CAMERA_MS;
      if (cameraDead && !warnedCamera) {
        warnedCamera = true;
        say("I'm not getting any camera frames.");
      }

      if (phase === "framing" && framing && profile.framing) {
        const framed = framing.update(pose.current?.landmarks, now);
        const low = framing.lowest;
        show({
          prompt: profile.framing.prompt,
          phase,
          big: cameraDead ? "NO CAMERA" : low === null ? "STEP INTO VIEW" : framing.inside ? "IN FRAME" : "TILT DOWN",
          meta: low === null
            ? "head and both shoulders in frame, please"
            : `lowest wrist at ${low.toFixed(2)} of frame height - ${profile.framing.wristMaxY} or less`,
          hand: framing.inside,
        });
        if (framed) {
          core.send({ type: "hud_trace", step: `capture ${run.profile} framing ok: lowest wrist ${low?.toFixed(2)} (line ${profile.framing.wristMaxY}) after ${(elapsed / 1000).toFixed(1)} s` });
          say(steps[0].spoken);
          enter("waiting", now);
        } else if (elapsed > FRAMING_WAIT_MS) {
          core.send({ type: "hud_trace", step: `capture ${run.profile} framing failed: lowest wrist ${low === null ? "none" : low.toFixed(2)} (line ${profile.framing.wristMaxY})` });
          say("Your hands never came into the picture. Capture stopped - nothing was saved.");
          end("failed", "HANDS OUT OF FRAME", "capture stopped - nothing saved");
        }
        return;
      }

      if (phase === "waiting") {
        if (seen) {
          if (handSince === 0) handSince = now;
        } else {
          handSince = 0;
        }
        show({
          prompt: title(current),
          phase,
          big: cameraDead ? "NO CAMERA" : seen ? "HOLD IT" : needsBody ? "STEP INTO VIEW" : "SHOW YOUR HAND",
          meta: cameraDead
            ? "no frames from the camera"
            : seen
              ? `${subject} found`
              : needsBody
                ? "head and both shoulders in frame, please"
                : "raise your hand in front of the camera",
          hand: seen,
        });
        if (handSince && now - handSince >= HAND_SETTLE_MS) enter("countdown", now);
        else if (elapsed > WAIT_HAND_MS) {
          say(cameraDead ? "The camera isn't sending frames. Capture stopped." : `I couldn't find your ${subject}. Capture stopped.`);
          end("failed", cameraDead ? "CAMERA NOT RUNNING" : `NO ${subject.toUpperCase()} FOUND`, "capture stopped - nothing saved for this step");
        }
        return;
      }

      if (phase === "countdown") {
        const count = Math.max(1, Math.ceil((countdownMs - elapsed) / 1000));
        show({ prompt: title(current), phase, big: String(count), meta: seen ? "get ready" : `keep your ${subject} in view`, hand: seen });
        if (elapsed >= countdownMs) {
          enter("recording", now);
          frames = [];
          // once per take: getSettings() is not free, and exposure is fixed or
          // auto for the whole take anyway
          cameraNow = needsBody ? camera() : null;
        }
        return;
      }

      // recording: one record per camera sample, however fast the render loop runs
      if (fresh) {
        const notes = needsBody ? { timing: timing.current, camera: cameraNow } : null;
        frames.push(snapshot(g, input.current, elapsed, pose.current, notes));
      }
      const withHand = frames.filter((f) => (needsBody ? Array.isArray(f.pose) : f.hand)).length;
      const count = Math.max(1, Math.ceil((recordMs - elapsed) / 1000));
      show({
        prompt: title(current),
        phase,
        big: current.kind === "motion" ? (elapsed < 700 ? "GO" : current.pace === "natural" ? String(count) : `SLOWLY ${count}`) : `REC ${count}`,
        meta: `${seen ? subject : `NO ${subject.toUpperCase()}`} - ${withHand}/${frames.length} frames`,
        hand: seen,
      });
      if (elapsed < recordMs) return;

      if (frames.length === 0) {
        say("The camera isn't sending frames. Capture stopped.");
        end("failed", "CAMERA NOT RUNNING", "no frames recorded");
        return;
      }
      if (withHand / frames.length < CONFIG.minHandShare) {
        tries += 1;
        console.log(`[irene] capture ${current.label} rep ${rep}: ${subject} in ${withHand}/${frames.length} frames - retry ${tries}`);
        if (tries >= MAX_TRIES) {
          say(`I kept losing your ${subject}. Capture stopped.`);
          end("failed", `${subject.toUpperCase()} OUT OF VIEW`, `only ${withHand}/${frames.length} frames had a ${subject}`);
          return;
        }
        say(`I lost your ${subject} there. Let's do that one again.`);
        handSince = 0;
        enter("waiting", now);
        return;
      }

      const sent = core.send({ type: "calibration", profile: run.profile, session, pose: current.label, rep, frames });
      console.log(
        `[irene] capture ${run.profile}/${current.label} rep ${rep}: ${withHand}/${frames.length} frames with a hand, ` +
          (sent ? "sent" : "NOT SENT (core down)"),
      );
      tries = 0;
      handSince = 0;
      rep += 1;
      if (rep < reps(current)) {
        say(current.repSpoken ?? "Again.");
        enter("waiting", now);
        return;
      }
      rep = 0;
      step += 1;
      if (step >= steps.length) {
        say(profile.done);
        end("done", "CAPTURE COMPLETE", `saved to core/calibration/${run.profile}-${session}.jsonl`);
        return;
      }
      say(steps[step].spoken);
      enter("waiting", now);
    });

    return () => {
      stop();
      armPose(false);
      running.current = false;
    };
  }, [run, gestures, input, pose, armPose, timing, camera, core]);

  if (!view) return null;
  return (
    <div className={`capture is-${view.phase}${view.hand ? " has-hand" : ""}`} role="status">
      <div className="capture-prompt">{view.prompt}</div>
      {view.big ? <div className="capture-count">{view.big}</div> : null}
      <div className="capture-meta readout">{view.meta}</div>
    </div>
  );
}

export default GestureCapture;
