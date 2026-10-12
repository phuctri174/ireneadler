// The zoom classifier's TypeScript side against the Python that trained it.
//
// core/scripts/zoom_train.py writes zoom.golden.json: whole takes from the real
// captures, with the 24 features and the forest's raw score it computed for every
// frame. If the port drifts - a feature in the wrong slot, a window off by one, a
// population vs sample standard deviation - the numbers stop matching here rather
// than the zoom quietly misbehaving on the matrix.
import { readFileSync } from "node:fs";
import { ZoomHistory, zoomFeatures, zoomScore, ZOOM_FEATURE_COUNT } from "../.verify/zoomFeatures.js";
import { GestureEngine, ZOOM_HOLD_MS } from "../.verify/gestures.js";

let failures = 0;
const check = (ok, label) => {
  if (!ok) {
    failures += 1;
    if (failures <= 10) console.error(`FAIL zoom: ${label}`);
  }
};

const golden = JSON.parse(readFileSync(new URL("./zoom.golden.json", import.meta.url), "utf8"));
check(golden.length > 0, "the golden file has takes in it");

const EPS = 2e-5;
let frames = 0;
let worstFeature = 0;
let worstScore = 0;

for (const take of golden) {
  // one history per take, exactly as the Python builds it: every frame goes in,
  // hand or no hand, so the window holds the same samples on both sides
  const history = new ZoomHistory();
  for (const frame of take.frames) {
    const f = frame.in;
    const wrist = Array.isArray(f.lm) && f.lm.length === 63 ? { x: f.lm[0], y: f.lm[1] } : { x: 0, y: 0 };
    history.push({ handX: wrist.x, handY: wrist.y, spread: f.spread ?? 0, timestamp: f.ts ?? 0 });
    const landmarks =
      Array.isArray(f.lm) && f.lm.length === 63
        ? Array.from({ length: 21 }, (_, i) => ({ x: f.lm[i * 3], y: f.lm[i * 3 + 1], z: f.lm[i * 3 + 2] }))
        : null;
    const got = zoomFeatures(
      {
        thumb: f.thumb ?? 0,
        index: f.index ?? 0,
        middle: f.middle ?? 0,
        ring: f.ring ?? 0,
        pinky: f.pinky ?? 0,
        spread: f.spread ?? 0,
        ratio: f.ratio ?? 0,
        tipGapPalm: f.tipGapPalm ?? 0,
        knuckleGapPalm: f.knuckleGapPalm ?? 0,
        palmSpan: f.palmSpan ?? 0,
        landmarks,
      },
      history,
    );
    check(got.length === ZOOM_FEATURE_COUNT, `${take.take}: ${got.length} features, expected ${ZOOM_FEATURE_COUNT}`);
    for (let i = 0; i < frame.features.length; i += 1) {
      const drift = Math.abs(got[i] - frame.features[i]);
      worstFeature = Math.max(worstFeature, drift);
      check(drift < EPS, `${take.take} frame ${frames}: feature ${i} is ${got[i]}, Python had ${frame.features[i]}`);
    }
    // the forest itself, on exactly the input Python scored: this must be exact
    const raw = zoomScore(frame.features);
    worstScore = Math.max(worstScore, Math.abs(raw - frame.raw));
    check(Math.abs(raw - frame.raw) < 1e-4, `${take.take}: score ${raw}, Python had ${frame.raw}`);
    // and the decision this port reaches on its own features, which is what ships
    check(zoomScore(got) >= 0 === frame.raw >= 0, `${take.take} frame ${frames}: decision disagrees with Python`);
    frames += 1;
  }
}

// the window must actually forget: a long still stretch cannot be swayed by
// something that happened a second earlier
const stale = new ZoomHistory();
for (let i = 0; i < 40; i += 1) stale.push({ handX: i < 5 ? i * 30 : 100, handY: 0, spread: 0.5, timestamp: i * 33 });
check(stale.motion()[0] === 0, `a settled hand reports no travel (got ${stale.motion()[0]})`);

// ---- the whole gesture engine, on real captured hands ----------------------------
//
// The gate is a learned classifier, so hand-built poses cannot validate it: the
// fixtures in gestures.verify.mjs carry z = 0 on every landmark and put fingers on
// straight lines, geometry that never comes out of real tracking. These are whole
// takes from the captures (core/scripts/zoom_fixture.py), replayed frame by frame.

const engine = JSON.parse(readFileSync(new URL("./zoom.engine.json", import.meta.url), "utf8"));
check(engine.length >= 10, `the engine fixture covers every pose (${engine.length} takes)`);

/** A take through the real engine; returns the state after every frame. */
function replay(take) {
  const gestures = new GestureEngine();
  const cursor = { x: 0.5, y: 0.5 };
  const log = [];
  for (const f of take.frames) {
    if (f.lm) {
      cursor.x = f.cx;
      cursor.y = f.cy;
    }
    const hand = f.lm
      ? { landmarks: Array.from({ length: 21 }, (_, i) => ({ x: f.lm[i * 3], y: f.lm[i * 3 + 1], z: f.lm[i * 3 + 2] })), handedness: "Right" }
      : null;
    log.push({ ...gestures.update({ hand, cursor, timestamp: f.ts, tracking: Boolean(f.lm) }) });
  }
  return log;
}

const share = (log) => log.filter((s) => s.zoom).length / Math.max(log.length, 1);

for (const take of engine) {
  const log = replay(take);
  const lit = share(log);
  if (take.expect === "never") {
    // a confuser may not hold a latch; the odd frame on the way past is survivable
    let worst = 0;
    let run = 0;
    for (const s of log) {
      run = s.zoom ? run + 1 : 0;
      worst = Math.max(worst, run);
    }
    check(worst <= 9, `${take.pose}: never holds a zoom (worst run ${worst} frames, ${(lit * 100).toFixed(0)}% of frames)`);
  } else {
    // a held pose or a zoom being performed: latched for nearly all of it, after
    // the hold has been waited out (each take replays from cold, so its first
    // ZOOM_HOLD_MS - plus a frame or two - is the hold itself)
    const start = take.frames[0].ts + ZOOM_HOLD_MS + 100;
    const after = log.filter((_, i) => take.frames[i].ts >= start);
    const held = share(after);
    check(held > 0.75, `${take.pose}: stays latched after the hold (${(held * 100).toFixed(0)}% of frames)`);
  }
  check(
    log.every((s) => s.zoomFactor >= 0.5 && s.zoomFactor <= 2),
    `${take.pose}: zoomFactor stays inside 0.5-2.0`,
  );
}

// the factor has to move the right way through a real in and a real out
for (const [pose, wantUp] of [["zoom_in", true], ["zoom_out", false]]) {
  const take = engine.find((t) => t.pose === pose);
  if (!take) continue;
  const held = replay(take).filter((s) => s.zoom);
  const head = held.slice(0, 5).reduce((a, s) => a + s.zoomFactor, 0) / 5;
  const tail = held.slice(-5).reduce((a, s) => a + s.zoomFactor, 0) / 5;
  check(
    held.length > 20 && (wantUp ? tail - head > 0.08 : head - tail > 0.08),
    `${pose}: zoomFactor tracks the motion (${head.toFixed(2)} -> ${tail.toFixed(2)})`,
  );
}

// a real resting hand, for a full minute: the synthetic version of this used to
// live in gestures.verify.mjs section 9, but a hand-built pose says nothing about
// a learned gate, so the relaxed take is looped instead
{
  const relaxed = engine.find((t) => t.pose === "relaxed");
  if (relaxed) {
    const gestures = new GestureEngine();
    const cursor = { x: 0.5, y: 0.5 };
    const step = 33;
    let ts = 1000;
    let latched = 0;
    let worst = 0;
    let run = 0;
    for (let loop = 0; loop < 15; loop += 1) {
      for (const f of relaxed.frames) {
        if (!f.lm) continue;
        const hand = { landmarks: Array.from({ length: 21 }, (_, i) => ({ x: f.lm[i * 3], y: f.lm[i * 3 + 1], z: f.lm[i * 3 + 2] })), handedness: "Right" };
        const s = gestures.update({ hand, cursor, timestamp: ts, tracking: true });
        ts += step;
        latched += s.zoom ? 1 : 0;
        run = s.zoom ? run + 1 : 0;
        worst = Math.max(worst, run);
      }
    }
    const seconds = ((ts - 1000) / 1000).toFixed(0);
    check(worst <= 9, `${seconds}s of a real resting hand never holds a zoom (worst run ${worst} frames, ${latched} latched)`);
  }
}

// losing the hand drops everything, whatever was latched
{
  const spread = engine.find((t) => t.pose === "spread");
  if (spread) {
    const gestures = new GestureEngine();
    const cursor = { x: 0.5, y: 0.5 };
    let last = null;
    for (const f of spread.frames) {
      const hand = f.lm
        ? { landmarks: Array.from({ length: 21 }, (_, i) => ({ x: f.lm[i * 3], y: f.lm[i * 3 + 1], z: f.lm[i * 3 + 2] })), handedness: "Right" }
        : null;
      last = gestures.update({ hand, cursor, timestamp: f.ts, tracking: Boolean(f.lm) });
    }
    check(last.zoom, "spread: latched before the hand goes");
    const after = spread.frames[spread.frames.length - 1].ts;
    for (let k = 1; k <= 6; k += 1) {
      last = gestures.update({ hand: null, cursor, timestamp: after + k * 33, tracking: false });
    }
    check(!last.zoom, "losing the hand releases zoom");
    check(last.zoomFactor === 1, "zoomFactor returns to 1 on release");
  }
}

if (failures > 0) {
  console.error(`zoom: ${failures} failure(s) over ${frames} frames`);
  process.exit(1);
} else {
  console.log(
    `zoom: ok (${frames} frames match Python, drift ${worstFeature.toExponential(1)}; ` +
      `${engine.length} captured takes through the engine: ${engine.map((t) => t.pose).join(", ")})`,
  );
}
