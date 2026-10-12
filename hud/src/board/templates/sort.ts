// A sorting algorithm animated step by step on bars: the two being compared light
// up amber, a swap or a write flashes cyan, sorted positions settle into the accent.
// Every step is computed here from the real algorithm, so what plays is exactly
// what the algorithm does.
//
//   { "template": "sort", "algorithm": "bubble|insertion|selection|merge|quick", "values": [5, 1, 4, 2] }

import type { Template } from "../kit";
import { fill, text, title } from "../kit";
import type { Color, Stroke } from "../strokes";
import { BoardError, numbers, str } from "../validate";

const ALGORITHMS = ["bubble", "insertion", "selection", "merge", "quick"] as const;
type Algorithm = (typeof ALGORITHMS)[number];

export interface Step {
  values: number[];
  compare: number[];
  write: number[];
  sorted: number[];
  note: string;
}

export function steps(algorithm: Algorithm, input: number[]): Step[] {
  const a = [...input];
  const out: Step[] = [{ values: [...a], compare: [], write: [], sorted: [], note: "START" }];
  const sorted = new Set<number>();
  const snap = (compare: number[], write: number[], note: string) => out.push({ values: [...a], compare, write, sorted: [...sorted], note });
  const n = a.length;
  switch (algorithm) {
    case "bubble":
      for (let end = n - 1; end > 0; end -= 1) {
        let swapped = false;
        for (let i = 0; i < end; i += 1) {
          snap([i, i + 1], [], `COMPARE ${a[i]} ${a[i + 1]}`);
          if (a[i] > a[i + 1]) {
            [a[i], a[i + 1]] = [a[i + 1], a[i]];
            swapped = true;
            snap([], [i, i + 1], "SWAP");
          }
        }
        sorted.add(end);
        if (!swapped) {
          for (let k = 0; k < end; k += 1) sorted.add(k);
          break;
        }
      }
      break;
    case "insertion":
      sorted.add(0);
      for (let i = 1; i < n; i += 1) {
        let j = i;
        snap([j - 1, j], [], `INSERT ${a[i]}`);
        while (j > 0 && a[j - 1] > a[j]) {
          [a[j - 1], a[j]] = [a[j], a[j - 1]];
          snap([], [j - 1, j], "SHIFT");
          j -= 1;
          if (j > 0) snap([j - 1, j], [], "COMPARE");
        }
        for (let k = 0; k <= i; k += 1) sorted.add(k);
      }
      break;
    case "selection":
      for (let i = 0; i < n - 1; i += 1) {
        let min = i;
        for (let j = i + 1; j < n; j += 1) {
          snap([min, j], [], `MIN ${a[min]}`);
          if (a[j] < a[min]) min = j;
        }
        if (min !== i) {
          [a[i], a[min]] = [a[min], a[i]];
          snap([], [i, min], "SWAP");
        }
        sorted.add(i);
      }
      break;
    case "merge": {
      const merge = (lo: number, hi: number): void => {
        if (hi - lo < 1) return;
        const mid = Math.floor((lo + hi) / 2);
        merge(lo, mid);
        merge(mid + 1, hi);
        const left = a.slice(lo, mid + 1);
        const right = a.slice(mid + 1, hi + 1);
        let i = 0;
        let j = 0;
        for (let k = lo; k <= hi; k += 1) {
          if (i < left.length && j < right.length) snap([lo + i, mid + 1 + j], [], `MERGE ${lo}-${hi}`);
          a[k] = j >= right.length || (i < left.length && left[i] <= right[j]) ? left[i++] : right[j++];
          snap([], [k], "WRITE");
        }
      };
      merge(0, n - 1);
      break;
    }
    case "quick": {
      const quick = (lo: number, hi: number): void => {
        if (lo >= hi) {
          if (lo === hi) sorted.add(lo);
          return;
        }
        const pivot = a[hi];
        let i = lo;
        for (let j = lo; j < hi; j += 1) {
          snap([j, hi], [], `PIVOT ${pivot}`);
          if (a[j] < pivot) {
            [a[i], a[j]] = [a[j], a[i]];
            if (i !== j) snap([], [i, j], "SWAP");
            i += 1;
          }
        }
        [a[i], a[hi]] = [a[hi], a[i]];
        snap([], [i, hi], "PIVOT IN PLACE");
        sorted.add(i);
        quick(lo, i - 1);
        quick(i + 1, hi);
      };
      quick(0, n - 1);
      break;
    }
  }
  for (let k = 0; k < n; k += 1) sorted.add(k);
  snap([], [], "SORTED");
  return out;
}

const STEP_MS = 450;
const START_MS = 1300;

export const template: Template<{ algorithm: Algorithm; steps: Step[] }> = {
  parse(a) {
    // "quicksort", "Merge Sort", "bubble_sort": the algorithm's name without "sort"
    const named = String(a.algorithm ?? "").toLowerCase().replace(/[\s_-]*sort$/, "").replace(/[\s_-]+/g, "");
    const algorithm = str({ algorithm: named }, "algorithm", { oneOf: ALGORITHMS }) as Algorithm;
    const values = numbers(a, "values", { min: 2, max: 16 });
    if (values.some((v) => v < 0 || v > 999)) throw new BoardError("values must be 0-999");
    return { algorithm, steps: steps(algorithm, values) };
  },
  render({ algorithm, steps: all }, { t }) {
    const k = Math.min(all.length - 1, Math.max(0, Math.floor((t - START_MS) / STEP_MS)));
    const s = all[k];
    const out: Stroke[] = [title(`${algorithm} sort`), text(2, 9, `STEP ${k}/${all.length - 1}`, "accent", "left", 1, 0.7)];
    const n = s.values.length;
    const max = Math.max(...s.values, 1);
    const slot = 120 / n;
    const w = Math.max(2, Math.floor(slot * 0.7));
    const base = 62;
    s.values.forEach((v, i) => {
      const h = Math.max(1, Math.round((v / max) * 36));
      const color: Color = s.write.includes(i) ? "cyan" : s.compare.includes(i) ? "amber" : s.sorted.includes(i) ? "accent" : "white";
      const x = Math.round(4 + slot * i + (slot - w) / 2);
      out.push(fill(x, base - h, w, h, color, color === "white" ? 0.45 : 0.9));
      if (slot >= 7) out.push(text(x + w / 2, base + 3, String(v), color === "white" ? "white" : color, "center", 1, 0.8));
    });
    out.push(text(64, 19, s.note, "amber", "center"));
    return out;
  },
};
