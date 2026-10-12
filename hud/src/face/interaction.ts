// When he last did anything: typed, opened the bar, sent a command, showed a hand,
// touched the panel. Idle life (face/idle.ts) waits for this to go quiet and stops
// the moment it moves. Anything that sees him interact stamps it; nothing else
// reads it but the face.

let last = 0;
// a skit is being filmed (core/irene/skit.py): her own idle life must not fill its
// pauses, so it counts as him interacting the whole time
let held = false;

/** He just did something. `at` is performance.now() time. */
export function noteInteraction(at: number = performance.now()): void {
  if (at > last) last = at;
}

export function holdInteraction(on: boolean): void {
  held = on;
  noteInteraction();
}

export function lastInteraction(): number {
  return held ? performance.now() : last;
}
