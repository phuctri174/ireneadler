// Stylized LED hands. A hand is a rig - a rounded palm and a capsule per finger -
// and a gesture is data: how far each finger is extended and where it points. The
// rig is rasterised onto the matrix as a bright rim with a faint fill, part by part
// in painter's order, so overlapping fingers (crossed, a fist's knuckles) stay
// readable at LED resolution.

import { FADE, INK, capsule, drawShape, lerp, roundBox } from "./grid";
import type { Frame, Ink, Vec } from "./grid";

export type FingerName = "index" | "middle" | "ring" | "pinky" | "thumb";

export interface Finger {
  /** 1 straight, 0 curled into the palm. */
  ext: number;
  /** Extra lean in degrees, clockwise; 0 is the finger's natural direction. */
  lean?: number;
  /** Moves the finger's base, in hand units - a thumbs-up thumb sits on top of the fist. */
  shift?: Vec;
}

export type HandPose = Record<FingerName, Finger> & {
  /** Draw the middle finger over the index (crossed-fingers sign). */
  middleOverIndex?: boolean;
};

export interface Placement {
  /** Palm centre in matrix cells. */
  x: number;
  y: number;
  /** Degrees clockwise; 0 is fingers up. */
  rot?: number;
  scale?: number;
  /** Mirror left-right: a left hand is a mirrored right hand. */
  mirror?: boolean;
  alpha?: number;
  ink?: Ink;
  fade?: number;
}

// Right hand, palm toward the viewer, fingers up. Local units are cells at scale 1.
const PALM = { c: { x: 0, y: 0.4 }, hw: 4.7, hh: 5.0, r: 2.3 };
const GEOMETRY: Record<FingerName, { base: Vec; angle: number; len: number; r: number }> = {
  index: { base: { x: -3.1, y: -3.6 }, angle: -7, len: 8.4, r: 1.2 },
  middle: { base: { x: -1.0, y: -4.0 }, angle: -1, len: 9.2, r: 1.2 },
  ring: { base: { x: 1.1, y: -3.8 }, angle: 5, len: 8.4, r: 1.15 },
  pinky: { base: { x: 3.1, y: -3.1 }, angle: 11, len: 6.8, r: 1.05 },
  thumb: { base: { x: -3.9, y: 1.6 }, angle: -50, len: 6.6, r: 1.35 },
};
// a curled thumb folds across the palm instead of shortening in place
const THUMB_FOLDED_ANGLE = 58;
const ORDER: FingerName[] = ["pinky", "ring", "middle", "index", "thumb"];
const ORDER_CROSSED: FingerName[] = ["pinky", "ring", "index", "middle", "thumb"];

const DEG = Math.PI / 180;

function fingerSegment(name: FingerName, finger: Finger): { a: Vec; b: Vec; r: number } {
  const g = GEOMETRY[name];
  const ext = Math.min(1, Math.max(0, finger.ext));
  const angle =
    (name === "thumb" ? lerp(THUMB_FOLDED_ANGLE, g.angle, ext) : g.angle) + (finger.lean ?? 0);
  const length = g.len * (name === "thumb" ? lerp(0.62, 1, ext) : lerp(0.26, 1, ext));
  const dir = { x: Math.sin(angle * DEG), y: -Math.cos(angle * DEG) };
  // curled fingers sit a little lower: knuckles, not stubs
  const drop = name === "thumb" ? 0 : (1 - ext) * 1.2;
  const a = { x: g.base.x + (finger.shift?.x ?? 0), y: g.base.y + drop + (finger.shift?.y ?? 0) };
  return { a, b: { x: a.x + dir.x * length, y: a.y + dir.y * length }, r: g.r };
}

/** World cell centre -> hand-local coordinates for a placement, plus its bounds. */
function frameOf(place: Placement) {
  const scale = place.scale ?? 1;
  const rot = (place.rot ?? 0) * DEG;
  const cos = Math.cos(rot);
  const sin = Math.sin(rot);
  const mirror = place.mirror ? -1 : 1;
  const local = (wx: number, wy: number): Vec => {
    const dx = (wx - place.x) / scale;
    const dy = (wy - place.y) / scale;
    const rx = dx * cos + dy * sin;
    const ry = -dx * sin + dy * cos;
    return { x: rx * mirror, y: ry };
  };
  const reach = 17 * scale;
  const bounds = { x0: place.x - reach, y0: place.y - reach, x1: place.x + reach, y1: place.y + reach };
  return { local, bounds, scale };
}

export function drawHand(frame: Frame, pose: HandPose, place: Placement): void {
  const alpha = place.alpha ?? 1;
  if (alpha <= 0.01) return;
  const ink = place.ink ?? INK.accent;
  const fade = place.fade ?? FADE.prop;
  const { local, bounds, scale } = frameOf(place);

  drawShape(
    frame,
    (x, y) => {
      const p = local(x, y);
      return roundBox(p.x, p.y, PALM.c, PALM.hw, PALM.hh, PALM.r) * scale;
    },
    bounds,
    ink,
    alpha,
    fade,
  );

  const order = pose.middleOverIndex ? ORDER_CROSSED : ORDER;
  for (const name of order) {
    const seg = fingerSegment(name, pose[name]);
    drawShape(
      frame,
      (x, y) => {
        const p = local(x, y);
        return capsule(p.x, p.y, seg.a, seg.b, seg.r) * scale;
      },
      bounds,
      ink,
      alpha,
      fade,
    );
  }
}

/**
 * Thumbs-up, drawn as a real one: the fist turned sideways (wider than tall), the
 * four curled fingers stacked as rolls on the side facing the viewer, and the
 * thumb standing straight up from above the knuckles. The palm-forward rig can't
 * make this - its raised thumb read as a pointing index finger.
 */
export function drawThumbsUp(frame: Frame, place: Placement): void {
  const alpha = place.alpha ?? 1;
  if (alpha <= 0.01) return;
  const ink = place.ink ?? INK.accent;
  const fade = place.fade ?? FADE.prop;
  const { local, bounds, scale } = frameOf(place);
  const shape = (sdf: (p: Vec) => number) =>
    drawShape(frame, (x, y) => sdf(local(x, y)) * scale, bounds, ink, alpha, fade);
  // back of the hand / fist body, and the wrist leaving to the right
  shape((p) => roundBox(p.x, p.y, { x: 1.2, y: 2.4 }, 5.6, 5.0, 2.2));
  shape((p) => capsule(p.x, p.y, { x: 5.5, y: 3.4 }, { x: 9.5, y: 3.8 }, 2.6));
  // curled fingers: four rolls, index on top, knuckles toward the viewer's left
  for (let k = 0; k < 4; k += 1) {
    const y = -1.3 + k * 2.25;
    shape((p) => capsule(p.x, p.y, { x: -4.6, y }, { x: 2.2, y }, 1.05));
  }
  // the thumb: up from the top of the fist, above the index knuckle
  shape((p) => capsule(p.x, p.y, { x: 1.4, y: -2.2 }, { x: 0.9, y: -9.2 }, 1.75));
}

// ---- gestures ----------------------------------------------------------------

const CURL: Finger = { ext: 0 };
const STRAIGHT: Finger = { ext: 1 };

export const HANDS = {
  open: { index: { ext: 1, lean: -6 }, middle: STRAIGHT, ring: { ext: 1, lean: 5 }, pinky: { ext: 1, lean: 9 }, thumb: STRAIGHT },
  flat: { index: { ext: 1, lean: 5 }, middle: STRAIGHT, ring: { ext: 1, lean: -4 }, pinky: { ext: 1, lean: -9 }, thumb: { ext: 0.55, lean: 22 } },
  fist: { index: CURL, middle: CURL, ring: CURL, pinky: CURL, thumb: CURL },
  point: { index: STRAIGHT, middle: CURL, ring: CURL, pinky: CURL, thumb: CURL },
  peace: { index: { ext: 1, lean: -13 }, middle: { ext: 1, lean: 12 }, ring: CURL, pinky: CURL, thumb: CURL },
  // counting: three fingers up (countOff's last count)
  three: { index: { ext: 1, lean: -12 }, middle: { ext: 1, lean: 0 }, ring: { ext: 1, lean: 11 }, pinky: CURL, thumb: CURL },
  // the summon sign: index and middle lean into each other and cross, middle in front
  crossed: {
    index: { ext: 1, lean: 27, shift: { x: -0.4, y: 0.6 } },
    middle: { ext: 1, lean: -19, shift: { x: 0.6, y: 0 } },
    ring: CURL,
    pinky: CURL,
    thumb: CURL,
    middleOverIndex: true,
  },
  // fingers bent over an edge, to grab and lift something (the summon visor)
  hook: { index: { ext: 0.5, lean: 8 }, middle: { ext: 0.52, lean: 4 }, ring: { ext: 0.5 }, pinky: { ext: 0.45, lean: -4 }, thumb: { ext: 0.45 } },
  cupped: { index: { ext: 0.75, lean: 6 }, middle: { ext: 0.75, lean: 4 }, ring: { ext: 0.72 }, pinky: { ext: 0.68, lean: -4 }, thumb: { ext: 0.7 } },
  // thumb and index crossed at the tips: the finger heart
  fingerHeart: { index: { ext: 0.62, lean: 38 }, middle: CURL, ring: CURL, pinky: CURL, thumb: { ext: 0.95, lean: 30 } },
} satisfies Record<string, HandPose>;

export type HandName = keyof typeof HANDS;
