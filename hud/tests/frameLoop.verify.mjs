// stubbed rAF: frames only advance when step() runs them
let nextId = 1;
const pending = new Map();
globalThis.requestAnimationFrame = (fn) => {
  const id = nextId++;
  pending.set(id, fn);
  return id;
};
globalThis.cancelAnimationFrame = (id) => {
  pending.delete(id);
};
let clock = 0;
const step = () => {
  clock += 16;
  const due = [...pending.values()];
  pending.clear();
  for (const fn of due) fn(clock);
};

const errors = [];
const realError = console.error;
console.error = (...args) => errors.push(args);

const { onFrame, frameSubscriberCount } = await import("../.verify/frameLoop.js");

let failures = 0;
const check = (ok, label) => {
  if (!ok) {
    failures += 1;
    realError(`FAIL frameLoop: ${label}`);
  }
};

// a throwing subscriber keeps getting called, logs once, and never blocks its neighbours
{
  let before = 0;
  let bad = 0;
  let after = 0;
  const offBefore = onFrame(() => { before += 1; });
  const offBad = onFrame(() => { bad += 1; throw new Error("boom"); });
  const offAfter = onFrame(() => { after += 1; });
  for (let i = 0; i < 5; i++) step();
  check(before === 5, `subscriber before the throw ran every frame, got ${before}`);
  check(bad === 5, `throwing subscriber still called every frame, got ${bad}`);
  check(after === 5, `subscriber after the throw ran every frame, got ${after}`);
  check(errors.length === 1, `first throw logged once, got ${errors.length}`);
  check(errors[0]?.some((arg) => arg instanceof Error && arg.message === "boom"), "log carries the error");
  check(pending.size === 1, `exactly one frame scheduled, got ${pending.size}`);
  offBefore();
  offBad();
  offAfter();
  check(pending.size === 0 && frameSubscriberCount() === 0, "loop stops with no subscribers");
}

// two distinct throwing subscribers each log their own first throw
{
  errors.length = 0;
  const offA = onFrame(() => { throw new Error("a"); });
  const offB = onFrame(() => { throw new Error("b"); });
  for (let i = 0; i < 3; i++) step();
  check(errors.length === 2, `one log per throwing subscriber, got ${errors.length}`);
  check(pending.size === 1, "loop still scheduled after throws");
  offA();
  offB();
}

// unsubscribing from inside a tick stops the loop rather than idling on
{
  let calls = 0;
  const off = onFrame(() => { calls += 1; off(); });
  step();
  step();
  check(calls === 1, `self-removing subscriber ran once, got ${calls}`);
  check(pending.size === 0, `no frame left scheduled, got ${pending.size}`);

  // leave and rejoin in the same tick: exactly one loop survives
  let rejoined = 0;
  const offOuter = onFrame(() => {
    offOuter();
    onFrame(() => { rejoined += 1; });
  });
  step();
  check(pending.size === 1, `one loop after rejoin, got ${pending.size}`);
  // Set iteration already reached the newcomer in the joining tick; count from here
  const joined = rejoined;
  step();
  step();
  check(rejoined - joined === 2, `rejoined subscriber ran once per frame, got ${rejoined - joined}`);
}

console.error = realError;
if (failures > 0) {
  console.error(`frameLoop: ${failures} failure(s)`);
  process.exit(1);
} else {
  console.log("frameLoop: ok");
}
