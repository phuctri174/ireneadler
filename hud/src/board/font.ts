// A 3x5 pixel font for the board's labels. On the 128x72 matrix a glyph is 5 LEDs
// tall - about 12 mm on a 27" 1440p screen at the interface's reference scale,
// ~40 arcminutes at 1 m, comfortably legible - and up to 32 characters fit across
// the whole board. Upper case only: lower case is drawn as upper. Size 2 doubles
// every cell (titles). Letters with a macron (dō) carry the bar above the glyph.

// five rows of three, "#" lit
const ART: Record<string, [string, string, string, string, string]> = {
  A: [".#.", "#.#", "###", "#.#", "#.#"],
  B: ["##.", "#.#", "##.", "#.#", "##."],
  C: [".##", "#..", "#..", "#..", ".##"],
  D: ["##.", "#.#", "#.#", "#.#", "##."],
  E: ["###", "#..", "##.", "#..", "###"],
  F: ["###", "#..", "##.", "#..", "#.."],
  G: [".##", "#..", "#.#", "#.#", ".##"],
  H: ["#.#", "#.#", "###", "#.#", "#.#"],
  I: ["###", ".#.", ".#.", ".#.", "###"],
  J: ["..#", "..#", "..#", "#.#", ".#."],
  K: ["#.#", "#.#", "##.", "#.#", "#.#"],
  L: ["#..", "#..", "#..", "#..", "###"],
  M: ["#.#", "###", "###", "#.#", "#.#"],
  N: ["##.", "#.#", "#.#", "#.#", "#.#"],
  O: [".#.", "#.#", "#.#", "#.#", ".#."],
  P: ["##.", "#.#", "##.", "#..", "#.."],
  Q: [".#.", "#.#", "#.#", "##.", ".##"],
  R: ["##.", "#.#", "##.", "#.#", "#.#"],
  S: [".##", "#..", ".#.", "..#", "##."],
  T: ["###", ".#.", ".#.", ".#.", ".#."],
  U: ["#.#", "#.#", "#.#", "#.#", "###"],
  V: ["#.#", "#.#", "#.#", "#.#", ".#."],
  W: ["#.#", "#.#", "###", "###", "#.#"],
  X: ["#.#", "#.#", ".#.", "#.#", "#.#"],
  Y: ["#.#", "#.#", ".#.", ".#.", ".#."],
  Z: ["###", "..#", ".#.", "#..", "###"],
  "0": ["###", "#.#", "#.#", "#.#", "###"],
  "1": [".#.", "##.", ".#.", ".#.", "###"],
  "2": ["##.", "..#", ".#.", "#..", "###"],
  "3": ["##.", "..#", ".#.", "..#", "##."],
  "4": ["#.#", "#.#", "###", "..#", "..#"],
  "5": ["###", "#..", "##.", "..#", "##."],
  "6": [".##", "#..", "###", "#.#", "###"],
  "7": ["###", "..#", ".#.", ".#.", ".#."],
  "8": ["###", "#.#", "###", "#.#", "###"],
  "9": ["###", "#.#", "###", "..#", "##."],
  " ": ["...", "...", "...", "...", "..."],
  ".": ["...", "...", "...", "...", ".#."],
  ",": ["...", "...", "...", ".#.", "#.."],
  ":": ["...", ".#.", "...", ".#.", "..."],
  ";": ["...", ".#.", "...", ".#.", "#.."],
  "!": [".#.", ".#.", ".#.", "...", ".#."],
  "?": ["##.", "..#", ".#.", "...", ".#."],
  "-": ["...", "...", "###", "...", "..."],
  "+": ["...", ".#.", "###", ".#.", "..."],
  "=": ["...", "###", "...", "###", "..."],
  "/": ["..#", "..#", ".#.", "#..", "#.."],
  "\\": ["#..", "#..", ".#.", "..#", "..#"],
  "(": [".#.", "#..", "#..", "#..", ".#."],
  ")": [".#.", "..#", "..#", "..#", ".#."],
  "[": ["##.", "#..", "#..", "#..", "##."],
  "]": [".##", "..#", "..#", "..#", ".##"],
  "'": [".#.", ".#.", "...", "...", "..."],
  '"': ["#.#", "#.#", "...", "...", "..."],
  "%": ["#.#", "..#", ".#.", "#..", "#.#"],
  "#": ["#.#", "###", "#.#", "###", "#.#"],
  "*": ["#.#", ".#.", "#.#", "...", "..."],
  "<": ["..#", ".#.", "#..", ".#.", "..#"],
  ">": ["#..", ".#.", "..#", ".#.", "#.."],
  _: ["...", "...", "...", "...", "###"],
  "&": [".#.", "#.#", ".#.", "#.#", ".##"],
  "^": [".#.", "#.#", "...", "...", "..."],
  "|": [".#.", ".#.", ".#.", ".#.", ".#."],
  "°": [".#.", "#.#", ".#.", "...", "..."],
  "~": ["...", ".#.", "#.#", "...", "..."],
  "$": [".##", "##.", ".#.", ".##", "##."],
};

const MACRON: Record<string, string> = { "Ō": "O", "Ū": "U", "Ā": "A", "Ē": "E", "Ī": "I" };

// Vietnamese ("ĐÀ LẠT" on the briefing board): a letter's marks as single cells
// around its glyph, in glyph cells (column, row; row -2 is above, 6 below). Each
// combining mark (Unicode NFD) has its own few cells; Đ is D with a bar through
// its stem.
const MARKS: Record<string, readonly (readonly [number, number])[]> = {
  "̀": [[0, -2]], // grave: À
  "́": [[2, -2]], // acute: Á
  "̉": [[1, -2]], // hook above: Ả
  "̃": [[0, -2], [2, -2]], // tilde: Ã
  "̣": [[1, 6]], // dot below: Ạ
  "̂": [[1, -2]], // circumflex: Â (a cap's peak)
  "̆": [[0, -2], [2, -2]], // breve: Ă
  "̛": [[3, 0]], // horn: Ơ, Ư
  "̄": [[0, -2], [1, -2], [2, -2]], // macron: Ō (as before)
};
const BARRED: Record<string, string> = { "Đ": "D" };

export const GLYPH_W = 3;
export const GLYPH_H = 5;
/** Horizontal advance: the glyph and one column of space. */
export const ADVANCE = GLYPH_W + 1;

export interface Cell {
  x: number;
  y: number;
}

function glyphOf(ch: string): { art: readonly string[]; marks: (readonly [number, number])[] } {
  const upper = ch.toUpperCase();
  if (MACRON[upper]) return { art: ART[MACRON[upper]], marks: [...MARKS["̄"]] };
  if (BARRED[upper]) return { art: ART[BARRED[upper]], marks: [[-1, 2], [1, 2]] };
  if (ART[upper]) return { art: ART[upper], marks: [] };
  // a letter with marks: its base glyph, then each mark's cells
  const [base, ...rest] = [...upper.normalize("NFD")];
  if (base && ART[base] && rest.length && rest.every((m) => MARKS[m])) {
    return { art: ART[base], marks: rest.flatMap((m) => MARKS[m]) };
  }
  return { art: ART["?"], marks: [] };
}

/** Whether every character of `text` has a glyph of its own (not the "?" stand-in). */
export function supported(text: string): boolean {
  return [...text].every((ch) => glyphOf(ch).art !== ART["?"] || ch === "?");
}

/** Cells lit by one character with its top-left at (x, y). */
export function glyphCells(ch: string, x: number, y: number, size = 1): Cell[] {
  const { art, marks } = glyphOf(ch);
  const out: Cell[] = [];
  for (let r = 0; r < GLYPH_H; r += 1) {
    for (let c = 0; c < GLYPH_W; c += 1) {
      if (art[r][c] !== "#") continue;
      for (let dy = 0; dy < size; dy += 1) for (let dx = 0; dx < size; dx += 1) out.push({ x: x + c * size + dx, y: y + r * size + dy });
    }
  }
  for (const [c, r] of marks) {
    for (let dy = 0; dy < size; dy += 1) for (let dx = 0; dx < size; dx += 1) out.push({ x: x + c * size + dx, y: y + r * size + dy });
  }
  return out;
}

/** Width in cells of `text` at `size`, without the trailing space. */
export function textWidth(text: string, size = 1): number {
  const n = [...text].length;
  return n === 0 ? 0 : (n * ADVANCE - 1) * size;
}

/** How many characters fit in `width` cells. */
export function fits(width: number, size = 1): number {
  return Math.max(0, Math.floor((width / size + 1) / ADVANCE));
}

export const FONT_CHARS = Object.keys(ART);
