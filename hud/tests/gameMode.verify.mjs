// Game mode (src/tracking/gameMode.ts): while a hand game runs, NO normal gesture
// fires - no pointing (the OS cursor), no dwell or pinch click, no scroll, no zoom,
// no summon - because rock, paper and scissors ARE the fist, the open palm and two
// fingers. Every sequence below is first shown to fire with game mode OFF (so the
// test has teeth), then replayed with it ON, where the state must stay neutral on
// every frame. Real captured takes of his hand (zoom.engine.json) and scripted ones.
import { readFileSync } from "node:fs";
import { GestureEngine } from "../.verify/gestures.js";
import { GameMode } from "../.verify/gameMode.js";

let failures = 0;
const check = (ok, label) => {
  if (!ok) {
    failures += 1;
    console.error(`FAIL gameMode: ${label}`);
  }
};

// ---- scripted hands (the same templates as gestures.verify.mjs) ----------------------------
const WRIST = { x: 0.5, y: 0.8 };
const PALM = 0.16;
const lerp = (a, b, t) => ({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t });
function buildHand({ curl, thumbTip, dy = 0, tipShift = [0, 0, 0, 0] }) {
  const w = { x: WRIST.x, y: WRIST.y + dy };
  const mcpY = w.y - PALM;
  const offs = [0.05, 0.017, -0.017, -0.05];
  const lm = new Array(21);
  lm[0] = { x: w.x, y: w.y, z: 0 };
  const tt = { x: thumbTip.x, y: thumbTip.y + dy };
  for (let j = 1; j <= 4; j += 1) lm[j] = { ...lerp(w, tt, j / 4), z: 0 };
  for (let f = 0; f < 4; f += 1) {
    const base = 5 + f * 4;
    const mx = w.x - offs[f];
    const c = curl[f];
    const s = tipShift[f] ?? 0;
    lm[base] = { x: mx, y: mcpY, z: 0 };
    lm[base + 1] = { x: mx, y: mcpY - 0.06, z: 0 };
    lm[base + 2] = { x: mx + s * 0.6, y: mcpY - 0.1 * (1 - c), z: 0 };
    lm[base + 3] = { x: mx + s, y: mcpY - 0.14 * (1 - c), z: 0 };
  }
  return lm;
}
const TUCKED = { x: WRIST.x - 0.02, y: WRIST.y - 0.12 };
const pointing = () => buildHand({ curl: [0, 1, 1, 1], thumbTip: TUCKED });
const scroll = (dy) => buildHand({ curl: [0, 0, 1, 1], thumbTip: TUCKED, dy });
const summon = () => buildHand({ curl: [0, 0, 1, 1], thumbTip: TUCKED, tipShift: [0.025, -0.02, 0, 0] });

const FRAME = 33;
const scripted = [
  // held still: pointing, and the dwell click
  { name: "pointing + dwell", frames: Array.from({ length: 120 }, () => pointing()), fires: (s) => s.pointing || s.selectCount > 0 },
  // two fingers, high in the frame: the wheel
  { name: "scroll", frames: Array.from({ length: 90 }, (_, i) => scroll(-0.25 - 0.001 * i)), fires: (s) => s.scroll },
  // crossed fingers held: the summon
  { name: "summon", frames: Array.from({ length: 120 }, () => summon()), fires: (s) => s.summon || s.summonCount > 0 },
];

/** A sequence through the gate; game mode on (for its whole length) or off. */
function replay(frames, gameOn) {
  const engine = new GestureEngine();
  const game = new GameMode();
  const log = [];
  let ts = 1000;
  if (gameOn) game.set(true, ts, 600000, "rps");
  for (const f of frames) {
    const hand = f ? { landmarks: f, handedness: "Right" } : null;
    log.push({ ...game.step(engine, { hand, cursor: { x: 0.5, y: 0.5 }, timestamp: ts, tracking: Boolean(f) }, ts) });
    if (f) game.record(ts, f, "Right");
    ts += FRAME;
  }
  return { log, game };
}

const anything = (s) =>
  s.pointing || s.scroll || s.zoom || s.summon || s.pinching || s.selectCount > 0 || s.summonCount > 0 || s.pinchCount > 0 || s.dwellProgress > 0 || s.handPresent;

for (const take of scripted) {
  const off = replay(take.frames, false).log;
  check(off.some(take.fires), `${take.name}: fires with game mode OFF (the test must have teeth)`);
  const { log, game } = replay(take.frames, true);
  check(!log.some(anything), `${take.name}: NOTHING fires in game mode`);
  check(game.frames.length > 0, `${take.name}: his hand still reaches the game's buffer`);
}

// his real hand: every captured zoom take latches with game mode off, and no take -
// zoom, fist, spread, pointing, the scroll pose, waving - fires anything with it on
const takes = JSON.parse(readFileSync(new URL("./zoom.engine.json", import.meta.url), "utf8"));
const toLm = (f) => (f.lm ? Array.from({ length: 21 }, (_, i) => ({ x: f.lm[i * 3], y: f.lm[i * 3 + 1], z: f.lm[i * 3 + 2] })) : null);
let realFired = 0;
for (const take of takes) {
  const frames = take.frames.map(toLm);
  const off = replay(frames, false).log;
  if (take.expect === "latched") {
    check(off.some((s) => s.zoom), `${take.pose}: zooms with game mode OFF`);
    realFired += 1;
  }
  const on = replay(frames, true).log;
  check(!on.some(anything), `${take.pose} (real hand): nothing fires in game mode`);
}
check(realFired >= 6, `real zoom takes exercised (${realFired})`);

// coming back: off again, the next frame is the engine's own (gestures restored), and
// a lost "off" ends game mode by itself at its deadline
{
  const engine = new GestureEngine();
  const game = new GameMode();
  game.set(true, 0, 2000, "rps");
  const at = (t) => game.step(engine, { hand: { landmarks: pointing(), handedness: "Right" }, cursor: { x: 0.5, y: 0.5 }, timestamp: t, tracking: true }, t);
  check(!at(500).handPresent, "in game mode at 0.5 s");
  check(at(2500).handPresent, "game mode ends by itself at its deadline: the hand is back");
  game.set(true, 3000, 60000, "rps");
  check(!at(3100).handPresent, "on again");
  game.set(false, 3200);
  check(at(3300).handPresent && game.frames.length === 0, "voice/core 'off': gestures restored at once, buffer cleared");
}

// the buffer keeps only the last few seconds, and a window is relative to the shoot instant
{
  const game = new GameMode();
  game.set(true, 0, 60000, "rps");
  for (let t = 0; t <= 6000; t += 33) game.record(t, pointing(), "Right");
  check(game.frames[game.frames.length - 1].t - game.frames[0].t <= 4000 && game.frames.length > 100, "buffer holds ~4 s");
  const w = game.window(5000, 4800, 5400);
  check(w.length > 0 && w[0].t >= -200 && w[w.length - 1].t <= 400 && w[0].lm.length === 63, "window relative to shoot");
}

if (failures > 0) {
  console.error(`gameMode: ${failures} failure(s)`);
  process.exit(1);
} else {
  console.log(`gameMode: ok (${scripted.length} scripted + ${takes.length} real takes silent in game mode)`);
}
