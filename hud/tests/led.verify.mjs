// The LED matrix composer, frame by frame: every gesture draws, scenes move, the
// summon visor really hides the eyes and gives them back, nothing throws.
import { COLS, ROWS, Frame } from "../.verify/led/grid.js";
import { compose } from "../.verify/led/compose.js";
import { EYE_W, LEFT_EYE_X, RIGHT_EYE_X, EYE_Y, EYE_H } from "../.verify/led/face.js";
import { INK } from "../.verify/led/grid.js";
import { DOMAIN_DROP, SUMMON_TAIL_MS } from "../.verify/led/summon.js";
import { REACTIONS } from "../.verify/face/reactions.js";
import { ACTIVITIES, ACTIVITY_LOOP_MS, IDLE_ACTIVITIES } from "../.verify/face/activity.js";
import { SCENES } from "../.verify/led/scenes.js";
import { scoreOn } from "../.verify/led/score.js";

let failures = 0;
const check = (ok, label) => {
  if (!ok) {
    failures += 1;
    console.error(`FAIL led: ${label}`);
  }
};

const NOW = 100000;
const base = {
  state: "listening",
  emotion: "neutral",
  level: 0,
  now: NOW,
  blinking: false,
  muted: false,
  reaction: null,
  activity: null,
  summon: null,
};

function frameOf(over) {
  const f = new Frame();
  compose(f, { ...base, ...over });
  return f;
}

const lit = (f) => f.value.reduce((n, v) => n + (v > 0.05 ? 1 : 0), 0);
const diff = (a, b) => a.value.reduce((n, v, i) => n + (Math.abs(v - b.value[i]) > 0.1 ? 1 : 0), 0);
const allFinite = (f) => f.value.every((v) => Number.isFinite(v) && v >= 0 && v <= 1.0001);

const plain = frameOf({});
check(lit(plain) > 300, `plain face lights enough cells (${lit(plain)})`);
check(allFinite(plain), "plain face values are 0..1");

// gestures: each changes the picture substantially and stays well-formed
for (const name of REACTIONS) {
  const f = frameOf({ reaction: { name, at: NOW - 1000 } });
  check(allFinite(f), `${name}: values 0..1`);
  check(diff(f, plain) > 120, `${name}: visibly different from the plain face (${diff(f, plain)} cells)`);
  // the start of the fade-in and after the end both look like the plain face
  check(diff(frameOf({ reaction: { name, at: NOW + 5 } }), plain) === 0, `${name}: not drawn before it starts`);
  check(diff(frameOf({ reaction: { name, at: NOW - 5000 } }), plain) === 0, `${name}: gone after it ends`);
}

// a "big" reaction (her answer to "what are you doing?" after a signature
// entrance): the same pose with her whole body moving further, over the hop
for (const name of ["cool", "giggle", "taDa", "handsUp", "excitedBounce", "facepalm", "thinking", "shrug", "yawn"]) {
  let most = 0;
  for (const t of [200, 350, 500, 700, 1000]) {
    const normal = frameOf({ reaction: { name, at: NOW - t } });
    const big = frameOf({ reaction: { name, at: NOW - t, big: true } });
    check(allFinite(big), `${name} big: values 0..1`);
    most = Math.max(most, diff(big, normal));
  }
  check(most > 40, `${name} big: her body visibly moves more than the normal one (${most} cells)`);
}

// scenes: animate over the loop, keep eyes on the matrix
for (const name of ACTIVITIES) {
  const frames = [0.1, 0.35, 0.6, 0.85].map((p) => frameOf({ activity: { name, at: NOW - ACTIVITY_LOOP_MS[name] * p } }));
  frames.forEach((f, i) => check(allFinite(f), `${name}[${i}]: values 0..1`));
  let moving = 0;
  for (let i = 1; i < frames.length; i += 1) moving += diff(frames[i], frames[i - 1]);
  // a tool prop is a small thing beside her face; a scene is her whole body moving
  const enough = IDLE_ACTIVITIES.includes(name) ? 150 : 60;
  check(moving > enough, `${name}: animates (${moving} cells changed across the loop)`);
  const eyesLit = frames.every((f) => {
    let n = 0;
    for (let y = EYE_Y; y < EYE_Y + EYE_H; y += 1) for (let x = LEFT_EYE_X; x < RIGHT_EYE_X + EYE_W; x += 1) if (f.value[y * COLS + x] > 0.5) n += 1;
    return n > 40;
  });
  check(eyesLit, `${name}: her eyes stay visible`);
  // loops: one full period later is the same picture (after any intro, which
  // plays once - kamae's suiting up)
  const intro = SCENES[name].introMs ?? 0;
  const a = frameOf({ activity: { name, at: NOW - intro - 1234 } });
  const b = frameOf({ activity: { name, at: NOW - intro - 1234 - (ACTIVITY_LOOP_MS[name] - intro) } });
  check(diff(a, b) === 0, `${name}: loops cleanly`);
}

// summon: visor hides both eyes during part 1; on part 2 one eye is revealed in
// ice-blue while the band stays over the other; afterwards both are normal again
// (during the domain her face sits DOMAIN_DROP rows lower, under her hair: `drop`)
const eye = (f, x0, drop = 0) => {
  let max = 0;
  let ice = 0;
  // inner rows only: the band's bright edge runs along the eye box's border
  for (let y = EYE_Y + 2 + drop; y < EYE_Y + EYE_H - 2 + drop; y += 1) {
    for (let x = x0 + 2; x < x0 + EYE_W - 2; x += 1) {
      const i = y * COLS + x;
      max = Math.max(max, f.value[i]);
      if (f.value[i] > 0.5 && (f.ink[i] === INK.iceCore || f.ink[i] === INK.iceRing)) ice += 1;
    }
  }
  return { max, ice };
};
const speaking = { state: "speaking", emotion: "happy", level: 0.5 };
const visor = frameOf({ ...speaking, summon: { start: NOW - 1500, part2: null } });
check(eye(visor, LEFT_EYE_X, DOMAIN_DROP).max <= 0.45 && eye(visor, RIGHT_EYE_X, DOMAIN_DROP).max <= 0.45,
  `visor hides both eyes (${eye(visor, LEFT_EYE_X, DOMAIN_DROP).max.toFixed(2)}, ${eye(visor, RIGHT_EYE_X, DOMAIN_DROP).max.toFixed(2)})`);
const held = frameOf({ ...speaking, summon: { start: NOW - 4500, part2: NOW - 1400 } });
check(eye(held, LEFT_EYE_X, DOMAIN_DROP).ice > 40, `revealed eye glows ice-blue (${eye(held, LEFT_EYE_X, DOMAIN_DROP).ice} ice cells)`);
check(eye(held, RIGHT_EYE_X, DOMAIN_DROP).ice === 0, "the other eye is not ice");
const after = frameOf({ ...speaking, summon: { start: NOW - 9000, part2: NOW - SUMMON_TAIL_MS - 10 } });
check(eye(after, LEFT_EYE_X).max > 0.9 && eye(after, RIGHT_EYE_X).max > 0.9, "both eyes back after the sequence");
check(eye(after, LEFT_EYE_X).ice === 0, "no ice left after the sequence");
const hand = diff(frameOf({ ...speaking, summon: { start: NOW - 1500, part2: null } }), frameOf({ ...speaking }));
check(hand > 200, `sequence draws visor and hand (${hand} cells)`);

// status glyph
check(diff(frameOf({ muted: true }), plain) > 10, "muted shows a glyph");

// geometry sanity
check(COLS === 128 && ROWS === 72, "matrix is 128x72");

// voice on her face: nothing while asleep; a mic while listening; the countdown bar
// along the bottom shrinks as the end-of-speech wait runs out
{
  const at = (voice, extra = 0) => {
    const f = new Frame();
    compose(f, { state: "listening", emotion: "neutral", level: 0, now: 90000 + extra, blinking: false, muted: false, reaction: null, activity: null, summon: null, voice });
    return f;
  };
  const lit = (f, y0, y1, x0 = 0, x1 = COLS) => {
    let n = 0;
    for (let y = y0; y < y1; y += 1) for (let x = x0; x < x1; x += 1) if (f.value[y * COLS + x] > 0.3) n += 1;
    return n;
  };
  const plain = at(null);
  // every mic state is visible, and each one looks different: he can always tell
  // whether she hears him
  const asleep = at({ phase: "asleep", at: 90000 });
  const off = at({ phase: "off", at: 90000 });
  const listening = at({ phase: "listening", at: 90000 });
  check(diff(asleep, plain) > 8, "voice: asleep shows a faint mic");
  check(diff(off, plain) > 8, "voice: no microphone shows a struck-out mic");
  check(diff(asleep, listening) > 8 && diff(off, listening) > 8 && diff(off, asleep) > 8, "voice: listening, asleep and off all look different");
  check(lit(at({ phase: "listening", at: 90000 }), 0, 14, 0, 12) > lit(plain, 0, 14, 0, 12) + 8, "voice: a mic in the corner while listening");
  const silence = { phase: "silence", at: 90000, remainingMs: 3000, totalMs: 3000 };
  const full = lit(at(silence), ROWS - 2, ROWS);
  const half = lit(at(silence, 1500), ROWS - 2, ROWS);
  const gone = lit(at(silence, 3100), ROWS - 2, ROWS);
  check(full > 100 && half < full * 0.7 && half > 20 && gone === lit(plain, ROWS - 2, ROWS), `voice: the countdown runs down (${full} -> ${half} -> ${gone})`);
  const h1 = at({ phase: "hearing", at: 90000 });
  const h2 = at({ phase: "hearing", at: 90000 }, 140);
  check(diff(h1, h2) > 0, "voice: sound bars move while he talks");
}

// ONE scene at a time: with two live, the frame is exactly the newest one alone
{
  const scene = { name: "chess", at: NOW - 600 };
  const entrance = { name: "kendo", at: NOW - 1200 };
  const both = frameOf({ activity: scene, entrance });
  check(diff(both, frameOf({ activity: scene })) === 0, "one scene: a newer activity clears the entrance under it");
  const later = { name: "kendo", at: NOW - 300 };
  const both2 = frameOf({ activity: scene, entrance: later });
  check(diff(both2, frameOf({ entrance: later })) === 0, "one scene: a newer entrance clears the activity under it");
  const summon = { start: NOW - 200, part2: null };
  check(diff(frameOf({ activity: scene, entrance, summon }), frameOf({ summon })) === 0, "one scene: the summon, newest, is the only one drawn");
}

// shiai's scoreboard: on the left of the dojo, only in the dojo; the side that just
// scored is the one that flashes; the bout's end takes it down
{
  const dojo = { name: "keiko", at: NOW - 9000 };
  let s = scoreOn(null, { action: "start" }, NOW - 5000);
  check(s && s.you === 0 && s.her === 0 && s.scored === null, "shiai start: 0-0");
  s = scoreOn(s, { action: "score", you: 1, her: 0 }, NOW - 100);
  check(s.you === 1 && s.her === 0 && s.scored === "you", "his point: 1-0, his side flashes");
  check(scoreOn(s, { action: "score", you: 1, her: 1 }, NOW).scored === "her", "her point: her side flashes");
  check(scoreOn(s, { action: "end" }, NOW) === null, "the bout's end takes the score down");
  const withScore = frameOf({ activity: dojo, score: s });
  const without = frameOf({ activity: dojo });
  let left = 0;
  let right = 0;
  for (let y = 0; y < ROWS; y += 1) {
    for (let x = 0; x < COLS; x += 1) {
      if (Math.abs(withScore.value[y * COLS + x] - without.value[y * COLS + x]) > 0.01) {
        if (x < 34) left += 1;
        else right += 1;
      }
    }
  }
  check(left > 60 && right === 0, `the score draws on the left of the dojo only (${left} left, ${right} elsewhere)`);
  check(diff(frameOf({ score: s }), frameOf({})) === 0, "no dojo, no scoreboard");
}

if (failures > 0) {
  console.error(`led: ${failures} failure(s)`);
  process.exit(1);
} else {
  console.log(`led: ok (${REACTIONS.length} gestures, ${ACTIVITIES.length} scenes, summon sequence)`);
}
