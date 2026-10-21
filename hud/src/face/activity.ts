// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Activity scenes: short looping LED animations Irene plays with her face still
// visible - a game of chess, kendo practice, a tool's prop. Like reactions, they
// never change state. This is the trigger API; the scenes are drawn in
// led/scenes.ts, whose table is the list.

import { SCENES } from "../led/scenes";
import type { SceneName } from "../led/scenes";
import { cueLabel } from "./reactions";

export type Activity = SceneName;

export const ACTIVITIES = Object.keys(SCENES) as Activity[];

/** Scenes that may play by themselves while she is dormant (not tool props). */
export const IDLE_ACTIVITIES = ACTIVITIES.filter((name) => (SCENES[name] as { idle?: boolean }).idle);

/** One pass of each loop, ms. */
export const ACTIVITY_LOOP_MS = Object.fromEntries(ACTIVITIES.map((name) => [name, SCENES[name].loopMs])) as Record<Activity, number>;

export const ACTIVITY_LABEL = Object.fromEntries(ACTIVITIES.map((name) => [name, cueLabel(name)])) as Record<Activity, string>;

export interface ActivityEvent {
  /** null stops whatever is playing. */
  name: Activity | null;
  /** performance.now() at trigger. */
  at: number;
  /** Loop passes to play before stopping; 0 loops until replaced or stopped. */
  loops: number;
}

type Listener = (event: ActivityEvent) => void;
const listeners = new Set<Listener>();
let current: ActivityEvent = { name: null, at: 0, loops: 0 };

export function isActivity(name: unknown): name is Activity {
  return typeof name === "string" && (ACTIVITIES as string[]).includes(name);
}

/**
 * Play a scene, or stop with null. The backend reaches this through the socket;
 * unknown names are ignored and reported rather than thrown.
 */
export function showActivity(name: string | null, loops = 0): boolean {
  if (name !== null && !isActivity(name)) {
    console.warn(`[irene] unknown activity: ${name}`);
    return false;
  }
  current = { name, at: performance.now(), loops };
  console.log(`[irene] activity -> ${name ?? "none"}`);
  for (const listener of listeners) listener(current);
  return true;
}

export function currentActivity(): ActivityEvent {
  return current;
}

/** Cycle for the debug hotkey: none -> chess -> kendo -> none. */
export function cycleActivity(): void {
  const index = current.name === null ? -1 : ACTIVITIES.indexOf(current.name);
  const next = index + 1 < ACTIVITIES.length ? ACTIVITIES[index + 1] : null;
  showActivity(next);
}

export function onActivity(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
