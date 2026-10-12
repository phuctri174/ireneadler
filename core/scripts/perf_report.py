r"""Where the time goes in the RUNNING app (start-irene.ps1 -Dev), no OS input:

  .venv\Scripts\python scripts\perf_report.py [label] [--turns N]

  HUD         the HUD's own reports in core/logs/core.log ("hud perf", every 10 s):
              hand tracking fps and ms, body (pose) tracking Hz and ms, her face's
              compose + draw per frame
  LLM / TTS   a few typed turns through core (as the command bar sends them):
              prefill, tokens/s, model's first phrase, first audio heard - the
              gap between those two is TTS
  VRAM        Windows' dedicated GPU memory counter (nvidia-smi misreads under WDDM)

Writes core/logs/perf-<label>.json.
"""
from __future__ import annotations

import asyncio
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

import websockets

LOGS = Path(__file__).resolve().parents[1] / "logs"
TURNS = [
    "Tell me one fun fact about octopuses.",
    "Why is the sky blue, in two sentences?",
    "What's a good name for a black cat?",
    "Give me one tip for kendo footwork.",
]


def vram_gb() -> float | None:
    cmd = "(Get-Counter '\\GPU Adapter Memory(*)\\Dedicated Usage').CounterSamples | Measure-Object -Property CookedValue -Maximum | Select-Object -ExpandProperty Maximum"
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=30)
        return round(float(out.stdout.strip()) / 2**30, 2)
    except Exception:
        return None


def hud_perf(since: float) -> list[dict]:
    rows = []
    for line in (LOGS / "core.log").read_text(encoding="utf-8", errors="replace").splitlines():
        if "hud perf:" not in line:
            continue
        stamp = time.mktime(time.strptime(line[:19], "%Y-%m-%d %H:%M:%S"))
        if stamp >= since:
            rows.append(json.loads(line.split("hud perf:", 1)[1]))
    return rows


async def turn(ws, text: str) -> dict:
    path = LOGS / "turns.jsonl"
    before = path.read_text(encoding="utf-8").count("\n")
    await ws.send(json.dumps({"type": "command", "text": text}))
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            m = json.loads(await asyncio.wait_for(ws.recv(), 1))
            if m.get("type") == "state" and m.get("value") == "listening":
                break
        except asyncio.TimeoutError:
            pass
    for _ in range(50):
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > before:
            return json.loads(lines[-1])
        await asyncio.sleep(0.1)
    return {}


def med(values):
    values = [v for v in values if isinstance(v, (int, float))]
    return round(statistics.median(values), 1) if values else None


async def main(label: str, n: int) -> None:
    started = time.time()
    report: dict = {"label": label, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "vram_gb_idle": vram_gb()}
    rows = []
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        for text in TURNS[:n]:
            r = await turn(ws, text)
            call = (r.get("calls") or [{}])[0]
            rows.append({"said": text, "prefill_ms": call.get("prefill_ms"), "tok_s": call.get("tok_s"), "first_text_ms": r.get("first_text_ms"),
                         "ttfa_ms": r.get("ttfa_ms"), "tts_ms": (r["ttfa_ms"] - r["first_text_ms"]) if r.get("ttfa_ms") and r.get("first_text_ms") else None})
            print(f"  {text[:40]:40} prefill {rows[-1]['prefill_ms']} ms, {rows[-1]['tok_s']} tok/s, first phrase {rows[-1]['first_text_ms']} ms, first audio {rows[-1]['ttfa_ms']} ms", flush=True)
            report["vram_gb_busy"] = max(report.get("vram_gb_busy") or 0, vram_gb() or 0)
    report["turns"] = rows
    report["llm"] = {k: med(r[k] for r in rows) for k in ("prefill_ms", "tok_s", "first_text_ms", "tts_ms", "ttfa_ms")}
    await asyncio.sleep(12)  # at least one more HUD report
    perf = hud_perf(started - 30)
    report["hud"] = {k: med(p.get(k) for p in perf) for k in ("handFps", "handMs", "poseHz", "poseMs", "poseWorstMs", "faceFps", "faceMs", "faceWorstMs")}
    report["hud_reports"] = len(perf)
    (LOGS / f"perf-{label}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "turns"}, indent=1))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    n = int(sys.argv[sys.argv.index("--turns") + 1]) if "--turns" in sys.argv else 4
    asyncio.run(main(args[0] if args else "now", n))
