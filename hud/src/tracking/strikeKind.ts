// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Shiai's block, beside the strike event (strikeEvent.ts, untouched): both wrists up,
// HELD - and a dev probe of what the body did. No strike types: every strike of his is
// a men (2026-10-18). No tsuki: depth from one camera is unusable (docs/kendo.md).
//
// BlockDetector both wrists up, HELD: a men strike passes through that pose on its
//               way up, then comes down fast; a block stays. Held holdMs, with
//               dropouts under graceMs tolerated (the zoom hold's pattern, gestures.ts)
//               so one lost frame is not a lowered guard. The strike event's own
//               guards apply: a wrist under minVis is not up, a jump over maxPeak
//               breaks the hold.
// MenSequence   shiai's men: a SEQUENCE, not a spike (his spec, 2026-10-19) -
//               FURIKABURI both wrists rise well above his kamae (the median of the
//               second before), then the CUT - the strike event (strikeEvent.ts, its
//               threshold and guards as they are) - starting within cutAfterRaiseMs
//               of that raised position, then ZANSHIN: both wrists still above that
//               kamae by finishAboveKamae, HELD holdMs
//               (dips under graceMs forgiven - the hold-grace pattern). All within
//               windowMs of the raise; any phase missing, no event. Jitter makes
//               spikes; it can't make a raise, a cut and a hold in order.
// BodyProbe     dev only (scripts/strike_probe.py): a second-by-second summary.

import { face } from "./strikeEvent";
import type { StrikeHit } from "./strikeEvent";

const L_SHOULDER = 11;
const R_SHOULDER = 12;
const L_WRIST = 15;
const R_WRIST = 16;
const SHOULDER_VIS = 0.5;
const GAP_MS = 250;

interface Point {
  width: number;
  x: number;
  y: number;
  z: number;
}

/** The shoulders' width and the wrists' midpoint from the shoulders', or null. */
function point(body: readonly number[] | null): Point | null {
  if (!body || body.length !== 132) return null;
  const at = (i: number) => body.slice(i * 4, i * 4 + 4);
  const [ls, rs, lw, rw] = [at(L_SHOULDER), at(R_SHOULDER), at(L_WRIST), at(R_WRIST)];
  const width = Math.hypot(ls[0] - rs[0], ls[1] - rs[1]);
  if (width < 1e-3 || Math.min(ls[3], rs[3]) < SHOULDER_VIS) return null;
  const mx = (ls[0] + rs[0]) / 2;
  const my = (ls[1] + rs[1]) / 2;
  const mz = (ls[2] + rs[2]) / 2;
  return { width, x: (lw[0] + rw[0]) / 2 - mx, y: (lw[1] + rw[1]) / 2 - my, z: (lw[2] + rw[2]) / 2 - mz };
}


export interface BlockTuning {
  /** Both wrists at least this many shoulder widths ABOVE the shoulders (negative: below). */
  above: number;
  /** Held this long... */
  holdMs: number;
  /** ...with dropouts (a wrist dipping, a lost body) shorter than this tolerated. */
  graceMs: number;
  /** After a block, nothing for this long. */
  refractoryMs: number;
  /** The strike event's own guards (strikeEvent.ts): a wrist the pose model is less
   *  sure of than this is not up... */
  minVis: number;
  /** ...and a wrist moving faster than this (shoulder widths per second) is a landmark
   *  jumping, which breaks the hold. */
  maxPeak: number;
}

export interface BlockHit {
  /** Where the lower wrist was held (shoulder widths below the shoulders; up is -). */
  height: number;
  /** Where it sat in the second before he raised it (his kamae). */
  rest: number;
}

const median = (xs: number[]) => {
  const v = [...xs].sort((a, b) => a - b);
  return v.length ? v[Math.floor(v.length / 2)] : NaN;
};

/** His block: both hands up over his head, held. Fires once per raise. */
export class BlockDetector {
  private since = 0;
  private lostSince = 0;
  private fired = false;
  private restUntil = -Infinity;
  private prev: { t: number; l: number; r: number } | null = null;
  private resting: { t: number; y: number }[] = [];
  private held: number[] = [];
  /** Why it is (or isn't) a block now - for the -Dev readout. */
  diag = "";

  constructor(readonly tuning: BlockTuning) {}

  /** A strike fired: the raise was its furikaburi, never a block. */
  cancel(): void {
    this.since = 0;
    this.lostSince = 0;
    this.held = [];
  }

  update(body: readonly number[] | null, now: number): BlockHit | null {
    const tu = this.tuning;
    let up = false;
    let lower = NaN;
    const p = body ? point(body) : null;
    if (p && body) {
      // each wrist's height from the shoulders' (down is +): the LOWER one must be up
      const my = (body[L_SHOULDER * 4 + 1] + body[R_SHOULDER * 4 + 1]) / 2;
      const l = (body[L_WRIST * 4 + 1] - my) / p.width;
      const r = (body[R_WRIST * 4 + 1] - my) / p.width;
      const sure = Math.min(body[L_WRIST * 4 + 3], body[R_WRIST * 4 + 3]) >= tu.minVis;
      const prev = this.prev;
      this.prev = { t: now, l, r };
      if (prev && now - prev.t <= GAP_MS) {
        const dt = Math.max(1, now - prev.t) / 1000;
        if (Math.max(Math.abs(l - prev.l), Math.abs(r - prev.r)) / dt > tu.maxPeak) {
          // a landmark jumping, not an arm: the hold starts over
          this.cancel();
          this.diag = "jump";
          return null;
        }
      }
      lower = Math.max(l, r);
      up = sure && lower <= -tu.above;
    } else {
      this.prev = null;
    }
    if (up) {
      this.lostSince = 0;
      this.held.push(lower);
      if (this.since === 0) this.since = now;
      if (!this.fired && now - this.since >= tu.holdMs && now >= this.restUntil) {
        this.fired = true;
        this.restUntil = now + tu.refractoryMs;
        this.diag = "BLOCK";
        return { height: median(this.held), rest: median(this.resting.map((r) => r.y)) };
      }
      this.diag = this.fired ? "held" : `holding ${Math.round(now - this.since)}/${tu.holdMs}ms`;
      return null;
    }
    if (Number.isFinite(lower) && this.since === 0) {
      // where his hands sit when not up: the second before a raise is his kamae
      this.resting.push({ t: now, y: lower });
      while (this.resting.length && now - this.resting[0].t > 1000) this.resting.shift();
    }
    if (this.since === 0) {
      this.fired = false;
      this.held = [];
      this.diag = "";
      return null;
    }
    // brief dropouts are tolerated; the hold timer keeps accumulating
    if (this.lostSince === 0) this.lostSince = now;
    const lost = now - this.lostSince;
    if (lost >= tu.graceMs) {
      this.since = 0;
      this.lostSince = 0;
      this.fired = false;
      this.held = [];
      this.diag = `hold reset: down ${Math.round(lost)}ms >= ${tu.graceMs}ms`;
    } else {
      this.diag = `holding (dropout ${Math.round(lost)}/${tu.graceMs}ms tolerated)`;
    }
    return null;
  }
}

export interface MenTuning {
  /** Furikaburi: both wrists at least this far above his kamae (shoulder widths). */
  raiseAboveKamae: number;
  /** Zanshin: both wrists at least this far above his kamae... */
  finishAboveKamae: number;
  /** ...held this long... */
  holdMs: number;
  /** ...a dip under the line shorter than this forgiven. */
  graceMs: number;
  /** His kamae: the median wrist height over this long... */
  kamaeMs: number;
  /** ...ending this long ago (so the raise itself never moves it). */
  kamaeLagMs: number;
  /** The cut (the strike event) within this long of the wrists last being raised. */
  cutAfterRaiseMs: number;
  /** Raise to the end of the zanshin, all within this. */
  windowMs: number;
  /** A wrist the pose model is less sure of than this is not where it says. */
  minVis: number;
}

/** Shiai's men: feed every body (or null) and the strike event's hit for that frame
 *  (or null); a men comes out once its zanshin has held - never from a spike alone.
 *  Heights are against HIS kamae just before, not his shoulders: in bogu the pose
 *  model never sees his wrists reach his shoulders (2026-10-19), and he moves about
 *  in a bout, so the reference is a rolling median, never fixed at the start. */
export class MenSequence {
  private recent: { t: number; y: number }[] = [];
  private raisedAt = -Infinity;
  private kamae = 0;
  private cut: { hit: StrikeHit; raised: number; kamae: number } | null = null;
  private holdSince = 0;
  private lostSince = 0;

  constructor(readonly tuning: MenTuning) {}

  /** Both wrists' height from the shoulders' (down is +), the lower of the two - or null. */
  private height(body: readonly number[] | null): number | null {
    const p = body ? point(body) : null;
    if (!p || !body || Math.min(body[L_WRIST * 4 + 3], body[R_WRIST * 4 + 3]) < this.tuning.minVis) return null;
    const my = (body[L_SHOULDER * 4 + 1] + body[R_SHOULDER * 4 + 1]) / 2;
    return (Math.max(body[L_WRIST * 4 + 1], body[R_WRIST * 4 + 1]) - my) / p.width;
  }

  /** His kamae now: the median height over kamaeMs, ending kamaeLagMs ago - or null. */
  private reference(now: number): number | null {
    const tu = this.tuning;
    const ys = this.recent.filter((r) => now - r.t >= tu.kamaeLagMs).map((r) => r.y);
    return ys.length >= 5 ? median(ys) : null;
  }

  update(body: readonly number[] | null, now: number, hit: StrikeHit | null): StrikeHit | null {
    const tu = this.tuning;
    const y = this.height(body);
    if (y !== null) this.recent.push({ t: now, y });
    while (this.recent.length && now - this.recent[0].t > tu.kamaeMs + tu.kamaeLagMs) this.recent.shift();
    // 1. furikaburi: both wrists well above his kamae of the second before
    if (!this.cut && y !== null) {
      const kamae = now - this.raisedAt > tu.cutAfterRaiseMs ? this.reference(now) : this.kamae;
      if (kamae !== null && y <= kamae - tu.raiseAboveKamae) {
        if (now - this.raisedAt > tu.cutAfterRaiseMs) this.kamae = kamae; // a new raise: its kamae
        this.raisedAt = now;
      }
    }
    // 2. the cut: the strike event, from that raised position - else it is a spike
    if (hit) {
      this.cut = now - this.raisedAt <= tu.cutAfterRaiseMs ? { hit, raised: this.raisedAt, kamae: this.kamae } : null;
      this.holdSince = 0;
      this.lostSince = 0;
    }
    if (!this.cut) return null;
    if (now - this.cut.raised > tu.windowMs) {
      this.cut = null;
      return null;
    }
    // 3. zanshin: held high above that kamae - the hold-grace pattern
    if (y !== null && y <= this.cut.kamae - tu.finishAboveKamae) {
      this.lostSince = 0;
      if (this.holdSince === 0) this.holdSince = now;
      if (now - this.holdSince >= tu.holdMs) {
        const men = { ...this.cut.hit, t: now };
        this.cut = null;
        this.raisedAt = -Infinity;
        return men;
      }
      return null;
    }
    // zanshin follows the cut: hands not high within the grace of its stop - no zanshin
    if (this.holdSince === 0) {
      if (now - this.cut.hit.t > tu.graceMs) this.cut = null;
      return null;
    }
    if (this.lostSince === 0) this.lostSince = now;
    if (now - this.lostSince >= tu.graceMs) {
      // the hands came down: a cut with no zanshin
      this.cut = null;
    }
    return null;
  }
}

/** Dev probe: what the body did, a second at a time - is anything moving, is the body
 *  steady (a second person or a jump would move the tracked shoulders), how sure the
 *  pose model is of the wrists, and the fastest downward and forward wrist speeds the
 *  detectors saw (shoulder widths per second, frame to frame, unsmoothed). */
export class BodyProbe {
  private start = -1;
  private prev: { t: number; y: [number, number]; z: number } | null = null;
  private s = BodyProbe.empty();

  private static empty() {
    return { frames: 0, bodies: 0, mxMin: Infinity, mxMax: -Infinity, myMin: Infinity, myMax: -Infinity, wMin: Infinity, wMax: -Infinity, visMin: Infinity, visSum: 0, downMax: 0, fwdMax: 0, fwdAbsSum: 0, fwdN: 0, faceMin: Infinity, faceMax: -Infinity, faces: 0 };
  }

  update(body: readonly number[] | null, now: number): Record<string, number> | null {
    if (this.start < 0) this.start = now;
    const s = this.s;
    s.frames += 1;
    const p = body ? point(body) : null;
    if (p && body) {
      s.bodies += 1;
      const mx = (body[L_SHOULDER * 4] + body[R_SHOULDER * 4]) / 2;
      const my = (body[L_SHOULDER * 4 + 1] + body[R_SHOULDER * 4 + 1]) / 2;
      s.mxMin = Math.min(s.mxMin, mx);
      s.mxMax = Math.max(s.mxMax, mx);
      s.myMin = Math.min(s.myMin, my);
      s.myMax = Math.max(s.myMax, my);
      s.wMin = Math.min(s.wMin, p.width);
      s.wMax = Math.max(s.wMax, p.width);
      const f = face(body).scale;
      if (f !== null) {
        s.faces += 1;
        s.faceMin = Math.min(s.faceMin, f);
        s.faceMax = Math.max(s.faceMax, f);
      }
      const vis = Math.min(body[L_WRIST * 4 + 3], body[R_WRIST * 4 + 3]);
      s.visMin = Math.min(s.visMin, vis);
      s.visSum += vis;
      const y: [number, number] = [(body[L_WRIST * 4 + 1] - my) / p.width, (body[R_WRIST * 4 + 1] - my) / p.width];
      const z = p.z / p.width;
      if (this.prev && now - this.prev.t <= GAP_MS) {
        const dt = Math.max(1, now - this.prev.t) / 1000;
        s.downMax = Math.max(s.downMax, (y[0] - this.prev.y[0]) / dt, (y[1] - this.prev.y[1]) / dt);
        const fwd = -(z - this.prev.z) / dt;
        s.fwdMax = Math.max(s.fwdMax, fwd);
        s.fwdAbsSum += Math.abs(fwd);
        s.fwdN += 1;
      }
      this.prev = { t: now, y, z };
    } else {
      this.prev = null;
    }
    if (now - this.start < 1000) return null;
    const out = {
      frames: s.frames, bodies: s.bodies,
      shoulderDx: s.bodies ? s.mxMax - s.mxMin : -1, shoulderDy: s.bodies ? s.myMax - s.myMin : -1,
      widthMin: s.bodies ? s.wMin : -1, widthMax: s.bodies ? s.wMax : -1,
      wristVisMin: s.bodies ? s.visMin : -1, wristVisMean: s.bodies ? s.visSum / s.bodies : -1,
      downMax: s.downMax, fwdMax: s.fwdMax, fwdMeanAbs: s.fwdN ? s.fwdAbsSum / s.fwdN : 0,
      faces: s.faces, faceMin: s.faces ? s.faceMin : -1, faceMax: s.faces ? s.faceMax : -1,
    };
    this.s = BodyProbe.empty();
    this.start = now;
    return out;
  }
}
