import {
  REACTIONS,
  REACTION_LABEL,
  REACTION_MS,
  REACTION_FADE_IN_MS,
  REACTION_FADE_OUT_MS,
  reactionEnvelope,
  isReaction,
} from "../.verify/face/reactions.js";

let failures = 0;
const check = (ok, label) => {
  if (!ok) {
    failures += 1;
    console.error(`FAIL reactions: ${label}`);
  }
};

check(REACTIONS.length >= 15, `at least fifteen reactions, got ${REACTIONS.length}`);
check(new Set(REACTIONS).size === REACTIONS.length, "reaction names are unique");
for (const name of REACTIONS) {
  check(typeof REACTION_LABEL[name] === "string" && REACTION_LABEL[name].length > 0, `${name} has a label`);
}

// envelope: dark before/after, full in the hold, monotonic ramps, ~2s total
check(REACTION_MS >= 1800 && REACTION_MS <= 2200, "reaction lasts about two seconds");
check(reactionEnvelope(0) === 0, "envelope starts dark");
check(reactionEnvelope(REACTION_MS) === 0, "envelope ends dark");
check(reactionEnvelope(REACTION_MS / 2) === 1, "envelope holds full");
// rAF time can trail the trigger stamp, so elapsed arrives slightly negative
check(reactionEnvelope(-7) === 0, "negative elapsed is dark, not NaN");
let last = 0;
for (let t = 0; t <= REACTION_FADE_IN_MS; t += 10) {
  const value = reactionEnvelope(t);
  check(value >= last, `fade-in monotonic at ${t}`);
  last = value;
}
last = 1;
for (let t = REACTION_MS - REACTION_FADE_OUT_MS; t <= REACTION_MS; t += 10) {
  const value = reactionEnvelope(t);
  check(value <= last, `fade-out monotonic at ${t}`);
  last = value;
}

check(isReaction("peace") && isReaction("thumbsUp") && isReaction("wave") && !isReaction("dab") && !isReaction(3), "isReaction guards names");

if (failures > 0) {
  console.error(`reactions: ${failures} failure(s)`);
  process.exit(1);
} else {
  console.log(`reactions: ok (${REACTIONS.length} gestures)`);
}
