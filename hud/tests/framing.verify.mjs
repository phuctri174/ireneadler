// The body capture's framing check (src/tracking/framing.ts): the run waits until the
// lower of his wrists has been inside the line, continuously, for FRAMED_MS.
import { FRAMED_MS, FramingCheck, lowestWrist } from "../.verify/framing.js";

let failures = 0;
const fail = (why) => {
  failures += 1;
  console.log(`FAIL framing: ${why}`);
};

const body = (left, right) => Array.from({ length: 33 }, (_, i) => ({ y: i === 15 ? left : i === 16 ? right : 0.4 }));

if (lowestWrist(body(0.7, 0.98)) !== 0.98) fail("the lower wrist is the larger y");
if (lowestWrist(null) !== null || lowestWrist([]) !== null) fail("no body is no reading");

{
  // the first desk session: kamae wrists at 0.98, never framed
  const check = new FramingCheck(0.85);
  let framed = false;
  for (let t = 0; t <= 5000; t += 33) framed ||= check.update(body(0.9, 0.98), t);
  if (framed || check.inside) fail("wrists at 0.98 must not pass a 0.85 line");
}
{
  const check = new FramingCheck(0.85);
  if (check.update(body(0.8, 0.82), 0)) fail("framed on the first frame");
  if (!check.inside) fail("0.82 is inside 0.85");
  if (check.update(body(0.8, 0.82), FRAMED_MS - 1)) fail("framed before FRAMED_MS");
  if (!check.update(body(0.8, 0.82), FRAMED_MS)) fail("not framed after FRAMED_MS inside");
}
{
  // a wrist dipping out restarts the hold; losing the body does too
  const check = new FramingCheck(0.85);
  check.update(body(0.8, 0.8), 0);
  check.update(body(0.8, 0.9), 600);
  if (check.update(body(0.8, 0.8), 1100)) fail("a dip out of frame did not restart the hold");
  check.update(null, 1200);
  if (check.update(body(0.8, 0.8), 2100)) fail("losing the body did not restart the hold");
  if (!check.update(body(0.8, 0.8), 2100 + FRAMED_MS)) fail("not framed after a clean hold");
}

console.log(failures ? `framing: ${failures} failed` : "framing: ok");
if (failures) process.exitCode = 1;
