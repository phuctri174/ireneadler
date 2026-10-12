r"""Orpheus 3B (Canopy Labs, Apache-2.0; 4-bit GGUF served by the local Ollama) on the
six expressive lines, voice "tara", with its <laugh> / <sigh> / <gasp> tags.

Orpheus has no zero-shot cloning - it speaks in its own trained voices, so this is
tara, not af_bella. It streams: audio tokens (7 per ~85 ms frame) come out of the
LLM and SNAC turns each window of 4 frames into sound, so time to first audio is
the time until the first window has decoded.

Setup (once): the GGUF imported into Ollama as orpheus-3b-q4 (README.md), snac in
the candidates venv.  <venv>\Scripts\python scripts\expressive\render_orpheus.py
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf
import torch
from snac import SNAC

HERE = Path(__file__).parent
CORE = HERE.parents[1]
OUT = CORE / "voice_samples" / "expressive" / "orpheus_tara"
LINES = json.loads((HERE / "lines.json").read_text(encoding="utf-8"))["lines"]
MODEL = "orpheus-3b-q4"
VOICE = "tara"
SR = 24000
TOKEN = re.compile(r"<custom_token_(\d+)>")


def ollama_vram_mb() -> int:
    """What Ollama holds in VRAM for the Orpheus model (it may already be loaded)."""
    for m in httpx.get("http://127.0.0.1:11434/api/ps").json()["models"]:
        if m["name"].startswith(MODEL):
            return round(m.get("size_vram", 0) / 2**20)
    return 0


def decode(snac: SNAC, ids: list[int]) -> np.ndarray:
    frames = len(ids) // 7
    c0, c1, c2 = [], [], []
    for f in range(frames):
        g = ids[f * 7 : f * 7 + 7]
        c0.append(g[0])
        c1 += [g[1], g[4]]
        c2 += [g[2], g[3], g[5], g[6]]
    codes = [torch.tensor([c], device="cuda") for c in (c0, c1, c2)]
    if any(((c < 0) | (c > 4095)).any() for c in codes):
        raise ValueError("audio token out of range")
    with torch.inference_mode():
        return snac.decode(codes).squeeze().float().cpu().numpy()


def render(snac: SNAC, text: str) -> tuple[np.ndarray, float]:
    prompt = f"<|audio|>{VOICE}: {text}<|eot_id|>"
    ids: list[int] = []
    first = None
    t0 = time.perf_counter()
    with httpx.stream("POST", "http://127.0.0.1:11434/api/generate", json={"model": MODEL, "prompt": prompt, "raw": True, "stream": True, "options": {"num_predict": 1600, "temperature": 0.6, "top_p": 0.9, "repeat_penalty": 1.1}}, timeout=120) as r:
        buffer = ""
        for line in r.iter_lines():
            if not line:
                continue
            buffer += json.loads(line).get("response", "")
            for m in TOKEN.finditer(buffer):
                raw = int(m.group(1))
                if raw < 10:
                    continue  # start-of-speech markers, not audio
                ids.append(raw - 10 - (len(ids) % 7) * 4096)
            buffer = buffer[buffer.rfind(">") + 1 :] if ">" in buffer else buffer
            if first is None and len(ids) >= 28:
                decode(snac, ids[:28])
                torch.cuda.synchronize()
                first = time.perf_counter() - t0
    return decode(snac, ids[: len(ids) // 7 * 7]), first or (time.perf_counter() - t0)


def main() -> None:
    snac = SNAC.from_pretrained("hubertsiuzdak/snac_24khz").eval().to("cuda")
    render(snac, "Ready.")  # loads the model into VRAM
    vram = ollama_vram_mb() + round(torch.cuda.max_memory_allocated() / 2**20)
    OUT.mkdir(parents=True, exist_ok=True)
    timing = {}
    for line in LINES:
        tagged = re.sub(r"\[(laugh|sigh|gasp|chuckle)\]", r"<\1>", line["tagged"])
        audio, first = render(snac, tagged)
        sf.write(OUT / f"{line['id']}.wav", audio, SR, subtype="PCM_16")
        timing[line["id"]] = {"ttfa_ms": round(first * 1000), "seconds": round(len(audio) / SR, 2)}
        print(line["id"], timing[line["id"]], flush=True)
    (OUT / "timing.json").write_text(json.dumps({"model": "orpheus_tara", "vram_mb": vram, "lines": timing}, indent=1), encoding="utf-8")
    print("VRAM (Ollama model + SNAC):", vram, "MB")


if __name__ == "__main__":
    main()
