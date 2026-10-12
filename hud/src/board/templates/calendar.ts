// A month calendar, weeks starting Monday, today boxed; other days can be marked.
//
//   { "template": "calendar", "month"?: "2026-09", "highlight"?: [25, 30] }

import type { Template } from "../kit";
import { box, fill, text } from "../kit";
import type { Stroke } from "../strokes";
import { BoardError, numbers, optStr } from "../validate";

const MONTHS = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"];
const CELL = { w: 13, h: 8 };
const X0 = 4;
const Y0 = 18;

export const template: Template<{ year: number | null; month: number | null; highlight: number[] }> = {
  parse(a) {
    const month = optStr(a, "month", 7);
    let ym: { year: number; month: number } | null = null;
    if (month) {
      const m = /^(\d{4})-(\d{1,2})$/.exec(month);
      if (!m || Number(m[2]) < 1 || Number(m[2]) > 12) throw new BoardError("month must be YYYY-MM");
      ym = { year: Number(m[1]), month: Number(m[2]) - 1 };
    }
    const highlight = numbers(a, "highlight", { def: [], max: 31 });
    if (highlight.some((d) => !Number.isInteger(d) || d < 1 || d > 31)) throw new BoardError("highlight days must be 1-31");
    return { year: ym?.year ?? null, month: ym?.month ?? null, highlight };
  },
  render(args, { now }) {
    const year = args.year ?? now.getFullYear();
    const month = args.month ?? now.getMonth();
    const days = new Date(year, month + 1, 0).getDate();
    const lead = (new Date(year, month, 1).getDay() + 6) % 7; // Monday first
    const today = now.getFullYear() === year && now.getMonth() === month ? now.getDate() : null;
    const out: Stroke[] = [text(2, 2, `${MONTHS[month]} ${year}`, "white", "left")];
    ["MO", "TU", "WE", "TH", "FR", "SA", "SU"].forEach((d, i) => out.push(text(X0 + i * CELL.w + 6, Y0 - 7, d, i >= 5 ? "amber" : "accent", "center")));
    for (let d = 1; d <= days; d += 1) {
      const k = lead + d - 1;
      const col = k % 7;
      const row = Math.floor(k / 7);
      const x = X0 + col * CELL.w;
      const y = Y0 + row * CELL.h;
      if (d === today) out.push(fill(x, y - 1, CELL.w - 1, CELL.h, "accent", 0.35), box(x, y - 1, CELL.w - 1, CELL.h, "accent"));
      else if (args.highlight.includes(d)) out.push(box(x, y - 1, CELL.w - 1, CELL.h, "amber"));
      out.push(text(x + 6, y + 1, String(d), d === today ? "white" : col >= 5 ? "amber" : "white", "center", 1, d === today ? 1 : 0.8));
    }
    return out;
  },
};
