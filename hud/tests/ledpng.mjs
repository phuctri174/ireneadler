// LED frames to PNG, the way the HUD draws them: lit cells with a soft glow over
// faint unlit dots. Shared by tests/snap.mjs and art previews.
import { deflateSync } from "node:zlib";
import { COLS, ROWS, INK } from "../.verify/led/grid.js";

const PITCH = 8;
const RGB = {
  [INK.accent]: [34, 224, 255],
  [INK.pink]: [255, 95, 162],
  [INK.white]: [234, 255, 255],
  [INK.amber]: [255, 182, 72],
  [INK.red]: [255, 92, 92],
  [INK.iceCore]: [168, 228, 255],
  [INK.iceRing]: [60, 150, 255],
  [INK.cyan]: [34, 224, 255],
  [INK.green]: [40, 196, 104],
  [INK.violet]: [176, 150, 255],
};
const BG = [4, 9, 13];
const UNLIT = [12, 26, 32];

function crc32(buf) {
  let c, crc = 0xffffffff;
  for (let n = 0; n < buf.length; n++) {
    c = (crc ^ buf[n]) & 0xff;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    crc = (crc >>> 8) ^ c;
  }
  return (crc ^ 0xffffffff) >>> 0;
}

export function png(width, height, rgb) {
  const raw = Buffer.alloc((width * 3 + 1) * height);
  for (let y = 0; y < height; y++) {
    raw[y * (width * 3 + 1)] = 0;
    for (let x = 0; x < width * 3; x++) raw[y * (width * 3 + 1) + 1 + x] = Math.max(0, Math.min(255, Math.round(rgb[y * width * 3 + x])));
  }
  const chunk = (type, data) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(type), data]);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(crc32(td));
    return Buffer.concat([len, td, crc]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", ihdr), chunk("IDAT", deflateSync(raw)), chunk("IEND", Buffer.alloc(0))]);
}

/** One frame drawn into an RGB float buffer at (ox, oy). */
export function paint(buf, stride, ox, oy, frame) {
  const glow = [];
  for (let r = -2; r <= 2; r++) for (let c = -2; c <= 2; c++) glow.push([c, r, Math.exp(-(c * c + r * r) / 2.2) * 0.12]);
  for (let row = 0; row < ROWS; row++) {
    for (let col = 0; col < COLS; col++) {
      const v = frame.value[row * COLS + col];
      const color = RGB[frame.ink[row * COLS + col]] ?? RGB[INK.accent];
      for (let py = 1; py < PITCH - 1; py++) {
        for (let px = 1; px < PITCH - 1; px++) {
          const i = ((oy + row * PITCH + py) * stride + ox + col * PITCH + px) * 3;
          // lit cells add light over the unlit dot, as the canvas does: never darker
          for (let k = 0; k < 3; k++) buf[i + k] = Math.max(buf[i + k], UNLIT[k] + (v > 0.012 ? color[k] * v : 0));
        }
      }
      if (v <= 0.012) continue;
      // the glow: a soft halo onto the neighbouring cells' gaps
      for (const [dc, dr, w] of glow) {
        const cx = col + dc, cy = row + dr;
        if (cx < 0 || cy < 0 || cx >= COLS || cy >= ROWS) continue;
        for (let py = 0; py < PITCH; py += 2) {
          for (let px = 0; px < PITCH; px += 2) {
            const i = ((oy + cy * PITCH + py) * stride + ox + cx * PITCH + px) * 3;
            for (let k = 0; k < 3; k++) buf[i + k] += color[k] * v * w;
          }
        }
      }
    }
  }
}


/** Frames side by side, `cols` across, as one PNG. */
export function paintSheet(frames, cols = 3) {
  const gap = 12;
  const rows = Math.ceil(frames.length / cols);
  const fw = COLS * PITCH, fh = ROWS * PITCH;
  const width = cols * fw + (cols - 1) * gap, height = rows * fh + (rows - 1) * gap;
  const buf = new Float32Array(width * height * 3);
  for (let i = 0; i < width * height; i++) for (let k = 0; k < 3; k++) buf[i * 3 + k] = BG[k];
  frames.forEach((frame, n) => paint(buf, width, (n % cols) * (fw + gap), Math.floor(n / cols) * (fh + gap), frame));
  return png(width, height, buf);
}
