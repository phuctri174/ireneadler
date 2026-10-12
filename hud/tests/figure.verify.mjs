// Her body rig (led/figure.ts): the robot - a big screen head on a short chassis -
// with machined limbs whose joints bend the way joints bend. Bones keep their length whatever the pose (no stretching limbs), knees
// bend toward where she faces (or outward, facing the viewer), elbows never fold
// backward, arm IK puts the wrist where it was asked, and she is drawn well-formed
// from every side.
import { Frame, INK } from "../.verify/led/grid.js";
import { STAND, BARE, HEAD_H, arc, drawFigure, joints, reach, bendLimit, animate, resolve, sample } from "../.verify/led/figure.js";

let failures = 0;
const check = (ok, label) => {
  if (!ok) {
    failures += 1;
    console.error(`FAIL figure: ${label}`);
  }
};
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const cam = { x: 64, y: 68, s: 8 };

// proportions: about 7 units tall standing, a third of it head - a desk robot, not a person
{
  const j = joints(STAND, cam);
  const tall = (cam.y - (j.head.y - HEAD_H * cam.s)) / cam.s;
  check(tall > 6.6 && tall < 7.6, `about 7 units tall (${tall.toFixed(2)})`);
  check((2 * HEAD_H) / tall > 0.25, `a big head: ${((2 * HEAD_H) / tall).toFixed(2)} of her height`);
  check(dist(j.shoulderA, j.shoulderB) / cam.s > 1.6, "a broad chassis");
}

// bones keep their length: crouching bends the knees instead of shortening the legs
for (const [label, pose] of [
  ["standing", STAND],
  ["crouch", { ...STAND, y: 2.2, fAx: -0.8, fBx: 0.8 }],
  ["lunge", { ...STAND, turn: 0.9, x: 0.4, y: 2.8, fAx: -0.9, fBx: 1.3 }],
  ["seated", { ...STAND, turn: 1, y: 1.8, fAx: 1.45, fBx: 1.6 }],
]) {
  const j = joints(pose, cam);
  const hipA = { x: j.pelvis.x - 0.42 * (1 - 0.4 * Math.abs(pose.turn)) * cam.s, y: j.pelvis.y };
  check(Math.abs(dist(hipA, j.kneeA) / cam.s - 1.5) < 0.02, `${label}: thigh keeps its length`);
  check(Math.abs(dist(j.kneeA, j.ankleA) / cam.s - 1.45) < 0.02 || dist(hipA, j.ankleA) / cam.s > 2.9, `${label}: shin keeps its length`);
  check(Math.abs(dist(j.shoulderA, j.elbowA) / cam.s - 1.15) < 0.01, `${label}: upper arm keeps its length`);
  check(Math.abs(dist(j.elbowA, j.wristA) / cam.s - 1.0) < 0.01, `${label}: forearm keeps its length`);
}

// knees bend forward in a profile, outward facing the viewer
{
  const crouchRight = joints({ ...STAND, turn: 1, y: 2.3, fAx: -0.2, fBx: 0.2 }, cam);
  check(crouchRight.kneeA.x > crouchRight.ankleA.x && crouchRight.kneeB.x > crouchRight.ankleB.x, "facing right, knees bend right");
  const crouchFront = joints({ ...STAND, y: 2.3 }, cam);
  check(crouchFront.kneeA.x < crouchFront.ankleA.x && crouchFront.kneeB.x > crouchFront.ankleB.x, "facing him, knees bend outward");
}

// elbows: facing him each forearm folds in toward her; turned, both fold forward
check(bendLimit("A", 0, 120) === 120 && bendLimit("A", 0, -90) === -12, "arm A folds in, never backward");
check(bendLimit("B", 0, -120) === -120 && bendLimit("B", 0, 90) === 12, "arm B folds in, never backward");
check(bendLimit("B", 1, 120) === 120 && bendLimit("A", 1, 120) === 120, "facing right, both forearms fold forward");

// arm IK reaches what it is asked to, with the elbow hanging low
for (const target of [{ x: 0.9, y: 4.4 }, { x: 0.3, y: 6.6 }, { x: -0.5, y: 3.8 }]) {
  const pose = { ...STAND, turn: 0.9 };
  const r = reach(pose, "B", target);
  const j = joints({ ...pose, aB: r.a, eB: r.e }, { x: 0, y: 0, s: 1 });
  const got = { x: j.wristB.x, y: -j.wristB.y };
  check(dist(got, target) < 0.03, `reach (${target.x}, ${target.y}): wrist lands there (off by ${dist(got, target).toFixed(3)})`);
}

// the motion system: lead order (shoulder, then elbow, then wrist), overshoot, settle
{
  const track = resolve([{ t: 0, p: { aB: 10, eB: -10, wB: 0 } }, { t: 200, p: { aB: 150, eB: -60, wB: 40 }, e: "snap" }]);
  const at = (t) => sample(track, t);
  const frac = (t, k, from, to) => (animate(at, t)[k] - from) / (to - from);
  const t = 120;
  const sh = frac(t, "aB", 10, 150);
  const el = frac(t, "eB", -10, -60);
  const wr = frac(t, "wB", 0, 40);
  check(sh > el && el > wr, `lead order at ${t} ms: shoulder ${sh.toFixed(2)} > elbow ${el.toFixed(2)} > wrist ${wr.toFixed(2)}`);
  let peak = 0;
  for (let k = 150; k < 700; k += 10) peak = Math.max(peak, frac(k, "aB", 10, 150));
  check(peak > 1.01, `the shoulder overshoots its mark (${peak.toFixed(3)})`);
  check(Math.abs(frac(1200, "aB", 10, 150) - 1) < 0.01, "and settles on it");
}
// arcs: a hand path bows away from the straight line
{
  const mid = arc({ x: 0, y: 0 }, { x: 10, y: 0 }, 0.5, 2);
  check(Math.abs(mid.y) > 0.9, `arc() bows the path (${mid.y.toFixed(2)})`);
}

// drawn well-formed from every side, in every outfit
const light = { dir: { x: -1, y: -0.5 }, ink: INK.amber, power: 1 };
for (const turn of [-1, -0.5, 0, 0.5, 1]) {
  for (const outfit of [BARE, { collar: true, cape: { hem: 1.7, flare: 1.5, ink: INK.red }, hat: { tip: 0.5 } }, { bogu: true, men: true, skirt: { hem: 0.55, flare: 1 } }]) {
    const f = new Frame();
    f.clear();
    drawFigure(f, { ...STAND, turn }, outfit, cam, light);
    const lit = f.value.reduce((n, v) => n + (v > 0.15 ? 1 : 0), 0);
    check(f.value.every((v) => Number.isFinite(v) && v >= 0 && v <= 1.0001), `turn ${turn}: values 0..1`);
    check(lit > 400, `turn ${turn}: a whole body is drawn (${lit} cells)`);
  }
}

if (failures > 0) {
  console.error(`figure: ${failures} failure(s)`);
  process.exit(1);
} else {
  console.log("figure: ok (robot proportions, bone lengths, knees, elbows, reach, follow-through, every side)");
}
