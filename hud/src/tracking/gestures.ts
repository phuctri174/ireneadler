// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
import type { NormalizedLandmark } from "@mediapipe/tasks-vision";
import { OneEuroFilter } from "./oneEuro";
import type { OneEuroConfig, Vec2 } from "./oneEuro";
import { ZoomHistory, zoomFeatures, zoomScore } from "./zoomFeatures";

export const THUMB_CLEAR_LATCH_RATIO = 0.58;
export const THUMB_CLEAR_RELEASE_RATIO = 0.46;

export const POINT_INDEX_LATCH_RATIO = 0.18;
export const POINT_INDEX_RELEASE_RATIO = 0.08;
export const POINT_MIDDLE_CURL_LATCH_RATIO = 0.06;
export const POINT_MIDDLE_CURL_RELEASE_RATIO = 0.16;
export const POINT_CURL_LATCH_RATIO = 0.06;
export const POINT_CURL_RELEASE_RATIO = 0.16;
export const POINT_THUMB_MAX_EXTENSION = 0.25;
export const POINT_THUMB_RELEASE_EXTENSION = 0.45;
export const POINT_HOLD_MS = 80;

export const SCROLL_MIDDLE_EXTEND_LATCH_RATIO = 0.3;
export const SCROLL_MIDDLE_EXTEND_RELEASE_RATIO = 0.18;
export const SCROLL_INDEX_LATCH_RATIO = 0.18;
export const SCROLL_INDEX_RELEASE_RATIO = 0.08;
export const SCROLL_CURL_LATCH_RATIO = 0.06;
export const SCROLL_CURL_RELEASE_RATIO = 0.16;
export const SCROLL_HOLD_MS = 80;

// Crossed fingers: the shortest distance between the index and middle tip bones
// (PIP->TIP), in palm spans - 0 when the bones actually intersect. Calibrated
// 2026-09-21 on 90 frames per pose: crossed max 0.023, parallel min 0.237. Latch
// sits a quarter into that gap, clear at its midpoint; between them the last
// state holds (hysteresis). The old tip/knuckle "cross" ratio overlapped the two
// poses and never latched on a real crossed hand; it is kept for diagnostics only.
export const CROSS_GAP_LATCH = 0.08;
export const CROSS_GAP_CLEAR = 0.13;
export const SUMMON_THUMB_MAX_EXTENSION = 0.3;
export const SUMMON_HOLD_MS = 600;
export const SUMMON_GRACE_MS = 120;

export const ZOOM_SPREAD_CLOSED = 0.5;
export const ZOOM_OPEN_FINGER_RATIO = 0.15;
export const ZOOM_OPEN_FINGER_RELEASE_RATIO = 0.08;
export const ZOOM_CLOSED_FINGER_RATIO = 0.02;
export const ZOOM_CLOSED_FINGER_RELEASE_RATIO = 0.09;
export const ZOOM_OPEN_THUMB_RATIO = 0.2;
export const ZOOM_OPEN_THUMB_RELEASE_RATIO = 0.12;
export const ZOOM_CLOSED_THUMB_RATIO = 0.1;
export const ZOOM_CLOSED_THUMB_RELEASE_RATIO = 0.18;
// Entry is deliberately hard (he sits close to the panel now, nearer than any
// capture the classifier was trained on, and a still hand latched): the pose has
// to score ZOOM_ENTRY_SCORE - about 88% sure, not just past the line - on every
// frame of a 700 ms hold, and a dip resets the hold after 60 ms. Once latched it
// stays latched while the score is >= 0, as before. core/scripts/zoom_eval.py
// replays this gate ("strict") against the captures; keep the two in step.
export const ZOOM_UNIFORM_GRACE_MS = 60;
export const ZOOM_HOLD_MS = 700;
export const ZOOM_ENTRY_SCORE = 2;
export const ZOOM_INVALID_GRACE_MS = 150;
// a held hand's spread jitters by a few percent: inside this band round 1 the
// factor reads exactly 1, so a still hand never scales anything; past it the
// factor carries on from 1 smoothly (no jump at the edge)
export const ZOOM_FACTOR_DEADBAND = 0.08;
export const ZOOM_MIN_FACTOR = 0.5;
export const ZOOM_MAX_FACTOR = 2;

export const DWELL_MIDDLE_SUPPRESS_RATIO = POINT_MIDDLE_CURL_LATCH_RATIO;
// the dwell as a system-wide click (src-tauri/src/pointer.rs): wide enough that a
// held hand's tremor never restarts it (0.02 did, every time, live) - the cursor
// itself stays still meanwhile (App.tsx's still-hand deadband)
export const DWELL_RADIUS = 0.035;
export const DWELL_HOLD_MS = 650;
// pinch = an instant click: thumb tip onto index tip (RAW landmarks, palm spans),
// with hysteresis; the middle fingertip must stay clear of the thumb, or it is a
// bunched hand (zoom-closed), not a pinch
export const PINCH_LATCH_RATIO = 0.22;
export const PINCH_RELEASE_RATIO = 0.4;
export const PINCH_MIDDLE_CLEAR_RATIO = 0.3;
// a pinch clicks only as the follow-through of pointing (point at it, then pinch):
// live, a resting hand's thumb brushing the index clicked twice with no aim
export const PINCH_AFTER_POINT_MS = 1500;

export const TRANSITION_LOCKOUT_MS = 150;

export const SCROLL_FILTER: OneEuroConfig = { minCutoff: 1, beta: 1.5, dCutoff: 1 };
export const ZOOM_FILTER: OneEuroConfig = { minCutoff: 1, beta: 1, dCutoff: 1 };

const WRIST = 0;
const THUMB_TIP = 4;
const INDEX_MCP = 5;
const INDEX_PIP = 6;
const INDEX_DIP = 7;
const INDEX_TIP = 8;
const MIDDLE_MCP = 9;
const MIDDLE_PIP = 10;
const MIDDLE_DIP = 11;
const MIDDLE_TIP = 12;
const RING_MCP = 13;
const RING_PIP = 14;
const RING_TIP = 16;
const PINKY_MCP = 17;
const PINKY_PIP = 18;
const PINKY_TIP = 20;

const PALM_POINTS = [WRIST, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP];
const FINGERTIPS = [THUMB_TIP, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP];

const LANDMARK_COUNT = 21;
const MIN_PALM_SPAN = 1e-4;

export type Handedness = "Left" | "Right";

export type GestureMode =
  | "idle"
  | "pointing"
  | "dwelling"
  | "scroll"
  | "zoom"
  | "summon";

export interface HandSample {
  landmarks: readonly NormalizedLandmark[];
  handedness: Handedness;
}

export interface GestureInput {
  hand: HandSample | null;
  cursor: Vec2;
  timestamp: number;
  tracking: boolean;
  /** low-power path: evaluate the summon pose only, skip every other gesture */
  summonOnly?: boolean;
}

export interface GestureDiag {
  thumb: number;
  index: number;
  middle: number;
  ring: number;
  pinky: number;
  allFiveOpen: boolean;
  allFiveClosed: boolean;
  openFail: string;
  closedFail: string;
  classes: string;
  crossTipGap: number;
  crossKnuckleGap: number;
  crossRatio: number;
  crossTipGapPalm: number;
  crossKnuckleGapPalm: number;
  palmSpan: number;
  summonGate: string;
  boneTip: string;
  boneDip: string;
  boneTipHit: boolean;
  boneDipHit: boolean;
  // the same two bone tests as numbers, for calibration capture
  boneTipT: number;
  boneTipU: number;
  boneTipGap: number;
  boneDipT: number;
  boneDipU: number;
  boneDipGap: number;
  zoom: string;
  zoomDelta: number;
  scrollPointRaw: number;
  summon: string;
  scroll: string;
  point: string;
  /** Why the dwell last restarted: "moved 0.041 > 0.035", "not pointing", ... */
  dwellReset: string;
}

export function neutralDiag(): GestureDiag {
  return {
    thumb: 0,
    index: 0,
    middle: 0,
    ring: 0,
    pinky: 0,
    allFiveOpen: false,
    allFiveClosed: false,
    openFail: "-",
    closedFail: "-",
    classes: "-",
    crossTipGap: 0,
    crossKnuckleGap: 0,
    crossRatio: 0,
    crossTipGapPalm: 0,
    crossKnuckleGapPalm: 0,
    palmSpan: 0,
    summonGate: "-",
    boneTip: "-",
    boneDip: "-",
    boneTipHit: false,
    boneDipHit: false,
    boneTipT: 0,
    boneTipU: 0,
    boneTipGap: 0,
    boneDipT: 0,
    boneDipU: 0,
    boneDipGap: 0,
    zoom: "no hand",
    zoomDelta: 0,
    dwellReset: "",
    scrollPointRaw: 0,
    summon: "no hand",
    scroll: "no hand",
    point: "no hand",
  };
}

export interface GestureState {
  mode: GestureMode;
  pointing: boolean;
  scroll: boolean;
  zoom: boolean;
  summon: boolean;
  dwellProgress: number;
  dwellFired: boolean;
  selectCount: number;
  summonCount: number;
  scrollPointY: number;
  zoomFactor: number;
  handPresent: boolean;
  indexExtension: number;
  middleExtension: number;
  thumbExtension: number;
  thumbIndexRatio: number;
  /** Pinches so far (thumb onto index): each one is an instant click. */
  pinchCount: number;
  pinching: boolean;
  spread: number;
  crossing: number;
  /** Tip-bone gap in palm spans; the crossed-fingers signal (0 = bones intersect). */
  crossGap: number;
  /** Camera samples processed so far - lets a consumer tell "no hand" from "no camera". */
  samples: number;
  diag: GestureDiag;
}

export function neutralGestures(): GestureState {
  return {
    samples: 0,
    crossGap: 1,
    mode: "idle",
    pointing: false,
    scroll: false,
    zoom: false,
    summon: false,
    dwellProgress: 0,
    dwellFired: false,
    selectCount: 0,
    summonCount: 0,
    scrollPointY: 0,
    zoomFactor: 1,
    handPresent: false,
    indexExtension: 0,
    middleExtension: 0,
    thumbExtension: 0,
    thumbIndexRatio: 1,
    pinchCount: 0,
    pinching: false,
    spread: 0,
    crossing: 0,
    diag: neutralDiag(),
  };
}

function distance(a: NormalizedLandmark, b: NormalizedLandmark): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function clamp(value: number, min: number, max: number): number {
  return value < min ? min : value > max ? max : value;
}

interface HandMetrics {
  palmSpan: number;
  crossTipGap: number;
  crossKnuckleGap: number;
  boneTip: SegmentCross;
  boneDip: SegmentCross;
  thumbIndexRatio: number;
  thumbMiddleRatio: number;
  index: number;
  middle: number;
  ring: number;
  pinky: number;
  thumb: number;
  spread: number;
  crossing: number;
  scrollPointY: number;
}

function extension(
  landmarks: readonly NormalizedLandmark[],
  pip: number,
  tip: number,
  palmSpan: number,
): number {
  const wrist = landmarks[WRIST];
  return (distance(wrist, landmarks[tip]) - distance(wrist, landmarks[pip])) / palmSpan;
}

function thumbExtension(landmarks: readonly NormalizedLandmark[], palmSpan: number): number {
  const indexMcp = landmarks[INDEX_MCP];
  const pinkyMcp = landmarks[PINKY_MCP];
  const axisX = indexMcp.x - pinkyMcp.x;
  const axisY = indexMcp.y - pinkyMcp.y;
  const axisLength = Math.hypot(axisX, axisY);
  if (axisLength < MIN_PALM_SPAN) return 0;

  const thumbTip = landmarks[THUMB_TIP];
  const projection =
    ((thumbTip.x - indexMcp.x) * axisX + (thumbTip.y - indexMcp.y) * axisY) / axisLength;
  return projection / palmSpan;
}

function handSpread(landmarks: readonly NormalizedLandmark[], palmSpan: number): number {
  let cx = 0;
  let cy = 0;
  for (const index of PALM_POINTS) {
    cx += landmarks[index].x;
    cy += landmarks[index].y;
  }
  cx /= PALM_POINTS.length;
  cy /= PALM_POINTS.length;

  let total = 0;
  for (const index of FINGERTIPS) {
    total += Math.hypot(landmarks[index].x - cx, landmarks[index].y - cy);
  }
  return total / FINGERTIPS.length / palmSpan;
}

export interface SegmentCross {
  intersect: boolean;
  t: number;
  u: number;
  minDistPalm: number;
}

function pointSegmentDistance(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
): number {
  const dx = bx - ax;
  const dy = by - ay;
  const lengthSq = dx * dx + dy * dy;
  if (lengthSq < 1e-12) return Math.hypot(px - ax, py - ay);
  let t = ((px - ax) * dx + (py - ay) * dy) / lengthSq;
  t = t < 0 ? 0 : t > 1 ? 1 : t;
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

/**
 * Do two finger bones actually cross in 2D? A topological test, unlike the
 * tip-distance metric, so a single mispredicted landmark cannot invert it.
 */
function segmentCross(
  a1: NormalizedLandmark,
  a2: NormalizedLandmark,
  b1: NormalizedLandmark,
  b2: NormalizedLandmark,
  palmSpan: number,
): SegmentCross {
  const rx = a2.x - a1.x;
  const ry = a2.y - a1.y;
  const sx = b2.x - b1.x;
  const sy = b2.y - b1.y;
  const denom = rx * sy - ry * sx;
  const qpx = b1.x - a1.x;
  const qpy = b1.y - a1.y;

  const minDist = Math.min(
    pointSegmentDistance(a1.x, a1.y, b1.x, b1.y, b2.x, b2.y),
    pointSegmentDistance(a2.x, a2.y, b1.x, b1.y, b2.x, b2.y),
    pointSegmentDistance(b1.x, b1.y, a1.x, a1.y, a2.x, a2.y),
    pointSegmentDistance(b2.x, b2.y, a1.x, a1.y, a2.x, a2.y),
  );

  if (Math.abs(denom) < 1e-12) {
    return { intersect: false, t: 0, u: 0, minDistPalm: minDist / palmSpan };
  }

  const t = (qpx * sy - qpy * sx) / denom;
  const u = (qpx * ry - qpy * rx) / denom;
  const intersect = t >= 0 && t <= 1 && u >= 0 && u <= 1;
  return { intersect, t, u, minDistPalm: intersect ? 0 : minDist / palmSpan };
}

function fingerCrossing(landmarks: readonly NormalizedLandmark[]): number {
  const knuckleGap = distance(landmarks[INDEX_MCP], landmarks[MIDDLE_MCP]);
  if (knuckleGap < MIN_PALM_SPAN) return 0;
  const tipGap = distance(landmarks[INDEX_TIP], landmarks[MIDDLE_TIP]);
  return 1 - tipGap / knuckleGap;
}

function readMetrics(sample: HandSample): HandMetrics | null {
  const { landmarks } = sample;
  if (landmarks.length < LANDMARK_COUNT) return null;

  const palmSpan = distance(landmarks[WRIST], landmarks[MIDDLE_MCP]);
  if (palmSpan < MIN_PALM_SPAN) return null;

  return {
    palmSpan,
    crossTipGap: distance(landmarks[INDEX_TIP], landmarks[MIDDLE_TIP]),
    crossKnuckleGap: distance(landmarks[INDEX_MCP], landmarks[MIDDLE_MCP]),
    boneTip: segmentCross(
      landmarks[INDEX_PIP],
      landmarks[INDEX_TIP],
      landmarks[MIDDLE_PIP],
      landmarks[MIDDLE_TIP],
      palmSpan,
    ),
    boneDip: segmentCross(
      landmarks[INDEX_PIP],
      landmarks[INDEX_DIP],
      landmarks[MIDDLE_PIP],
      landmarks[MIDDLE_DIP],
      palmSpan,
    ),
    thumbIndexRatio: distance(landmarks[THUMB_TIP], landmarks[INDEX_TIP]) / palmSpan,
    thumbMiddleRatio: distance(landmarks[THUMB_TIP], landmarks[MIDDLE_TIP]) / palmSpan,
    index: extension(landmarks, INDEX_PIP, INDEX_TIP, palmSpan),
    middle: extension(landmarks, MIDDLE_PIP, MIDDLE_TIP, palmSpan),
    ring: extension(landmarks, RING_PIP, RING_TIP, palmSpan),
    pinky: extension(landmarks, PINKY_PIP, PINKY_TIP, palmSpan),
    thumb: thumbExtension(landmarks, palmSpan),
    spread: handSpread(landmarks, palmSpan),
    crossing: fingerCrossing(landmarks),
    scrollPointY: (landmarks[INDEX_TIP].y + landmarks[MIDDLE_TIP].y) / 2,
  };
}

type FingerClass = "extended" | "curled" | "between";

const FINGER_LABEL: Record<FingerClass, string> = {
  extended: "ext",
  curled: "cur",
  between: "---",
};

class FingerHysteresis {
  private state: FingerClass = "between";

  update(value: number, openLatch: number, openRelease: number, closedLatch: number, closedRelease: number): FingerClass {
    if (this.state === "extended") {
      if (value < openRelease) this.state = value < closedLatch ? "curled" : "between";
    } else if (this.state === "curled") {
      if (value > closedRelease) this.state = value > openLatch ? "extended" : "between";
    } else if (value > openLatch) {
      this.state = "extended";
    } else if (value < closedLatch) {
      this.state = "curled";
    }
    return this.state;
  }

  get value(): FingerClass {
    return this.state;
  }

  reset(): void {
    this.state = "between";
  }
}

class Latch {
  private readonly holdMs: number;
  private active = false;
  private pendingSince = 0;

  constructor(holdMs = 0) {
    this.holdMs = holdMs;
  }

  update(enter: boolean, exit: boolean, timestamp: number, latchAllowed: boolean): boolean {
    if (this.active) {
      if (exit) {
        this.active = false;
        this.pendingSince = 0;
      }
      return this.active;
    }

    if (!enter || !latchAllowed) {
      this.pendingSince = 0;
      return false;
    }

    if (this.pendingSince === 0) this.pendingSince = timestamp;
    if (timestamp - this.pendingSince >= this.holdMs) {
      this.active = true;
      this.pendingSince = 0;
    }
    return this.active;
  }

  get value(): boolean {
    return this.active;
  }

  pendingMs(timestamp: number): number {
    return this.pendingSince === 0 ? 0 : timestamp - this.pendingSince;
  }

  reset(): void {
    this.active = false;
    this.pendingSince = 0;
  }
}

export class GestureEngine {
  private readonly state = neutralGestures();
  private readonly pointLatch = new Latch(POINT_HOLD_MS);
  private readonly scrollLatch = new Latch(SCROLL_HOLD_MS);

  private readonly fingers = {
    thumb: new FingerHysteresis(),
    index: new FingerHysteresis(),
    middle: new FingerHysteresis(),
    ring: new FingerHysteresis(),
    pinky: new FingerHysteresis(),
  };
  private readonly scrollFilter = new OneEuroFilter(SCROLL_FILTER);
  private readonly zoomFilter = new OneEuroFilter(ZOOM_FILTER);
  // where the hand has just been, for the classifier's motion features
  private readonly zoomHistory = new ZoomHistory();

  private lockoutUntil = 0;
  private dwellAnchor: Vec2 | null = null;
  private dwellSince = 0;
  private dwellArmed = true;
  private pinched = false;
  private pointedAt = -Infinity;
  /** The last reason the dwell's anchor moved (read into diag by update). */
  dwellResetWhy = "";
  private scrollActive = false;
  private zoomActive = false;
  private zoomPendingSince = 0;
  private zoomInvalidSince = 0;
  private zoomUniformLostSince = 0;
  private zoomBaseline = 0;
  private lastZoomFactor = 1;
  private summonActive = false;
  private summonPendingSince = 0;
  private summonLostSince = 0;
  private summonCrossed = false;
  private wasSummon = false;

  update(input: GestureInput): GestureState {
    const { hand, cursor, timestamp, tracking } = input;
    const state = this.state;
    state.samples += 1;
    const metrics = hand ? readMetrics(hand) : null;

    if (input.summonOnly) return this.updateSummonOnly(metrics, timestamp);
    const wasActive = this.anyActive();
    const latchAllowed = timestamp >= this.lockoutUntil;

    if (!metrics) {
      this.pinched = false;
      state.pinching = false;
      this.releaseAll();
      if (wasActive) this.lockoutUntil = timestamp + TRANSITION_LOCKOUT_MS;
      this.writeIdle(state);
      this.updateDwell(false, cursor, timestamp);
      state.dwellProgress = 0;
      state.dwellFired = false;
      state.mode = "idle";
      return state;
    }

    const ratio = metrics.thumbIndexRatio;
    const ringPinkyCurled =
      metrics.ring < SCROLL_CURL_LATCH_RATIO && metrics.pinky < SCROLL_CURL_LATCH_RATIO;
    const ringPinkyOpen =
      metrics.ring > SCROLL_CURL_RELEASE_RATIO || metrics.pinky > SCROLL_CURL_RELEASE_RATIO;

    const twoFingersUp =
      metrics.index > SCROLL_INDEX_LATCH_RATIO &&
      metrics.middle > SCROLL_MIDDLE_EXTEND_LATCH_RATIO &&
      ringPinkyCurled;
    const twoFingersDown =
      metrics.index < SCROLL_INDEX_RELEASE_RATIO ||
      metrics.middle < SCROLL_MIDDLE_EXTEND_RELEASE_RATIO ||
      ringPinkyOpen;

    const pointRaw =
      metrics.index > POINT_INDEX_LATCH_RATIO &&
      metrics.middle < POINT_MIDDLE_CURL_LATCH_RATIO &&
      metrics.ring < POINT_CURL_LATCH_RATIO &&
      metrics.pinky < POINT_CURL_LATCH_RATIO &&
      metrics.thumb < POINT_THUMB_MAX_EXTENSION &&
      ratio > THUMB_CLEAR_LATCH_RATIO;

    const zoom = this.updateZoomPose(metrics, timestamp, latchAllowed, pointRaw || twoFingersUp, hand?.landmarks ?? null);

    const summon = this.evaluateSummon(metrics, timestamp, latchAllowed, zoom, twoFingersUp);

    const crossGap = metrics.boneTip.minDistPalm;
    const scroll = this.scrollLatch.update(
      twoFingersUp &&
        crossGap > CROSS_GAP_CLEAR &&
        ratio > THUMB_CLEAR_LATCH_RATIO &&
        !zoom &&
        !summon,
      twoFingersDown ||
        crossGap < CROSS_GAP_LATCH ||
        ratio < THUMB_CLEAR_RELEASE_RATIO ||
        zoom ||
        summon,
      timestamp,
      latchAllowed,
    );

    const pointing = this.pointLatch.update(
      pointRaw && !zoom && !summon && !scroll,
      metrics.index < POINT_INDEX_RELEASE_RATIO ||
        metrics.middle > POINT_MIDDLE_CURL_RELEASE_RATIO ||
        metrics.ring > POINT_CURL_RELEASE_RATIO ||
        metrics.pinky > POINT_CURL_RELEASE_RATIO ||
        metrics.thumb > POINT_THUMB_RELEASE_EXTENSION ||
        ratio < THUMB_CLEAR_RELEASE_RATIO ||
        zoom ||
        summon ||
        scroll,
      timestamp,
      latchAllowed,
    );

    if (wasActive && !this.anyActive()) this.lockoutUntil = timestamp + TRANSITION_LOCKOUT_MS;

    state.zoom = zoom;
    state.summon = summon && !zoom;
    state.scroll = scroll && !zoom && !summon;
    state.pointing = pointing && !zoom && !summon && !scroll;
    state.handPresent = true;
    state.indexExtension = metrics.index;
    state.middleExtension = metrics.middle;
    state.thumbExtension = metrics.thumb;
    state.thumbIndexRatio = ratio;
    state.spread = metrics.spread;
    state.crossing = metrics.crossing;
    state.crossGap = metrics.boneTip.minDistPalm;

    const diag = state.diag;
    diag.thumb = metrics.thumb;
    diag.index = metrics.index;
    diag.middle = metrics.middle;
    diag.ring = metrics.ring;
    diag.pinky = metrics.pinky;
    diag.scrollPointRaw = metrics.scrollPointY;
    diag.palmSpan = metrics.palmSpan;
    diag.crossTipGap = metrics.crossTipGap;
    diag.crossKnuckleGap = metrics.crossKnuckleGap;
    diag.crossRatio =
      metrics.crossKnuckleGap > MIN_PALM_SPAN ? metrics.crossTipGap / metrics.crossKnuckleGap : 0;
    diag.crossTipGapPalm = metrics.crossTipGap / metrics.palmSpan;
    diag.crossKnuckleGapPalm = metrics.crossKnuckleGap / metrics.palmSpan;

    const describe = (c: SegmentCross): string =>
      `${c.intersect ? "CROSS" : "clear"} t=${c.t.toFixed(3)} u=${c.u.toFixed(3)} ` +
      `gap=${c.minDistPalm.toFixed(3)}palm`;
    diag.boneTip = describe(metrics.boneTip);
    diag.boneDip = describe(metrics.boneDip);
    diag.boneTipHit = metrics.boneTip.intersect;
    diag.boneDipHit = metrics.boneDip.intersect;
    diag.boneTipT = metrics.boneTip.t;
    diag.boneTipU = metrics.boneTip.u;
    diag.boneTipGap = metrics.boneTip.minDistPalm;
    diag.boneDipT = metrics.boneDip.t;
    diag.boneDipU = metrics.boneDip.u;
    diag.boneDipGap = metrics.boneDip.minDistPalm;

    const gatePart = (label: string, value: number, threshold: number, wantAbove: boolean): string => {
      const ok = wantAbove ? value > threshold : value < threshold;
      return `${label} ${value.toFixed(2)} ${ok ? "OK" : `FAIL(${wantAbove ? ">" : "<"}${threshold})`}`;
    };
    diag.summonGate =
      `${gatePart("idx", metrics.index, SCROLL_INDEX_LATCH_RATIO, true)} | ` +
      `${gatePart("mid", metrics.middle, SCROLL_MIDDLE_EXTEND_LATCH_RATIO, true)} | ` +
      `${gatePart("ring", metrics.ring, SCROLL_CURL_LATCH_RATIO, false)} | ` +
      `${gatePart("pky", metrics.pinky, SCROLL_CURL_LATCH_RATIO, false)}`;

    const twoFingerFail = [
      metrics.index > SCROLL_INDEX_LATCH_RATIO ? null : `index ${metrics.index.toFixed(2)}<=${SCROLL_INDEX_LATCH_RATIO}`,
      metrics.middle > SCROLL_MIDDLE_EXTEND_LATCH_RATIO ? null : `mid ${metrics.middle.toFixed(2)}<=${SCROLL_MIDDLE_EXTEND_LATCH_RATIO}`,
      metrics.ring < SCROLL_CURL_LATCH_RATIO ? null : `ring ${metrics.ring.toFixed(2)}>=${SCROLL_CURL_LATCH_RATIO}`,
      metrics.pinky < SCROLL_CURL_LATCH_RATIO ? null : `pinky ${metrics.pinky.toFixed(2)}>=${SCROLL_CURL_LATCH_RATIO}`,
    ]
      .filter(Boolean)
      .join(" ");

    if (state.scroll) {
      diag.scroll = "LATCHED";
    } else if (!twoFingersUp) {
      diag.scroll = `no two-finger pose: ${twoFingerFail}`;
    } else if (metrics.boneTip.minDistPalm <= CROSS_GAP_CLEAR) {
      diag.scroll = `crossed: bone gap ${metrics.boneTip.minDistPalm.toFixed(3)} <= ${CROSS_GAP_CLEAR}`;
    } else if (ratio <= THUMB_CLEAR_LATCH_RATIO) {
      diag.scroll = `thumb-index gap ${ratio.toFixed(2)} <= ${THUMB_CLEAR_LATCH_RATIO}`;
    } else if (zoom || summon) {
      diag.scroll = zoom ? "blocked: zoom latched" : "blocked: summon latched";
    } else {
      diag.scroll = `holding ${this.scrollLatch.pendingMs(timestamp)}/${SCROLL_HOLD_MS}ms`;
    }

    if (state.pointing) {
      diag.point = "LATCHED";
    } else if (metrics.index <= POINT_INDEX_LATCH_RATIO) {
      diag.point = `index ${metrics.index.toFixed(2)} <= ${POINT_INDEX_LATCH_RATIO}`;
    } else if (metrics.middle >= POINT_MIDDLE_CURL_LATCH_RATIO) {
      diag.point = `mid ${metrics.middle.toFixed(2)} >= ${POINT_MIDDLE_CURL_LATCH_RATIO}`;
    } else if (metrics.ring >= POINT_CURL_LATCH_RATIO || metrics.pinky >= POINT_CURL_LATCH_RATIO) {
      diag.point = `ring/pinky not curled ${metrics.ring.toFixed(2)}/${metrics.pinky.toFixed(2)}`;
    } else if (metrics.thumb >= POINT_THUMB_MAX_EXTENSION) {
      diag.point = `thumb ${metrics.thumb.toFixed(2)} >= ${POINT_THUMB_MAX_EXTENSION}`;
    } else if (ratio <= THUMB_CLEAR_LATCH_RATIO) {
      diag.point = `gap ${ratio.toFixed(2)} <= ${THUMB_CLEAR_LATCH_RATIO}`;
    } else if (zoom || summon || scroll) {
      diag.point = "blocked by another gesture";
    } else {
      diag.point = `holding ${this.pointLatch.pendingMs(timestamp)}/${POINT_HOLD_MS}ms`;
    }

    if (state.summon && !this.wasSummon) state.summonCount += 1;
    this.wasSummon = state.summon;

    state.scrollPointY = this.updateScroll(state.scroll, metrics.scrollPointY, timestamp);
    state.zoomFactor = this.updateZoomFactor(zoom, metrics.spread, timestamp);
    diag.zoomDelta = zoom ? state.zoomFactor - this.lastZoomFactor : 0;
    this.lastZoomFactor = state.zoomFactor;

    // pinch: thumb onto index is a click at once (not while zooming or summoning)
    if (state.pointing) this.pointedAt = timestamp;
    const aimed = timestamp - this.pointedAt <= PINCH_AFTER_POINT_MS;
    if (!this.pinched && ratio < PINCH_LATCH_RATIO && metrics.thumbMiddleRatio > PINCH_MIDDLE_CLEAR_RATIO && aimed && !state.zoom && !state.summon) {
      this.pinched = true;
      state.pinchCount += 1;
    } else if (this.pinched && ratio > PINCH_RELEASE_RATIO) {
      this.pinched = false;
    }
    state.pinching = this.pinched;

    const dwellEligible =
      state.pointing && tracking && metrics.middle < DWELL_MIDDLE_SUPPRESS_RATIO;
    diag.dwellReset = !state.pointing
      ? "not pointing"
      : !tracking
        ? "hand not tracked"
        : metrics.middle >= DWELL_MIDDLE_SUPPRESS_RATIO
          ? `middle finger out (${metrics.middle.toFixed(2)})`
          : diag.dwellReset;
    const dwell = this.updateDwell(dwellEligible, cursor, timestamp);
    if (dwellEligible) diag.dwellReset = this.dwellResetWhy;
    state.dwellProgress = dwell.progress;
    state.dwellFired = dwell.fired;
    if (dwell.fired) state.selectCount += 1;

    state.mode = this.pickMode(state);
    return state;
  }

  private updateSummonOnly(metrics: HandMetrics | null, timestamp: number): GestureState {
    const state = this.state;
    const diag = state.diag;

    // nothing but summon runs in this mode
    this.pointLatch.reset();
    this.scrollLatch.reset();
    this.scrollActive = false;
    this.zoomActive = false;
    this.zoomPendingSince = 0;
    this.zoomUniformLostSince = 0;
    this.zoomInvalidSince = 0;
    this.zoomBaseline = 0;

    state.pointing = false;
    state.scroll = false;
    state.zoom = false;
    state.dwellProgress = 0;
    state.dwellFired = false;
    state.scrollPointY = 0;
    state.zoomFactor = 1;
    state.mode = "idle";

    if (!metrics) {
      this.summonActive = false;
      this.summonPendingSince = 0;
      this.summonLostSince = 0;
      this.summonCrossed = false;
      state.handPresent = false;
      state.crossing = 0;
      state.crossGap = 1;
      diag.summon = "no hand (low-power)";
      this.wasSummon = false;
      return state;
    }

    const twoFingersUp =
      metrics.index > SCROLL_INDEX_LATCH_RATIO &&
      metrics.middle > SCROLL_MIDDLE_EXTEND_LATCH_RATIO &&
      metrics.ring < SCROLL_CURL_LATCH_RATIO &&
      metrics.pinky < SCROLL_CURL_LATCH_RATIO;

    state.handPresent = true;
    state.crossing = metrics.crossing;
    state.crossGap = metrics.boneTip.minDistPalm;
    diag.crossTipGap = metrics.crossTipGap;
    diag.crossKnuckleGap = metrics.crossKnuckleGap;
    diag.crossRatio =
      metrics.crossKnuckleGap > MIN_PALM_SPAN ? metrics.crossTipGap / metrics.crossKnuckleGap : 0;

    const summon = this.evaluateSummon(metrics, timestamp, true, false, twoFingersUp);
    state.summon = summon;
    if (summon && !this.wasSummon) state.summonCount += 1;
    this.wasSummon = summon;
    state.mode = summon ? "summon" : "idle";
    return state;
  }

  private evaluateSummon(
    metrics: HandMetrics,
    timestamp: number,
    latchAllowed: boolean,
    blocked: boolean,
    twoFingersUp: boolean,
  ): boolean {
    const diag = this.state.diag;

    // hysteresis: crossed once the tip bones come within CROSS_GAP_LATCH palm spans
    // (usually they intersect: gap 0), uncrossed only past CROSS_GAP_CLEAR
    const gap = metrics.boneTip.minDistPalm;
    if (this.summonCrossed) {
      if (gap > CROSS_GAP_CLEAR) this.summonCrossed = false;
    } else if (gap < CROSS_GAP_LATCH) {
      this.summonCrossed = true;
    }

    const poseValid =
      this.summonCrossed &&
      twoFingersUp &&
      metrics.thumb < SUMMON_THUMB_MAX_EXTENSION &&
      !blocked;

    const why = (): string => {
      if (blocked) return "blocked: zoom latched";
      if (!this.summonCrossed) return `bone gap ${gap.toFixed(3)} >= ${CROSS_GAP_LATCH}`;
      if (!twoFingersUp) return `finger gate: ${diag.summonGate}`;
      if (metrics.thumb >= SUMMON_THUMB_MAX_EXTENSION) {
        return `thumb ${metrics.thumb.toFixed(2)} >= ${SUMMON_THUMB_MAX_EXTENSION}`;
      }
      return "-";
    };

    if (this.summonActive) {
      if (poseValid) {
        this.summonLostSince = 0;
        diag.summon = "LATCHED";
      } else {
        if (this.summonLostSince === 0) this.summonLostSince = timestamp;
        const lost = timestamp - this.summonLostSince;
        if (lost >= SUMMON_GRACE_MS) {
          this.summonActive = false;
          this.summonLostSince = 0;
          this.summonPendingSince = 0;
          diag.summon = `released after ${lost}ms invalid`;
          return false;
        }
        diag.summon = `LATCHED (dropout ${lost}/${SUMMON_GRACE_MS}ms tolerated)`;
      }
      return true;
    }

    if (!latchAllowed) {
      this.summonPendingSince = 0;
      this.summonLostSince = 0;
      diag.summon = "blocked: transition lockout";
      return false;
    }

    if (poseValid) {
      this.summonLostSince = 0;
      if (this.summonPendingSince === 0) this.summonPendingSince = timestamp;
      const held = timestamp - this.summonPendingSince;
      if (held < SUMMON_HOLD_MS) {
        diag.summon = `holding ${held}/${SUMMON_HOLD_MS}ms`;
        return false;
      }
      this.summonActive = true;
      this.summonPendingSince = 0;
      this.summonLostSince = 0;
      diag.summon = "LATCHED";
      return true;
    }

    if (this.summonPendingSince === 0) {
      diag.summon = why();
      return false;
    }

    // brief dips keep the hold timer accumulating
    if (this.summonLostSince === 0) this.summonLostSince = timestamp;
    const lost = timestamp - this.summonLostSince;
    if (lost >= SUMMON_GRACE_MS) {
      this.summonPendingSince = 0;
      this.summonLostSince = 0;
      diag.summon = `hold reset: invalid ${lost}ms >= ${SUMMON_GRACE_MS}ms (${why()})`;
    } else {
      diag.summon =
        `holding ${timestamp - this.summonPendingSince}/${SUMMON_HOLD_MS}ms ` +
        `(dropout ${lost}/${SUMMON_GRACE_MS}ms tolerated: ${why()})`;
    }
    return false;
  }

  private updateZoomPose(
    metrics: HandMetrics,
    timestamp: number,
    latchAllowed: boolean,
    otherPoseRaw: boolean,
    landmarks: readonly NormalizedLandmark[] | null,
  ): boolean {
    const cls = {
      thumb: this.fingers.thumb.update(
        metrics.thumb,
        ZOOM_OPEN_THUMB_RATIO,
        ZOOM_OPEN_THUMB_RELEASE_RATIO,
        ZOOM_CLOSED_THUMB_RATIO,
        ZOOM_CLOSED_THUMB_RELEASE_RATIO,
      ),
      index: this.fingers.index.update(
        metrics.index,
        ZOOM_OPEN_FINGER_RATIO,
        ZOOM_OPEN_FINGER_RELEASE_RATIO,
        ZOOM_CLOSED_FINGER_RATIO,
        ZOOM_CLOSED_FINGER_RELEASE_RATIO,
      ),
      middle: this.fingers.middle.update(
        metrics.middle,
        ZOOM_OPEN_FINGER_RATIO,
        ZOOM_OPEN_FINGER_RELEASE_RATIO,
        ZOOM_CLOSED_FINGER_RATIO,
        ZOOM_CLOSED_FINGER_RELEASE_RATIO,
      ),
      ring: this.fingers.ring.update(
        metrics.ring,
        ZOOM_OPEN_FINGER_RATIO,
        ZOOM_OPEN_FINGER_RELEASE_RATIO,
        ZOOM_CLOSED_FINGER_RATIO,
        ZOOM_CLOSED_FINGER_RELEASE_RATIO,
      ),
      pinky: this.fingers.pinky.update(
        metrics.pinky,
        ZOOM_OPEN_FINGER_RATIO,
        ZOOM_OPEN_FINGER_RELEASE_RATIO,
        ZOOM_CLOSED_FINGER_RATIO,
        ZOOM_CLOSED_FINGER_RELEASE_RATIO,
      ),
    };

    const allFiveOpen =
      cls.thumb === "extended" &&
      cls.index === "extended" &&
      cls.middle === "extended" &&
      cls.ring === "extended" &&
      cls.pinky === "extended";
    const allFiveClosed =
      cls.thumb === "curled" &&
      cls.index === "curled" &&
      cls.middle === "curled" &&
      cls.ring === "curled" &&
      cls.pinky === "curled";

    // The decision is the classifier's (tracking/zoomFeatures.ts). "All five
    // fingers agree" survives below as a readout only: against the captures it
    // latched on 95% of waving frames and 34% of held fists, because a spread, a
    // wave and a resting hand are all open hands and no threshold on finger
    // extension separates them. What does is how the hand moves, so the wrist
    // goes in too.
    const wrist = landmarks?.[WRIST];
    this.zoomHistory.push({ handX: wrist?.x ?? 0, handY: wrist?.y ?? 0, spread: metrics.spread, timestamp });
    const score =
      zoomScore(
        zoomFeatures(
          {
            thumb: metrics.thumb,
            index: metrics.index,
            middle: metrics.middle,
            ring: metrics.ring,
            pinky: metrics.pinky,
            spread: metrics.spread,
            ratio: metrics.crossKnuckleGap > MIN_PALM_SPAN ? metrics.crossTipGap / metrics.crossKnuckleGap : 0,
            tipGapPalm: metrics.crossTipGap / metrics.palmSpan,
            knuckleGapPalm: metrics.crossKnuckleGap / metrics.palmSpan,
            palmSpan: metrics.palmSpan,
            landmarks,
          },
          this.zoomHistory,
        ),
      );
    const uniform = score >= 0;

    const diag = this.state.diag;
    diag.allFiveOpen = allFiveOpen;
    diag.allFiveClosed = allFiveClosed;
    diag.classes =
      `th=${FINGER_LABEL[cls.thumb]} ix=${FINGER_LABEL[cls.index]} ` +
      `md=${FINGER_LABEL[cls.middle]} rg=${FINGER_LABEL[cls.ring]} pk=${FINGER_LABEL[cls.pinky]}`;
    const notExtended = Object.entries(cls)
      .filter(([, v]) => v !== "extended")
      .map(([k, v]) => `${k}:${FINGER_LABEL[v]}`)
      .join(" ");
    const notCurled = Object.entries(cls)
      .filter(([, v]) => v !== "curled")
      .map(([k, v]) => `${k}:${FINGER_LABEL[v]}`)
      .join(" ");
    diag.openFail = allFiveOpen ? "-" : notExtended;
    diag.closedFail = allFiveClosed ? "-" : notCurled;

    if (this.zoomActive) {
      if (!uniform || otherPoseRaw) {
        diag.zoom = `LATCHED but releasing: ${!uniform ? "not uniform" : "other pose"} for ${
          this.zoomInvalidSince === 0 ? 0 : timestamp - this.zoomInvalidSince
        }/${ZOOM_INVALID_GRACE_MS}ms`;
        if (this.zoomInvalidSince === 0) this.zoomInvalidSince = timestamp;
        if (timestamp - this.zoomInvalidSince >= ZOOM_INVALID_GRACE_MS) {
          this.zoomActive = false;
          this.zoomInvalidSince = 0;
          this.zoomBaseline = 0;
          return false;
        }
      } else {
        this.zoomInvalidSince = 0;
        diag.zoom = "LATCHED";
      }
      return true;
    }

    // the classifier weighs spread along with everything else, so the separate
    // gate on it is gone; entering takes a confident score, not just a positive one
    const poseValid = score >= ZOOM_ENTRY_SCORE;

    if (!latchAllowed) {
      this.zoomPendingSince = 0;
      this.zoomUniformLostSince = 0;
      diag.zoom = "blocked: transition lockout";
      return false;
    }

    if (poseValid) {
      this.zoomUniformLostSince = 0;
      if (this.zoomPendingSince === 0) this.zoomPendingSince = timestamp;
      if (timestamp - this.zoomPendingSince < ZOOM_HOLD_MS) {
        diag.zoom = `holding ${timestamp - this.zoomPendingSince}/${ZOOM_HOLD_MS}ms`;
        return false;
      }
    } else {
      if (this.zoomPendingSince === 0) {
        diag.zoom = uniform
          ? `score ${score.toFixed(2)} < entry ${ZOOM_ENTRY_SCORE}`
          : allFiveClosed
            ? `closed but spread ${metrics.spread.toFixed(3)} >= ${ZOOM_SPREAD_CLOSED}`
            : `not uniform | open needs: ${diag.openFail} | closed needs: ${diag.closedFail}`;
        return false;
      }

      // brief dropouts are tolerated; the hold timer keeps accumulating
      if (this.zoomUniformLostSince === 0) this.zoomUniformLostSince = timestamp;
      const lost = timestamp - this.zoomUniformLostSince;
      if (lost >= ZOOM_UNIFORM_GRACE_MS) {
        this.zoomPendingSince = 0;
        this.zoomUniformLostSince = 0;
        diag.zoom = `hold reset: invalid ${lost}ms >= ${ZOOM_UNIFORM_GRACE_MS}ms`;
      } else {
        diag.zoom =
          `holding ${timestamp - this.zoomPendingSince}/${ZOOM_HOLD_MS}ms ` +
          `(dropout ${lost}/${ZOOM_UNIFORM_GRACE_MS}ms tolerated: ${diag.openFail})`;
      }
      return false;
    }

    this.zoomActive = true;
    this.zoomPendingSince = 0;
    this.zoomUniformLostSince = 0;
    this.zoomInvalidSince = 0;
    this.zoomBaseline = 0;
    diag.zoom = "LATCHED";
    return true;
  }

  private updateZoomFactor(active: boolean, spread: number, timestamp: number): number {
    if (!active) {
      this.zoomBaseline = 0;
      return 1;
    }

    if (this.zoomBaseline === 0) {
      this.zoomBaseline = spread;
      this.zoomFilter.reset();
      this.zoomFilter.seed(spread, timestamp);
      return 1;
    }

    const smoothed = this.zoomFilter.filter(spread, timestamp);
    const ratio = smoothed / this.zoomBaseline;
    const beyond = Math.max(0, Math.abs(ratio - 1) - ZOOM_FACTOR_DEADBAND);
    return clamp(1 + Math.sign(ratio - 1) * beyond, ZOOM_MIN_FACTOR, ZOOM_MAX_FACTOR);
  }

  private updateScroll(active: boolean, y: number, timestamp: number): number {
    if (!active) {
      this.scrollActive = false;
      return 0;
    }

    if (!this.scrollActive) {
      this.scrollActive = true;
      this.scrollFilter.reset();
      this.scrollFilter.seed(y, timestamp);
      return y;
    }

    return this.scrollFilter.filter(y, timestamp);
  }

  private updateDwell(
    eligible: boolean,
    cursor: Vec2,
    timestamp: number,
  ): { progress: number; fired: boolean } {
    const moved = this.dwellAnchor ? Math.hypot(cursor.x - this.dwellAnchor.x, cursor.y - this.dwellAnchor.y) : 0;
    if (!this.dwellAnchor || moved > DWELL_RADIUS) {
      if (this.dwellAnchor) this.dwellResetWhy = `moved ${moved.toFixed(3)} > ${DWELL_RADIUS}`;
      this.dwellAnchor = { x: cursor.x, y: cursor.y };
      this.dwellSince = timestamp;
      this.dwellArmed = true;
      return { progress: 0, fired: false };
    }

    if (!eligible) {
      this.dwellSince = timestamp;
      return { progress: 0, fired: false };
    }

    if (!this.dwellArmed) return { progress: 1, fired: false };

    const progress = clamp((timestamp - this.dwellSince) / DWELL_HOLD_MS, 0, 1);
    if (progress < 1) return { progress, fired: false };

    this.dwellArmed = false;
    return { progress: 1, fired: true };
  }

  private pickMode(state: GestureState): GestureMode {
    if (state.zoom) return "zoom";
    if (state.summon) return "summon";
    if (state.scroll) return "scroll";
    if (state.pointing) return state.dwellProgress > 0 ? "dwelling" : "pointing";
    return "idle";
  }

  private anyActive(): boolean {
    return (
      this.zoomActive ||
      this.pointLatch.value ||
      this.scrollLatch.value ||
      this.summonActive
    );
  }

  private releaseAll(): void {
    this.pointLatch.reset();
    this.scrollLatch.reset();
    this.summonActive = false;
    this.summonPendingSince = 0;
    this.summonLostSince = 0;
    this.summonCrossed = false;
    this.scrollActive = false;
    this.zoomActive = false;
    this.zoomPendingSince = 0;
    this.zoomUniformLostSince = 0;
    this.zoomInvalidSince = 0;
    this.zoomBaseline = 0;
    for (const finger of Object.values(this.fingers)) finger.reset();
    this.wasSummon = false;
  }

  private writeIdle(state: GestureState): void {
    state.pointing = false;
    state.scroll = false;
    state.zoom = false;
    state.summon = false;
    state.scrollPointY = 0;
    state.zoomFactor = 1;
    state.handPresent = false;
    state.indexExtension = 0;
    state.middleExtension = 0;
    state.thumbExtension = 0;
    state.thumbIndexRatio = 1;
    state.spread = 0;
    state.crossing = 0;
    state.crossGap = 1;
  }

  reset(): void {
    this.releaseAll();
    this.lockoutUntil = 0;
    this.dwellAnchor = null;
    this.dwellSince = 0;
    this.dwellArmed = true;
    this.scrollFilter.reset();
    this.zoomFilter.reset();

    const state = this.state;
    this.writeIdle(state);
    state.mode = "idle";
    state.dwellProgress = 0;
    state.dwellFired = false;
  }

  snapshot(): GestureState {
    return { ...this.state, diag: { ...this.state.diag } };
  }
}
