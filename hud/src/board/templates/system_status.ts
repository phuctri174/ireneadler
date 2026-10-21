// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// System status: CPU, GPU, RAM and VRAM as four gauges - the numbers come from the
// system_status tool, never guessed.
//
//   { "template": "system_status", "cpu": 23, "gpu": 61, "ram": 48, "vram": 88,
//     "ram_gb"?: "15.2/31.9", "vram_gb"?: "14.1/16.0" }

import type { Template } from "../kit";
import { title } from "../kit";
import type { Reading } from "./progress";
import { gauges } from "./gauge";
import { num, optStr } from "../validate";

export const template: Template<Reading[]> = {
  parse(a) {
    const pct = (k: string) => num(a, k, { min: 0, max: 100 });
    return [
      { label: "CPU", value: pct("cpu"), max: 100 },
      { label: "GPU", value: pct("gpu"), max: 100 },
      { label: "RAM", value: pct("ram"), max: 100, detail: optStr(a, "ram_gb", 12) },
      { label: "VRAM", value: pct("vram"), max: 100, detail: optStr(a, "vram_gb", 12) },
    ];
  },
  render(items) {
    return [title("SYSTEM"), ...gauges(items)];
  },
};
