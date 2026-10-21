// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Draws the eased matrix onto a canvas. Every cell is the same fixture as the old
// DOM face - a rounded LED with a soft glow over a faint unlit dot - rendered as
// one pre-baked sprite per ink, stamped additively where lit, so overlapping
// glows add up like real LEDs.

import { COLS, INK, INK_COUNT, ROWS } from "./grid";

const LIT_EPSILON = 0.012;
const CORE = 0.74; // lit square, as a fraction of pitch
const GLOW = 0.95; // blur radius, as a fraction of pitch
const UNLIT = "rgba(150, 220, 240, 0.085)";

export type Rgb = [number, number, number];

export function parseColor(css: string): Rgb {
  const value = css.trim();
  if (value.startsWith("#")) {
    const hex = value.length === 4 ? value.replace(/^#(.)(.)(.)$/, "#$1$1$2$2$3$3") : value;
    const n = Number.parseInt(hex.slice(1, 7), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  const parts = value.match(/[\d.]+/g)?.map(Number) ?? [255, 255, 255];
  return [parts[0], parts[1], parts[2]];
}

export class LedRenderer {
  private readonly ctx: CanvasRenderingContext2D;
  private pitch = 1;
  private offsetX = 0;
  private offsetY = 0;
  private sprites: (HTMLCanvasElement | null)[] = new Array(INK_COUNT).fill(null);
  private colors: Rgb[] = new Array(INK_COUNT).fill([255, 255, 255]);
  private unlit: HTMLCanvasElement | null = null;
  // the last frame drawn: an identical one is not drawn again (no GPU work at all)
  private lastValues: Float32Array | null = null;
  private lastInks: Uint8Array | null = null;

  constructor(private readonly canvas: HTMLCanvasElement) {
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("2d canvas unavailable");
    this.ctx = ctx;
  }

  /** Size the backing store to the element's on-screen size (after transforms). */
  resize(): void {
    const rect = this.canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.round(rect.width * dpr));
    const height = Math.max(1, Math.round(rect.height * dpr));
    if (width === this.canvas.width && height === this.canvas.height && this.unlit) return;
    this.canvas.width = width;
    this.canvas.height = height;
    this.pitch = Math.min(width / COLS, height / ROWS);
    this.offsetX = (width - this.pitch * COLS) / 2;
    this.offsetY = (height - this.pitch * ROWS) / 2;
    this.sprites.fill(null);
    this.unlit = this.bakeUnlit(width, height);
    // the unlit dots never change: the compositor holds them as the canvas's
    // background instead of every frame re-blitting a full-size image (measured:
    // under GPU load from the model her frames came 67 ms apart)
    this.canvas.style.backgroundImage = `url(${this.unlit.toDataURL()})`;
    this.canvas.style.backgroundSize = "100% 100%";
    this.lastValues = null;
  }

  setColor(ink: number, rgb: Rgb): void {
    const old = this.colors[ink];
    if (old[0] === rgb[0] && old[1] === rgb[1] && old[2] === rgb[2] && this.sprites[ink]) return;
    this.colors[ink] = rgb;
    this.sprites[ink] = null;
    // the same dots in a new colour are a new frame
    this.lastValues = null;
  }

  draw(values: Float32Array, inks: Uint8Array): void {
    if (this.same(values, inks)) return;
    const { ctx, pitch } = this;
    ctx.globalCompositeOperation = "source-over";
    ctx.globalAlpha = 1;
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    ctx.globalCompositeOperation = "lighter";
    const half = this.spriteSize() / 2;
    for (let row = 0; row < ROWS; row += 1) {
      const cy = this.offsetY + (row + 0.5) * pitch - half;
      for (let col = 0; col < COLS; col += 1) {
        const i = row * COLS + col;
        const v = values[i];
        if (v < LIT_EPSILON) continue;
        const sprite = this.sprite(inks[i]);
        ctx.globalAlpha = v > 1 ? 1 : v;
        ctx.drawImage(sprite, this.offsetX + (col + 0.5) * pitch - half, cy);
      }
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
  }

  /** This frame is the last one again (values to 1/512, the same inks)? Keeps a copy. */
  private same(values: Float32Array, inks: Uint8Array): boolean {
    const lv = this.lastValues;
    const li = this.lastInks;
    if (lv && li && lv.length === values.length && li.length === inks.length) {
      let i = 0;
      for (; i < values.length; i += 1) {
        if (Math.abs(values[i] - lv[i]) > 1 / 512 || inks[i] !== li[i]) break;
      }
      if (i === values.length) return true;
      lv.set(values);
      li.set(inks);
      return false;
    }
    this.lastValues = new Float32Array(values);
    this.lastInks = new Uint8Array(inks);
    return false;
  }

  private spriteSize(): number {
    return Math.ceil(this.pitch * (1 + GLOW * 2.2));
  }

  private sprite(ink: number): HTMLCanvasElement {
    const cached = this.sprites[ink];
    if (cached) return cached;
    const size = this.spriteSize();
    const node = document.createElement("canvas");
    node.width = size;
    node.height = size;
    const g = node.getContext("2d");
    if (!g) return node;
    const [r, gg, b] = this.colors[ink] ?? this.colors[INK.accent];
    const color = `rgb(${r}, ${gg}, ${b})`;
    const core = this.pitch * CORE;
    const x = (size - core) / 2;
    const radius = Math.max(1, core * 0.2);
    // two glow passes then a crisp core, like the old 4px + 11px box-shadows
    g.fillStyle = color;
    for (const [blur, alpha] of [
      [this.pitch * GLOW, 0.85],
      [this.pitch * GLOW * 0.35, 0.9],
    ] as const) {
      g.shadowColor = color;
      g.shadowBlur = blur;
      g.globalAlpha = alpha;
      roundRect(g, x, x, core, core, radius);
      g.fill();
    }
    g.shadowBlur = 0;
    g.globalAlpha = 1;
    roundRect(g, x, x, core, core, radius);
    g.fill();
    this.sprites[ink] = node;
    return node;
  }

  /**
   * Unlit LEDs across the whole canvas, on the matrix's pitch and phase - not just
   * the 128x72 area - so the margins a wider well leaves beside the matrix read as
   * more of the same panel instead of a dead strip.
   */
  private bakeUnlit(width: number, height: number): HTMLCanvasElement {
    const node = document.createElement("canvas");
    node.width = width;
    node.height = height;
    const g = node.getContext("2d");
    if (!g) return node;
    g.fillStyle = UNLIT;
    const dot = Math.max(1, this.pitch * 0.14);
    const firstCol = -Math.ceil(this.offsetX / this.pitch);
    const firstRow = -Math.ceil(this.offsetY / this.pitch);
    const lastCol = COLS + Math.ceil(this.offsetX / this.pitch);
    const lastRow = ROWS + Math.ceil(this.offsetY / this.pitch);
    for (let row = firstRow; row < lastRow; row += 1) {
      for (let col = firstCol; col < lastCol; col += 1) {
        const x = this.offsetX + (col + 0.5) * this.pitch;
        const y = this.offsetY + (row + 0.5) * this.pitch;
        if (x < 0 || y < 0 || x > width || y > height) continue;
        g.beginPath();
        g.arc(x, y, dot, 0, Math.PI * 2);
        g.fill();
      }
    }
    return node;
  }
}

function roundRect(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  g.beginPath();
  g.moveTo(x + r, y);
  g.arcTo(x + w, y, x + w, y + h, r);
  g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r);
  g.arcTo(x, y, x + w, y, r);
  g.closePath();
}
