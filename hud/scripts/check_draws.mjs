// Would the HUD draw these? Reads a JSON array of <draw> specs from the file given,
// prints a JSON array of { ok, why } - the board's own full checks (board.prepare),
// for the evals (core/evals/drawing.py). Needs the compiled modules in .verify.
import { readFileSync } from "node:fs";

const { prepare } = await import(new URL("../.verify/board/board.js", import.meta.url));
const specs = JSON.parse(readFileSync(process.argv[2], "utf8"));
const out = specs.map((spec) => {
  let why = null;
  const ok = prepare(spec, (reason) => (why = reason)) !== null;
  return { ok, why };
});
console.log(JSON.stringify(out));
