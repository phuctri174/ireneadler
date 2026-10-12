// Key frames of the LED matrix as PNGs, straight from the composer - no window, no
// OS input. Each shot is a Stage (led/compose.ts) at a moment; cells are drawn as
// the HUD draws them: a lit core with a soft glow over a faint unlit dot.
//
//   node scripts/render_frames.mjs <shots.json> <out dir>
//
// shots.json: [{ "name": "wave", "stage": { ...Stage fields } }], or with "draw": a
// <draw> spec for the illustration board (and "t", ms since it was shown)
// Stage times are relative: "at" fields may be given as negative ms before now
// (at: -900 = started 900 ms ago). Needs the compiled modules in .verify
// (node tests/run.mjs builds them).
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { deflateSync } from "node:zlib";

const V = new URL("../.verify/", import.meta.url);
const { Frame, COLS, ROWS, INK } = await import(new URL("led/grid.js", V));
const { compose } = await import(new URL("led/compose.js", V));
const { prepare } = await import(new URL("board/board.js", V));

const PITCH = 10;
const STATE_RGB = {
  dormant: [0x4a, 0x8a, 0x9e],
  listening: [0x22, 0xe0, 0xff],
  thinking: [0xff, 0xb6, 0x48],
  speaking: [0x5e, 0xf2, 0xb8],
  error: [0xff, 0x5c, 0x5c],
};
const FIXED = {
  [INK.pink]: [255, 95, 162],
  [INK.white]: [234, 255, 255],
  [INK.amber]: [0xff, 0xb6, 0x48],
  [INK.red]: [0xff, 0x5c, 0x5c],
  [INK.iceCore]: [168, 228, 255],
  [INK.iceRing]: [60, 150, 255],
  [INK.cyan]: [0x22, 0xe0, 0xff],
};

function crc32(buf) {
  let c;
  const table = crc32.table ?? (crc32.table = Array.from({ length: 256 }, (_, n) => {
    c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  }));
  let crc = 0xffffffff;
  for (const b of buf) crc = table[(crc ^ b) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function png(width, height, rgb) {
  const chunk = (type, data) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const body = Buffer.concat([Buffer.from(type), data]);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(crc32(body));
    return Buffer.concat([len, body, crc]);
  };
  const raw = Buffer.alloc((width * 3 + 1) * height);
  for (let y = 0; y < height; y += 1) {
    raw[y * (width * 3 + 1)] = 0;
    rgb.copy(raw, y * (width * 3 + 1) + 1, y * width * 3, (y + 1) * width * 3);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

export function renderFrame(frame, state) {
  const width = COLS * PITCH;
  const height = ROWS * PITCH;
  const light = new Float32Array(width * height * 3);
  const add = (x, y, r, g, b, a) => {
    if (x < 0 || y < 0 || x >= width || y >= height) return;
    const i = (y * width + x) * 3;
    light[i] += r * a;
    light[i + 1] += g * a;
    light[i + 2] += b * a;
  };
  const accent = STATE_RGB[state] ?? STATE_RGB.listening;
  for (let row = 0; row < ROWS; row += 1) {
    for (let col = 0; col < COLS; col += 1) {
      const cx = col * PITCH + PITCH / 2;
      const cy = row * PITCH + PITCH / 2;
      // unlit dot
      for (let dy = -1; dy <= 0; dy += 1) for (let dx = -1; dx <= 0; dx += 1) add(cx + dx, cy + dy, 150, 220, 240, 0.09);
      const v = Math.min(1, frame.value[row * COLS + col]);
      if (v < 0.012) continue;
      const [r, g, b] = FIXED[frame.ink[row * COLS + col]] ?? accent;
      const reach = PITCH * 1.4;
      for (let y = Math.floor(cy - reach); y <= cy + reach; y += 1) {
        for (let x = Math.floor(cx - reach); x <= cx + reach; x += 1) {
          const dx = Math.abs(x + 0.5 - cx);
          const dy = Math.abs(y + 0.5 - cy);
          const core = dx < PITCH * 0.37 && dy < PITCH * 0.37 ? 1 : 0;
          const glow = Math.exp(-(dx * dx + dy * dy) / (2 * (PITCH * 0.45) ** 2)) * 0.5;
          add(x, y, r, g, b, v * Math.max(core, glow));
        }
      }
    }
  }
  const out = Buffer.alloc(width * height * 3);
  for (let i = 0; i < light.length; i += 1) out[i] = Math.min(255, Math.round(light[i] + (i % 3 === 2 ? 12 : 8)));
  return png(width, height, out);
}

const NOW = 100000;
const DEFAULT = { state: "listening", emotion: "neutral", level: 0, now: NOW, blinking: false, muted: false, reaction: null, activity: null, summon: null };

function stamp(value) {
  // relative times: negative numbers are "ms ago"
  if (Array.isArray(value)) return value.map(stamp);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, ["at", "start", "part2", "since"].includes(k) && typeof v === "number" && v <= 0 ? NOW + v : stamp(v)]));
  }
  return value;
}

export function shoot(shot) {
  const stage = { ...DEFAULT, ...stamp(shot.stage ?? {}) };
  // a <draw> spec: the board as it looks `t` ms after it was shown (default: done)
  if (shot.draw) stage.board = { drawing: prepare(shot.draw), at: NOW - (shot.t ?? 30000) };
  const frame = new Frame();
  compose(frame, stage);
  return renderFrame(frame, stage.state);
}

if (process.argv[2]) {
  const shots = JSON.parse(readFileSync(process.argv[2], "utf8"));
  const dir = process.argv[3] ?? "shots";
  mkdirSync(dir, { recursive: true });
  for (const shot of shots) {
    writeFileSync(join(dir, `${shot.name}.png`), shoot(shot));
  }
  console.log(`${shots.length} frame(s) -> ${dir}`);
}
