import {
  GestureEngine,
  CROSS_GAP_CLEAR,
  CROSS_GAP_LATCH,
  DWELL_HOLD_MS,
  DWELL_RADIUS,
  POINT_MIDDLE_CURL_LATCH_RATIO,
  SCROLL_MIDDLE_EXTEND_LATCH_RATIO,
  SUMMON_GRACE_MS,
  SUMMON_HOLD_MS,
  PINCH_LATCH_RATIO,
  THUMB_CLEAR_LATCH_RATIO,
  TRANSITION_LOCKOUT_MS,
  ZOOM_HOLD_MS,
  ZOOM_OPEN_FINGER_RATIO,
  ZOOM_SPREAD_CLOSED,
} from "../.verify/gestures.js";

const FRAME = 33;
const WRIST = { x: 0.5, y: 0.8 };
const PALM = 0.16;

let pass = 0;
let fail = 0;

function check(name, cond, detail = "") {
  if (cond) {
    pass += 1;
    return;
  }
  fail += 1;
  console.log(`  FAIL ${name} ${detail}`);
}

function lerp(a, b, t) {
  return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
}

// tipShift moves a finger's tip sideways without moving its knuckle,
// which is how the crossed-finger sign is built.
function buildHand({ curl, thumbTip, thumbSide = -1, dx = 0, dy = 0, tipShift = [0, 0, 0, 0] }) {
  const w = { x: WRIST.x + dx, y: WRIST.y + dy };
  const mcpY = w.y - PALM;
  const offs = [0.05, 0.017, -0.017, -0.05];
  const lm = new Array(21);
  lm[0] = { x: w.x, y: w.y, z: 0, visibility: 1 };

  const tt = { x: thumbTip.x + dx, y: thumbTip.y + dy };
  for (let j = 1; j <= 4; j += 1) {
    const p = lerp(w, tt, j / 4);
    lm[j] = { x: p.x, y: p.y, z: 0, visibility: 1 };
  }

  for (let f = 0; f < 4; f += 1) {
    const base = 5 + f * 4;
    const mx = w.x + thumbSide * offs[f];
    const c = curl[f];
    const shift = tipShift[f] ?? 0;
    lm[base] = { x: mx, y: mcpY, z: 0, visibility: 1 };
    lm[base + 1] = { x: mx, y: mcpY - 0.06, z: 0, visibility: 1 };
    lm[base + 2] = { x: mx + shift * 0.6, y: mcpY - 0.1 * (1 - c), z: 0, visibility: 1 };
    lm[base + 3] = { x: mx + shift, y: mcpY - 0.14 * (1 - c), z: 0, visibility: 1 };
  }
  return lm;
}

const CURLED = [1, 1, 1, 1];
const THUMB_TUCKED = { x: WRIST.x - 0.02, y: WRIST.y - 0.12 };
const THUMB_WIDE = { x: WRIST.x - 0.19, y: WRIST.y - 0.1 };

function indexTip() {
  return { x: WRIST.x - 0.05, y: WRIST.y - PALM - 0.14 };
}

function pointingHand(middleCurl = 1) {
  return buildHand({ curl: [0, middleCurl, 1, 1], thumbTip: THUMB_TUCKED });
}

function scrollHand(dy = 0) {
  return buildHand({ curl: [0, 0, 1, 1], thumbTip: THUMB_TUCKED, dy });
}

// crossed: index rides over middle so the TIPS converge far closer than the knuckles
function summonHand(dy = 0) {
  return buildHand({
    curl: [0, 0, 1, 1],
    thumbTip: THUMB_TUCKED,
    dy,
    tipShift: [0.025, -0.02, 0, 0],
  });
}

// peace sign: two fingers splayed apart, the most uncrossed pose there is
function peaceHand() {
  return buildHand({
    curl: [0, 0, 1, 1],
    thumbTip: THUMB_TUCKED,
    tipShift: [-0.03, 0.03, 0, 0],
  });
}

function openHand(extra = 0) {
  return buildHand({
    curl: [-extra, -extra, -extra, -extra],
    thumbTip: { x: THUMB_WIDE.x - extra * 0.12, y: THUMB_WIDE.y },
  });
}

function closedHand() {
  return buildHand({ curl: CURLED, thumbTip: { x: WRIST.x - 0.03, y: WRIST.y - PALM + 0.02 } });
}

function relaxedHand(jitter = 0) {
  return buildHand({
    curl: [0.55 + jitter, 0.6 + jitter, 0.65 + jitter, 0.7 + jitter],
    thumbTip: { x: WRIST.x - 0.06 + jitter * 0.01, y: WRIST.y - 0.14 },
  });
}

const H = (lm, handedness = "Right") => ({ landmarks: lm, handedness });

function run(frames) {
  const engine = new GestureEngine();
  const cursor = { x: 0.5, y: 0.5 };
  let ts = 1000;
  const log = [];
  for (const frame of frames) {
    if (frame.cursor) {
      cursor.x = frame.cursor.x;
      cursor.y = frame.cursor.y;
    }
    const state = engine.update({
      hand: frame.hand ?? null,
      cursor,
      timestamp: ts,
      tracking: frame.tracking !== false,
    });
    log.push({ ...state, ts });
    ts += FRAME;
  }
  return log;
}

function repeat(n, make) {
  return Array.from({ length: n }, (_, i) => make(i));
}

const metricsOf = (hand) => run([{ hand: H(hand) }])[0];

console.log("0. pose metric separation");
{
  const poses = {
    open: openHand(),
    closed: closedHand(),
    relaxed: relaxedHand(),
    pointing: pointingHand(),
    scroll: scrollHand(),
    summon: summonHand(),
    peace: peaceHand(),
  };
  for (const [name, hand] of Object.entries(poses)) {
    const m = metricsOf(hand);
    console.log(
      `   ${name.padEnd(9)} spread=${m.spread.toFixed(3)} cross=${m.crossing.toFixed(3)} ` +
        `gap=${m.thumbIndexRatio.toFixed(3)} idx=${m.indexExtension.toFixed(2)} mid=${m.middleExtension.toFixed(2)}`,
    );
  }

  const spread = (h) => metricsOf(h).spread;
  // Zoom no longer gates on these numbers - the classifier does (led by
  // tracking/zoomFeatures.ts, checked on real captured hands in zoom.verify.mjs).
  // They stay as a readout: a hand-built pose with z = 0 on every landmark cannot
  // tell you anything about a model trained on real tracking.
  {
    const o = metricsOf(poses.open);
    const sc = metricsOf(poses.scroll);
    const openMin = Math.min(o.diag.thumb, o.diag.index, o.diag.middle, o.diag.ring, o.diag.pinky);
    const scrollMax = Math.max(sc.diag.ring, sc.diag.pinky);
    console.log(
      `   ZOOM open gate: weakest open finger=${openMin.toFixed(3)} (needs >${ZOOM_OPEN_FINGER_RATIO}), ` +
        `scroll ring/pinky max=${scrollMax.toFixed(3)} -> separation ${(openMin - scrollMax).toFixed(3)}`,
    );
  }
  // Whether a pose falsely latches zoom is answered on real hands, in
  // zoom.verify.mjs - relaxed, pointing, the scroll pose, waving and scratching,
  // each a whole captured take.
  for (const name of ["scroll", "peace", "summon"]) {
    const m = metricsOf(poses[name]);
    console.log(
      `   BONE ${name.padEnd(7)} tipSeg: ${m.diag.boneTip}   dipSeg: ${m.diag.boneDip}`,
    );
  }

  // the gate's signal: tip-bone gap in palm spans, 0 when the bones intersect
  const gap = (h) => metricsOf(h).crossGap;
  console.log(
    `   BONE gap: plain=${gap(poses.scroll).toFixed(3)} peace=${gap(poses.peace).toFixed(3)} ` +
      `crossed=${gap(poses.summon).toFixed(3)} (crossed<${CROSS_GAP_LATCH} clear>${CROSS_GAP_CLEAR})`,
  );
  check("plain two-finger reads uncrossed", gap(poses.scroll) > CROSS_GAP_CLEAR,
    `plain=${gap(poses.scroll).toFixed(3)}`);
  check("peace sign reads uncrossed", gap(poses.peace) > CROSS_GAP_CLEAR,
    `peace=${gap(poses.peace).toFixed(3)}`);
  check("crossed pose reads crossed", gap(poses.summon) < CROSS_GAP_LATCH,
    `crossed=${gap(poses.summon).toFixed(3)}`);
  check("latch and clear leave a hysteresis band", CROSS_GAP_LATCH < CROSS_GAP_CLEAR);
  check("point pose has no thumb-index contact",
    metricsOf(poses.pointing).thumbIndexRatio > THUMB_CLEAR_LATCH_RATIO);
}

console.log("1. mutual exclusion across the whole set");
{
  const log = run([
    ...repeat(20, () => ({ hand: H(pointingHand()) })),
    ...repeat(20, () => ({ hand: H(scrollHand()) })),
    ...repeat(30, () => ({ hand: H(summonHand()) })),
    ...repeat(20, () => ({ hand: H(openHand()) })),
    ...repeat(20, () => ({ hand: H(closedHand()) })),
    ...repeat(10, () => ({ hand: null })),
  ]);

  let bad = 0;
  for (const s of log) {
    const active = [s.pointing, s.scroll, s.zoom, s.summon].filter(Boolean).length;
    if (active > 1) bad += 1;
  }
  check("never more than one gesture active", bad === 0, `violations=${bad}`);
  check("pointing observed", log.some((s) => s.pointing));
  check("scroll observed", log.some((s) => s.scroll));
  check("summon observed", log.some((s) => s.summon));
}

console.log("2. SCROLL vs SUMMON - the critical pair");
{
  const scrolling = run(repeat(60, () => ({ hand: H(scrollHand()) })));
  check("a plain two-finger pose NEVER fires summon",
    scrolling.every((s) => !s.summon) && scrolling[scrolling.length - 1].summonCount === 0);
  check("plain two-finger pose does scroll", scrolling.some((s) => s.scroll));

  const crossed = run(repeat(60, () => ({ hand: H(summonHand()) })));
  check("a crossed pose NEVER starts scrolling", crossed.every((s) => !s.scroll));
  check("crossed pose fires summon", crossed.some((s) => s.summon));
  check("neither latches while the other is latched",
    scrolling.concat(crossed).every((s) => !(s.scroll && s.summon)));

  const handover = run([
    ...repeat(30, () => ({ hand: H(summonHand()) })),
    ...repeat(30, () => ({ hand: H(scrollHand()) })),
  ]);
  check("summon -> scroll handover stays exclusive",
    handover.every((s) => !(s.scroll && s.summon)));
  check("scroll takes over after uncrossing", handover[handover.length - 1].scroll);
}

console.log("3. SUMMON fires once and needs release");
{
  const held = run(repeat(80, () => ({ hand: H(summonHand()) })));
  check("fires exactly once while held", held[held.length - 1].summonCount === 1,
    `count=${held[held.length - 1].summonCount}`);
  const at = held.findIndex((s) => s.summon);
  check("waits out the 600ms hold", held[at].ts - held[0].ts >= SUMMON_HOLD_MS,
    `t=${held[at].ts - held[0].ts}`);

  const twice = run([
    ...repeat(35, () => ({ hand: H(summonHand()) })),
    ...repeat(12, () => ({ hand: H(relaxedHand()) })),
    ...repeat(35, () => ({ hand: H(summonHand()) })),
  ]);
  check("re-fires only after releasing the pose",
    twice[twice.length - 1].summonCount === 2, `count=${twice[twice.length - 1].summonCount}`);
}

console.log("3b. SUMMON hold survives brief dropouts");
{
  // middle finger foreshortens while crossed: drop the pose 1 frame in 4
  const flicker = run(
    repeat(60, (i) => ({ hand: H(i % 4 === 3 ? scrollHand() : summonHand()) })),
  );
  check("a 1-in-4 dropout still fires summon", flicker[flicker.length - 1].summonCount >= 1,
    `count=${flicker[flicker.length - 1].summonCount}`);

  // sustained loss past the grace resets the timer
  const sustained = run([
    ...repeat(10, () => ({ hand: H(summonHand()) })),
    ...repeat(10, () => ({ hand: H(scrollHand()) })),
    ...repeat(10, () => ({ hand: H(summonHand()) })),
  ]);
  check("a sustained loss resets the hold", sustained.every((s) => s.summonCount === 0),
    `count=${sustained[sustained.length - 1].summonCount}`);

  check("grace is shorter than the hold", SUMMON_GRACE_MS < SUMMON_HOLD_MS);

  // hysteresis: once crossed, a dip that stays above the clear threshold holds
  const plain = run(repeat(60, () => ({ hand: H(scrollHand()) })));
  check("a plain pose still never fires summon", plain.every((s) => s.summonCount === 0));
}

console.log("3c. low-power summon-only mode");
{
  const engine = new GestureEngine();
  const cursor = { x: 0.5, y: 0.5 };
  let ts = 1000;
  const log = [];
  for (let i = 0; i < 40; i += 1) {
    const state = engine.update({
      hand: H(summonHand()),
      cursor,
      timestamp: ts,
      tracking: false,
      summonOnly: true,
    });
    log.push({ ...state });
    ts += 100; // 10fps
  }
  check("summon fires in low-power mode", log[log.length - 1].summonCount === 1,
    `count=${log[log.length - 1].summonCount}`);
  check("no other gesture evaluates while low-power",
    log.every((s) => !s.pointing && !s.scroll && !s.zoom));
  check("no cursor/scroll/zoom output while low-power",
    log.every((s) => s.scrollPointY === 0 && s.zoomFactor === 1 && s.dwellProgress === 0));

  const idleEngine = new GestureEngine();
  let ts2 = 1000;
  const idleLog = [];
  for (let i = 0; i < 40; i += 1) {
    idleLog.push({
      ...idleEngine.update({
        hand: H(relaxedHand(Math.sin(i) * 0.03)),
        cursor,
        timestamp: ts2,
        tracking: false,
        summonOnly: true,
      }),
    });
    ts2 += 100;
  }
  check("a resting hand never summons in low-power mode",
    idleLog.every((s) => s.summonCount === 0 && !s.summon));
}

// 5, 5b and 5c used to drive zoom from hand-built poses: the per-finger
// uniformity gate, its dropout grace, and the hysteresis that stopped a finger
// flickering on its threshold. None of those gate zoom any more - a classifier
// does (tracking/zoomFeatures.ts) - and a pose with z = 0 on every landmark
// cannot test a model trained on real tracking. The behaviour they protected is
// checked in zoom.verify.mjs against whole captured takes instead: the fist and
// the spread latch, an in and an out stay latched with zoomFactor tracking them,
// the five confusers never hold a latch, and the release paths still release.

console.log("6. POINT vs SCROLL dead band still holds");
{
  const samples = [];
  for (let c = 0; c <= 1.0001; c += 0.02) {
    const log = run(repeat(12, () => ({ hand: H(pointingHand(1 - c)) })));
    const last = log[log.length - 1];
    samples.push({ middle: last.middleExtension, pointing: last.pointing, scroll: last.scroll });
  }
  check("no sample is both", samples.every((s) => !(s.pointing && s.scroll)));
  check("pointing stays below its threshold",
    samples.filter((s) => s.pointing).every((s) => s.middle < POINT_MIDDLE_CURL_LATCH_RATIO));
  check("scroll stays above its threshold",
    samples.filter((s) => s.scroll).every((s) => s.middle > SCROLL_MIDDLE_EXTEND_LATCH_RATIO));
  const inBand = samples.filter(
    (s) => s.middle > POINT_MIDDLE_CURL_LATCH_RATIO && s.middle < SCROLL_MIDDLE_EXTEND_LATCH_RATIO,
  );
  check("dead band reachable and inert",
    inBand.length > 0 && inBand.every((s) => !s.pointing && !s.scroll));
}

console.log("7. dwell select unchanged");
{
  const log = run(repeat(60, () => ({ hand: H(pointingHand()) })));
  const fires = log.filter((s) => s.dwellFired);
  const at = log.findIndex((s) => s.dwellFired);
  check("fires exactly once", fires.length === 1);
  check("fires at ~600ms",
    log[at].ts - log[0].ts >= DWELL_HOLD_MS && log[at].ts - log[0].ts <= DWELL_HOLD_MS + 4 * FRAME);

  const moved = run([
    ...repeat(10, () => ({ hand: H(pointingHand()), cursor: { x: 0.5, y: 0.5 } })),
    ...repeat(6, () => ({ hand: H(pointingHand()), cursor: { x: 0.5 + DWELL_RADIUS * 2, y: 0.5 } })),
  ]);
  check("leaving the radius resets progress", moved[10].dwellProgress === 0);

  const untracked = run(repeat(60, () => ({ hand: H(pointingHand()), tracking: false })));
  check("no dwell without tracking", untracked.every((s) => !s.dwellFired));
}

console.log("8. transition lockout");
{
  const log = run([
    ...repeat(20, () => ({ hand: H(pointingHand()) })),
    { hand: null },
    ...repeat(10, () => ({ hand: H(pointingHand()) })),
  ]);
  const blocked = log.slice(20, 20 + Math.ceil(TRANSITION_LOCKOUT_MS / FRAME));
  check("nothing latches during lockout",
    blocked.every((s) => !s.pointing && !s.scroll && !s.zoom && !s.summon));
  check("pointing recovers after lockout", log[log.length - 1].pointing);
}

console.log("9. a resting hand latches NOTHING (60s)");
{
  const idle = run(repeat(1800, (i) => ({ hand: H(relaxedHand(Math.sin(i / 7) * 0.03)) })));
  check("60s of idle tracking latches nothing",
    idle.every((s) => !s.pointing && !s.scroll && !s.summon));
  check("no counters advance",
    idle[idle.length - 1].selectCount === 0 && idle[idle.length - 1].summonCount === 0);
  // zoom on a resting hand is answered on a real relaxed take (zoom.verify.mjs);
  // what this file still owns is that none of the OTHER gestures wake up
  check("no other gesture wakes up",
    idle.every((s) => !["pointing", "dwelling", "scroll", "summon"].includes(s.mode)));
}

console.log("10. scroll reports a tracked position");
{
  const high = run([
    ...repeat(6, () => ({ hand: H(scrollHand(0)) })),
    ...repeat(30, () => ({ hand: H(scrollHand(-0.18)) })),
  ]);
  check("scroll latches", high.some((s) => s.scroll));
  check("tracks the hand upward", high.slice(-10).every((s) => s.scrollPointY < 0.5));

  const low = run([
    ...repeat(6, () => ({ hand: H(scrollHand(0)) })),
    ...repeat(30, () => ({ hand: H(scrollHand(0.18)) })),
  ]);
  check("tracks the hand downward", low.slice(-10).every((s) => s.scrollPointY > 0.6));

  const settled = low.slice(-15).map((s) => s.scrollPointY);
  check("holding a position keeps reporting it",
    Math.max(...settled) - Math.min(...settled) < 0.01);

  const dropped = run([
    ...repeat(20, () => ({ hand: H(scrollHand(0.18)) })),
    ...repeat(8, () => ({ hand: H(pointingHand()) })),
  ]);
  const last = dropped[dropped.length - 1];
  check("dropping the pose stops immediately", last.scroll === false && last.scrollPointY === 0);
}

console.log("11. pinch is an instant click - once per pinch, never at rest");
{
  // thumb tip brought onto the index tip of a pointing hand
  const pinchHand = (gap = 0) => {
    const lm = pointingHand().map((p) => ({ ...p }));
    lm[4] = { x: lm[8].x + gap, y: lm[8].y + gap, z: lm[8].z };
    return lm;
  };
  const twice = run([
    ...repeat(10, () => ({ hand: H(pointingHand()) })),
    ...repeat(6, () => ({ hand: H(pinchHand()) })),
    ...repeat(10, () => ({ hand: H(pointingHand()) })),
    ...repeat(30, () => ({ hand: H(pinchHand()) })),
  ]);
  check("two pinches are two clicks (a held pinch is one)", twice[twice.length - 1].pinchCount === 2, `got ${twice[twice.length - 1].pinchCount}`);
  check("pinching reports while held", twice[twice.length - 1].pinching === true);
  const idle = run(repeat(1800, (i) => ({ hand: H(relaxedHand(Math.sin(i / 7) * 0.03)) })));
  check("60s of a resting hand never pinches", idle[idle.length - 1].pinchCount === 0);
  // every fingertip bunched together (zoom-closed): not a pinch
  const bunched = run(repeat(20, () => {
    const lm = pinchHand().map((p) => ({ ...p }));
    lm[12] = { ...lm[8] };
    return { hand: H(lm) };
  }));
  check("a bunched hand is not a pinch", bunched[bunched.length - 1].pinchCount === 0);
  check("latch threshold is tight", PINCH_LATCH_RATIO <= 0.25);
  // a pinch with no pointing before it (a resting hand's thumb on its index) is no click
  const unaimed = run(repeat(40, () => ({ hand: H(pinchHand()) })));
  check("a pinch without pointing first does not click", unaimed[unaimed.length - 1].pinchCount === 0);
}

console.log(`\n${pass} passed, ${fail} failed`);
// keeps a failure the earlier verify files set on process.exitCode - exiting 0 here hid them
process.exit(fail === 0 ? (process.exitCode ?? 0) : 1);
