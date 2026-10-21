// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// That he struck at her - from his upper body - and, in shiai, how he moved.
//
// A tuned threshold, not a learned classifier (docs/gestures.md says why): he is in
// a mode, holding a shinai, to hit her, and a false positive is a funny noise.
//
// A strike: one wrist's SIGNED downward speed (shoulder-widths per second, measured
// from the shoulders' midpoint, so leaning or stepping doesn't count) peaks over
// `threshold`, and then the swing stops sharply - the speed falls to `stopRatio` of
// that peak within `stopMs`. Signed, so the raise and anything moving up never
// count; the stop, so an arm sinking to the lap doesn't either. A swing whose wrist
// the pose model was unsure of at its peak (visibility under `minVis`), or faster
// than any arm (over `maxPeak`), is a landmark jumping, not a strike: live, the camera
// reported 541 while his fastest recorded strike is 35. After an event both
// wrists rest for `refractoryMs`: one two-handed swing is one strike. The numbers
// come from core (config/strike_event.json and his 3-swing calibration).
//
// Shiai also reads his feet, from the shoulders: their width growing or shrinking
// over `windowMs` is him advancing or retreating, their midpoint moving sideways is
// a step to the side - and the new width (or place) must HOLD past the threshold for
// `holdMs`, dips under `graceMs` forgiven: the hold-grace pattern (docs/gestures.md).
// In kamae his hands cover his shoulders and their width jitters ~7% within a second
// (measured 2026-10-18): a flicker past 8% is not a step. And it can change for a
// second or longer with him not moving at all (the gate, 2026-10-18: -8% held, and a
// -15% dip for a second, his shoulders' midpoint still) - so a step must show in his
// FACE too, which his hands never cover: its scale (ear to ear, else eye to eye) has to
// change the same way by at least half as much, and for a side step his nose has to
// move the same way by at least half as far. A real step moves all of him.

const L_SHOULDER = 11;
const R_SHOULDER = 12;
const WRISTS = [
  ["left", 15],
  ["right", 16],
] as const;
const SHOULDER_VIS = 0.5;
/** A gap in the body longer than this and a wrist starts over. */
export const GAP_MS = 250;

export interface StrikeTuning {
  /** Peak downward wrist speed for a strike, shoulder-widths per second. */
  threshold: number;
  /** The swing has stopped once the speed is down to this share of its peak... */
  stopRatio: number;
  /** ...within this long of the peak. */
  stopMs: number;
  /** After a strike, nothing for this long. */
  refractoryMs: number;
  /** The wrist's visibility at the peak at least this - lower is the pose model guessing. */
  minVis: number;
  /** A peak over this is a landmark jumping, not an arm. */
  maxPeak: number;
}

export interface StrikeHit {
  t: number;
  wrist: "left" | "right";
  /** Its peak downward speed, shoulder-widths per second - what he tunes against. */
  peak: number;
  /** Peak to stop, ms. */
  stopMs: number;
}

interface Shoulders {
  width: number;
  mx: number;
  my: number;
}

const NOSE = 0;
const FACE_PAIRS = [
  [7, 8], // ear to ear
  [3, 6], // eye to eye (outer corners)
] as const;
const FACE_VIS = 0.5;

/** His face's scale (the first pair the pose model is sure of) and his nose's x, or nulls. */
export function face(body: readonly number[] | null): { scale: number | null; nose: number | null } {
  if (!body || body.length !== 132) return { scale: null, nose: null };
  let scale: number | null = null;
  for (const [a, b] of FACE_PAIRS) {
    if (Math.min(body[a * 4 + 3], body[b * 4 + 3]) >= FACE_VIS) {
      scale = Math.hypot(body[a * 4] - body[b * 4], body[a * 4 + 1] - body[b * 4 + 1]);
      break;
    }
  }
  return { scale, nose: body[NOSE * 4 + 3] >= FACE_VIS ? body[NOSE * 4] : null };
}

function shoulders(body: readonly number[] | null): Shoulders | null {
  if (!body || body.length !== 132) return null;
  const ls = body.slice(L_SHOULDER * 4, L_SHOULDER * 4 + 4);
  const rs = body.slice(R_SHOULDER * 4, R_SHOULDER * 4 + 4);
  const width = Math.hypot(ls[0] - rs[0], ls[1] - rs[1]);
  if (width < 1e-3 || Math.min(ls[3], rs[3]) < SHOULDER_VIS) return null;
  return { width, mx: (ls[0] + rs[0]) / 2, my: (ls[1] + rs[1]) / 2 };
}

/** A wrist's height below the shoulders, in shoulder widths (down is +), and its visibility. */
function wristY(body: readonly number[], s: Shoulders, i: number): { y: number; vis: number } {
  return { y: (body[i * 4 + 1] - s.my) / s.width, vis: body[i * 4 + 3] };
}

class WristSpeed {
  private prev: { t: number; y: number } | null = null;
  private speeds: number[] = [];
  private peak = 0;
  private peakAt = -1;
  private peakVis = 1;

  constructor(readonly name: "left" | "right") {}

  reset(): void {
    this.prev = null;
    this.speeds = [];
    this.peakAt = -1;
  }

  update(w: { y: number; vis: number } | null, now: number, tuning: StrikeTuning): StrikeHit | null {
    if (w === null || (this.prev && now - this.prev.t > GAP_MS)) {
      this.reset();
      if (w === null) return null;
    }
    const y = w.y;
    const prev = this.prev;
    this.prev = { t: now, y };
    if (!prev) return null;
    // two samples averaged: one noisy frame is not a swing
    this.speeds.push(((y - prev.y) * 1000) / Math.max(1, now - prev.t));
    if (this.speeds.length > 2) this.speeds.shift();
    const speed = this.speeds.reduce((a, b) => a + b, 0) / this.speeds.length;
    if (this.peakAt < 0) {
      if (speed >= tuning.threshold) {
        this.peak = speed;
        this.peakAt = now;
        this.peakVis = w.vis;
      }
      return null;
    }
    if (speed > this.peak) {
      this.peak = speed;
      this.peakAt = now;
      this.peakVis = w.vis;
      return null;
    }
    const since = now - this.peakAt;
    if (speed <= tuning.stopRatio * this.peak) {
      this.peakAt = -1;
      const real = this.peakVis >= tuning.minVis && this.peak <= tuning.maxPeak;
      return since <= tuning.stopMs && real ? { t: now, wrist: this.name, peak: this.peak, stopMs: since } : null;
    }
    // still coming down slowly long after the peak: sinking, not a strike
    if (since > tuning.stopMs) this.peakAt = -1;
    return null;
  }
}

/** Strikes from his upper body: feed every body (or null) with its time in ms. */
export class StrikeEventDetector {
  private readonly wrists = WRISTS.map(([name]) => new WristSpeed(name));
  private restUntil = -Infinity;
  count = 0;

  constructor(readonly tuning: StrikeTuning) {}

  update(body: readonly number[] | null, now: number): StrikeHit | null {
    const s = shoulders(body);
    let hit: StrikeHit | null = null;
    WRISTS.forEach(([, i], k) => {
      const got = this.wrists[k].update(s && body ? wristY(body, s, i) : null, now, this.tuning);
      if (got && !hit && now >= this.restUntil) hit = got;
    });
    if (hit) {
      this.restUntil = now + this.tuning.refractoryMs;
      this.count += 1;
    }
    return hit;
  }
}

export interface MoveTuning {
  /** Shoulder width up (or down) by this share over windowMs: an advance (a retreat). */
  scaleRatio: number;
  /** The shoulders' midpoint moved this many shoulder widths sideways over windowMs. */
  lateral: number;
  windowMs: number;
  /** After a move, nothing for this long. */
  refractoryMs: number;
  /** The move holds past its threshold this long before it counts... */
  holdMs?: number;
  /** ...a dip back under it shorter than this forgiven. */
  graceMs?: number;
}

export type Move = "advance" | "retreat" | "side";

/** His footwork, from his shoulders: advance, retreat, a step to the side. */
type Place = { width: number; mx: number; face: number | null; nose: number | null };

export class MoveDetector {
  private history: ({ t: number } & Place)[] = [];
  private restUntil = -Infinity;
  // a move seen, waiting to hold: against the place he moved from
  private pending: { move: Move; base: Place; since: number; lostSince: number } | null = null;

  constructor(readonly tuning: MoveTuning) {}

  /** Is `move` still past its threshold from `base`, on the last three frames - his
   *  shoulders, and his face agreeing (when the pose model can see it)? */
  private past(move: Move, base: Place): boolean {
    const recent = this.history.slice(-3);
    const mean = (xs: (number | null)[]) => {
      const v = xs.filter((x): x is number => x !== null);
      return v.length === xs.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
    };
    const width = mean(recent.map((h) => h.width)) as number;
    const mx = mean(recent.map((h) => h.mx)) as number;
    const faceNow = mean(recent.map((h) => h.face));
    const noseNow = mean(recent.map((h) => h.nose));
    const r = this.tuning.scaleRatio;
    const faced = faceNow !== null && base.face !== null;
    if (move === "advance") return width >= base.width * (1 + r) && (!faced || faceNow >= (base.face as number) * (1 + r / 2));
    if (move === "retreat") return width * (1 + r) <= base.width && (!faced || faceNow * (1 + r / 2) <= (base.face as number));
    const shift = (mx - base.mx) / width;
    if (Math.abs(shift) < this.tuning.lateral) return false;
    if (noseNow === null || base.nose === null) return true;
    const nose = (noseNow - base.nose) / width;
    return Math.sign(nose) === Math.sign(shift) && Math.abs(nose) >= this.tuning.lateral / 2;
  }

  update(body: readonly number[] | null, now: number): Move | null {
    const s = shoulders(body);
    if (!s) {
      this.history = [];
      this.pending = null;
      return null;
    }
    const f = face(body);
    this.history.push({ t: now, width: s.width, mx: s.mx, face: f.scale, nose: f.nose });
    while (this.history.length && now - this.history[0].t > this.tuning.windowMs + 400) this.history.shift();
    if (now < this.restUntil) return null;
    const holdMs = this.tuning.holdMs ?? 200;
    const graceMs = this.tuning.graceMs ?? 60;
    const pending = this.pending;
    if (pending) {
      if (this.past(pending.move, pending.base)) {
        pending.lostSince = 0;
        if (now - pending.since >= holdMs) {
          this.pending = null;
          this.restUntil = now + this.tuning.refractoryMs;
          this.history = [];
          return pending.move;
        }
        return null;
      }
      // brief dips are forgiven; a flicker that falls back is not a step
      if (pending.lostSince === 0) pending.lostSince = now;
      if (now - pending.lostSince >= graceMs) this.pending = null;
      return null;
    }
    const then = this.history.find((h) => now - h.t <= this.tuning.windowMs + 34);
    if (!then || now - then.t < this.tuning.windowMs * 0.6) return null;
    // the last three frames against where he was: the median of the window's first
    // half, so neither one jumpy frame nor a flicker becomes the place he moved from
    const before = this.history.filter((h) => h.t >= then.t && now - h.t >= this.tuning.windowMs / 2);
    const mid = (xs: number[]) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)];
    const known = (xs: (number | null)[]) => (xs.every((x) => x !== null) ? mid(xs as number[]) : null);
    const base = { width: mid(before.map((h) => h.width)), mx: mid(before.map((h) => h.mx)), face: known(before.map((h) => h.face)), nose: known(before.map((h) => h.nose)) };
    const move = (["advance", "retreat", "side"] as const).find((m) => this.past(m, base)) ?? null;
    if (move) this.pending = { move, base, since: now, lostSince: 0 };
    return null;
  }
}
