// LED frames to PNG, for judging art by eye: compose() at chosen moments, drawn as
// the HUD draws them (lit cells with a glow over faint unlit dots). Not a test.
//
//   node tests/run.mjs            (once: compiles src/ into .verify/)
//   node tests/snap.mjs <out dir> <spec.json>
//
// spec.json: [{ "file": "kendo_1.png", "stage": { ...Stage fields, times relative to
// "now": 0 }, "cols": 1 }] - or a "sheet": [[stage, label], ...] rendered as one
// contact sheet. Times in a stage (entrance.at, reaction.at, summon.start/part2) are
// ms before the moment drawn when negative.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { Frame } from "../.verify/led/grid.js";
import { compose } from "../.verify/led/compose.js";
import { paintSheet } from "./ledpng.mjs";

const NOW = 100000;

function at(stage) {
  // times in the spec are relative to the moment drawn
  const s = { state: "listening", emotion: "happy", level: 0, now: NOW, blinking: false, muted: false, reaction: null, activity: null, summon: null, ...stage };
  s.now = NOW;
  if (s.entrance) s.entrance = { ...s.entrance, at: NOW + s.entrance.at };
  if (s.reaction) s.reaction = { ...s.reaction, at: NOW + s.reaction.at };
  if (s.activity) s.activity = { ...s.activity, at: NOW + s.activity.at };
  if (s.summon) s.summon = { ...s.summon, start: NOW + s.summon.start, part2: s.summon.part2 == null ? null : NOW + s.summon.part2 };
  if (s.emotionAt != null) s.emotionAt = NOW + s.emotionAt;
  const f = new Frame();
  compose(f, s);
  return f;
}

const [outDir, specPath] = process.argv.slice(2);
mkdirSync(outDir, { recursive: true });
for (const item of JSON.parse(readFileSync(specPath, "utf8"))) {
  const frames = item.sheet ?? [[item.stage, ""]];
  const cols = item.cols ?? Math.min(3, frames.length);
  writeFileSync(join(outDir, item.file), paintSheet(frames.map(([stage]) => at(stage)), cols));
  console.log(join(outDir, item.file));
}
