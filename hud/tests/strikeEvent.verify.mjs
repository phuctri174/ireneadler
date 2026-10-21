// The strike detector (src/tracking/strikeEvent.ts) on made-up bodies: a threshold on
// SIGNED downward wrist speed and a sharp stop, a rest after each strike - and
// shiai's footwork from the shoulders.
import { MoveDetector, StrikeEventDetector } from "../.verify/strikeEvent.js";

let failures = 0;
const fail = (why) => {
  failures += 1;
  console.log(`FAIL strike events: ${why}`);
};

const TUNING = { threshold: 8, stopRatio: 0.35, stopMs: 160, refractoryMs: 400, minVis: 0.4, maxPeak: 60 };
const MOVES = { scaleRatio: 0.08, lateral: 0.5, windowMs: 500, refractoryMs: 800, holdMs: 200, graceMs: 60 };
const FRAME = 33;

/** A body: shoulders `width` apart centred on (mx, 0.5); wrists at y shoulder-widths
 *  below them; a face (ears and nose) scaled `faceScale` (default: with the shoulders). */
function body(left, right, width = 0.2, mx = 0.5, wristVis = 1, faceScale = width, nose = mx) {
  const b = new Array(132).fill(0);
  const set = (i, x, y, v = 1) => b.splice(i * 4, 4, x, y, 0, v);
  set(0, nose, 0.35);
  set(7, nose - faceScale * 0.35, 0.36);
  set(8, nose + faceScale * 0.35, 0.36);
  set(11, mx - width / 2, 0.5);
  set(12, mx + width / 2, 0.5);
  set(15, mx - 0.05, 0.5 + left * width, wristVis);
  set(16, mx + 0.05, 0.5 + right * width, wristVis);
  return b;
}

/** Wrist heights over time: [ms, y] keyframes, linear between, sampled every frame. */
function path(keys, from = 0) {
  const out = [];
  const end = keys[keys.length - 1][0];
  for (let t = 0; t <= end; t += FRAME) {
    let k = 0;
    while (k < keys.length - 2 && keys[k + 1][0] <= t) k += 1;
    const [t0, y0] = keys[k];
    const [t1, y1] = keys[k + 1];
    out.push([from + t, y0 + (y1 - y0) * Math.min(1, (t - t0) / Math.max(1, t1 - t0))]);
  }
  return out;
}

function fires(samples, { both = true, tuning = TUNING } = {}) {
  const d = new StrikeEventDetector(tuning);
  const hits = [];
  for (const [t, y] of samples) {
    const hit = d.update(body(y, both ? y : 0.6), t);
    if (hit) hits.push(hit);
  }
  return hits;
}

// a chisai men: from kamae (0.6) up to -0.6, then down to 0.6 in 100 ms (12/s), a dead stop
const STRIKE = [[0, 0.6], [300, -0.6], [400, 0.6], [900, 0.6]];
{
  const hits = fires(path(STRIKE));
  if (hits.length !== 1) fail(`one strike fired ${hits.length}x`);
  else if (hits[0].peak < 8) fail(`the strike's peak ${hits[0].peak.toFixed(1)} under the threshold it fired at`);
}
// the raise alone, fast, never down: signed - it is not a strike
if (fires(path([[0, 0.6], [130, -0.8], [600, -0.8]])).length) fail("a fast raise fired");
// the return stroke to chudan: down, but slow (0.4 to 0.6 in 300 ms)
if (fires(path([[0, 0.4], [300, 0.6], [700, 0.6]])).length) fail("the slow return to chudan fired");
// an arm sinking to the lap: fast enough, but it slows over half a second - no sharp stop
if (fires(path([[0, -0.6], [120, 0.3], [300, 0.9], [500, 1.2], [700, 1.35], [1000, 1.4]])).length) fail("a sinking arm fired");
// both wrists on the shinai: one swing is one strike
if (fires(path(STRIKE), { both: true }).length !== 1) fail("a two-handed strike fired twice");
// the same strike with the wrist barely seen: the pose model guessing - not a strike
{
  const d = new StrikeEventDetector(TUNING);
  let fired = 0;
  for (const [t, y] of path(STRIKE)) fired += d.update(body(y, y, 0.2, 0.5, 0.3), t) ? 1 : 0;
  if (fired) fail("a strike on a wrist at visibility 0.3 fired");
}
// a landmark jumping ~9 shoulder widths in a frame (~130/s after the two-sample average;
// the live camera reported up to 541): not an arm
if (fires(path([[0, 0.6], [300, -0.6], [333, 8.0], [700, 8.0]])).length) fail("a landmark jump fired");
// one strike is one event: a men whose wrists rebound and come down again inside the
// 400 ms refractory (follow-through) fires exactly once - the refractory is intact
{
  const swing = [[0, 0.6], [300, -0.6], [400, 0.6], [470, -0.1], [530, 0.9], [600, 0.9], [1200, 0.9]];
  const hits = fires(path(swing));
  if (hits.length !== 1) fail(`one strike with a rebound fired ${hits.length}x`);
  // (the rebound alone is strike-fast: without the refractory it would be a second event)
  if (fires(path(swing), { tuning: { ...TUNING, refractoryMs: 0 } }).length !== 2) fail("the rebound test no longer tests the refractory");
}
// three strikes 1.2 s apart: three
{
  const three = [...path(STRIKE), ...path(STRIKE, 1200), ...path(STRIKE, 2400)];
  const hits = fires(three);
  if (hits.length !== 3) fail(`three strikes fired ${hits.length}x`);
}
// over the threshold only once tuned down: the threshold is the knob
if (fires(path(STRIKE), { tuning: { ...TUNING, threshold: 30 } }).length) fail("a threshold over the strike's peak still fired");
// no body for a while mid-swing: nothing fires from the stale half
{
  const d = new StrikeEventDetector(TUNING);
  let fired = 0;
  for (const [t, y] of path(STRIKE)) fired += d.update(t > 330 && t < 700 ? null : body(y, y), t) ? 1 : 0;
  if (fired) fail("a swing with a hole in it fired");
}

function moves(frames) {
  const d = new MoveDetector(MOVES);
  const out = [];
  frames.forEach(([t, width, mx, faceScale, nose]) => {
    const m = d.update(body(0.6, 0.6, width, mx, 1, faceScale ?? width, nose ?? mx), t);
    if (m) out.push(m);
  });
  return out;
}
const still = Array.from({ length: 40 }, (_, i) => [i * FRAME, 0.2 + (i % 2 ? 0.003 : -0.003), 0.5]);
if (moves(still).length) fail("a still body moved");
const step = (fn) => Array.from({ length: 40 }, (_, i) => [i * FRAME, ...fn(Math.min(1, Math.max(0, (i * FRAME - 300) / 300)))]);
const adv = moves(step((k) => [0.2 * (1 + 0.15 * k), 0.5]));
if (adv[0] !== "advance" || adv.length !== 1) fail(`an advance read as ${adv.join(",") || "nothing"}`);
const ret = moves(step((k) => [0.2 / (1 + 0.15 * k), 0.5]));
if (ret[0] !== "retreat" || ret.length !== 1) fail(`a retreat read as ${ret.join(",") || "nothing"}`);
const side = moves(step((k) => [0.2, 0.5 + 0.15 * k]));
if (side[0] !== "side" || side.length !== 1) fail(`a side step read as ${side.join(",") || "nothing"}`);
// kamae's jitter (measured: ~7% within a second, hands over the shoulders): a width
// that flicks 12% wider for 100 ms and back is not a step - it must hold (holdMs)
{
  const flick = Array.from({ length: 60 }, (_, i) => [i * FRAME, 0.2 * (i >= 20 && i < 23 ? 1.12 : 1), 0.5]);
  if (moves(flick).length) fail(`a 100 ms width flicker read as ${moves(flick).join(",")}`);
  // and jitter that keeps crossing and falling back: nothing
  const jitter = Array.from({ length: 90 }, (_, i) => [i * FRAME, 0.2 * (1 + 0.1 * Math.sin(i * 1.7)), 0.5]);
  if (moves(jitter).length) fail(`width jitter read as ${moves(jitter).join(",")}`);
}
// the gate (2026-10-18): his shoulders narrowing 12% and STAYING, his face the same size
// - hands over his shoulders, not a step back. Nor does a shoulder-only drift sideways
{
  const narrowed = step((k) => [0.2 / (1 + 0.12 * k), 0.5, 0.2, 0.5]);
  if (moves(narrowed).length) fail(`shoulders narrowing with the face unchanged read as ${moves(narrowed).join(",")}`);
  const drift = step((k) => [0.2, 0.5 + 0.15 * k, 0.2, 0.5]);
  if (moves(drift).length) fail(`the shoulders' midpoint moving with the nose still read as ${moves(drift).join(",")}`);
}

console.log(failures ? `strike events: ${failures} failed` : "strike events: ok");
if (failures) process.exitCode = 1;
