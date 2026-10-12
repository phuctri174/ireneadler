// The LED matrix every face element, hand, prop and scene is drawn into. One
// target frame is composed per animation frame; the renderer eases each cell
// toward it at that cell's fade rate, so everything crossfades the same way the
// old face did, cell by cell.

export const COLS = 128;
export const ROWS = 72;
export const CELLS = COLS * ROWS;

/** Colour of a lit cell. Accent follows the assistant state; the rest are fixed. */
export const INK = {
  accent: 0,
  pink: 1,
  white: 2,
  amber: 3,
  red: 4,
  // the summon reveal's eye: a white-blue core inside a deeper ice-blue ring
  iceCore: 5,
  iceRing: 6,
  // fixed cyan, whatever the state colour (the summon burst)
  cyan: 7,
  // the kendo club's green (its banner in the dojo)
  green: 8,
  // the domain's violet: the black hole's glow and the drifting specks
  violet: 9,
} as const;
export type Ink = (typeof INK)[keyof typeof INK];
export const INK_COUNT = 10;

/** Fade times (ms to ~90%) by what is being drawn. */
export const FADE = {
  eyes: 200,
  mouth: 55,
  blink: 58,
  prop: 140,
  scene: 90,
  fast: 40,
  idle: 160,
} as const;

export class Frame {
  readonly value = new Float32Array(CELLS);
  readonly ink = new Uint8Array(CELLS);
  readonly fade = new Float32Array(CELLS);

  clear(): void {
    this.value.fill(0);
    this.ink.fill(INK.accent);
    this.fade.fill(FADE.idle);
  }

  /** Brightest wins - for things that glow together (face parts). */
  lighten(col: number, row: number, value: number, ink: Ink, fade: number): void {
    if (col < 0 || col >= COLS || row < 0 || row >= ROWS) return;
    const i = row * COLS + col;
    if (value >= this.value[i]) {
      this.value[i] = value;
      this.ink[i] = ink;
    }
    this.fade[i] = fade;
  }

  /** Replace, dark included - for things in front (hands, props, a board). */
  cover(col: number, row: number, value: number, ink: Ink, fade: number): void {
    if (col < 0 || col >= COLS || row < 0 || row >= ROWS) return;
    const i = row * COLS + col;
    this.value[i] = value;
    this.ink[i] = ink;
    this.fade[i] = fade;
  }
}

// ---- sprites ---------------------------------------------------------------

/**
 * Art key, shared with the eye art: `.` transparent, `_` opaque-dark (hides what
 * is behind), `,` faint, `-` dim, `+` mid, `#` full.
 */
const LEVEL: Record<string, number> = { _: 0, ",": 0.1, "-": 0.22, "+": 0.55, "#": 1 };

export interface Sprite {
  w: number;
  h: number;
  /** NaN where transparent. */
  cells: Float32Array;
}

export function sprite(lines: readonly string[]): Sprite {
  const h = lines.length;
  const w = Math.max(...lines.map((line) => line.length));
  const cells = new Float32Array(w * h).fill(Number.NaN);
  for (let row = 0; row < h; row += 1) {
    for (let col = 0; col < w; col += 1) {
      const level = LEVEL[lines[row][col] ?? "."];
      if (level !== undefined) cells[row * w + col] = level;
    }
  }
  return { w, h, cells };
}

export interface BlitOptions {
  ink?: Ink;
  alpha?: number;
  fade?: number;
  flipX?: boolean;
  /** Integer upscale; each art cell becomes scale x scale LEDs. */
  scale?: number;
  /** Cover (occlude) rather than lighten. Default true: sprites sit in front. */
  cover?: boolean;
}

/** Draw `s` with its top-left at (x, y). */
export function blit(frame: Frame, s: Sprite, x: number, y: number, options: BlitOptions = {}): void {
  const { ink = INK.accent, alpha = 1, fade = FADE.prop, flipX = false, scale = 1, cover = true } = options;
  const ox = Math.round(x);
  const oy = Math.round(y);
  for (let row = 0; row < s.h; row += 1) {
    for (let col = 0; col < s.w; col += 1) {
      const level = s.cells[row * s.w + (flipX ? s.w - 1 - col : col)];
      if (Number.isNaN(level)) continue;
      for (let dy = 0; dy < scale; dy += 1) {
        for (let dx = 0; dx < scale; dx += 1) {
          const c = ox + col * scale + dx;
          const r = oy + row * scale + dy;
          if (cover && alpha >= 0.999) {
            frame.cover(c, r, level, ink, fade);
          } else if (cover) {
            // partially faded-in cover: blend toward the sprite
            if (c < 0 || c >= COLS || r < 0 || r >= ROWS) continue;
            const i = r * COLS + c;
            frame.value[i] = frame.value[i] * (1 - alpha) + level * alpha;
            if (alpha > 0.5) frame.ink[i] = ink;
            frame.fade[i] = fade;
          } else {
            frame.lighten(c, r, level * alpha, ink, fade);
          }
        }
      }
    }
  }
}

/**
 * Smooth integer upscale of a small value grid into the frame, lighten-blended,
 * with (x, y) the top-left of the output. Bilinear sampling keeps authored shapes
 * but rounds their steps, so a 7x7 eye reads as curves at 3x rather than blocks.
 */
export function upscale(
  frame: Frame,
  grid: Float32Array,
  cols: number,
  rows: number,
  factor: number,
  x: number,
  y: number,
  gain: number,
  ink: Ink,
  fade: number,
): void {
  const outW = cols * factor;
  const outH = rows * factor;
  const at = (c: number, r: number): number => {
    if (c < 0 || c >= cols || r < 0 || r >= rows) return 0;
    return grid[r * cols + c];
  };
  for (let oy = 0; oy < outH; oy += 1) {
    const sy = (oy + 0.5) / factor - 0.5;
    const r0 = Math.floor(sy);
    const fy = sy - r0;
    for (let ox = 0; ox < outW; ox += 1) {
      const sx = (ox + 0.5) / factor - 0.5;
      const c0 = Math.floor(sx);
      const fx = sx - c0;
      const top = at(c0, r0) * (1 - fx) + at(c0 + 1, r0) * fx;
      const bottom = at(c0, r0 + 1) * (1 - fx) + at(c0 + 1, r0 + 1) * fx;
      let v = top * (1 - fy) + bottom * fy;
      // firm up the edges so the shape doesn't read as blurred
      v = Math.min(1, Math.max(0, (v - 0.08) / 0.84));
      frame.lighten(x + ox, y + oy, v * gain, ink, fade);
    }
  }
}

// ---- signed-distance shapes, for the hand rig and props ----------------------

export interface Vec {
  x: number;
  y: number;
}

/** Distance from p to segment ab, minus radius: <0 inside a capsule. */
export function capsule(px: number, py: number, a: Vec, b: Vec, radius: number): number {
  const bx = b.x - a.x;
  const by = b.y - a.y;
  const t = Math.max(0, Math.min(1, ((px - a.x) * bx + (py - a.y) * by) / (bx * bx + by * by || 1)));
  const dx = px - (a.x + bx * t);
  const dy = py - (a.y + by * t);
  return Math.sqrt(dx * dx + dy * dy) - radius;
}

/** Rounded box centred at c with half-size (hw, hh). */
export function roundBox(px: number, py: number, c: Vec, hw: number, hh: number, radius: number): number {
  const qx = Math.abs(px - c.x) - (hw - radius);
  const qy = Math.abs(py - c.y) - (hh - radius);
  const outside = Math.sqrt(Math.max(qx, 0) ** 2 + Math.max(qy, 0) ** 2);
  return outside + Math.min(Math.max(qx, qy), 0) - radius;
}

/**
 * Rasterise one closed shape in front of what is already drawn: a bright rim where
 * |sdf| is small and a faint fill inside that hides whatever is behind. Drawing
 * parts in order (palm, then fingers) is what makes overlaps readable. A null fill
 * draws the rim alone and leaves the inside see-through (a helmet over a face).
 */
export function drawShape(
  frame: Frame,
  sdf: (x: number, y: number) => number,
  bounds: { x0: number; y0: number; x1: number; y1: number },
  ink: Ink,
  alpha: number,
  fade: number,
  rim = 1,
  fill: number | null = 0.16,
): void {
  const x0 = Math.max(0, Math.floor(bounds.x0));
  const y0 = Math.max(0, Math.floor(bounds.y0));
  const x1 = Math.min(COLS - 1, Math.ceil(bounds.x1));
  const y1 = Math.min(ROWS - 1, Math.ceil(bounds.y1));
  for (let row = y0; row <= y1; row += 1) {
    for (let col = x0; col <= x1; col += 1) {
      const d = sdf(col + 0.5, row + 0.5);
      if (d > 0.55) continue;
      const onRim = d > -0.55;
      if (!onRim && fill === null) continue;
      // rim fades out across the edge so diagonals anti-alias
      const floor = fill ?? 0;
      const level = onRim ? Math.max(rim * Math.min(1, (0.55 - d) / 0.5), floor) : floor;
      const i = row * COLS + col;
      if (alpha >= 0.999) {
        frame.value[i] = level;
      } else {
        frame.value[i] = frame.value[i] * (1 - alpha) + level * alpha;
      }
      frame.ink[i] = ink;
      frame.fade[i] = fade;
    }
  }
}

export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

export function clamp01(t: number): number {
  return Math.min(1, Math.max(0, t));
}

export function ease(t: number): number {
  const x = clamp01(t);
  return x * x * (3 - 2 * x);
}

export function easeOutBack(t: number): number {
  const x = clamp01(t);
  const c = 1.4;
  return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2;
}
