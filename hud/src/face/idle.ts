// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Idle life: while he leaves her alone, every 20-60 s she does something small on
// her own - looks around, stretches, hums a little tune, or plays a short scene.
// The moment he interacts (types, speaks to her, shows a hand, touches the panel)
// or she has something real to do (thinking, speaking, a drawing, a summon), the
// beat stops and the clock starts over.
//
// Pure scheduling: update() says which beat is on; the face draws it. `random`
// is injectable so the tests get a fixed sequence.

import type { AssistantState } from "./faceState";

export type IdleKind = "glance" | "stretch" | "hum" | "scene";

export interface IdleBeat {
  kind: IdleKind;
  /** performance.now() when it started. */
  at: number;
  ms: number;
  /** For "scene": which one. */
  scene?: string;
}

export interface IdleInput {
  state: AssistantState;
  /** On screen: idle life only plays to an audience. */
  visible: boolean;
  /** performance.now() of his last interaction (face/interaction.ts). */
  lastInteraction: number;
  /** Something real owns the face (a reply's cue, a drawing, an entrance...). */
  busy: boolean;
}

export interface IdleUpdate {
  beat: IdleBeat | null;
  /** The beat that began this frame, if one did. */
  started: IdleBeat | null;
  /** The beat that ended (or was cut off) this frame, if one did. */
  stopped: IdleBeat | null;
}

export const IDLE_GAP_MS: [number, number] = [20000, 60000];
export const BEAT_MS: Record<Exclude<IdleKind, "scene">, number> = { glance: 2600, stretch: 2000, hum: 4200 };

export class IdleLife {
  private beat: IdleBeat | null = null;
  private next = 0;
  /** When the current quiet stretch began (his last interaction, or her last real act). */
  private quietSince = -1;
  private lastKind: IdleKind | null = null;

  constructor(
    /** The scenes she may play on her own, with one pass's length. */
    private readonly scenes: Record<string, number>,
    private readonly random: () => number = Math.random,
  ) {}

  private between([lo, hi]: [number, number]): number {
    return lo + this.random() * (hi - lo);
  }

  private pick(state: AssistantState): IdleBeat {
    // shut, dormant eyes can't glance; everything else suits both
    const kinds: IdleKind[] = state === "dormant" ? ["stretch", "hum", "scene"] : ["glance", "stretch", "hum", "scene"];
    const sceneNames = Object.keys(this.scenes);
    const options = kinds.filter((k) => k !== this.lastKind && (k !== "scene" || sceneNames.length > 0));
    const kind = options[Math.min(options.length - 1, Math.floor(this.random() * options.length))];
    this.lastKind = kind;
    if (kind === "scene") {
      const scene = sceneNames[Math.min(sceneNames.length - 1, Math.floor(this.random() * sceneNames.length))];
      return { kind, at: 0, ms: this.scenes[scene], scene };
    }
    return { kind, at: 0, ms: BEAT_MS[kind] };
  }

  current(): IdleBeat | null {
    return this.beat;
  }

  update(now: number, input: IdleInput): IdleUpdate {
    const quiet = input.visible && !input.busy && (input.state === "listening" || input.state === "dormant");
    let stopped: IdleBeat | null = null;
    const interrupted = !quiet || (this.beat !== null && input.lastInteraction > this.beat.at);
    if (interrupted) {
      if (this.beat) stopped = this.beat;
      this.beat = null;
      this.next = 0;
      this.quietSince = -1;
      if (!quiet) return { beat: null, started: null, stopped };
    }
    if (this.beat && now >= this.beat.at + this.beat.ms) {
      stopped = this.beat;
      this.beat = null;
    }
    const since = Math.max(input.lastInteraction, this.quietSince < 0 ? now : this.quietSince);
    if (this.quietSince < 0 || input.lastInteraction > this.quietSince) {
      this.quietSince = since;
      this.next = since + this.between(IDLE_GAP_MS);
    }
    let started: IdleBeat | null = null;
    if (!this.beat && now >= this.next) {
      started = { ...this.pick(input.state), at: now };
      this.beat = started;
      this.next = now + started.ms + this.between(IDLE_GAP_MS);
    }
    return { beat: this.beat, started, stopped };
  }
}

/** Where her eyes are during a glance: left, a beat, right, back. Cells. */
export function glanceGaze(beat: IdleBeat, now: number): { x: number; y: number } {
  const t = (now - beat.at) / beat.ms;
  if (t < 0.08 || t > 0.9) return { x: 0, y: 0 };
  if (t < 0.45) return { x: -3, y: -1 };
  if (t < 0.52) return { x: 0, y: -1 };
  return { x: 3, y: -1 };
}
