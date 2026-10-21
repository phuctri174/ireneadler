// Her hand in rock-paper-scissors (src/led/gameHand.ts). The fairness rule: the three
// pumps of the count render IDENTICALLY whatever she sealed - her throw reaches the
// matrix only from the shoot instant. Core's exact message sequence for a round is
// replayed once per sealed throw, and the whole composed frame (face and hand) is
// compared cell for cell at every 10 ms of the count. Then: the shoot frame IS her
// throw, the pumps really move, and every glyph is its own.
import { Frame } from "../.verify/led/grid.js";
import { compose } from "../.verify/led/compose.js";
import { PUMP_DEPTH, gameHandOn, gameHandPose, glyphSprite } from "../.verify/led/gameHand.js";

let failures = 0;
const check = (ok, label) => {
  if (!ok) {
    failures += 1;
    console.error(`FAIL gameHand: ${label}`);
  }
};

const THROWS = ["rock", "paper", "scissors"];
// a round as core sends it (app.py _rps_count): the hand shown as the game starts,
// a beat as each counted word reaches the speaker (the clip's steady beat), then
// game_shoot carrying her throw on the fourth
const START = 1000;
const BEAT = 640;
const WORDS = [START + 2000, START + 2000 + BEAT, START + 2000 + 2 * BEAT];
const SHOOT = START + 2000 + 3 * BEAT;

function events(sealed) {
  return [
    [START, { kind: "show" }],
    ...WORDS.map((t, n) => [t, { kind: "beat", n }]),
    [SHOOT, { kind: "throw", glyph: sealed }],
  ];
}

function handAt(sealed, now) {
  let hand = null;
  for (const [t, event] of events(sealed)) if (t <= now) hand = gameHandOn(hand, event, t);
  return hand;
}

function render(sealed, now) {
  const f = new Frame();
  compose(f, { state: "speaking", emotion: "firedUp", emotionAt: START, level: 0.4, now, blinking: false, muted: false, reaction: null, activity: null, summon: null, gameHand: handAt(sealed, now) });
  return f;
}

const same = (a, b) => a.value.every((v, i) => v === b.value[i]) && a.ink.every((v, i) => v === b.ink[i]);
const lit = (f) => f.value.reduce((n, v) => n + (v > 0 ? 1 : 0), 0);

// 1. the count - from the hand fading in to the instant before shoot - is the same
//    picture whatever she sealed
{
  let compared = 0;
  let differs = 0;
  for (let now = START; now < SHOOT; now += 10) {
    const [rock, paper, scissors] = THROWS.map((s) => render(s, now));
    if (!same(rock, paper) || !same(rock, scissors)) differs += 1;
    compared += 1;
  }
  check(differs === 0, `the count renders the same for every sealed throw (${differs} of ${compared} moments differ)`);
  // and the hand's own pose, in every pump, is the neutral glyph
  for (const sealed of THROWS) {
    for (const t of WORDS) {
      for (let k = 0; k < BEAT; k += 20) {
        const pose = gameHandPose(handAt(sealed, t + k), t + k);
        if (pose.glyph !== "neutral") check(false, `pump at word ${t} +${k} ms shows ${pose.glyph} (sealed ${sealed})`);
      }
    }
  }
}

// 2. the shoot frame is her throw, at once - and three different pictures
{
  const frames = THROWS.map((s) => render(s, SHOOT));
  for (const [i, sealed] of THROWS.entries()) {
    check(gameHandPose(handAt(sealed, SHOOT), SHOOT).glyph === sealed, `on the shoot instant the hand is ${sealed}`);
    check(gameHandPose(handAt(sealed, SHOOT - 1), SHOOT - 1).glyph === "neutral", `1 ms before shoot it is still neutral (sealed ${sealed})`);
    check(!same(frames[i], frames[(i + 1) % 3]), `${sealed} and ${THROWS[(i + 1) % 3]} look different on shoot`);
  }
}

// 3. the pumps move: down on the word, back up before the next
{
  for (const t of WORDS) {
    const bottom = gameHandPose(handAt("rock", t + 90), t + 90);
    const before = gameHandPose(handAt("rock", t - 5), t - 5);
    check(bottom.dy === PUMP_DEPTH, `pump at ${t}: down ${bottom.dy} cells on the word`);
    check(before.dy === 0, `pump at ${t}: back up before it (${before.dy})`);
  }
  check(!same(render("rock", WORDS[1] + 90), render("rock", WORDS[1] - 5)), "a pump changes the picture");
}

// 4. the redo: shrug, then back to neutral; game over: gone
{
  let hand = handAt("paper", SHOOT + 2000);
  hand = gameHandOn(hand, { kind: "shrug" }, SHOOT + 2000);
  check(gameHandPose(hand, SHOOT + 2100).glyph === "neutral", "redo: her throw drops back first");
  check(gameHandPose(hand, SHOOT + 2800).glyph === "shrug", "redo: then the shrug");
  check(gameHandPose(hand, SHOOT + 5000).glyph === "neutral", "redo: then neutral, ready");
  hand = gameHandOn(hand, { kind: "beat", n: 0 }, SHOOT + 6000);
  check(gameHandPose(hand, SHOOT + 6000).glyph === "neutral", "next round's first pump is neutral");
  hand = gameHandOn(hand, { kind: "hide" }, SHOOT + 7000);
  const f = new Frame();
  compose(f, { state: "listening", emotion: "neutral", level: 0, now: SHOOT + 7400, blinking: false, muted: false, reaction: null, activity: null, summon: null });
  const g = new Frame();
  compose(g, { state: "listening", emotion: "neutral", level: 0, now: SHOOT + 7400, blinking: false, muted: false, reaction: null, activity: null, summon: null, gameHand: hand });
  check(same(f, g), "game over: the hand has faded out");
  check(gameHandOn(null, { kind: "throw", glyph: "rock" }, 0) === null, "a throw with no game hand up draws nothing");
}

// 5. five distinct glyphs, neutral unlike any throw
{
  const names = ["neutral", "rock", "paper", "scissors", "shrug"];
  const key = (n) => { const s = glyphSprite(n); return `${s.w}x${s.h}:${Array.from(s.cells).join(",")}`; };
  check(new Set(names.map(key)).size === names.length, "every glyph is its own");
  check(lit(render("rock", SHOOT + 500)) > lit(render("rock", START - 1)), "the hand is on the matrix");
}

if (failures > 0) {
  console.error(`gameHand: ${failures} failure(s)`);
  process.exit(1);
} else {
  console.log("gameHand: ok (the count is the same picture whatever she sealed; her throw from the shoot instant only)");
}
