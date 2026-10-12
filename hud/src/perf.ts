// Where the HUD's time goes, measured in the running app: the hand tracker, the
// body (pose) tracker, and her face's compose + draw. App.tsx sends a summary to
// core every 10 s ("hud perf" in core/logs/core.log), then starts over.

interface Lane {
  n: number;
  ms: number;
  worst: number;
}

const lane = (): Lane => ({ n: 0, ms: 0, worst: 0 });
// gap: the time between two drawn frames of her face (a stutter is a long one);
// pointer: each hand-pointer call to Rust (pointer.rs)
let lanes = { hand: lane(), pose: lane(), face: lane(), gap: lane(), pointer: lane() };
// frames that came more than JANK_MS after the one before: a visible skip
const JANK_MS = 34;
let janks = 0;
let since = performance.now();

export function note(which: keyof typeof lanes, ms: number): void {
  const l = lanes[which];
  l.n += 1;
  l.ms += ms;
  if (ms > l.worst) l.worst = ms;
  if (which === "gap" && ms > JANK_MS) janks += 1;
}

export interface PerfSummary {
  seconds: number;
  handFps: number;
  handMs: number;
  poseHz: number;
  poseMs: number;
  poseWorstMs: number;
  faceFps: number;
  faceMs: number;
  faceWorstMs: number;
  faceGapWorstMs: number;
  faceJanks: number;
  pointerHz: number;
}

/** The last window's numbers, and a fresh window. */
export function take(): PerfSummary {
  const seconds = (performance.now() - since) / 1000;
  const r = (x: number) => Math.round(x * 10) / 10;
  const per = (l: Lane) => (l.n ? l.ms / l.n : 0);
  const out = {
    seconds: r(seconds),
    handFps: r(lanes.hand.n / seconds),
    handMs: r(per(lanes.hand)),
    poseHz: r(lanes.pose.n / seconds),
    poseMs: r(per(lanes.pose)),
    poseWorstMs: r(lanes.pose.worst),
    faceFps: r(lanes.face.n / seconds),
    faceMs: r(per(lanes.face)),
    faceWorstMs: r(lanes.face.worst),
    faceGapWorstMs: r(lanes.gap.worst),
    faceJanks: janks,
    pointerHz: r(lanes.pointer.n / seconds),
  };
  lanes = { hand: lane(), pose: lane(), face: lane(), gap: lane(), pointer: lane() };
  janks = 0;
  since = performance.now();
  return out;
}
