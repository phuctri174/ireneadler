// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Shiai's scoreboard on the matrix (core/irene/shiai.py): the running score on the
// left of the dojo, where the scene leaves the wall bare. His row on top, "YOU" in
// amber; hers below, "IRENE" in pink; each count a big digit. Core sends the score
// the moment a point is called, before she says it - the side that just scored
// flashes white for a moment.

import { glyphCells, textWidth } from "../board/font";
import { FADE, INK } from "./grid";
import type { Frame, Ink } from "./grid";

export interface ShiaiScore {
  you: number;
  her: number;
  /** When it last changed (performance.now()). */
  at: number;
  /** Who just scored (null: the bout just began). */
  scored: "you" | "her" | null;
}

const FLASH_MS = 900;
const LEFT = 1;
const DIGIT_X = 23;
const DIGIT_SIZE = 3;

let score: ShiaiScore | null = null;

/** The bout's score (null: no shiai). Set from core's "shiai" messages. */
export function shiaiScore(next: ShiaiScore | null): void {
  score = next;
}

export function currentScore(): ShiaiScore | null {
  return score;
}

/** One of core's "shiai" messages applied to the score. Pure. */
export function scoreOn(prev: ShiaiScore | null, message: { action: string; you?: number; her?: number }, now: number): ShiaiScore | null {
  if (message.action === "end") return null;
  if (message.action === "start") return { you: 0, her: 0, at: now, scored: null };
  if (message.action !== "score") return prev;
  const you = Math.max(0, Math.round(message.you ?? 0));
  const her = Math.max(0, Math.round(message.her ?? 0));
  const scored = prev && you > prev.you ? "you" : prev && her > prev.her ? "her" : null;
  return { you, her, at: now, scored };
}

function write(frame: Frame, text: string, x: number, y: number, v: number, ink: Ink, size = 1): void {
  let at = x;
  for (const ch of text) {
    for (const c of glyphCells(ch, at, y, size)) frame.cover(c.x, c.y, v, ink, FADE.fast);
    at += textWidth(ch, size) + size;
  }
}

/** The scoreboard: his row, a rule, her row. */
export function drawScore(frame: Frame, s: ShiaiScore, now: number): void {
  const k = now - s.at;
  const flashing = (who: "you" | "her") => s.scored === who && k >= 0 && k < FLASH_MS && Math.floor(k / 150) % 2 === 0;
  const rows: [string, number, "you" | "her", Ink, number][] = [
    ["YOU", s.you, "you", INK.amber, 6],
    ["IRENE", s.her, "her", INK.pink, 27],
  ];
  for (const [label, n, who, ink, y] of rows) {
    const hot = flashing(who);
    write(frame, label, LEFT, y + 5, 1, hot ? INK.white : ink);
    write(frame, String(Math.min(n, 9)), DIGIT_X, y, 1, hot ? INK.white : ink, DIGIT_SIZE);
  }
  // the rule between them
  for (let x = LEFT; x <= DIGIT_X + 8; x += 1) frame.cover(x, 23, 0.35, INK.white, FADE.fast);
}
