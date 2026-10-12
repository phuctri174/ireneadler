// Replay a gesture capture (core/calibration/<profile>-<session>.jsonl) through the
// real GestureEngine - compiled fresh from src/tracking/gestures.ts, so edited
// thresholds are what gets measured - and report, per take:
//   - per-finger ratio ranges against the zoom latch thresholds (margins)
//   - how much of the take zoom was latched
//   - zoomFactor from start to end, and whether it moved the right way
//
//   node scripts/replay_capture.mjs ../core/calibration/zoom-<session>.jsonl [--json]
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { join, resolve } from "node:path";

const OUT = ".verify-replay";
const require = createRequire(import.meta.url);
const tsc = spawnSync(
  process.execPath,
  [require.resolve("typescript/bin/tsc"), "src/tracking/gestures.ts", "--ignoreConfig", "--outDir", OUT,
    "--module", "esnext", "--target", "es2020", "--moduleResolution", "bundler", "--skipLibCheck"],
  { stdio: "inherit" },
);
if (tsc.status !== 0) process.exit(tsc.status ?? 1);
// node wants explicit extensions on the compiled relative imports
for (const name of readdirSync(OUT)) {
  if (!name.endsWith(".js")) continue;
  const path = join(OUT, name);
  writeFileSync(path, readFileSync(path, "utf8").replace(
    /(from\s+")(\.\.?\/[^"]+?)(")/g,
    (match, head, spec, tail) => (spec.endsWith(".js") ? match : `${head}${spec}.js${tail}`),
  ));
}
const g = await import(pathToFileURL(resolve(OUT, "gestures.js")).href);

const file = process.argv[2];
if (!file) {
  console.error("usage: node scripts/replay_capture.mjs <capture.jsonl> [--json]");
  process.exit(2);
}
const rows = readFileSync(file, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));

// takes in recorded order: (pose, rep)
const takes = [];
for (const row of rows) {
  const last = takes.at(-1);
  if (!last || last.pose !== row.pose || last.rep !== row.rep) takes.push({ pose: row.pose, rep: row.rep, rows: [] });
  takes.at(-1).rows.push(row);
}

const FINGERS = ["thumb", "index", "middle", "ring", "pinky"];
const toLandmarks = (lm) => Array.from({ length: lm.length / 3 }, (_, k) => ({ x: lm[3 * k], y: lm[3 * k + 1], z: lm[3 * k + 2] }));

function replay(take) {
  const engine = new g.GestureEngine();
  const out = [];
  for (const row of take.rows) {
    if (row.ts === undefined) continue; // recorded before inputs were logged
    const hand = row.lm ? { landmarks: toLandmarks(row.lm), handedness: row.handed ?? "Right" } : null;
    const state = engine.update({ hand, cursor: { x: row.cx ?? 0.5, y: row.cy ?? 0.5 }, timestamp: row.ts, tracking: row.tracking ?? !!hand });
    out.push({
      hand: !!hand,
      zoom: state.zoom,
      factor: state.zoomFactor,
      mode: state.mode,
      fingers: Object.fromEntries(FINGERS.map((f) => [f, state.diag[f]])),
      spread: state.spread,
      recordedZoom: row.zoom,
    });
  }
  return out;
}

const stats = (xs) => (xs.length ? { min: Math.min(...xs), max: Math.max(...xs), mean: xs.reduce((a, b) => a + b, 0) / xs.length } : null);
const f3 = (x) => (x === undefined || x === null ? "  -  " : x.toFixed(3));

const report = [];
for (const take of takes) {
  const frames = replay(take);
  const withHand = frames.filter((f) => f.hand);
  const latched = frames.filter((f) => f.zoom);
  const factors = latched.map((f) => f.factor);
  // direction over the latched part: first vs last 20% of latched frames
  const n = factors.length;
  const head = factors.slice(0, Math.max(1, Math.floor(n / 5)));
  const tail = factors.slice(Math.max(0, n - Math.max(1, Math.floor(n / 5))));
  const avg = (xs) => xs.reduce((a, b) => a + b, 0) / xs.length;
  const trend = n >= 2 ? avg(tail) - avg(head) : 0;
  report.push({
    pose: take.pose,
    rep: take.rep,
    frames: frames.length,
    hand: withHand.length,
    latched: latched.length,
    latchedLive: frames.filter((f) => f.recordedZoom).length,
    factorStart: factors[0],
    factorEnd: factors.at(-1),
    factorMin: n ? Math.min(...factors) : undefined,
    factorMax: n ? Math.max(...factors) : undefined,
    trend,
    fingers: Object.fromEntries(FINGERS.map((f) => [f, stats(withHand.map((x) => x.fingers[f]))])),
    spread: stats(withHand.map((x) => x.spread)),
  });
}

if (process.argv.includes("--json")) {
  console.log(JSON.stringify({ thresholds: {
    openFinger: g.ZOOM_OPEN_FINGER_RATIO, openFingerRelease: g.ZOOM_OPEN_FINGER_RELEASE_RATIO,
    closedFinger: g.ZOOM_CLOSED_FINGER_RATIO, closedFingerRelease: g.ZOOM_CLOSED_FINGER_RELEASE_RATIO,
    openThumb: g.ZOOM_OPEN_THUMB_RATIO, openThumbRelease: g.ZOOM_OPEN_THUMB_RELEASE_RATIO,
    closedThumb: g.ZOOM_CLOSED_THUMB_RATIO, closedThumbRelease: g.ZOOM_CLOSED_THUMB_RELEASE_RATIO,
    spreadClosed: g.ZOOM_SPREAD_CLOSED,
  }, takes: report }, null, 1));
  process.exit(0);
}

console.log(`zoom latch: finger open > ${g.ZOOM_OPEN_FINGER_RATIO} (release < ${g.ZOOM_OPEN_FINGER_RELEASE_RATIO}), ` +
  `closed < ${g.ZOOM_CLOSED_FINGER_RATIO} (release > ${g.ZOOM_CLOSED_FINGER_RELEASE_RATIO}); ` +
  `thumb open > ${g.ZOOM_OPEN_THUMB_RATIO}, closed < ${g.ZOOM_CLOSED_THUMB_RATIO}; fist spread < ${g.ZOOM_SPREAD_CLOSED}`);
for (const r of report) {
  const fingers = FINGERS.map((f) => `${f.slice(0, 2)} ${f3(r.fingers[f]?.min)}..${f3(r.fingers[f]?.max)}`).join("  ");
  console.log(
    `${r.pose.padEnd(12)} rep ${r.rep}  hand ${r.hand}/${r.frames}  zoom ${r.latched} (live ${r.latchedLive})  ` +
      `factor ${f3(r.factorStart)} -> ${f3(r.factorEnd)} [${f3(r.factorMin)}..${f3(r.factorMax)}] trend ${f3(r.trend)}\n` +
      `             ${fingers}  spread ${f3(r.spread?.min)}..${f3(r.spread?.max)}`,
  );
}
