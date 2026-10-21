// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// A small number on her face for a moment: in -Dev, the peak speed of the strike he
// just made against the threshold ("12.4/8.0"), so he can tune by feel against the
// number he actually produces. Core sends it only in -Dev (strike_readout).
import { glyphCells, textWidth } from "../board/font";
import { COLS } from "./grid";
import type { Frame } from "./grid";
import { FADE, INK } from "./grid";

const SHOW_MS = 2500;

let readout: { text: string; at: number } | null = null;

export function showReadout(text: string, now: number): void {
  readout = { text: text.toUpperCase().slice(0, 16), at: now };
}

/** Top-right corner, over whatever scene is up, fading in its last half second. */
export function drawReadout(frame: Frame, now: number): void {
  if (!readout || now < readout.at || now - readout.at > SHOW_MS) return;
  const left = SHOW_MS - (now - readout.at);
  const v = left < 500 ? left / 500 : 1;
  const width = [...readout.text].reduce((w, ch) => w + textWidth(ch) + 1, -1);
  let x = COLS - 1 - width;
  for (const ch of readout.text) {
    for (const c of glyphCells(ch, x, 0)) frame.cover(c.x, c.y, v, INK.amber, FADE.fast);
    x += textWidth(ch) + 1;
  }
}
