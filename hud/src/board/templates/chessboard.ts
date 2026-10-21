// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// A chessboard, accurately: a position from a FEN (checked for legality by chess.js),
// squares highlighted, arrows for moves, a game stepped through move by move from
// SAN/PGN. An opening is always its MOVES - there is no table of named openings
// (Round 7: the table was why only a few could ever be drawn); "opening" is just
// its name, shown as the title.
//
//   { "template": "chessboard", "fen"?: "...", "moves"?: ["e4", "e5"] | "1. e4 e5",
//     "opening"?: "Ruy Lopez", "highlight"?: ["e4"], "arrows"?: [["e2", "e4"]],
//     "flip"?: false }
//
// Illustrating an answer (core/irene/illustrate.py sends these, never the model):
//   "sync": true    the moves play only as she says them - each "reveal" item
//                   { "key": "ply:3", "at": ms } plays up to that move - and
//   "notes"         [{ "text", "at" }] her key terms, in the panel under the moves
//
// A game with him (core/irene/chess_game.py sends these after every move):
//   "live": true    the position NOW, at once - no stepping through moves; "last"
//                   ["e2", "e4"] lights the move just played, "history" is the game's
//                   SAN so far for the move list, "status" the line under it
//                   ("YOUR MOVE"). The HUD keeps a live board up without re-sketching.
//                   "history" is always the WHOLE game, numbered here from move one.
//                   "ply" is which position of the game this is: the HUD echoes it back
//                   with what it drew (liveEcho) and core checks it against the game -
//                   the HUD never keeps a game of its own, never decides legality.

import { Chess, validateFen } from "chess.js";
import type { Template } from "../kit";
import { arrow, box, fill, text, wrap } from "../kit";
import type { Stroke } from "../strokes";
import { BoardError, bool, list, num, obj, optStr, str } from "../validate";

const SQ = 7;
const X0 = 6;
const Y0 = 8;
const STEP_MS = 1100;
const PANEL = { x: 67, y: 18, chars: 15 };
const FIRST_MOVE_MS = 1500;

// 5x5 piece art, drawn inside a 7x7 square
// (each its own silhouette, readable at a glance: a small round-headed pawn; the
// rook's battlements; the knight's head and muzzle facing left; the bishop's mitre
// with its slit; the queen's three-point crown; the king's cross)
const PIECES: Record<string, readonly string[]> = {
  p: [".....", "..#..", ".###.", "..#..", ".###."],
  r: ["#.#.#", "#####", ".###.", ".###.", "#####"],
  n: ["..##.", ".####", "##.##", "..###", ".####"],
  b: ["..#..", ".#.#.", ".##..", "..#..", ".###."],
  q: ["#.#.#", "#####", ".###.", "..#..", "#####"],
  k: ["..#..", "#####", "..#..", ".###.", "#####"],
};

interface Position {
  board: ({ type: string; color: "w" | "b" } | null)[][];
  last: { from: string; to: string } | null;
  san: string | null;
  turn: "w" | "b";
}

interface ChessArgs {
  positions: Position[];
  title: string | null;
  highlight: string[];
  arrows: [string, string][];
  flip: boolean;
  // illustrating an answer: the plies reached (with when), and her key terms
  sync: boolean;
  plies: { ply: number; at: number }[];
  notes: { text: string; at: number }[];
  // a game in progress: the position now, its moves so far, and the status line
  live: boolean;
  history: string[];
  status: string | null;
  ply: number | null;
}

const SYNC_STEP_MS = 700; // moves named in one sentence still play one by one
const NOTE_FRESH_MS = 1400;

/** The move shown at `t` when the moves follow her sentences. */
function syncedStep(plies: ChessArgs["plies"], last: number, t: number): number {
  let shown = 0;
  for (const { ply, at } of plies) {
    if (at > t) break;
    const target = Math.min(ply, last);
    if (target > shown) shown = Math.min(target, shown + 1 + Math.floor((t - at) / SYNC_STEP_MS));
  }
  return shown;
}

const SQUARE = /^[a-h][1-8]$/;

function square(value: unknown, what: string): string {
  const s = String(value ?? "").trim().toLowerCase();
  if (!SQUARE.test(s)) throw new BoardError(`${what} must be a square like e4`);
  return s;
}

type MoveText = string | { from: string; to: string; promotion?: string };

function sanList(raw: unknown): MoveText[] {
  // SAN ("Nf3"), coordinates ("g1f3") or square pairs (["g1", "f3"]) all name a move
  if (Array.isArray(raw)) {
    return raw
      .map((m): MoveText => (Array.isArray(m) && m.length === 2 ? { from: String(m[0]).toLowerCase(), to: String(m[1]).toLowerCase(), promotion: "q" } : String(m).trim()))
      .filter((m) => m !== "");
  }
  if (typeof raw === "string") {
    // PGN movetext: drop move numbers, comments, results
    return raw
      .replace(/\{[^}]*\}/g, " ")
      .replace(/\d+\.(\.\.)?/g, " ")
      .replace(/\b(1-0|0-1|1\/2-1\/2|\*)\s*$/, " ")
      .split(/\s+/)
      .filter(Boolean);
  }
  throw new BoardError("moves must be a list of SAN moves or PGN text");
}

function snapshot(game: Chess, last: Position["last"], san: string | null): Position {
  return { board: game.board().map((row) => row.map((p) => (p ? { type: p.type, color: p.color } : null))), last, san, turn: game.turn() };
}

export const template: Template<ChessArgs> = {
  parse(a) {
    const fen = optStr(a, "fen", 100);
    const openingName = optStr(a, "opening", 40);
    let title: string | null = optStr(a, "title", 24) ?? null;
    let moves = a.moves === undefined ? [] : sanList(a.moves);
    if (openingName) {
      // an opening is its moves: a name with none is nothing to draw
      if (moves.length === 0 && !fen) throw new BoardError(`${openingName}: give its moves (SAN), e.g. ["e4", "e5", "Nf3"]`);
      title = title ?? openingName.slice(0, 24);
    }
    if (moves.length > 80) throw new BoardError("at most 80 moves");
    let position = fen;
    if (position) {
      let check = validateFen(position);
      // an en-passant square that can't be right changes nothing on the board: drop it
      if (!check.ok && /en.?passant/i.test(check.error ?? "")) {
        const fields = position.split(/\s+/);
        fields[3] = "-";
        position = fields.join(" ");
        check = validateFen(position);
      }
      if (!check.ok) throw new BoardError(`illegal FEN: ${check.error}`);
    }
    let game: Chess;
    try {
      game = new Chess(position || undefined);
    } catch (error) {
      throw new BoardError(`illegal FEN: ${error instanceof Error ? error.message : error}`);
    }
    const positions = [snapshot(game, null, null)];
    for (const m of moves) {
      let done;
      try {
        done = game.move(m);
      } catch {
        throw new BoardError(`illegal move ${typeof m === "string" ? m : `${m.from}${m.to}`} after ${positions.length - 1} move(s)`);
      }
      positions.push(snapshot(game, { from: done.from, to: done.to }, done.san));
    }
    const highlight = list(a, "highlight", { def: [], max: 16 }).map((s, i) => square(s, `highlight[${i}]`));
    const arrows = list(a, "arrows", { def: [], max: 8 }).map((raw, i): [string, string] => {
      if (typeof raw === "string" && /^[a-h][1-8][a-h][1-8]$/i.test(raw.trim())) return [raw.slice(0, 2).toLowerCase(), raw.slice(2, 4).toLowerCase()];
      if (Array.isArray(raw) && raw.length === 2) return [square(raw[0], `arrows[${i}][0]`), square(raw[1], `arrows[${i}][1]`)];
      throw new BoardError(`arrows[${i}] must be ["e2", "e4"]`);
    });
    const sync = bool(a, "sync");
    const plies = list(a, "reveal", { def: [], max: 40 })
      .map((raw, i) => {
        const r = obj(raw, `reveal[${i}]`);
        const key = str(r, "key", { max: 12 });
        const m = /^ply:(\d+)$/.exec(key);
        if (!m) throw new BoardError(`reveal[${i}] must be ply:N`);
        return { ply: Number(m[1]), at: num(r, "at", { min: 0, max: 600000, def: 0 }) };
      })
      .sort((x, y) => x.at - y.at);
    const notes = list(a, "notes", { def: [], max: 24 }).map((raw, i) => {
      const n = obj(raw, `notes[${i}]`);
      return { text: str(n, "text", { max: 30 }), at: num(n, "at", { min: 0, max: 600000, def: 0 }) };
    });
    const live = bool(a, "live");
    if (live) {
      const lastRaw = list(a, "last", { def: [], max: 2 });
      if (lastRaw.length === 2) positions[positions.length - 1].last = { from: square(lastRaw[0], "last[0]"), to: square(lastRaw[1], "last[1]") };
    }
    const history = list(a, "history", { def: [], max: 400 }).map((m, i) => {
      const s = String(m ?? "").trim();
      if (!s || s.length > 8) throw new BoardError(`history[${i}] must be a SAN move`);
      return s;
    });
    const status = optStr(a, "status", 22) ?? null;
    const ply = live && a.ply !== undefined ? num(a, "ply", { min: 0, max: 1000, def: 0 }) : null;
    return { positions, title, highlight, arrows, flip: bool(a, "flip"), sync, plies, notes, live, history, status, ply };
  },

  render(g, { t }) {
    // after the board is sketched, the moves play one by one, then it holds
    // (illustrating her answer: each move as she says it)
    const step = g.positions.length === 1 || g.live ? g.positions.length - 1 : g.sync ? syncedStep(g.plies, g.positions.length - 1, t) : Math.min(g.positions.length - 1, Math.max(0, Math.floor((t - FIRST_MOVE_MS) / STEP_MS) + 1));
    const pos = g.positions[step];
    const at = (sq: string) => {
      const file = sq.charCodeAt(0) - 97;
      const rank = Number(sq[1]) - 1;
      const col = g.flip ? 7 - file : file;
      const row = g.flip ? rank : 7 - rank;
      return { x: X0 + col * SQ, y: Y0 + row * SQ };
    };
    const out: Stroke[] = [];
    // the panel beside the board, under her face: title, moves, whose turn
    let y = PANEL.y;
    if (g.title) for (const l of wrap(g.title.toUpperCase(), PANEL.chars).slice(0, 2)) {
      out.push(text(PANEL.x, y, l, "white"));
      y += 7;
    }
    out.push(box(X0 - 1, Y0 - 1, SQ * 8 + 2, SQ * 8 + 2, "accent", 0.7));
    for (let r = 0; r < 8; r += 1) {
      for (let c = 0; c < 8; c += 1) {
        if ((r + c) % 2 === 0) out.push(fill(X0 + c * SQ, Y0 + r * SQ, SQ, SQ, "white", 0.12));
      }
    }
    // file letters under, rank numbers beside
    for (let k = 0; k < 8; k += 1) {
      const file = String.fromCharCode(97 + (g.flip ? 7 - k : k));
      const rank = String(g.flip ? k + 1 : 8 - k);
      out.push(text(X0 + k * SQ + 2, Y0 + SQ * 8 + 2, file, "accent", "left", 1, 0.7));
      out.push(text(X0 - 5, Y0 + k * SQ + 1, rank, "accent", "left", 1, 0.7));
    }
    if (pos.last) for (const sq of [pos.last.from, pos.last.to]) {
      const p = at(sq);
      out.push(fill(p.x, p.y, SQ, SQ, "amber", 0.28));
    }
    for (const sq of g.highlight) {
      const p = at(sq);
      out.push(fill(p.x, p.y, SQ, SQ, "cyan", 0.3), box(p.x, p.y, SQ, SQ, "cyan"));
    }
    pos.board.forEach((rowCells, r) =>
      rowCells.forEach((piece, c) => {
        if (!piece) return;
        const sq = `${String.fromCharCode(97 + c)}${8 - r}`;
        const p = at(sq);
        const cells: { x: number; y: number }[] = [];
        PIECES[piece.type].forEach((line, y) => {
          for (let x = 0; x < 5; x += 1) if (line[x] === "#") cells.push({ x: p.x + 1 + x, y: p.y + 1 + y });
        });
        out.push({ kind: "cells", cells, color: piece.color === "w" ? "white" : "pink" });
      }),
    );
    for (const [from, to] of g.arrows) {
      const a = at(from);
      const b = at(to);
      out.push(arrow(a.x + 3, a.y + 3, b.x + 3, b.y + 3, "amber", 3));
    }
    // moves so far, numbered from wherever the game started
    const first = g.positions[0];
    const played = g.live ? g.history : g.positions.slice(1, step + 1).map((p) => p.san as string);
    const lines: string[] = [];
    let k = 0;
    let n = 1;
    if (played.length && first.turn === "b" && !g.live) lines.push(`${n++}... ${played[k++]}`);
    for (; k < played.length; k += 2) lines.push(`${n++}.${played[k]}${played[k + 1] ? ` ${played[k + 1]}` : ""}`);
    const notes = g.notes.filter((n) => n.at <= t);
    if (g.sync && notes.length) {
      // the moves on one line, her key terms under them as she says them
      const moves = lines.join(" ").toUpperCase();
      const moveLines = moves ? wrap(moves, PANEL.chars).slice(-2) : [];
      moveLines.forEach((l, i) => out.push(text(PANEL.x, y + i * 7, l, "amber")));
      y += moveLines.length * 7 + (moveLines.length ? 2 : 0);
      const room = Math.max(1, Math.floor((62 - y) / 7));
      notes.slice(-room).forEach((n, i) => {
        const fresh = t - n.at < NOTE_FRESH_MS;
        out.push(text(PANEL.x, y + i * 7, n.text.toUpperCase().slice(0, PANEL.chars), fresh ? "amber" : "white"));
      });
    } else {
      const room = Math.max(1, Math.floor((62 - y) / 7));
      lines.slice(-room).forEach((l, i, shown) => out.push(text(PANEL.x, y + i * 7, l.toUpperCase(), i === shown.length - 1 ? "amber" : "white")));
    }
    out.push(text(PANEL.x, 66, g.status ?? (pos.turn === "w" ? "WHITE TO MOVE" : "BLACK TO MOVE"), g.status ? "amber" : "accent", "left", 1, g.status ? 1 : 0.7));
    return out;
  },
};

/** A drawn position as the first two FEN fields: its pieces and whose move it is. */
function placementOf(p: Position): string {
  const rows = p.board.map((row) => {
    let out = "";
    let empty = 0;
    for (const cell of row) {
      if (!cell) {
        empty += 1;
        continue;
      }
      if (empty) out += String(empty);
      empty = 0;
      out += cell.color === "w" ? cell.type.toUpperCase() : cell.type;
    }
    return out + (empty ? String(empty) : "");
  });
  return `${rows.join("/")} ${p.turn}`;
}

/** What a live game board really shows, for core to check against the game: the
 *  pieces and turn drawn, and where the move list it prints replays to from the
 *  start (the list is drawn from "history", the pieces from "fen" - they must agree). */
export function liveEcho(g: ChessArgs): { ply: number; fen: string; replayed: string | null; moves: number } | null {
  if (!g.live || g.ply === null) return null;
  const shown = g.positions[g.positions.length - 1];
  let replayed: string | null = null;
  try {
    const game = new Chess();
    for (const m of g.history) game.move(m);
    replayed = game.fen().split(" ").slice(0, 2).join(" ");
  } catch {
    replayed = "unreplayable";
  }
  return { ply: g.ply, fen: placementOf(shown), replayed, moves: g.history.length };
}
