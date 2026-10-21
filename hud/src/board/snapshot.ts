// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// One of her board drawings as a picture, for a lecture note (core/irene/lecture_board.py
// sends board_render): drawn whole by the board's own code (prepare, drawBoard) into a
// frame of its own - never the live face - and painted as the board looks: lit dots
// with a soft glow over faint unlit ones (the same look as tests/ledpng.mjs).
import { COLS, Frame, INK, ROWS } from "../led/grid";
import { drawBoard, prepare } from "./board";

const PITCH = 8;
const RGB: Record<number, [number, number, number]> = {
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
const BG: [number, number, number] = [4, 9, 13];
const UNLIT: [number, number, number] = [12, 26, 32];
// long after it was shown: every stroke whole
const DONE_MS = 120_000;

/** The drawing as a data:image/png URI, or "" if it can't be drawn. */
export function boardSnapshot(spec: unknown): string {
  const prepared = prepare(spec, (why) => console.warn(`[irene] board snapshot refused: ${why}`));
  if (!prepared) return "";
  const frame = new Frame();
  frame.clear();
  drawBoard(frame, prepared, DONE_MS);
  const width = COLS * PITCH;
  const height = ROWS * PITCH;
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return "";
  const image = ctx.createImageData(width, height);
  const buf = new Float32Array(width * height * 3);
  for (let i = 0; i < width * height; i += 1) for (let k = 0; k < 3; k += 1) buf[i * 3 + k] = BG[k];
  const glow: [number, number, number][] = [];
  for (let r = -2; r <= 2; r += 1) for (let c = -2; c <= 2; c += 1) glow.push([c, r, Math.exp(-(c * c + r * r) / 2.2) * 0.12]);
  for (let row = 0; row < ROWS; row += 1) {
    for (let col = 0; col < COLS; col += 1) {
      const v = frame.value[row * COLS + col];
      const color = RGB[frame.ink[row * COLS + col]] ?? RGB[INK.accent];
      for (let py = 1; py < PITCH - 1; py += 1) {
        for (let px = 1; px < PITCH - 1; px += 1) {
          const i = ((row * PITCH + py) * width + col * PITCH + px) * 3;
          for (let k = 0; k < 3; k += 1) buf[i + k] = Math.max(buf[i + k], UNLIT[k] + (v > 0.012 ? color[k] * v : 0));
        }
      }
      if (v <= 0.012) continue;
      for (const [dc, dr, w] of glow) {
        const cx = col + dc;
        const cy = row + dr;
        if (cx < 0 || cy < 0 || cx >= COLS || cy >= ROWS) continue;
        for (let py = 0; py < PITCH; py += 2) {
          for (let px = 0; px < PITCH; px += 2) {
            const i = ((cy * PITCH + py) * width + cx * PITCH + px) * 3;
            for (let k = 0; k < 3; k += 1) buf[i + k] += color[k] * v * w;
          }
        }
      }
    }
  }
  for (let i = 0; i < width * height; i += 1) {
    for (let k = 0; k < 3; k += 1) image.data[i * 4 + k] = Math.max(0, Math.min(255, Math.round(buf[i * 3 + k])));
    image.data[i * 4 + 3] = 255;
  }
  ctx.putImageData(image, 0, 0);
  return canvas.toDataURL("image/png");
}
