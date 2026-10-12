// Men, kote, gyaku-dou - from his upper body, during keiko.
//
// The TS twin of core/irene/strikes.py (read its header for the why); it must stay in
// step - hud/tests/strike.verify.mjs replays the trainer's golden takes through this
// and compares every window, every probability and every strike fired.
//
// A strike is a movement, so the classifier reads the last WINDOW_MS of the body,
// resampled at STEPS moments; and it is an event, so it is judged once per peak of
// the hands' speed, AFTER_MS after it - then held for the trainer's settleMs in case
// a faster peak follows (the raise before a strike is itself fast). Every number in
// the gate comes from core/scripts/strike_train.py, fitted on his captures.

export const STRIKE_CLASSES = ["men", "kote", "gyaku_dou", "none"] as const;
export type Strike = (typeof STRIKE_CLASSES)[number];

export interface StrikeModel {
  mean: number[];
  scale: number[];
  weights: number[][];
  bias: number[];
  gate: { threshold: Record<string, number>; restMs: number; speedMin: number; settleMs: number; clean: number };
  features?: number;
  classes?: string[];
  _about?: string;
}

const L_SHOULDER = 11;
const R_SHOULDER = 12;
const L_ELBOW = 13;
const R_ELBOW = 14;
const L_WRIST = 15;
const R_WRIST = 16;

export const WINDOW_MS = 900;
export const STEPS = 9;
const TRACKED = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 13];
const WRIST_VIS = 11;
export const AFTER_MS = 250;

/** One body (flat [x, y, z, visibility] x 33) -> 15 numbers, or null without shoulders. */
export function strikeFrame(body: readonly number[]): number[] | null {
  if (body.length !== 132) return null;
  const at = (i: number) => ({ x: body[i * 4], y: body[i * 4 + 1], z: body[i * 4 + 2], v: body[i * 4 + 3] });
  const ls = at(L_SHOULDER);
  const rs = at(R_SHOULDER);
  const width = Math.hypot(ls.x - rs.x, ls.y - rs.y);
  if (width < 1e-3 || Math.min(ls.v, rs.v) < 0.5) return null;
  const mx = (ls.x + rs.x) / 2;
  const my = (ls.y + rs.y) / 2;
  const mz = (ls.z + rs.z) / 2;
  const rel = (i: number): [number, number] => [(at(i).x - mx) / width, (at(i).y - my) / width];
  const depth = (i: number): number => (at(i).z - mz) / width;
  const lw = rel(L_WRIST);
  const rw = rel(R_WRIST);
  const le = rel(L_ELBOW);
  const re = rel(R_ELBOW);
  return [
    lw[0], lw[1], rw[0], rw[1],
    le[0], le[1], re[0], re[1],
    Math.hypot(lw[0] - rw[0], lw[1] - rw[1]), (lw[0] + rw[0]) / 2, (lw[1] + rw[1]) / 2,
    Math.min(at(L_WRIST).v, at(R_WRIST).v), Math.min(at(L_ELBOW).v, at(R_ELBOW).v),
    (depth(L_WRIST) + depth(R_WRIST)) / 2, (depth(L_ELBOW) + depth(R_ELBOW)) / 2,
  ];
}

export type Sample = [number, number[] | null];

/** The window's features at `now` from (ms, strikeFrame()) samples, oldest first; null if not covered. */
export function strikeWindow(samples: readonly Sample[], now: number): number[] | null {
  const start = now - WINDOW_MS;
  const valid = samples.filter((s): s is [number, number[]] => s[1] !== null && start - 200 <= s[0] && s[0] <= now);
  if (valid.length < 4 || valid[0][0] > start + WINDOW_MS * 0.25) return null;
  const picked: number[][] = [];
  let j = 0;
  for (let k = 0; k < STEPS; k += 1) {
    const moment = start + (WINDOW_MS * k) / (STEPS - 1);
    while (j + 1 < valid.length && valid[j + 1][0] <= moment) j += 1;
    picked.push(valid[j][1]);
  }
  const out: number[] = [];
  for (const i of TRACKED) {
    const series = picked.map((p) => p[i]);
    const lo = Math.min(...series);
    const hi = Math.max(...series);
    out.push(series[0], series[STEPS - 1], lo, hi, series.indexOf(lo) / (STEPS - 1), series.indexOf(hi) / (STEPS - 1));
  }
  const speeds: number[] = [];
  for (let k = 0; k < STEPS - 1; k += 1) speeds.push(Math.hypot(picked[k + 1][9] - picked[k][9], picked[k + 1][10] - picked[k][10]));
  const peak = Math.max(...speeds);
  out.push(peak, speeds.indexOf(peak) / (STEPS - 2), picked.reduce((a, p) => a + p[WRIST_VIS], 0) / STEPS);
  return out;
}

/** Softmax over STRIKE_CLASSES. */
export function strikeProbs(model: StrikeModel, v: readonly number[]): number[] {
  const x = v.map((a, i) => (a - model.mean[i]) / model.scale[i]);
  const z = model.weights.map((row, c) => model.bias[c] + row.reduce((acc, w, i) => acc + w * x[i], 0));
  const top = Math.max(...z);
  const e = z.map((q) => Math.exp(q - top));
  const total = e.reduce((a, b) => a + b, 0);
  return e.map((q) => q / total);
}

/** Shoulder-widths per second between two bodies' hand midpoints. */
export function handSpeed(prev: [number, number[]], cur: [number, number[]]): number {
  const dt = Math.max(1, cur[0] - prev[0]);
  return (Math.hypot(cur[1][9] - prev[1][9], cur[1][10] - prev[1][10]) * 1000) / dt;
}

export interface StrikeEvent {
  strike: Exclude<Strike, "none">;
  p: number;
  /** As good as his good strikes in training: ippon-worthy. */
  clean: boolean;
}

/** When a strike happened. Feed it each body (or null) with its time in ms. */
export class StrikeWatcher {
  private samples: Sample[] = [];
  private speeds: number[] = [];
  private peak: [number, number] | null = null;
  private pending: [number, number, number[]] | null = null;
  private restUntil = -Infinity;
  last: number[] = [0, 0, 0, 0];

  constructor(private readonly model: StrikeModel) {}

  update(body: readonly number[] | null, now: number): StrikeEvent | null {
    const gate = this.model.gate;
    const f = body ? strikeFrame(body) : null;
    let prev: [number, number[]] | null = null;
    for (let k = this.samples.length - 1; k >= 0; k -= 1) {
      const s = this.samples[k];
      if (s[1] !== null) {
        prev = [s[0], s[1]];
        break;
      }
    }
    this.samples.push([now, f]);
    while (this.samples.length && now - this.samples[0][0] > WINDOW_MS + 400) this.samples.shift();
    if (f !== null && prev !== null) {
      this.speeds.push(handSpeed(prev, [now, f]));
      if (this.speeds.length > 3) this.speeds.splice(0, this.speeds.length - 3);
      const speed = this.speeds.reduce((a, b) => a + b, 0) / this.speeds.length;
      if (this.peak === null || speed > this.peak[1]) this.peak = [now, speed];
      if (this.pending !== null && speed > this.pending[1]) this.pending = null;
    }
    if (this.peak !== null && now - this.peak[0] >= AFTER_MS) {
      const peak = this.peak;
      this.peak = null;
      if (peak[1] >= gate.speedMin) {
        const v = strikeWindow(this.samples, now);
        if (v !== null) this.pending = [peak[0], peak[1], strikeProbs(this.model, v)];
      }
    }
    if (this.pending === null || now - this.pending[0] < AFTER_MS + gate.settleMs) return null;
    const p = this.pending[2];
    this.pending = null;
    this.last = p;
    if (now < this.restUntil) return null;
    let k = 0;
    for (let i = 1; i < p.length; i += 1) if (p[i] > p[k]) k = i;
    const name = STRIKE_CLASSES[k];
    if (name === "none" || p[k] < gate.threshold[name]) return null;
    this.restUntil = now + gate.restMs;
    return { strike: name, p: p[k], clean: p[k] >= gate.clean };
  }
}
