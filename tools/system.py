# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""His PC's load: CPU, GPU, RAM and VRAM. Read-only, local only (psutil and the
NVIDIA driver's nvidia-smi); nothing leaves the machine."""
from __future__ import annotations

import asyncio
import shutil
import subprocess

import psutil

from .registry import ToolContext, tool


def _gpu() -> tuple[float, float, float] | None:
    """(utilisation %, VRAM used GB, VRAM total GB) of the first GPU, or None."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        util, used, total = (float(v) for v in out.splitlines()[0].split(","))
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None
    return util, used / 1024, total / 1024


def read() -> dict:
    cpu = psutil.cpu_percent(interval=0.3)
    mem = psutil.virtual_memory()
    status = {"cpu": round(cpu), "ram": round(mem.percent), "ram_gb": f"{mem.used / 2**30:.1f}/{mem.total / 2**30:.0f}"}
    gpu = _gpu()
    if gpu:
        util, used, total = gpu
        status |= {"gpu": round(util), "vram": round(used / total * 100), "vram_gb": f"{used:.1f}/{total:.0f}"}
    return status


@tool(
    "system_status",
    "His PC's current CPU, GPU, RAM and VRAM load, in percent. For 'how's my PC doing', 'is my GPU busy', 'how much memory is free'.",
    cue="chip",
)
async def system_status(_ctx: ToolContext) -> str:
    s = await asyncio.to_thread(read)
    gpu = f"GPU {s['gpu']}%, VRAM {s['vram']}% ({s['vram_gb']} GB)" if "gpu" in s else "no NVIDIA GPU readings"
    return (
        f"CPU {s['cpu']}%, RAM {s['ram']}% ({s['ram_gb']} GB), {gpu}. "
        f"To show it: <draw>{{\"template\": \"system_status\", \"cpu\": {s['cpu']}, \"gpu\": {s.get('gpu', 0)}, "
        f"\"ram\": {s['ram']}, \"vram\": {s.get('vram', 0)}, \"ram_gb\": \"{s['ram_gb']}\", \"vram_gb\": \"{s.get('vram_gb', '-')}\"}}</draw>"
    )
