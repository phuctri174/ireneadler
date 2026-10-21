// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
export type FrameCallback = (now: number, deltaSeconds: number) => void;

const MAX_DELTA_SECONDS = 0.1;

const callbacks = new Set<FrameCallback>();
// subscribers that have already thrown once; later throws stay silent
const reported = new WeakSet<FrameCallback>();
let handle = 0;
let last = 0;

function tick(now: number): void {
  const current = handle;
  const delta = last === 0 ? 0 : Math.min((now - last) / 1000, MAX_DELTA_SECONDS);
  last = now;
  for (const callback of callbacks) {
    // one bad subscriber must not starve the rest or kill the loop
    try {
      callback(now, delta);
    } catch (cause) {
      if (!reported.has(callback)) {
        reported.add(callback);
        console.error("[irene] frame subscriber threw (further throws suppressed)", cause);
      }
    }
  }
  // handle changed mid-tick: the last subscriber left (0) or a new loop already started
  if (handle === current) handle = requestAnimationFrame(tick);
}

export function onFrame(callback: FrameCallback): () => void {
  callbacks.add(callback);
  if (handle === 0) {
    last = 0;
    handle = requestAnimationFrame(tick);
  }
  return () => {
    callbacks.delete(callback);
    if (callbacks.size === 0 && handle !== 0) {
      cancelAnimationFrame(handle);
      handle = 0;
      last = 0;
    }
  };
}

export function frameSubscriberCount(): number {
  return callbacks.size;
}
