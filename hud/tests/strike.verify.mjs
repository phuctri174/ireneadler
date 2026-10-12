// The strike recogniser's TS twin against the trainer (core/scripts/strike_train.py):
// the golden takes are replayed frame by frame through hud/src/tracking/strikeFeatures.ts
// with the model that made them, and every window, probability and fired strike
// must match what Python computed.
import { existsSync, readFileSync } from "node:fs";
import { StrikeWatcher, strikeFrame, strikeProbs, strikeWindow } from "../.verify/strikeFeatures.js";

const GOLDEN = new URL("./strike.golden.json", import.meta.url);
let failures = 0;
const fail = (why) => {
  failures += 1;
  console.log(`FAIL strikes: ${why}`);
};
if (!existsSync(GOLDEN)) {
  console.log("strikes: no golden takes yet (run core/scripts/strike_train.py)");
} else {
  const { model, takes } = JSON.parse(readFileSync(GOLDEN, "utf8"));
  let windows = 0;
  for (const take of takes) {
    const samples = [];
    const checks = new Map(take.checks.map((c) => [c.now, c]));
    const watcher = new StrikeWatcher(model);
    const fired = [];
    for (const f of take.frames) {
      samples.push([f.t, f.body ? strikeFrame(f.body) : null]);
      const want = checks.get(f.t);
      if (want) {
        windows += 1;
        const got = strikeWindow(samples, f.t);
        if (!got || got.some((v, i) => Math.abs(v - want.window[i]) > 1e-9)) fail(`${take.label}: window at ${f.t} differs`);
        const probs = strikeProbs(model, want.window);
        if (probs.some((p, i) => Math.abs(p - want.probs[i]) > 1e-9)) fail(`${take.label}: probabilities at ${f.t} differ`);
      }
      const e = watcher.update(f.body ?? null, f.t);
      if (e) fired.push(e.strike);
    }
    // like the trainer: the answer comes after the strike, so keep watching
    const end = take.frames[take.frames.length - 1].t;
    for (let k = 1; k <= 45; k += 1) {
      const e = watcher.update(null, end + k * 33);
      if (e) fired.push(e.strike);
    }
    if (JSON.stringify(fired) !== JSON.stringify(take.fired)) fail(`${take.label}: fired ${JSON.stringify(fired)}, the trainer ${JSON.stringify(take.fired)}`);
  }
  if (!failures) console.log(`strikes: ok (${takes.length} takes, ${windows} windows match the trainer)`);
}
if (failures) process.exitCode = 1;
