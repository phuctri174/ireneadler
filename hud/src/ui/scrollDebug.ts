// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// What the hand-scroll of the panel measured, for the calibration overlay (F10).

export interface PanelScrollDebug {
  latched: boolean;
  rectTop: number;
  rectHeight: number;
  handY: number;
  centred: number;
  region: string;
  rate: number;
  pxPerSec: number;
  scrollTop: number;
  scrollMax: number;
  reason: string;
}

export function neutralScrollDebug(): PanelScrollDebug {
  return {
    latched: false,
    rectTop: 0,
    rectHeight: 0,
    handY: 0,
    centred: 0,
    region: "-",
    rate: 0,
    pxPerSec: 0,
    scrollTop: 0,
    scrollMax: 0,
    reason: "scroll not latched",
  };
}

