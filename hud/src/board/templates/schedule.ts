// A day's schedule as a strip: an hour ruler, each item a block on its own row,
// and a "now" marker when today falls inside it.
//
//   { "template": "schedule", "items": [{ "start": "09:00", "end": "10:30", "label": "Lecture" }] }

import type { Template } from "../kit";
import { box, fill, line, text, title } from "../kit";
import type { Stroke } from "../strokes";
import { BoardError, list, obj, str } from "../validate";

interface Item {
  start: number; // minutes since midnight
  end: number;
  label: string;
}

const X0 = 4;
const X1 = 124;
const Y0 = 30;
const ROW = 9;

function minutes(value: string, what: string): number {
  const m = /^(\d{1,2}):(\d{2})$/.exec(value);
  if (!m || Number(m[1]) > 24 || Number(m[2]) > 59) throw new BoardError(`${what} must be HH:MM`);
  return Number(m[1]) * 60 + Number(m[2]);
}

export const template: Template<{ items: Item[]; from: number; to: number }> = {
  parse(a) {
    const items = list(a, "items", { min: 1, max: 5 }).map((raw, i) => {
      const it = obj(raw, `items[${i}]`);
      const item = { start: minutes(str(it, "start"), `items[${i}].start`), end: minutes(str(it, "end"), `items[${i}].end`), label: str(it, "label", { max: 24 }) };
      if (item.end <= item.start) throw new BoardError(`items[${i}] ends before it starts`);
      return item;
    });
    items.sort((x, y) => x.start - y.start);
    const from = Math.floor(Math.min(...items.map((i) => i.start)) / 60) * 60;
    const to = Math.ceil(Math.max(...items.map((i) => i.end)) / 60) * 60;
    return { items, from, to: Math.max(to, from + 60) };
  },
  render({ items, from, to }, { now }) {
    const x = (m: number) => X0 + ((m - from) / (to - from)) * (X1 - X0);
    const out: Stroke[] = [title("TODAY")];
    const hours = (to - from) / 60;
    const every = hours > 10 ? 2 : 1;
    out.push(line(X0, Y0 - 3, X1, Y0 - 3, "accent", 0.5));
    for (let h = from; h <= to; h += 60 * every) {
      out.push(line(x(h), Y0 - 5, x(h), Y0 - 2, "accent", 0.7), text(x(h), Y0 - 11, String(h / 60), "accent", "center", 1, 0.7));
    }
    items.forEach((it, i) => {
      const y = Y0 + i * ROW;
      const w = Math.max(3, x(it.end) - x(it.start));
      out.push(fill(x(it.start), y, w, ROW - 2, "accent", 0.3), box(x(it.start), y, w, ROW - 2, "accent"));
      const room = Math.floor((w - 2) / 4);
      const inside = room >= Math.min(it.label.length, 6);
      const label = it.label.length > room && inside ? `${it.label.slice(0, room - 1)}.` : it.label;
      // inside the block if it fits, else after it, else before it
      const after = x(it.end) + 2 + it.label.length * 4 <= 127;
      out.push(inside ? text(x(it.start) + 2, y + 1, label.toUpperCase(), "white") : after ? text(x(it.end) + 2, y + 1, it.label.toUpperCase(), "white") : text(x(it.start) - 2, y + 1, it.label.toUpperCase(), "white", "right"));
    });
    const nowMin = now.getHours() * 60 + now.getMinutes();
    if (nowMin >= from && nowMin <= to) out.push(line(x(nowMin), Y0 - 6, x(nowMin), Y0 + items.length * ROW, "amber"), text(x(nowMin), Y0 + items.length * ROW + 2, "NOW", "amber", "center"));
    return out;
  },
};
