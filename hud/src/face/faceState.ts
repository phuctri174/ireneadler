// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Face vocabulary for the main interface: what Irene is doing (state) and how she
// carries it (emotion). State is authoritative - it is only ever set from a real
// signal, never from an animation. Emotion is a presentation layer on top.

export type AssistantState = "dormant" | "listening" | "thinking" | "speaking" | "error";


export const ASSISTANT_STATES: AssistantState[] = [
  "dormant",
  "listening",
  "thinking",
  "speaking",
  "error",
];


export const EYE_COLS = 7;
export const EYE_ROWS = 7;
export const MOUTH_COLS = 13;
export const MOUTH_ROWS = 5;

/** Authored as art so a shape can be read in the source. `.` off `-` dim `+` mid `#` full. */
export type EyeArt = readonly string[];

export interface EyePair {
  left: EyeArt;
  right: EyeArt;
}

const CELL_LEVEL: Record<string, number> = { ".": 0, "-": 0.22, "+": 0.55, "#": 1 };

// Left eye is authored; the right eye mirrors it unless a variant names its own,
// so asymmetric shapes (confused, wink) stay deliberate rather than accidental.
// A new expression is one entry here plus one in config/cues.json.
const EMOTION_ART = {
  neutral: [
    ".+###+.",
    "+#####+",
    "#######",
    "#######",
    "#######",
    "+#####+",
    ".+###+.",
  ],
  happy: [
    ".......",
    "..###..",
    ".#####.",
    "###.###",
    "##...##",
    "+.....+",
    ".......",
  ],
  curious: {
    left: [
      "..+#+..",
      ".#####.",
      "#######",
      "#######",
      ".#####.",
      "..###..",
      ".......",
    ],
    right: [
      ".+###+.",
      "+#####+",
      "#######",
      "#######",
      "#######",
      "+#####+",
      ".+###+.",
    ],
  },
  concerned: [
    "....+#.",
    "..+###+",
    ".#####+",
    "#######",
    "#######",
    "+#####+",
    ".+###+.",
  ],
  confused: {
    left: [
      ".......",
      ".......",
      "+#####+",
      "#######",
      "+#####+",
      ".......",
      ".......",
    ],
    right: [
      "..###..",
      ".#####.",
      "##...##",
      "##...##",
      "##...##",
      ".#####.",
      "..###..",
    ],
  },
  // wide open rings with a small pupil: O_O
  surprised: [
    ".+###+.",
    "+#...#+",
    "#.....#",
    "#..#..#",
    "#.....#",
    "+#...#+",
    ".+###+.",
  ],
  // a heavy lid sloping down to the outside
  sad: [
    ".......",
    ".......",
    "....+##",
    "..+####",
    "+######",
    ".+####+",
    "..+#+..",
  ],
  // sparkling stars
  excited: [
    "...#...",
    "...#...",
    "..###..",
    "#######",
    "..###..",
    ".##.##.",
    ".#...#.",
  ],
  // one eye open, the other shut in a smiling arc
  wink: {
    left: [
      ".+###+.",
      "+#####+",
      "#######",
      "#######",
      "#######",
      "+#####+",
      ".+###+.",
    ],
    right: [
      ".......",
      ".......",
      "..###..",
      ".#...#.",
      "#.....#",
      ".......",
      ".......",
    ],
  },
  // hearts, drawn pink (EMOTION_INK)
  love: [
    ".##.##.",
    "#######",
    "#######",
    "#######",
    ".#####.",
    "..###..",
    "...#...",
  ],
  // a bright eight-point sparkle on a softly lit eye, drawn gold (EMOTION_INK):
  // awe, something amazing - more than excited's little stars
  starryEyed: [
    ".--#--.",
    "-#-#-#-",
    "--###--",
    "#######",
    "--###--",
    "-#-#-#-",
    ".--#--.",
  ],
  // lids half down, level: friendly smugness
  proud: [
    ".......",
    ".......",
    "#######",
    "#######",
    "#######",
    "+#####+",
    ".+###+.",
  ],
  // eyes closed in a low, soft arc, settled near the bottom of the box: content,
  // at ease - happy's arch is taller and brighter, this one is calm
  satisfied: [
    ".......",
    ".......",
    ".......",
    "..###..",
    ".#####.",
    "##+++##",
    "+.....+",
  ],
  // a heavy lid pulled most of the way down over an eye looking at the floor:
  // put out, and making sure it shows
  sulking: [
    "#######",
    "#######",
    "#######",
    "#######",
    ".#####.",
    "..+++..",
    ".......",
  ],
  // eyes slid away to one side under lowered lids: caught out, or praised and
  // not sure where to look. Both eyes glance the same way, so it reads as a
  // glance rather than a squint
  sheepish: {
    left: [
      ".......",
      ".......",
      "..+####",
      "..#####",
      "..#####",
      "...+##+",
      ".......",
    ],
    right: [
      ".......",
      ".......",
      "..+####",
      "..#####",
      "..#####",
      "...+##+",
      ".......",
    ],
  },
  // sleepy: heavy lids drooping over eyes half shut, the outer corners sagging -
  // a long day, a late hour, too comfortable to move
  sleepy: [
    ".......",
    ".......",
    ".......",
    "#######",
    "+#####+",
    ".#####.",
    "..+++..",
  ],
  // dizzy: crossed-out X eyes - spun round, overwhelmed, knocked for six (a joke
  // about too much at once, not real distress)
  dizzy: [
    "#.....#",
    ".#...#.",
    "..#.#..",
    "...#...",
    "..#.#..",
    ".#...#.",
    "#.....#",
  ],
  // focused: both eyes narrowed to level bars, steady - concentrating hard (a chess
  // position, a tricky problem), nothing else getting in
  focused: [
    ".......",
    ".......",
    "+#####+",
    "#######",
    "+#####+",
    ".......",
    ".......",
  ],
  // amused: one eye relaxed under a lazy half-lid, the other's brow cocked up over
  // it - entertained, a little superior, not laughing yet (Irene Adler's look)
  amused: {
    left: [
      ".......",
      ".......",
      ".......",
      "#######",
      "#######",
      "+#####+",
      ".+###+.",
    ],
    right: [
      ".+###+.",
      "+.....+",
      ".......",
      ".#####.",
      "#######",
      "#######",
      ".#####.",
    ],
  },
  // fired up: a hard brow slanting down to the middle over a narrowed, blazing eye -
  // pumped, ready to fight or train (keiko, a match, a challenge). Drawn in amber,
  // like fire.
  firedUp: {
    left: [
      "##.....",
      ".###...",
      "..####.",
      ".......",
      ".#####.",
      "#######",
      ".#####.",
    ],
    right: [
      ".....##",
      "...###.",
      ".####..",
      ".......",
      ".#####.",
      "#######",
      ".#####.",
    ],
  },
  // The theatrical four (led/theatre.ts draws the rest of each face - mouth, brows,
  // tears, halo, hands - big enough to read on a phone):
  // sobbing: eyes squeezed shut, > <
  sobbing: [
    "##.....",
    "####...",
    "..####.",
    "....###",
    "..####.",
    "####...",
    "##.....",
  ],
  // innocent: serene closed arcs, the halo above
  innocent: [
    ".......",
    ".......",
    "..###..",
    ".#...#.",
    "#.....#",
    ".......",
    ".......",
  ],
  // peeking: her hands cover her face - the one eye in their gap is drawn there
  // (led/theatre.ts), over the fingers, so both eyes here are covered
  peeking: {
    left: [
      ".......",
      ".......",
      ".......",
      ".......",
      ".......",
      ".......",
      ".......",
    ],
    right: [
      ".......",
      ".......",
      ".......",
      ".......",
      ".......",
      ".......",
      ".......",
    ],
  },
  // smug: half-lidded, pupils slid sideways at him; the raised-brow eye a little
  // more open than the other
  smug: {
    left: [
      ".......",
      ".......",
      "#######",
      "###..##",
      "###..##",
      "+#####+",
      ".+###+.",
    ],
    right: [
      ".......",
      ".......",
      ".......",
      "#######",
      "###..##",
      "+#####+",
      ".+###+.",
    ],
  },
  // fuming, on his behalf: glaring slits under brows driven down to the middle
  // (led/theatre.ts adds the red brows, the clenched frown and the steam)
  fuming: {
    left: [
      ".......",
      ".......",
      ".......",
      "#######",
      "###.###",
      ".#####.",
      ".......",
    ],
    right: [
      ".......",
      ".......",
      ".......",
      "#######",
      "###.###",
      ".#####.",
      ".......",
    ],
  },
  // shocked: eyes blown wide open, pupils shrunk to a point - "she did WHAT"
  // (led/theatre.ts drops the jaw)
  shocked: [
    ".#####.",
    "#.....#",
    "#.....#",
    "#..#..#",
    "#.....#",
    "#.....#",
    ".#####.",
  ],
  // caughtOffGuard: "oh really?" - eyes blown round, the pupils pinned high and
  // tiny, staring at him (led/theatre.ts shoots the brows up, adds the small "o"
  // and the bead of sweat)
  caughtOffGuard: [
    ".+###+.",
    "+#...#+",
    "#..#..#",
    "#.....#",
    "#.....#",
    "+#...#+",
    ".+###+.",
  ],
  // arrogant: pleased with herself - lids drawn down flat, looking down her nose
  // at him (led/theatre.ts adds the arched brows and the wide, closed smile)
  arrogant: [
    ".......",
    ".......",
    ".......",
    "#######",
    "#######",
    "+#####+",
    ".+###+.",
  ],
  // triumphant: she beat him - sharp, high crescents, squeezed up by the grin
  // (led/theatre.ts adds the big open grin and the sparkles)
  triumphant: [
    ".......",
    "..###..",
    ".#####.",
    "##+.+##",
    "#.....#",
    ".......",
    ".......",
  ],
  // outplayed: he beat her - eyes squeezed shut > <, "how?!" (the pout and the
  // sweat drop are led/theatre.ts)
  outplayed: [
    "#......",
    "###....",
    "..###..",
    "....###",
    "..###..",
    "###....",
    "#......",
  ],
  // standoff: a draw - level slits sizing him up
  standoff: [
    ".......",
    ".......",
    "+#####+",
    "#######",
    "+#####+",
    ".......",
    ".......",
  ],
  // oops: she didn't catch his throw - one eye wide, one squinting, as if that
  // would help (led/theatre.ts adds the raised brow, the question mark and the wobble)
  oops: {
    left: [
      ".+###+.",
      "+#####+",
      "#######",
      "###.###",
      "#######",
      "+#####+",
      ".+###+.",
    ],
    right: [
      ".......",
      ".......",
      ".......",
      "+#####+",
      ".+###+.",
      ".......",
      ".......",
    ],
  },
  // the study-mode hits (core/irene/study.py), comic throughout - never real distress:
  // bonked: "ow!" - one eye winced shut, the other blown wide, its pupil knocked off
  // centre (led/theatre.ts adds the bonk's burst and the stars circling her head)
  bonked: {
    left: [
      ".......",
      "..#.#..",
      ".......",
      "#######",
      ".......",
      ".......",
      ".......",
    ],
    right: [
      ".+###+.",
      "+#...#+",
      "#.....#",
      "#....##",
      "#.....#",
      "+#...#+",
      ".+###+.",
    ],
  },
  // indignant: "I AM studying" - brows slammed into a V over glaring half-moons
  // (the anger mark is led/theatre.ts)
  indignant: [
    "#......",
    ".##....",
    "...##..",
    ".....##",
    ".......",
    "+#####+",
    ".#####.",
  ],
  // surrender: "okay okay okay" - T_T, eyes shut, a tear running from each (the
  // waterfall and the white flag are led/theatre.ts)
  surrender: [
    ".......",
    "#######",
    "#######",
    "...#...",
    "...#...",
    "..###..",
    "...#...",
  ],
} satisfies Record<string, EyeArt | EyePair>;

export type Emotion = keyof typeof EMOTION_ART;

export const EMOTIONS = Object.keys(EMOTION_ART) as Emotion[];

export function isEmotion(name: unknown): name is Emotion {
  return typeof name === "string" && (EMOTIONS as string[]).includes(name);
}

/** Expressions drawn in their own colour rather than the state's. */
export const EMOTION_INK: Partial<Record<Emotion, "pink" | "gold">> = { love: "pink", starryEyed: "gold", firedUp: "gold" };

const DORMANT_ART: EyeArt = [
  ".......",
  ".......",
  ".......",
  "+#####+",
  "-+++++-",
  ".......",
  ".......",
];

const ERROR_ART: EyeArt = [
  "#+...+#",
  "+#+.+#+",
  ".+#+#+.",
  "..###..",
  ".+#+#+.",
  "+#+.+#+",
  "#+...+#",
];

const BLINK_ART: EyeArt = [
  ".......",
  ".......",
  ".......",
  "#######",
  "+++++++",
  ".......",
  ".......",
];

export type EyeGrid = Float32Array;

function toGrid(art: EyeArt): EyeGrid {
  const grid = new Float32Array(EYE_COLS * EYE_ROWS);
  for (let row = 0; row < EYE_ROWS; row += 1) {
    const line = art[row] ?? "";
    for (let col = 0; col < EYE_COLS; col += 1) {
      grid[row * EYE_COLS + col] = CELL_LEVEL[line[col] ?? "."] ?? 0;
    }
  }
  return grid;
}

function mirror(grid: EyeGrid): EyeGrid {
  const out = new Float32Array(grid.length);
  for (let row = 0; row < EYE_ROWS; row += 1) {
    for (let col = 0; col < EYE_COLS; col += 1) {
      out[row * EYE_COLS + col] = grid[row * EYE_COLS + (EYE_COLS - 1 - col)];
    }
  }
  return out;
}

/** Positive `by` lifts the shape; vacated rows go dark. Reads as looking upward. */
function shiftRows(grid: EyeGrid, by: number): EyeGrid {
  if (by === 0) return grid;
  const out = new Float32Array(grid.length);
  for (let row = 0; row < EYE_ROWS; row += 1) {
    const source = row + by;
    if (source < 0 || source >= EYE_ROWS) continue;
    for (let col = 0; col < EYE_COLS; col += 1) {
      out[row * EYE_COLS + col] = grid[source * EYE_COLS + col];
    }
  }
  return out;
}

function isArt(art: EyeArt | EyePair): art is EyeArt {
  return Array.isArray(art);
}

export interface GridPair {
  left: EyeGrid;
  right: EyeGrid;
}

function pairFrom(art: EyeArt | EyePair): GridPair {
  if (isArt(art)) {
    const left = toGrid(art);
    return { left, right: mirror(left) };
  }
  return { left: toGrid(art.left), right: toGrid(art.right) };
}

const EMOTION_GRIDS = Object.fromEntries(
  EMOTIONS.map((emotion) => [emotion, pairFrom(EMOTION_ART[emotion] as EyeArt | EyePair)]),
) as Record<Emotion, GridPair>;

const EMOTION_GRIDS_UP = Object.fromEntries(
  EMOTIONS.map((emotion) => {
    const pair = EMOTION_GRIDS[emotion];
    return [emotion, { left: shiftRows(pair.left, 1), right: shiftRows(pair.right, 1) }];
  }),
) as Record<Emotion, GridPair>;

const DORMANT_GRIDS = pairFrom(DORMANT_ART);
const ERROR_GRIDS = pairFrom(ERROR_ART);
const BLINK_GRIDS = pairFrom(BLINK_ART);

/**
 * The shape actually on the matrix. State wins over emotion where the two would
 * contradict each other: a dormant face has shut eyes whatever its mood, and an
 * error is never worn happily.
 */
export function eyeGrids(state: AssistantState, emotion: Emotion, blinking: boolean): GridPair {
  if (blinking && state !== "error") return BLINK_GRIDS;
  switch (state) {
    case "dormant":
      return DORMANT_GRIDS;
    case "error":
      return ERROR_GRIDS;
    case "thinking":
      return EMOTION_GRIDS_UP[emotion];
    case "listening":
    case "speaking":
      return EMOTION_GRIDS[emotion];
  }
}

/** Shut eyes regardless of state or emotion - the dormant shape. */
export function closedEyes(): GridPair {
  return DORMANT_GRIDS;
}

/** Brightness ceiling per state, so a dormant face is dim without changing shape. */
export const STATE_GAIN: Record<AssistantState, number> = {
  dormant: 0.6,
  listening: 1,
  thinking: 0.92,
  speaking: 1,
  error: 1,
};

export const STATE_LABEL: Record<AssistantState, string> = {
  dormant: "DORMANT",
  listening: "LISTENING",
  thinking: "THINKING",
  speaking: "SPEAKING",
  error: "ERROR",
};

const TAU = Math.PI * 2;

function bell(x: number): number {
  // x in -1..1 -> 0..1, flat-ish across the middle of the mouth
  return Math.cos(x * (Math.PI / 2)) ** 1.5;
}

function wobble(col: number, now: number): number {
  const a = Math.sin(col * 1.7 + now * 0.011);
  const b = Math.sin(col * 0.9 - now * 0.017);
  return (a + b) * 0.25 + 0.7;
}

/**
 * Mouth is generated per frame rather than authored, because it is the one part of
 * the face that tracks a continuous signal. `level` is 0..1 short-window audio RMS.
 */
export function mouthGrid(
  out: Float32Array,
  state: AssistantState,
  level: number,
  now: number,
): void {
  out.fill(0);
  const mid = (MOUTH_ROWS - 1) / 2;
  const set = (col: number, row: number, value: number): void => {
    if (col < 0 || col >= MOUTH_COLS || row < 0 || row >= MOUTH_ROWS) return;
    const index = row * MOUTH_COLS + col;
    if (value > out[index]) out[index] = value;
  };

  switch (state) {
    case "dormant": {
      const breath = 0.2 + 0.12 * (0.5 + 0.5 * Math.sin((now / 4200) * TAU));
      for (let col = 4; col <= MOUTH_COLS - 5; col += 1) set(col, mid, breath);
      break;
    }
    case "listening": {
      // an even line with a soft glow drifting along it - attentive, not busy. No
      // vertical bulge: upscaled, a travelling bulge read as a lump on the mouth.
      const phase = (now / 2400) * TAU;
      for (let col = 0; col < MOUTH_COLS; col += 1) {
        const glow = 0.5 + 0.5 * Math.sin(phase - col * 0.45);
        set(col, mid, 0.5 + 0.22 * glow);
      }
      break;
    }
    case "thinking": {
      const step = Math.floor(now / 260) % 4;
      for (let dot = 0; dot < 3; dot += 1) {
        const col = 3 + dot * 3;
        set(col, mid, step === dot ? 1 : 0.2);
        set(col + 1, mid, step === dot ? 0.5 : 0.12);
      }
      break;
    }
    case "speaking": {
      const drive = Math.min(1, Math.max(0, level));
      for (let col = 0; col < MOUTH_COLS; col += 1) {
        const x = (col - (MOUTH_COLS - 1) / 2) / ((MOUTH_COLS - 1) / 2);
        const height = drive * bell(x) * wobble(col, now) * (mid + 0.7);
        set(col, mid, 0.42 + 0.58 * Math.min(1, drive * 1.6));
        for (let step = 1; step <= mid; step += 1) {
          const fill = Math.min(1, Math.max(0, height - (step - 1)));
          if (fill <= 0) break;
          set(col, mid - step, fill);
          set(col, mid + step, fill);
        }
      }
      break;
    }
    case "error": {
      for (let col = 0; col < MOUTH_COLS; col += 1) {
        set(col, mid, col % 2 === 0 ? 1 : 0.15);
      }
      set(1, mid - 1, 0.6);
      set(MOUTH_COLS - 2, mid - 1, 0.6);
      break;
    }
  }
}
