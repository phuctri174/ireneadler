// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Generic icons for the board: weather, music, an idea, a warning, a tick. Drawn
// as small cell art (9x9) so they can be scaled up whole; the freehand "sprite"
// shape and the icon template both use this table. All original, all generic.

import type { Color } from "./strokes";

export interface Icon {
  art: readonly string[];
  color: Color;
  /** Cells drawn in a second colour ("o" in the art). */
  second?: Color;
}

export const ICONS: Record<string, Icon> = {
  sun: {
    color: "amber",
    art: ["#...#...#", ".#..#..#.", "...###...", "..#####..", "#########", "..#####..", "...###...", ".#..#..#.", "#...#...#"],
  },
  cloud: {
    color: "white",
    art: [".........", "...###...", "..#####..", ".#######.", "#########", "#########", ".#######.", ".........", "........."],
  },
  rain: {
    color: "white",
    second: "cyan",
    art: ["...###...", "..#####..", ".#######.", "#########", ".#######.", ".........", ".o..o..o.", "o..o..o..", "........."],
  },
  snow: {
    color: "white",
    second: "cyan",
    art: ["...###...", "..#####..", ".#######.", "#########", ".#######.", ".........", ".o..o..o.", "..o..o...", ".o..o..o."],
  },
  storm: {
    color: "white",
    second: "amber",
    art: ["...###...", "..#####..", ".#######.", "#########", ".###o###.", "....o....", "...oo....", "....o....", "...o....."],
  },
  partly_cloudy: {
    color: "white",
    second: "amber",
    art: ["o..o.....", ".ooo.....", "ooooo....", ".o###....", "o#####...", ".#######.", "#########", ".#######.", "........."],
  },
  music: {
    color: "pink",
    art: ["...######", "...######", "...#....#", "...#....#", "...#....#", ".###..###", "####.####", "####..##.", ".##......"],
  },
  lightbulb: {
    color: "amber",
    second: "white",
    art: ["..#####..", ".#.....#.", "#...o...#", "#..o.o..#", "#...o...#", ".#..o..#.", "..#####..", "..ooooo..", "...ooo..."],
  },
  warning: {
    color: "amber",
    second: "white",
    art: ["....#....", "...#.#...", "...#o#...", "..#.o.#..", "..#.o.#..", ".#..o..#.", ".#.....#.", "#...o...#", "#########"],
  },
  check: {
    color: "accent",
    art: [".........", "........#", ".......##", "#.....##.", "##...##..", ".##.##...", "..###....", "...#.....", "........."],
  },
  cross: {
    color: "red",
    art: ["#.......#", ".#.....#.", "..#...#..", "...#.#...", "....#....", "...#.#...", "..#...#..", ".#.....#.", "#.......#"],
  },
  heart: {
    color: "pink",
    art: [".........", ".##...##.", "####.####", "#########", "#########", ".#######.", "..#####..", "...###...", "....#...."],
  },
  star: {
    color: "amber",
    art: ["....#....", "....#....", "...###...", "#########", ".#######.", "..#####..", "..##.##..", ".##...##.", "#.......#"],
  },
  clock: {
    color: "white",
    second: "amber",
    art: ["..#####..", ".#.....#.", "#...o...#", "#...o...#", "#...ooo.#", "#.......#", "#.......#", ".#.....#.", "..#####.."],
  },
  question: {
    color: "cyan",
    art: ["..####...", ".#....#..", "......#..", ".....#...", "....#....", "....#....", ".........", "....#....", "........."],
  },
};

export const ICON_NAMES = Object.keys(ICONS);
