r"""Compare models on the full eval set, plus VRAM with Kokoro (core) loaded.

Run with core running (so Kokoro is resident), e.g.:
  .venv\Scripts\python evals\compare_models.py gemma3:12b gemma4:12b --repeat 2

VRAM: every Ollama model is unloaded, the baseline (desktop + Kokoro) is read with
nvidia-smi, then each model is loaded alone and read again. The model the app
uses (irene.llm.MODEL) is reloaded and pinned at the end.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time

from harness import MODEL_DEFAULT, Ollama, Report, run_reactions, run_routing, summary


def vram_used_mib() -> int:
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, check=True,
    ).stdout
    return int(out.strip().splitlines()[0])


def loaded_models() -> list[str]:
    out = subprocess.run(["ollama", "ps"], capture_output=True, text=True).stdout.splitlines()[1:]
    return [line.split()[0] for line in out if line.strip()]


def unload_all() -> None:
    for name in loaded_models():
        subprocess.run(["ollama", "stop", name], capture_output=True)
    deadline = time.time() + 30
    while loaded_models() and time.time() < deadline:
        time.sleep(1)
    time.sleep(3)  # let the driver release the memory


async def measure(model: str, repeat: int) -> dict:
    unload_all()
    baseline = vram_used_mib()
    llm = Ollama(model)
    await llm.warm()
    time.sleep(2)
    loaded = vram_used_mib()
    report = Report(model)
    try:
        await run_routing(llm, report, repeat)
        await run_reactions(llm, report, repeat)
    finally:
        await llm.close()
    result = summary(report)
    result["vram_baseline_mib"] = baseline
    result["vram_with_model_mib"] = loaded
    result["vram_model_mib"] = loaded - baseline
    result["failures"] = [line for line in report.lines if line.startswith("FAIL")]
    return result


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("models", nargs="+")
    parser.add_argument("--repeat", type=int, default=2)
    args = parser.parse_args()
    results = []
    try:
        for model in args.models:
            print(f"== {model}", flush=True)
            results.append(await measure(model, args.repeat))
            print(json.dumps({k: v for k, v in results[-1].items() if k != "failures"}, indent=1), flush=True)
    finally:
        unload_all()
        llm = Ollama(MODEL_DEFAULT)
        await llm.warm()
        await llm.close()
    for r in results:
        print(f"\n-- failures, {r['model']}:")
        for line in r["failures"]:
            print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
