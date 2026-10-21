// Shiai's block (src/tracking/strikeKind.ts) on made-up bodies: held up = a block, a
// strike's raise is not, and the strike event's own guards apply to it.
import { BlockDetector, MenSequence } from "../.verify/strikeKind.js";
import { StrikeEventDetector } from "../.verify/strikeEvent.js";

let failures = 0;
const fail = (why) => {
  failures += 1;
  console.log(`FAIL block: ${why}`);
};

// the block: both wrists `y` shoulder widths from the shoulders (up is -)
const BLOCK = { above: 0.15, holdMs: 250, graceMs: 120, refractoryMs: 1000, minVis: 0.4, maxPeak: 60 };
function guard(y, yRight = y, vis = 1) {
  const b = new Array(132).fill(0);
  const set = (i, x, yy, v = 1) => b.splice(i * 4, 4, x, yy, 0, v);
  set(11, 0.4, 0.5);
  set(12, 0.6, 0.5);
  set(15, 0.48, 0.5 + y * 0.2, vis);
  set(16, 0.52, 0.5 + yRight * 0.2, vis);
  return b;
}
function blocks(ys, vis = 1) {
  const d = new BlockDetector(BLOCK);
  const hits = [];
  ys.forEach(([y, yr], k) => {
    const hit = d.update(y === null ? null : guard(y, yr ?? y, vis), k * 33);
    if (hit) hits.push(hit);
  });
  return hits;
}
const hold = (y, ms) => Array.from({ length: Math.ceil(ms / 33) }, () => [y]);
{
  const got = blocks([...hold(1.5, 300), ...hold(-1.2, 600)]);
  if (got.length !== 1) fail("hands held up over the head is one block");
  else if (Math.abs(got[0].height + 1.2) > 1e-9 || Math.abs(got[0].rest - 1.5) > 1e-9) fail(`the block's height ${got[0].height} / rest ${got[0].rest}, want -1.2 / 1.5`);
}
// the strike event's guards: a wrist the pose model is unsure of is not up...
if (blocks([...hold(1.5, 300), ...hold(-1.2, 600)], 0.3).length !== 0) fail("a block from wrists under minVis");
// ...and a landmark jump (1.5 to -1.2 in one frame is 82 sw/s, over maxPeak) is not a raise
if (blocks([...hold(1.5, 300), [-1.2], [1.5], ...hold(1.5, 100)]).length !== 0) fail("a one-frame jump made a block");
// a men's furikaburi: up for ~150 ms, then down fast - not a block
if (blocks([...hold(1.5, 300), ...hold(-1.5, 150), ...hold(1.4, 400)]).length !== 0) fail("a strike's raise counted as a block");
// one hand up is not a guard
if (blocks([...hold(1.5, 300), ...Array.from({ length: 20 }, () => [-1.2, 1.4])]).length !== 0) fail("one hand up counted as a block");
// a dropped frame inside the hold is forgiven (the grace)
if (blocks([...hold(-1.2, 165), [null], ...hold(-1.2, 200)]).length !== 1) fail("one lost body broke the hold");
// held through a long dip: starts over, and needs the full hold again
if (blocks([...hold(-1.2, 165), ...hold(1.4, 200), ...hold(-1.2, 165)]).length !== 0) fail("a dip past the grace kept the hold");

// shiai's men, as a sequence: the strike event (its own tuning) feeding MenSequence -
// raise, cut, zanshin, or nothing
const STRIKE = { threshold: 8, stopRatio: 0.35, stopMs: 160, refractoryMs: 400, minVis: 0.4, maxPeak: 60 };
const MEN = { raiseAboveKamae: 1.8, finishAboveKamae: 1.1, holdMs: 400, graceMs: 120, kamaeMs: 1000, kamaeLagMs: 300,
  cutAfterRaiseMs: 700, windowMs: 2000, minVis: 0.4 };
/** Both wrists' height (shoulder widths, up is -) through keyframes [ms, y], every frame. */
function moves(keys) {
  const out = [];
  const end = keys[keys.length - 1][0];
  for (let t = 0; t <= end; t += 33) {
    let k = 0;
    while (k < keys.length - 2 && keys[k + 1][0] <= t) k += 1;
    const [t0, y0] = keys[k];
    const [t1, y1] = keys[k + 1];
    out.push([t, y0 + (y1 - y0) * Math.min(1, (t - t0) / Math.max(1, t1 - t0))]);
  }
  return out;
}
function men(keys) {
  const strikes = new StrikeEventDetector(STRIKE);
  const seq = new MenSequence(MEN);
  let n = 0;
  for (const [t, y] of moves(keys)) {
    const b = guard(y);
    if (seq.update(b, t, strikes.update(b, t))) n += 1;
  }
  return n;
}
// a proper men: kamae (wrists 1.5 below the shoulders), furikaburi, the cut, zanshin held
// above the kamae (here at -0.2: 1.7 above it)
const RAISE = [[0, 1.5], [1200, 1.5], [1600, -1.5]];
const MEN_OK = [...RAISE, [1700, -0.2], [2500, -0.2], [3300, 1.5], [3900, 1.5]];
if (men(MEN_OK) !== 1) fail(`a proper men with zanshin scored ${men(MEN_OK)}`);
// the same, twice, 3 s apart: two
const twice = [...MEN_OK, ...MEN_OK.map(([t, y]) => [t + 4000, y])];
if (men(twice) !== 2) fail(`two men scored ${men(twice)}`);
// the cut with no zanshin: straight down to kamae
const NO_ZANSHIN = [...RAISE, [1700, 1.5], [3900, 1.5]];
if (men(NO_ZANSHIN) !== 0) fail(`a cut with no zanshin scored ${men(NO_ZANSHIN)}`);
// the cut held only 200 ms, then dropped: no zanshin either
const SHORT = [...RAISE, [1700, -0.2], [1900, -0.2], [2000, 1.5], [3900, 1.5]];
if (men(SHORT) !== 0) fail(`a 200 ms zanshin scored ${men(SHORT)}`);
// a spike alone - jitter in kamae, fast enough to be a strike event
const SPIKE = [[0, 1.5], [1200, 1.5], [1300, 0.4], [1370, 1.6], [3000, 1.6]];
if (men(SPIKE) !== 0) fail(`a spike in kamae scored ${men(SPIKE)}`);
// the worst jitter the readout saw: a 'raise' of 1.49 above kamae, its 'cut' ending 0.69 above, held
const JITTER = [[0, 2.4], [1500, 2.4], [1600, 0.9], [1650, 1.7], [3500, 1.7]];
if (men(JITTER) !== 0) fail(`the readout's worst jitter scored ${men(JITTER)}`);
// the same men from a lower kamae (he stepped about, his wrists sit 2.0 below): still one -
// the reference is his kamae of the second before, not a fixed line
// (his real men in bogu, 2026-10-19: rose 2.34 above kamae, the cut ended 1.62 above)
const LOW = [[0, 2.0], [1200, 2.0], [1600, -0.4], [1650, 0.4], [2500, 0.4], [3300, 2.0], [3900, 2.0]];
if (men(LOW) !== 1) fail(`a men from a low kamae scored ${men(LOW)}`);
// his kamae drifting (an advance, a retreat) then a men: the reference follows it
const DRIFT = [[0, 1.0], [1500, 2.2], [2700, 2.2], [3100, -0.2], [3150, 0.6], [4000, 0.6], [4800, 2.2], [5400, 2.2]];
if (men(DRIFT) !== 1) fail(`a men after the kamae drifted scored ${men(DRIFT)}`);
// waving the shinai around: up and down, fast, for 3 s
const WAVE = [[0, 1.5], [1100, 1.5], ...Array.from({ length: 11 }, (_, i) => [1200 + i * 300, i % 2 ? -1.0 : 1.5])];
if (men(WAVE) !== 0) fail(`waving the shinai scored ${men(WAVE)}`);
// a raise held, with no cut
const NO_CUT = [...RAISE, [2900, -1.5], [3500, 1.5], [3900, 1.5]];
if (men(NO_CUT) !== 0) fail(`a raise with no cut scored ${men(NO_CUT)}`);
// the cut ends low, then the hands go back up and hold: that is not zanshin
const UP_AGAIN = [[0, 1.5], [1200, 1.5], [1500, -1.5], [1700, 1.4], [2600, 1.4], [2700, -0.2], [3600, -0.2], [3900, 1.5]];
if (men(UP_AGAIN) !== 0) fail(`hands raised again after a low cut scored ${men(UP_AGAIN)}`);
// a cut a long time after the raise (the hands drifting down first): not from the raised position
const LATE = [[0, 1.5], [1200, 1.5], [1500, -1.5], [1600, -1.5], [2500, -0.3], [2600, -0.3], [2700, 1.5], [3900, 1.5]];
if (men(LATE) !== 0) fail(`a late cut scored ${men(LATE)}`);

console.log("block: the pose, its hold and its guards checked; men: raise, cut, zanshin - or nothing");
if (failures) process.exitCode = 1;
