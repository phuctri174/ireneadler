// Idle life (src/face/idle.ts): a beat every 20-60 s while he's inactive, varied,
// never while she's busy or hidden, and cut off the moment he interacts.
import { IdleLife, IDLE_GAP_MS, glanceGaze } from "../.verify/idle.js";

let failures = 0;
const check = (ok, label) => {
  if (!ok) {
    failures += 1;
    console.error(`FAIL idle: ${label}`);
  }
};

// a fixed pseudo-random sequence
const seeded = (seed) => () => {
  seed = (seed * 16807) % 2147483647;
  return seed / 2147483647;
};

const scenes = { chess: 12000, kendo: 6000 };
const quiet = (lastInteraction = 0) => ({ state: "listening", visible: true, lastInteraction, busy: false });

function run(life, from, to, input, step = 50) {
  const beats = [];
  for (let now = from; now <= to; now += step) {
    const u = life.update(now, typeof input === "function" ? input(now) : input);
    if (u.started) beats.push(u.started);
  }
  return beats;
}

{
  const life = new IdleLife(scenes, seeded(7));
  const beats = run(life, 0, 10 * 60 * 1000, quiet());
  check(beats.length >= 8 && beats.length <= 30, `ten quiet minutes give 8-30 beats, got ${beats.length}`);
  check(beats[0].at >= IDLE_GAP_MS[0] && beats[0].at <= IDLE_GAP_MS[1], `the first beat comes 20-60 s in (${beats[0].at} ms)`);
  for (let i = 1; i < beats.length; i += 1) {
    const gap = beats[i].at - (beats[i - 1].at + beats[i - 1].ms);
    check(gap >= IDLE_GAP_MS[0] - 60 && gap <= IDLE_GAP_MS[1] + 60, `beats are 20-60 s apart (gap ${gap} ms)`);
    check(beats[i].kind !== beats[i - 1].kind, `never the same kind twice running (${beats[i].kind})`);
  }
  const kinds = new Set(beats.map((b) => b.kind));
  check(["glance", "stretch", "hum", "scene"].every((k) => kinds.has(k)), `every kind turns up (${[...kinds]})`);
}

{
  // he keeps interacting (a hand in view every frame): nothing ever plays
  const life = new IdleLife(scenes, seeded(3));
  const beats = run(life, 0, 5 * 60 * 1000, (now) => quiet(now));
  check(beats.length === 0, `no idle life while he interacts (${beats.length} beats)`);
}

{
  // busy, speaking, thinking or hidden: nothing plays
  for (const input of [
    { ...quiet(), busy: true },
    { ...quiet(), state: "speaking" },
    { ...quiet(), state: "thinking" },
    { ...quiet(), visible: false },
  ]) {
    const life = new IdleLife(scenes, seeded(5));
    check(run(life, 0, 3 * 60 * 1000, input).length === 0, `nothing while ${JSON.stringify(input)}`);
  }
}

{
  // a beat is cut off the moment he interacts, and the clock starts again
  const life = new IdleLife(scenes, seeded(11));
  let now = 0;
  let playing = null;
  while (!playing && now < 120000) {
    playing = life.update(now, quiet()).started;
    now += 50;
  }
  check(playing !== null, "a beat started");
  const touch = now + 10;
  const cut = life.update(now + 20, quiet(touch));
  check(cut.stopped === playing && cut.beat === null, "his interaction stops the beat at once");
  const next = run(life, now + 40, now + 40 + IDLE_GAP_MS[0] - 200, quiet(touch));
  check(next.length === 0, "and nothing new plays for at least 20 s after it");
}

{
  // dormant (eyes shut): no glances
  const life = new IdleLife(scenes, seeded(13));
  const beats = run(life, 0, 20 * 60 * 1000, { ...quiet(), state: "dormant" });
  check(beats.length > 0 && beats.every((b) => b.kind !== "glance"), "a dormant face never glances");
}

{
  const beat = { kind: "glance", at: 1000, ms: 2600 };
  const left = glanceGaze(beat, 1000 + 2600 * 0.3);
  const right = glanceGaze(beat, 1000 + 2600 * 0.7);
  check(left.x < 0 && right.x > 0 && glanceGaze(beat, 1000 + 2600).x === 0, "a glance looks left, then right, then back");
}

if (failures > 0) {
  console.error(`idle: ${failures} failure(s)`);
  process.exitCode = 1;
} else {
  console.log("idle: ok");
}
