// The illustration board: registry and modules agree; every template's registry
// example draws, sketches in over time and keeps out of her face's corner;
// anything wrong - an unknown template, a bad argument, an illegal FEN or move,
// garbage - draws nothing and throws nothing; an opening is always its moves.
import { readFileSync } from "node:fs";
import { Chess } from "chess.js";
import { COLS, Frame } from "../.verify/led/grid.js";
import { compose } from "../.verify/led/compose.js";
import { FACE_CORNER, drawBoard, prepare } from "../.verify/board/board.js";
import { TEMPLATES } from "../.verify/board/templates/index.js";
import { FONT_CHARS, supported } from "../.verify/board/font.js";
import { steps } from "../.verify/board/templates/sort.js";

let failures = 0;
const check = (ok, label) => {
  if (!ok) {
    failures += 1;
    console.error(`FAIL board: ${label}`);
  }
};
const quiet = () => {};

const registry = JSON.parse(readFileSync(new URL("../../config/board.json", import.meta.url), "utf8"));
const names = registry.templates.map((t) => t.name);
for (const n of names) check(n in TEMPLATES, `registry template "${n}" has no module`);
for (const n of Object.keys(TEMPLATES)) check(names.includes(n), `template module "${n}" has no registry entry`);

const lit = (f) => f.value.reduce((n, v) => n + (v > 0.05 ? 1 : 0), 0);
const cornerLit = (f) => {
  let n = 0;
  for (let y = FACE_CORNER.y; y < FACE_CORNER.y + FACE_CORNER.h; y += 1) for (let x = FACE_CORNER.x; x < COLS; x += 1) n += f.value[y * COLS + x] > 0.05 ? 1 : 0;
  return n;
};
const at = (drawing, t) => {
  const f = new Frame();
  f.clear();
  drawBoard(f, drawing, t, new Date(2026, 8, 22, 14, 5, 30));
  return f;
};

for (const entry of [...registry.templates, { name: "shapes", example: registry.shapes_example }]) {
  const drawing = prepare(entry.example, (why) => check(false, `${entry.name}: example refused (${why})`));
  if (!drawing) continue;
  const early = lit(at(drawing, 150));
  const done = at(drawing, 30000);
  check(lit(done) > 80, `${entry.name}: draws a picture (${lit(done)} cells)`);
  check(early < lit(done), `${entry.name}: sketches in (${early} cells at 150 ms, ${lit(done)} when done)`);
  check(cornerLit(done) === 0, `${entry.name}: keeps out of her face's corner`);
  check(done.value.every((v) => Number.isFinite(v) && v >= 0 && v <= 1), `${entry.name}: values 0..1`);
}

// her face in the corner while the board is up, and back when it's gone
const stage = { state: "speaking", emotion: "happy", level: 0.4, now: 90000, blinking: false, muted: false, reaction: null, activity: null, summon: null };
const drawing = prepare(registry.templates[0].example, quiet);
const withBoard = new Frame();
compose(withBoard, { ...stage, board: { drawing, at: 60000 } });
check(cornerLit(withBoard) > 20, `her face shows in the corner (${cornerLit(withBoard)} cells)`);
const plain = new Frame();
compose(plain, stage);
check(cornerLit(plain) === 0, "no corner face without a board");

// nothing wrong ever draws, and nothing throws
const bad = [
  null,
  "chessboard",
  42,
  [],
  {},
  { template: "no_such_template" },
  { template: "chessboard", fen: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0" },
  { template: "chessboard", fen: "8/8/8/8/8/8/8/8 w - - 0 1" },
  { template: "chessboard", fen: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKKNR w KQkq - 0 1" },
  { template: "chessboard", fen: "pnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1" },
  { template: "chessboard", moves: ["e4", "e5", "Ke3", "Qh4", "Kxe5"] },
  { template: "chessboard", moves: ["e5"] },
  { template: "chessboard", opening: "The Totally Made Up Gambit" },
  { template: "chessboard", moves: ["e4", "e5", "Ke3"] },
  { template: "chessboard", highlight: ["z9"] },
  { template: "footwork", step: "moonwalk" },
  { template: "shinai", highlight: "blade" },
  { template: "calendar", month: "2026-13" },
  { template: "clock", time: "25:00" },
  { template: "timer" },
  { template: "bar_chart", values: [1, 2], labels: ["a"] },
  { template: "bar_chart", values: "lots" },
  { template: "progress", items: [{ label: "x", value: 120 }] },
  { template: "sort", algorithm: "bogo", values: [3, 1] },
  { template: "binary_tree", values: [null, 1] },
  { template: "binary_tree", values: [1, null, 2, 3] },
  { template: "graph", nodes: ["A"], edges: [["A", "Z"]] },
  { template: "flowchart", nodes: [{ id: "a", text: "x" }, { id: "a", text: "y" }], links: [] },
  { template: "number_line", from: 5, to: 1 },
  { template: "icon", names: ["mickey"] },
  { template: "system_status", cpu: 20, gpu: 30, ram: 40 },
  { template: "schedule", items: [{ start: "10:00", end: "09:00", label: "x" }] },
  { shapes: [] },
  { shapes: [{ type: "spaceship", x: 1, y: 1 }] },
  { shapes: [{ type: "line", x1: 0, y1: 0, x2: "far", y2: 3 }] },
  { shapes: [{ type: "rect", x: 1, y: 1 }] },
  { shapes: [{ type: "sprite", name: "logo", x: 1, y: 1 }] },
];
for (const spec of bad) {
  let result;
  try {
    result = prepare(spec, quiet);
  } catch (error) {
    check(false, `prepare threw on ${JSON.stringify(spec)}: ${error}`);
    continue;
  }
  check(result === null, `refused: ${JSON.stringify(spec).slice(0, 90)}`);
}

// forgiving where a sketch can be, strict where accuracy is the point
check(prepare({ shapes: [{ type: "rect", x: 20, y: 20, w: 100, h: 80, fill: "red" }] }, quiet) !== null, "a freehand rect too big and with fill as a colour still sketches");
const house = prepare({ shapes: [{ type: "rect", x: 30, y: 36, w: 40, h: 30 }, { type: "polygon", points: [[26, 36], [50, 18], [74, 36]] }, { type: "chimney", x: 60 }] }, quiet);
check(house && house.args.length === 4, "a sketch keeps what it can draw (rect + 3-sided roof), skipping an unknown shape");
const pairs = prepare({ template: "chessboard", moves: [["e2", "e4"], ["e7", "e5"], "Nf3"] }, quiet);
check(pairs && pairs.args.positions.length === 4, "moves as square pairs and SAN mixed");
const najdorf = prepare({ template: "chessboard", opening: "Sicilian Najdorf", moves: ["e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4", "Nf6", "Nc3", "a6"] }, quiet);
check(najdorf && najdorf.args.positions.length === 11 && najdorf.args.title === "Sicilian Najdorf", "an opening is played from its moves, its name the title");
check(prepare({ template: "chessboard", opening: "Ruy Lopez" }, quiet) === null, "a name with no moves draws nothing - there is no table to look it up in");
// the King's Indian, the London System: any opening, from its moves
const kid = prepare({ template: "chessboard", moves: ["d4", "Nf6", "c4", "g6", "Nc3", "Bg7", "e4", "d6"], title: "King's Indian", sync: true, reveal: [{ key: "ply:8", at: 0 }] }, quiet);
check(kid && kid.args.positions.length === 9, "the King's Indian from its moves");

// sorting steps really sort, for every algorithm
for (const algorithm of ["bubble", "insertion", "selection", "merge", "quick"]) {
  const input = [9, 3, 7, 1, 8, 2, 6, 5, 4];
  const s = steps(algorithm, input);
  check(JSON.stringify(s[s.length - 1].values) === JSON.stringify([...input].sort((a, b) => a - b)), `${algorithm} sort ends sorted`);
  check(s.length > input.length, `${algorithm} sort shows its steps (${s.length})`);
}

// the font has every letter and digit, and dō
check([..."ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"].every((c) => FONT_CHARS.includes(c)), "font covers A-Z and 0-9");
check(supported("DŌ, TSUKI!") && supported("e4-e5 (x2)"), "font covers macrons and punctuation");

// ---- illustrating her answer (core/irene/illustrate.py): elements as she says them
import { strokesOf } from "../.verify/board/board.js";
const textsAt = (drawing, t) => strokesOf(drawing, { t, now: new Date() }).filter((s) => s.kind === "text").map((s) => s.text);
{
  // the Queen's Gambit: no move until she says one; "d4, d5, then c4" plays all three, one by one
  const qg = prepare({ template: "chessboard", title: "Queen's Gambit", moves: ["d4", "d5", "c4"], sync: true, reveal: [{ key: "ply:3", at: 2000 }], notes: [{ text: "Gambit", at: 500 }, { text: "Pawn", at: 2000 }] });
  check(qg && qg.args.positions.length === 4, "the Queen's Gambit is d4 d5 c4");
  const moves = (t) => textsAt(qg, t).join(" ");
  check(!/1\.D4/.test(moves(1500)), "no move before she says one");
  check(/1\.D4/.test(moves(2100)) && !/C4/.test(moves(2100)), "her sentence starts the moves: the first plays at once");
  check(/C4/.test(moves(4000)), "all three play, one by one");
  check(textsAt(qg, 1000).includes("GAMBIT") && !textsAt(qg, 1000).includes("PAWN"), "her key terms join the panel as she says them");
  check(cornerLit(at(qg, 5000)) === 0, "the synced board keeps out of her face's corner");
  const plain = prepare({ template: "chessboard", moves: ["d4", "d5", "c4"] });
  check(/C4/.test(textsAt(plain, 9000).join(" ")), "without sync the opening still plays by itself");
}
{
  // the shinai: each label as she names it, amber while new
  const shinai = prepare({ template: "shinai", sync: true, labels: ["kensen", "tsuba", "tsuka"], reveal: [{ key: "tsuba", at: 1000 }] });
  check(shinai && shinai.sync, "a synced shinai");
  check(!textsAt(shinai, 500).includes("TSUBA") && textsAt(shinai, 1200).includes("TSUBA"), "the tsuba's label appears when she names it");
  check(!textsAt(shinai, 5000).includes("KENSEN"), "an unnamed part's label waits");
  const fresh = strokesOf(shinai, { t: 1200, now: new Date() }).find((s) => s.kind === "text" && s.text === "TSUBA");
  check(fresh && fresh.color === "amber", "a label just named glows amber");
  const dou = prepare({ template: "bogu", sync: true, labels: ["do"], reveal: [{ key: "do", at: 0 }] });
  check(textsAt(dou, 100).includes("DŌ"), "the do is the DŌ (macron)");
}
{
  const flow = prepare({ template: "flow", title: "photosynthesis", steps: [{ text: "Sunlight", at: 0 }, { text: "Chlorophyll", at: 3000 }] });
  check(textsAt(flow, 1000).includes("SUNLIGHT") && !textsAt(flow, 1000).includes("CHLOROPHYLL"), "a flow step joins as she says it");
  check(prepare({ template: "flow", steps: [] }) !== null, "a flow starts empty");
  const cmp = prepare({ template: "compare", left: "Python", right: "Rust", points: [{ side: "right", text: "Memory safe", at: 2000 }] });
  check(textsAt(cmp, 100).includes("PYTHON") && !textsAt(cmp, 100).includes("MEMORY SAFE") && textsAt(cmp, 2100).includes("MEMORY SAFE"), "a comparison point appears under its side as she says it");
  check(cornerLit(at(cmp, 5000)) === 0 && cornerLit(at(flow, 5000)) === 0, "flow and compare keep out of her face's corner");
}

if (failures > 0) {
  console.error(`board: ${failures} failure(s)`);
  process.exit(1);
} else {
  console.log(`board: ok (${names.length} templates + shapes, ${bad.length} bad drawings refused)`);
}
