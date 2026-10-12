// Summon entrances against their registry (config/entrances.json): every entry but
// domain_expansion has art and the same length, each runs 5.8 s over a backdrop that
// exists, draws something of its own, moves, stays well-formed, and hands back to
// the plain listening face.
import { readFileSync } from "node:fs";
import { Frame } from "../.verify/led/grid.js";
import { compose } from "../.verify/led/compose.js";
import { ENTRANCES, ENTRANCE_NAMES } from "../.verify/led/entrances.js";
import { BACKDROPS } from "../.verify/led/backdrops.js";

let failures = 0;
const check = (ok, label) => {
  if (!ok) {
    failures += 1;
    console.error(`FAIL entrances: ${label}`);
  }
};

const { entrances } = JSON.parse(readFileSync(new URL("../../config/entrances.json", import.meta.url), "utf8"));
const registered = entrances.filter((e) => e.name !== "domain_expansion");
check(entrances.some((e) => e.name === "domain_expansion"), "domain_expansion stays in the pool");
for (const e of registered) {
  check(ENTRANCE_NAMES.includes(e.name), `registry entrance "${e.name}" has no art`);
  if (ENTRANCES[e.name]) check(ENTRANCES[e.name].ms === e.ms, `${e.name}: art is ${ENTRANCES[e.name].ms} ms, registry says ${e.ms}`);
}
for (const name of ENTRANCE_NAMES) check(registered.some((e) => e.name === name), `entrance art "${name}" has no registry entry`);

const NOW = 200000;
const base = { state: "listening", emotion: "neutral", level: 0, now: NOW, blinking: false, muted: false, reaction: null, activity: null, summon: null };
const frameAt = (name, elapsed, over = {}) => {
  const f = new Frame();
  compose(f, { ...base, ...over, entrance: name ? { name, at: NOW - elapsed } : null });
  return f;
};
const diff = (a, b) => a.value.reduce((n, v, i) => n + (Math.abs(v - b.value[i]) > 0.1 ? 1 : 0), 0);
const wellFormed = (f) => f.value.every((v) => Number.isFinite(v) && v >= 0 && v <= 1.0001);
const plain = frameAt(null, 0);

for (const name of ENTRANCE_NAMES) {
  const { ms, backdrop } = ENTRANCES[name];
  check(ms >= 5500 && ms <= 6500, `${name}: as long as the domain expansion, 5.8 s (${ms} ms)`);
  check(Boolean(BACKDROPS[backdrop]), `${name}: backdrop "${backdrop}" has no art`);
  const samples = [0.05, 0.2, 0.35, 0.5, 0.65, 0.8, 0.95].map((p) => frameAt(name, ms * p, { state: "speaking", level: 0.3 }));
  samples.forEach((f, i) => check(wellFormed(f), `${name}[${i}]: values 0..1`));
  const drawn = Math.max(...samples.map((f) => diff(f, plain)));
  check(drawn > 250, `${name}: draws its own picture (${drawn} cells off the plain face)`);
  let moving = 0;
  for (let i = 1; i < samples.length; i += 1) moving += diff(samples[i], samples[i - 1]);
  check(moving > 400, `${name}: moves (${moving} cells changed across it)`);
  check(diff(frameAt(name, ms + 5), plain) === 0, `${name}: ends on the plain listening face`);
  check(diff(frameAt(name, -5), plain) === 0, `${name}: nothing before it starts`);
}

if (failures > 0) {
  console.error(`entrances: ${failures} failure(s)`);
  process.exit(1);
} else {
  console.log(`entrances: ok (${ENTRANCE_NAMES.length} + domain_expansion, ${ENTRANCE_NAMES.map((n) => `${n} ${ENTRANCES[n].ms}`).join(", ")})`);
}
