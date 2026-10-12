// The cue registry (config/cues.json) against the art: every entry has art of its
// kind and every piece of art has an entry, so a new cue can't be half-added. Then
// the expressions read as different faces, and the micro-expressions stay small,
// deterministic and out of the way of states that must look still.
import { readFileSync } from "node:fs";
import { Frame, COLS } from "../.verify/led/grid.js";
import { compose } from "../.verify/led/compose.js";
import { EYE_H, EYE_W, EYE_Y, LEFT_EYE_X, RIGHT_EYE_X } from "../.verify/led/face.js";
import { EMOTIONS } from "../.verify/face/faceState.js";
import { REACTIONS } from "../.verify/face/reactions.js";
import { ACTIVITIES, IDLE_ACTIVITIES } from "../.verify/face/activity.js";
import { MicroExpressions } from "../.verify/micro.js";

let failures = 0;
const check = (ok, label) => {
  if (!ok) {
    failures += 1;
    console.error(`FAIL cues: ${label}`);
  }
};

const { cues } = JSON.parse(readFileSync(new URL("../../config/cues.json", import.meta.url), "utf8"));
const art = {
  expression: EMOTIONS.filter((name) => name !== "neutral"),
  gesture: REACTIONS,
  scene: IDLE_ACTIVITIES,
  prop: ACTIVITIES.filter((name) => !IDLE_ACTIVITIES.includes(name)),
};
for (const [kind, names] of Object.entries(art)) {
  const registered = cues.filter((c) => c.kind === kind).map((c) => c.name);
  for (const name of registered) check(names.includes(name), `registry ${kind} "${name}" has no art`);
  for (const name of names) check(registered.includes(name), `${kind} art "${name}" has no registry entry`);
}
for (const cue of cues) {
  check(["expression", "gesture", "scene", "prop"].includes(cue.kind), `${cue.name}: unknown kind ${cue.kind}`);
  check(cue.kind === "prop" ? !cue.when : typeof cue.when === "string" && cue.when.length > 8, `${cue.name}: a 'when' for the model (props never have one)`);
}

// expressions: each is its own face
const NOW = 50000;
const base = { state: "listening", level: 0, now: NOW, blinking: false, muted: false, reaction: null, activity: null, summon: null };
const eyes = (emotion) => {
  const f = new Frame();
  compose(f, { ...base, emotion });
  const cells = [];
  for (let y = EYE_Y - 2; y < EYE_Y + EYE_H + 2; y += 1) for (let x = LEFT_EYE_X - 2; x < RIGHT_EYE_X + EYE_W + 2; x += 1) cells.push(f.value[y * COLS + x]);
  return { cells, ink: f.ink };
};
const faces = Object.fromEntries(EMOTIONS.map((e) => [e, eyes(e).cells]));
for (let i = 0; i < EMOTIONS.length; i += 1) {
  for (let j = i + 1; j < EMOTIONS.length; j += 1) {
    const a = faces[EMOTIONS[i]];
    const b = faces[EMOTIONS[j]];
    const differ = a.reduce((n, v, k) => n + (Math.abs(v - b[k]) > 0.2 ? 1 : 0), 0);
    check(differ > 25, `${EMOTIONS[i]} and ${EMOTIONS[j]} look different (${differ} cells)`);
  }
}

// body movement: a feeling or a gesture moves her whole face, not just its shape.
// Where the lit cells of each eye sit, as a (x, y) centroid.
const eyeCentre = (stage) => {
  const f = new Frame();
  compose(f, { ...base, ...stage });
  const centre = (x0, x1) => {
    let n = 0, sx = 0, sy = 0;
    for (let y = 0; y < 38; y += 1) for (let x = x0; x < x1; x += 1) {
      const v = f.value[y * COLS + x];
      if (v > 0.3) { n += v; sx += v * x; sy += v * y; }
    }
    return { x: sx / n, y: sy / n };
  };
  return { left: centre(LEFT_EYE_X - 8, LEFT_EYE_X + EYE_W + 4), right: centre(RIGHT_EYE_X - 4, RIGHT_EYE_X + EYE_W + 8) };
};
const still = eyeCentre({ emotion: "neutral", emotionAt: NOW - 3000 });
const at = (ms, stage) => eyeCentre({ ...stage, now: NOW + ms });
// excited-bounce: the face hops, frame to frame
const hops = [0, 60, 120, 190, 250, 320].map((ms) => at(ms, { emotion: "neutral", reaction: { name: "excitedBounce", at: NOW - 400 } }).left.y);
check(Math.max(...hops) - Math.min(...hops) >= 3, `excitedBounce bounces her face (${hops.map((y) => y.toFixed(1))})`);
// head tilt: one eye drops, the other rises
const tilted = at(0, { emotion: "neutral", reaction: { name: "headTilt", at: NOW - 900 } });
check(tilted.left.y - tilted.right.y >= 3, `headTilt tilts her head (left ${tilted.left.y.toFixed(1)}, right ${tilted.right.y.toFixed(1)})`);
// sad droops, sulking turns away, surprised jumps back, excited bounces
const sad = eyeCentre({ emotion: "sad", emotionAt: NOW - 1500 });
const sadStill = eyeCentre({ emotion: "sad" });
check(sad.left.y - sadStill.left.y >= 3, "sad: her head droops");
const sulk = eyeCentre({ emotion: "sulking", emotionAt: NOW - 1500 });
const sulkStill = eyeCentre({ emotion: "sulking" });
check(sulkStill.left.x - sulk.left.x >= 4, "sulking: she turns away");
const jump = eyeCentre({ emotion: "surprised", emotionAt: NOW - 40 });
check(eyeCentre({ emotion: "surprised" }).left.y - jump.left.y >= 2, "surprised: she jumps back");
const bounce = [0, 104, 208].map((ms) => at(ms, { emotion: "excited", emotionAt: NOW - 417 }).left.y);
check(Math.max(...bounce) - Math.min(...bounce) >= 2, "excited: she bounces");
// a shrug lifts the shoulders and sinks the head
const shrug = at(0, { emotion: "neutral", reaction: { name: "shrug", at: NOW - 450 } });
check(shrug.left.y - still.left.y >= 1.5, "shrug: her head sinks between her shoulders");
// dormant stays still whatever the feeling
check(eyeCentre({ state: "dormant", emotion: "sad", emotionAt: NOW - 1500 }).left.y === eyeCentre({ state: "dormant", emotion: "sad" }).left.y, "dormant: no movement");

// micro-expressions: deterministic under a fixed random, small, and quiet when dormant
const seq = (seed) => {
  let s = seed;
  return () => {
    s = (s * 16807) % 2147483647;
    return s / 2147483647;
  };
};
const run = (state, emotion, typing, ms = 20000) => {
  const micro = new MicroExpressions(seq(7));
  const out = [];
  for (let t = 0; t < ms; t += 16) out.push(micro.update(t, { state, emotion, typing }));
  return out;
};
const talk = run("speaking", "neutral", false);
check(JSON.stringify(talk) === JSON.stringify(run("speaking", "neutral", false)), "micro is deterministic for a fixed random");
check(talk.every((m) => Math.abs(m.gazeX) <= 2 && Math.abs(m.gazeY) <= 1), "speaking glances stay small");
check(new Set(talk.map((m) => `${m.gazeX},${m.gazeY}`)).size >= 4, "speaking glances move around");
const blinks = talk.filter((m, i) => m.blinking && !talk[i - 1]?.blinking).length;
check(blinks >= 3 && blinks <= 14, `speaking blinks now and then (${blinks} in 20 s)`);
const flashes = new Set(talk.map((m) => m.flash).filter(Boolean));
check(flashes.size >= 1 && [...flashes].every((f) => EMOTIONS.includes(f)), `feelings flicker through while speaking (${[...flashes]})`);
check(talk.filter((m) => m.flash).length < talk.length * 0.35, "a blend is brief, not the face");
check(run("listening", "neutral", false).every((m) => m.flash === null), "no blends while just listening");
const dormant = run("dormant", "neutral", false);
check(dormant.every((m) => m.gazeX === 0 && m.gazeY === 0 && !m.blinking && m.flash === null), "dormant stays still");
const typing = run("listening", "neutral", true, 4000);
check(typing.every((m) => m.gazeY === 3), "typing: eyes down on the bar");
check(new Set(typing.map((m) => m.gazeX)).size >= 3, "typing: eyes follow the line");
check(run("thinking", "neutral", false).every((m) => m.gazeY === -1 || m.gazeY === 0), "thinking looks up");

if (failures > 0) {
  console.error(`cues: ${failures} failure(s)`);
  process.exit(1);
} else {
  console.log(`cues: ok (${cues.length} registered: ${Object.entries(art).map(([k, v]) => `${v.length} ${k}`).join(", ")})`);
}
