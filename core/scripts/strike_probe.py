r"""What shiai's detectors fire while he does nothing - measured, through the RUNNING
app (start-irene.ps1 -Dev), the dev socket only: no OS input, nothing acted on.

    .venv\Scripts\python scripts\strike_probe.py [--seconds 30] [--no-thrust]

Core arms the HUD's detectors exactly as shiai does (the strike event at his
calibrated threshold, footwork, the block pose, and the tsuki thrust trigger unless
--no-thrust), records every event they fire and a second-by-second summary of the
body, and acts on none of it. Printed: each event with its values, then per second
whether a body was there, how much the shoulders moved (a second person, or the
tracker jumping, moves them), wrist visibility, and the fastest downward and forward
wrist speeds - against the thresholds that would fire.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import sys

import websockets


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--no-thrust", action="store_true")
    a = ap.parse_args()
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        await ws.send(json.dumps({"type": "mic_deaf", "value": True}))
        await ws.send(json.dumps({"type": "strike_probe", "seconds": a.seconds, "thrust": not a.no_thrust}))
        result = None
        try:
            async for raw in ws:
                m = json.loads(raw)
                if m.get("type") == "strike_probe_result":
                    result = m
                    break
        finally:
            await ws.send(json.dumps({"type": "mic_deaf", "value": False}))
    if result is None or result.get("error"):
        print("no result:", result and result.get("error"))
        return 2
    cfg = result["config"]
    print(f"armed: strike threshold {cfg['strikes']['threshold']} (minVis {cfg['strikes']['minVis']}, maxPeak {cfg['strikes']['maxPeak']}, "
          f"stop {cfg['strikes']['stopRatio']} in {cfg['strikes']['stopMs']} ms, rest {cfg['strikes']['refractoryMs']} ms); "
          f"thrust {cfg['thrust']['threshold'] if cfg.get('thrust') else 'OFF'}; block above {cfg['block']['above']}")
    events = result["events"]
    kinds = collections.Counter(e["type"] if e["type"] != "shiai_move" else f"move:{e.get('move')}" for e in events)
    print(f"\n{len(events)} events in {a.seconds:.0f} s: {dict(kinds) or 'none'}")
    for e in events:
        extra = {k: v for k, v in e.items() if k not in ("t", "type")}
        print(f"  {e['t']:6.2f} s  {e['type']:14} {extra}")
    print("\nper second: body frames/frames, shoulder drift dx dy (image units), width, wrist vis min/mean, "
          "fastest downward wrist (sw/s), fastest forward / mean |forward| (sw/s)")
    for s in result["stats"]:
        print(f"  {s['t']:6.2f}  {s['bodies']:3}/{s['frames']:3}  dx {s['shoulderDx']:.3f} dy {s['shoulderDy']:.3f}  "
              f"w {s['widthMin']:.3f}-{s['widthMax']:.3f}  vis {s['wristVisMin']:.2f}/{s['wristVisMean']:.2f}  "
              f"down {s['downMax']:5.1f}  fwd {s['fwdMax']:5.1f} / {s['fwdMeanAbs']:4.1f}  "
              f"face {s.get('faceMin', -1):.3f}-{s.get('faceMax', -1):.3f} ({s.get('faces', 0)})")
    print(f"\nkept: {result['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
