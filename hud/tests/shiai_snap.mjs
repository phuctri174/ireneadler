// Shiai's beats to PNG, for judging by eye (her attack's windup and its three
// endings, a called point, the reset, hajime): compose() at chosen moments with the
// keiko moment set as core's message would set it. Not a test.
//
//   node tests/run.mjs                       (once: compiles src/ into .verify/)
//   node tests/shiai_snap.mjs <out dir>
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { Frame } from "../.verify/led/grid.js";
import { compose } from "../.verify/led/compose.js";
import { keikoReact } from "../.verify/led/scenes.js";
import { paintSheet } from "./ledpng.mjs";

const NOW = 100000;

function at(moment, k, score = { you: 1, her: 0 }) {
  keikoReact(moment ? { ...moment, at: NOW - k } : null);
  const f = new Frame();
  compose(f, {
    state: "listening", emotion: "neutral", level: 0, now: NOW, blinking: false, muted: false, reaction: null, summon: null,
    activity: { name: "keiko", at: NOW - 10000 }, score: { ...score, at: NOW - 5000, scored: null },
  });
  return f;
}

const outDir = process.argv[2] ?? "shiai-snaps";
mkdirSync(outDir, { recursive: true });
const sheets = {
  "windup_men.png": [0, 200, 450, 800, 1100, 1350].map((k) => at({ action: "windup", target: "men", ms: 1400 }, k)),
  "windup_kote_do_tsuki.png": [["kote", 300], ["kote", 1200], ["dou", 300], ["dou", 1200], ["tsuki", 300], ["tsuki", 1200]].map(([t, k]) => at({ action: "windup", target: t, ms: 1400 }, k)),
  "impact.png": [["hit", 60], ["hit", 300], ["blocked", 120], ["blocked", 400], ["dodged", 120], ["dodged", 400]].map(([r, k]) => at({ action: "impact", target: "men", result: r }, k)),
  "point_reset_hajime.png": [
    at({ action: "ippon", flags: 3, call: "KOTE ARI", who: "you" }, 600),
    at({ action: "ippon", flags: 3, call: "MEN ARI", who: "her" }, 600, { you: 1, her: 1 }),
    at({ action: "reset", label: "NIHONME", ms: 2600 }, 800),
    at({ action: "reset", label: "SHOBU", ms: 2600 }, 800, { you: 1, her: 1 }),
    at({ action: "hajime" }, 200),
    at(null, 0),
  ],
};
sheets["countdown.png"] = [
  at({ action: "countdown", ms: 10000 }, 200, { you: 0, her: 0 }),
  at({ action: "countdown", ms: 10000 }, 7400, { you: 0, her: 0 }),
  at({ action: "countdown", ms: 3000, label: "NIHONME" }, 900),
  at({ action: "hajime" }, 150),
];
for (const [file, frames] of Object.entries(sheets)) {
  writeFileSync(join(outDir, file), paintSheet(frames, 3));
  console.log(join(outDir, file));
}
