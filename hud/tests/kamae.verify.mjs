// The kamae detector's TypeScript side against the Python that trained it, and the
// watcher that decides a kamae is HELD rather than passed through.
//
// core/scripts/kamae_train.py writes kamae.golden.json: real captured frames with
// the features and score it computed. If the port drifts, the numbers stop
// matching here rather than her suiting up at the wrong moment.
import { readFileSync } from "node:fs";
import { KamaeWatcher, kamaeFeatures, kamaeScore } from "../.verify/kamaeFeatures.js";
import { KAMAE_MODEL } from "../.verify/kamaeModel.js";

let failures = 0;
const check = (ok, label) => {
  if (!ok) {
    failures += 1;
    if (failures <= 10) console.error(`FAIL kamae: ${label}`);
  }
};

const golden = JSON.parse(readFileSync(new URL("./kamae.golden.json", import.meta.url), "utf8"));
check(golden.length >= 10, "the golden file has frames in it");
let worst = 0;
for (const frame of golden) {
  const f = kamaeFeatures(frame.body);
  check(f !== null && f.length === frame.features.length, "features computed");
  if (!f) continue;
  for (let i = 0; i < f.length; i += 1) worst = Math.max(worst, Math.abs(f[i] - frame.features[i]));
  worst = Math.max(worst, Math.abs(kamaeScore(f) - frame.p));
}
check(worst < 1e-6, `TS matches Python (worst difference ${worst})`);

// a golden kamae frame and a golden non-kamae frame to drive the watcher with
const yes = golden.find((g) => g.p > 0.9)?.body;
const no = golden.find((g) => g.p < 0.1)?.body;
check(yes && no, "the golden set has a clear kamae and a clear non-kamae frame");
if (yes && no) {
  const gate = KAMAE_MODEL.gate;
  // held steady at ~10 Hz: fires once, and only after the whole hold time
  const w = new KamaeWatcher();
  const events = [];
  for (let t = 0; t <= 4000; t += 100) {
    const e = w.update(yes, t);
    if (e) events.push([t, e.kind]);
  }
  check(events.length === 1 && events[0][1] === "start" && events[0][0] >= gate.holdMs * 0.9 && events[0][0] <= gate.holdMs + 500, `a steady held kamae fires once, after the hold time (${JSON.stringify(events)})`);
  // he lowers the shinai: "end" once he has been out of it for the release time
  let ended = null;
  for (let t = 4100; t <= 7000; t += 100) {
    const e = w.update(no, t);
    if (e && !ended) ended = [t, e.kind];
  }
  check(ended && ended[1] === "end" && ended[0] - 4100 >= gate.releaseMs - 100, `leaving kamae ends it after the release time (${ended})`);
  // back into kamae at once: not again until the refire time has passed
  let refired = null;
  for (let t = 7100; t <= 7100 + gate.refireMs - 200; t += 100) {
    const e = w.update(yes, t);
    if (e) refired = t;
  }
  check(refired === null || refired - ended[0] >= gate.refireMs, `no refire inside the lockout (${refired})`);
  // a glimpse - kamae for 300 ms in the middle of something else - never fires
  const g = new KamaeWatcher();
  let fired = false;
  for (let t = 0; t <= 4000; t += 100) fired = !!g.update(t >= 1000 && t < 1300 ? yes : no, t) || fired;
  check(!fired, "a glimpse of kamae mid-movement does not fire");
  // hands in the right place but MOVING (a reach, a wave, talking with them):
  // never fires - kamae is held still
  const moved = (dx) => {
    const b = [...yes];
    const width = Math.hypot(b[11 * 4] - b[12 * 4], b[11 * 4 + 1] - b[12 * 4 + 1]);
    for (const i of [13, 14, 15, 16]) b[i * 4] += dx * width;
    return b;
  };
  const m = new KamaeWatcher();
  let movedFired = false;
  for (let t = 0; t <= 5000; t += 100) movedFired = !!m.update(moved(((t / 100) % 2 ? 1 : -1) * 0.8), t) || movedFired;
  check(!movedFired, "hands moving about never fire");
  // nobody in view never fires
  const n = new KamaeWatcher();
  let any = false;
  for (let t = 0; t <= 4000; t += 100) any = !!n.update(null, t) || any;
  check(!any, "no body, no kamae");
}

if (failures > 0) {
  console.error(`kamae: ${failures} failure(s)`);
  process.exit(1);
} else {
  console.log(`kamae: ok (${golden.length} golden frames match Python, worst ${worst.toExponential(1)}; watcher holds steady, releases with hysteresis, ignores glimpses and moving hands)`);
}
