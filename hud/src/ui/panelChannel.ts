// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
import { useSyncExternalStore } from "react";
import type { PanelContent } from "./content";

// The panel's only input. Content is pushed here - by the backend over
// irene://panel, or by the F7 debug push - and whatever surface hosts the panel
// subscribes. Today that host is PanelDock inside the overlay; later it can be a
// window of its own on a second monitor listening to the same event, and nothing
// in the main interface has to change. Nothing else should hold panel content.

type Listener = () => void;

let current: PanelContent | null = null;
// what was on the panel before it was dismissed, so a toggle can bring it back
let last: PanelContent | null = null;
const listeners = new Set<Listener>();

function publish(next: PanelContent | null): void {
  if (next === current) return;
  current = next;
  if (next) last = next;
  for (const listener of listeners) listener();
}

/** Show `content` on the panel. The panel appears only through here. */
export function pushPanel(content: PanelContent): void {
  publish(content);
}

/** Dismiss the panel. No content, no panel. */
export function clearPanel(): void {
  publish(null);
}

/**
 * Hide the panel if it is showing; otherwise bring back whatever it last showed.
 * With nothing ever shown, `empty` is shown instead - the panel says so rather
 * than inventing content.
 */
export function togglePanel(empty: PanelContent): void {
  publish(current ? null : (last ?? empty));
}

export function getPanel(): PanelContent | null {
  return current;
}

export function onPanel(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function usePanelContent(): PanelContent | null {
  return useSyncExternalStore(onPanel, getPanel);
}

// Links on the panel are opened by whoever hosts it (the overlay sends them to
// core, which opens his Chrome); the panel itself only says which one was clicked.
let linkOpener: ((url: string) => void) | null = null;

export function setLinkOpener(opener: ((url: string) => void) | null): void {
  linkOpener = opener;
}

export function openLink(url: string): void {
  linkOpener?.(url);
}
