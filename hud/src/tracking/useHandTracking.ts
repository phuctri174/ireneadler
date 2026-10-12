import { useCallback, useEffect, useRef, useState } from "react";
import { KAMAE_MODEL } from "./kamaeModel";
import { note as perfNote } from "../perf";
import type { RefObject } from "react";
import { HandLandmarker } from "@mediapipe/tasks-vision";
import type { NormalizedLandmark } from "@mediapipe/tasks-vision";
import { DEFAULT_CURSOR_FILTER, Vec2Filter } from "./oneEuro";
import type { OneEuroConfig, Vec2 } from "./oneEuro";
import { GestureEngine, neutralGestures } from "./gestures";
import type { GestureInput, GestureState, HandSample, Handedness } from "./gestures";
import { syntheticSample } from "./synthetic";
import { PoseTracker, flatten } from "./poseTracking";
import type { PoseSample } from "./poseTracking";
import { KamaeWatcher } from "./kamaeFeatures";
import type { KamaeEvent } from "./kamaeFeatures";
import { StrikeWatcher } from "./strikeFeatures";
import type { StrikeEvent } from "./strikeFeatures";
import { STRIKE_MODEL } from "./strikeModel";
import hudConfig from "../../../config/hud.json";

// Kamae as a TRIGGER is retired: it fired on everyday arm movements. Keiko starts by
// his voice only (core/irene/keiko.py). The watcher below stays for the dev hook and
// the captures; nothing turns it on.
const KAMAE_ON = false && hudConfig.kamae?.enabled === true;
const KAMAE_EVERY = Math.max(1, Math.round(hudConfig.kamae?.poseEveryNthFrame ?? 3));
// the body model costs as much as the hand one, so it only scouts (~2 Hz) until
// something kamae-like shows; then it runs at KAMAE_EVERY for a few seconds
const KAMAE_SCOUT_EVERY = Math.max(KAMAE_EVERY, Math.round(hudConfig.kamae?.scoutEveryNthFrame ?? 15));
const KAMAE_INTEREST_MS = 3000;

const MEDIAPIPE_ASSETS = "/mediapipe";
const MODEL_ASSET = `${MEDIAPIPE_ASSETS}/hand_landmarker.task`;
const WASM_FILESET = {
  wasmLoaderPath: `${MEDIAPIPE_ASSETS}/vision_wasm_internal.js`,
  wasmBinaryPath: `${MEDIAPIPE_ASSETS}/vision_wasm_internal.wasm`,
};
const CAPTURE_WIDTH = 1280;
const CAPTURE_HEIGHT = 720;
const CAPTURE_FPS = 30;
const MAX_HANDS = 1;
const CURSOR_LANDMARK = 8;
const LANDMARK_COUNT = 21;
const LOST_HAND_GRACE_MS = 300;
const FPS_WINDOW_MS = 500;
const IDLE_DETECT_INTERVAL_MS = 100;

export interface HandTrackingOptions {
  mirror?: boolean;
  cursorFilter?: OneEuroConfig;
  minHandDetectionConfidence?: number;
  minHandPresenceConfidence?: number;
  minTrackingConfidence?: number;
  /** He took kamae at her ("start"), or left it ("end"). Only with kamae enabled. */
  onKamae?: (event: KamaeEvent) => void;
  /** Keiko is on and he struck (the strike recogniser, strikeFeatures.ts). */
  onStrike?: (event: StrikeEvent) => void;
}

export interface HandTracking {
  video: RefObject<HTMLVideoElement | null>;
  cursor: RefObject<Vec2>;
  landmarks: RefObject<NormalizedLandmark[][] | null>;
  /** Where this frame's hand came from: the camera, or the dev synthetic hand. The
   *  OS pointer acts on the camera's only - a test must never click his desktop. */
  handSource: RefObject<"camera" | "synthetic" | null>;
  gestureRef: RefObject<GestureState>;
  inputRef: RefObject<GestureInput | null>;
  /** The upper body, for keiko only - null unless armPose(true) is in force. */
  poseRef: RefObject<PoseSample | null>;
  armPose: (on: boolean) => void;
  /** Keiko on/off: the body model runs every frame and his strikes are read. */
  setKeiko: (on: boolean) => void;
  gestures: GestureState;
  fps: number;
  detectMs: number;
  sourceFps: number;
  tracking: boolean;
  error: string | null;
  setActive: (active: boolean) => void;
  /** Screens-off mode: no detection at all - not even the hidden-window summon
   *  probe - until it is lifted. */
  setSuspended: (suspended: boolean) => void;
}

function sameFlags(a: GestureState, b: GestureState): boolean {
  return (
    a.mode === b.mode &&
    a.pointing === b.pointing &&
    a.scroll === b.scroll &&
    a.zoom === b.zoom &&
    a.summon === b.summon &&
    a.selectCount === b.selectCount &&
    a.summonCount === b.summonCount &&
    a.handPresent === b.handPresent
  );
}

function toHandedness(name: string | undefined): Handedness {
  return name === "Left" ? "Left" : "Right";
}

export function useHandTracking(options: HandTrackingOptions = {}): HandTracking {
  const {
    mirror = true,
    cursorFilter = DEFAULT_CURSOR_FILTER,
    minHandDetectionConfidence = 0.5,
    minHandPresenceConfidence = 0.5,
    minTrackingConfidence = 0.5,
    onKamae,
    onStrike,
  } = options;
  const onKamaeRef = useRef(onKamae);
  onKamaeRef.current = onKamae;
  const onStrikeRef = useRef(onStrike);
  onStrikeRef.current = onStrike;
  // keiko: his strikes read from the upper body (no model shipped yet: none are)
  const keikoOn = useRef(false);
  const strikeWatch = useRef<StrikeWatcher | null>(null);

  const video = useRef<HTMLVideoElement | null>(null);
  const cursor = useRef<Vec2>({ x: 0.5, y: 0.5 });
  const landmarks = useRef<NormalizedLandmark[][] | null>(null);
  const handSource = useRef<"camera" | "synthetic" | null>(null);
  const gestureRef = useRef<GestureState>(neutralGestures());
  // the exact input of the last full engine update - gesture capture logs it so a
  // take can be replayed through the engine offline
  const inputRef = useRef<GestureInput | null>(null);
  // keiko: the upper body, and the switch that decides whether to look for it.
  // Off by default, so the pose model is never even loaded during normal use.
  const poseRef = useRef<PoseSample | null>(null);
  const poseArmed = useRef(false);
  const poseTracker = useRef<PoseTracker | null>(null);
  if (poseTracker.current === null) poseTracker.current = new PoseTracker();
  const pose = poseTracker.current;

  /** Turn the upper-body tracker on for a keiko capture, and off again after. */
  const armPose = useCallback(
    (on: boolean): void => {
      poseArmed.current = on;
      if (on) {
        void pose.arm();
      } else {
        poseRef.current = null;
        // kamae watching keeps the model loaded between captures
        if (!KAMAE_ON) pose.disarm();
      }
    },
    [pose],
  );
  const setKeiko = useCallback(
    (on: boolean): void => {
      keikoOn.current = on;
      strikeWatch.current = on && STRIKE_MODEL ? new StrikeWatcher(STRIKE_MODEL) : null;
      armPose(on);
    },
    [armPose],
  );
  const active = useRef(true);
  const idleControl = useRef<{ start: () => void; stop: () => void } | null>(null);

  const [gestures, setGestures] = useState<GestureState>(neutralGestures);
  const [fps, setFps] = useState(0);
  const [detectMs, setDetectMs] = useState(0);
  const [sourceFps, setSourceFps] = useState(0);
  const [tracking, setTracking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const suspended = useRef(false);
  const wantActive = useRef(true);
  const setActive = useCallback((next: boolean) => {
    wantActive.current = next;
    active.current = next && !suspended.current;
    if (active.current || suspended.current) idleControl.current?.stop();
    else idleControl.current?.start();
  }, []);
  const setSuspended = useCallback(
    (on: boolean) => {
      suspended.current = on;
      setActive(wantActive.current);
    },
    [setActive],
  );

  useEffect(() => {
    let disposed = false;
    let stream: MediaStream | null = null;
    let landmarker: HandLandmarker | null = null;
    let frameHandle = 0;

    const element = video.current;
    const smoother = new Vec2Filter(cursorFilter);
    const engine = new GestureEngine();
    const kamae = new KamaeWatcher();
    let poseFrame = 0;
    let poseInterestUntil = 0;
    if (KAMAE_ON) void pose.arm();

    let lastTimestamp = 0;
    let lastHandAt = 0;
    let handVisible = false;
    let frameCount = 0;
    let fpsWindowStart = 0;
    let detectTotal = 0;
    let cursorFrozen = false;
    let cursorHand: Handedness | null = null;
    let published = neutralGestures();
    let idleTimer = 0;
    let idleProbeCount = 0;
    let idleProbeAt = 0;
    let idleDetectTotal = 0;
    const anchor: Vec2 = { x: 0.5, y: 0.5 };

    const publishTracking = (next: boolean): void => {
      if (next === handVisible) return;
      handVisible = next;
      setTracking(next);
      if (!next) {
        landmarks.current = null;
        cursorFrozen = false;
        cursorHand = null;
        engine.reset();
        smoother.reset();
        published = engine.snapshot();
        gestureRef.current = published;
        setGestures(published);
      }
    };

    const onFrame = (now: number): void => {
      if (disposed || !landmarker || !element) return;

      if (!active.current) {
        if (handVisible) publishTracking(false);
        frameCount = 0;
        fpsWindowStart = 0;
        detectTotal = 0;
        frameHandle = element.requestVideoFrameCallback(onFrame);
        return;
      }


      const timestamp = Math.max(now, lastTimestamp + 1);
      lastTimestamp = timestamp;

      const detectStart = performance.now();
      const result = landmarker.detectForVideo(element, timestamp);
      detectTotal += performance.now() - detectStart;
      perfNote("hand", performance.now() - detectStart);

      if (fpsWindowStart === 0) fpsWindowStart = now;
      frameCount += 1;
      const windowElapsed = now - fpsWindowStart;
      if (windowElapsed >= FPS_WINDOW_MS) {
        setFps(Math.round((frameCount * 1000) / windowElapsed));
        setDetectMs(Math.round((detectTotal / frameCount) * 10) / 10);
        frameCount = 0;
        detectTotal = 0;
        fpsWindowStart = now;
      }

      const detected = result.landmarks[0];
      const camera: HandSample | null =
        detected && detected.length >= LANDMARK_COUNT
          ? {
              landmarks: detected,
              handedness: toHandedness(result.handedness[0]?.[0]?.categoryName),
            }
          : null;
      // dev builds only: a synthetic pointing hand stands in for the camera's
      const synthetic = import.meta.env.DEV ? syntheticSample(performance.now(), mirror) : null;
      const source = synthetic ?? camera;
      handSource.current = synthetic ? "synthetic" : camera ? "camera" : null;

      if (source) {
        lastHandAt = now;
        landmarks.current = synthetic ? [[...synthetic.landmarks]] : result.landmarks;
        publishTracking(true);
      } else if (handVisible && now - lastHandAt > LOST_HAND_GRACE_MS) {
        publishTracking(false);
      }

      const input: GestureInput = {
        hand: source,
        cursor: { ...cursor.current },
        timestamp,
        tracking: handVisible,
      };
      const state = engine.update(input);
      inputRef.current = input;

      // keiko only: the upper body, kept beside the hand rather than inside it, so
      // nothing in the gesture engine can see it or be changed by it
      // Kamae watching adds a pose detect on every Nth frame; a capture needs every one.
      poseFrame += 1;
      const every = now < poseInterestUntil || kamae.active ? KAMAE_EVERY : KAMAE_SCOUT_EVERY;
      const lookForKamae = KAMAE_ON && poseFrame % every === 0;
      const poseStart = performance.now();
      const body = poseArmed.current || lookForKamae ? pose.detect(element, timestamp) : null;
      if (poseArmed.current || lookForKamae) perfNote("pose", performance.now() - poseStart);
      poseRef.current = poseArmed.current ? body : null;
      if (keikoOn.current && strikeWatch.current) {
        const struck = strikeWatch.current.update(body ? flatten(body) : null, now);
        if (struck) onStrikeRef.current?.(struck);
      }
      if (lookForKamae) {
        const event = kamae.update(body ? flatten(body) : null, now);
        // kamae-like (or already in it): full rate for a while
        if (kamae.active || kamae.lastScore >= KAMAE_MODEL.gate.exit) poseInterestUntil = now + KAMAE_INTEREST_MS;
        if (event) onKamaeRef.current?.(event);
      }

      gestureRef.current = state;
      if (!sameFlags(state, published)) {
        published = engine.snapshot();
        setGestures(published);
      }

      if (source) {
        if (source.handedness !== cursorHand) {
          cursorHand = source.handedness;
          cursorFrozen = false;
          smoother.reset();
        }

        const tip = source.landmarks[CURSOR_LANDMARK];
        const tipX = mirror ? 1 - tip.x : tip.x;

        if (state.zoom || state.scroll) {
          if (!cursorFrozen) {
            cursorFrozen = true;
            anchor.x = cursor.current.x;
            anchor.y = cursor.current.y;
          }
          cursor.current.x = anchor.x;
          cursor.current.y = anchor.y;
        } else if (cursorFrozen) {
          cursorFrozen = false;
          smoother.seed(anchor.x, anchor.y, timestamp);
          cursor.current.x = anchor.x;
          cursor.current.y = anchor.y;
        } else {
          smoother.filterInto(cursor.current, tipX, tip.y, timestamp);
        }
      }

      frameHandle = element.requestVideoFrameCallback(onFrame);
    };

    const idleTick = (): void => {
      if (disposed || !landmarker || !element || active.current) return;

      const now = performance.now();
      idleProbeCount += 1;

      const timestamp = Math.max(now, lastTimestamp + 1);
      lastTimestamp = timestamp;

      const detectStart = performance.now();
      const result = landmarker.detectForVideo(element, timestamp);
      idleDetectTotal += performance.now() - detectStart;
      const hand = result.landmarks[0];
      const sample: HandSample | null =
        hand && hand.length >= LANDMARK_COUNT
          ? { landmarks: hand, handedness: toHandedness(result.handedness[0]?.[0]?.categoryName) }
          : null;

      const state = engine.update({
        hand: sample,
        cursor: cursor.current,
        timestamp,
        tracking: false,
        summonOnly: true,
      });

      gestureRef.current = state;
      if (state.summonCount !== published.summonCount) {
        published = engine.snapshot();
        setGestures(published);
      }
    };

    idleControl.current = {
      start: () => {
        if (idleTimer === 0) {
          idleProbeAt = performance.now();
          idleProbeCount = 0;
          idleDetectTotal = 0;
          idleTimer = window.setInterval(idleTick, IDLE_DETECT_INTERVAL_MS);
        }
      },
      stop: () => {
        if (idleTimer !== 0) {
          window.clearInterval(idleTimer);
          idleTimer = 0;
          const elapsed = performance.now() - idleProbeAt;
          console.warn(
            `[idle-probe] hidden for ${(elapsed / 1000).toFixed(1)}s -> ` +
              `${idleProbeCount} detections (${(idleProbeCount / (elapsed / 1000)).toFixed(1)}/s) ` +
              `avg detect ${(idleDetectTotal / Math.max(idleProbeCount, 1)).toFixed(1)}ms`,
          );
        }
      },
    };

    const start = async (): Promise<void> => {
      if (!element) {
        setError("video element is not mounted");
        return;
      }

      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: {
            width: { ideal: CAPTURE_WIDTH },
            height: { ideal: CAPTURE_HEIGHT },
            frameRate: { ideal: CAPTURE_FPS },
          },
          audio: false,
        });
        if (disposed) return;

        const track = stream.getVideoTracks()[0];
        if (track) setSourceFps(Math.round(track.getSettings().frameRate ?? 0));

        element.srcObject = stream;
        await element.play();
        if (disposed) return;

        landmarker = await HandLandmarker.createFromOptions(WASM_FILESET, {
          baseOptions: { modelAssetPath: MODEL_ASSET, delegate: "GPU" },
          runningMode: "VIDEO",
          numHands: MAX_HANDS,
          minHandDetectionConfidence,
          minHandPresenceConfidence,
          minTrackingConfidence,
        });
        if (disposed) {
          landmarker.close();
          landmarker = null;
          return;
        }

        setError(null);
        frameHandle = element.requestVideoFrameCallback(onFrame);
      } catch (cause) {
        if (disposed) return;
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    };

    void start();

    return () => {
      disposed = true;
      if (frameHandle && element) element.cancelVideoFrameCallback(frameHandle);
      if (element) {
        element.pause();
        element.srcObject = null;
      }
      if (idleTimer !== 0) window.clearInterval(idleTimer);
      idleControl.current = null;
      if (stream) for (const track of stream.getTracks()) track.stop();
      landmarker?.close();
      landmarker = null;
      landmarks.current = null;
    };
  }, [
    mirror,
    cursorFilter,
    minHandDetectionConfidence,
    minHandPresenceConfidence,
    minTrackingConfidence,
  ]);

  return {
    video,
    cursor,
    landmarks,
    handSource,
    gestureRef,
    inputRef,
    poseRef,
    armPose,
    setKeiko,
    gestures,
    fps,
    detectMs,
    sourceFps,
    tracking,
    error,
    setActive,
    setSuspended,
  };
}
