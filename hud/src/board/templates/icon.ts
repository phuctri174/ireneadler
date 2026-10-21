// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Generic icons, large: weather, music, an idea, a warning, a tick, a cross... up to
// three side by side, each with an optional caption.
//
//   { "template": "icon", "names": ["sun", "rain"], "captions"?: ["SAT", "SUN"] }

import type { Template } from "../kit";
import { iconStrokes, spread, text } from "../kit";
import { ICON_NAMES } from "../icons";
import type { Stroke } from "../strokes";
import { BoardError, list, str, strings } from "../validate";

export const template: Template<{ names: string[]; captions: string[] }> = {
  parse(a) {
    const raw = a.names ?? (a.name !== undefined ? [a.name] : undefined);
    const names = list({ names: raw }, "names", { min: 1, max: 3 }).map((n, i) => str({ n }, "n", { oneOf: ICON_NAMES }) || String(i));
    const captions = strings(a, "captions", { def: [], max: 3, each: 8 });
    if (captions.length > names.length) throw new BoardError("more captions than icons");
    return { names, captions };
  },
  render({ names, captions }) {
    const scale = names.length === 1 ? 5 : names.length === 2 ? 4 : 3;
    const size = 9 * scale;
    const xs = spread(names.length, 8 + size / 2, 94 - size / 2);
    const out: Stroke[] = [];
    names.forEach((n, i) => {
      const x = Math.round(xs[i] - size / 2);
      const y = Math.round(34 - size / 2);
      out.push(...iconStrokes(n, x, y, scale));
      if (captions[i]) out.push(text(xs[i], y + size + 3, captions[i].toUpperCase(), "white", "center"));
    });
    return out;
  },
};
