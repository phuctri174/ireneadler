# Hardware constraints

Built and tested on one machine: Windows 11, an NVIDIA RTX 5060 Ti 16 GB (Blackwell,
compute capability 12.0 / sm_120), two monitors, a webcam, a microphone. Nothing here
has been tested on other hardware.

## Blackwell (sm_120): float16 only for Whisper

faster-whisper runs on CTranslate2. At the start of the project (2026-09-20), Whisper
large-v3-turbo with `compute_type="int8"` crashed on this card and float16 worked, so
float16 became a hard rule: `irene/stt.py` refuses any other compute type rather than
try one. The library versions at the time were not pinned or recorded, and the crash
itself was not logged.

**Re-tested 2026-10-17, and the crash does not reproduce.** With ctranslate2 4.8.2 and
faster-whisper 1.2.1, `float16`, `int8` and `int8_float16` all loaded and transcribed
an 8.9 s test clip identically, and `int8` transcribed 170 s of audio (23 segments in
11.1 s) without a fault. So the constraint as originally found is not current, and
why it changed is not known. The float16-only rule stays in code until int8 has been tested on real turns and its word
error rate compared on the held-out corpus. Until then, the rule is not evidence that
int8 is broken.

The same generation constraint shapes the install:

- **PyTorch** comes from the CUDA 12.8 wheel index (`cu128`) for sm_120 support.
- **Chatterbox-Turbo** is installed with `--no-deps`, because it pins torch 2.6,
  which has no sm_120 kernels; its other dependencies are installed by hand
  (`core/requirements.txt`).

## VRAM: everything resident on 16 GB

Loading models on demand would put seconds of latency into a conversation, so the
language model, Whisper and her voice all stay loaded.

Measured 2026-10-17, the app launched (`start-irene.ps1 -Dev`) after one fast-path and
one model turn, everything resident. Per process from Windows' GPU counters
(`\GPU Process Memory(*)\Dedicated Usage`; these overlap, so they don't sum to the
card), the total from `nvidia-smi`:

| Resident | VRAM |
|---|---|
| gemma3:12b Q4_K_M, 16k context, flash attention + q8_0 KV cache (Ollama's runner) | 8.82 GB |
| core: Whisper large-v3-turbo float16 + Chatterbox-Turbo | 5.31 GB |
| the HUD's webviews | 0.66 GB |
| **card total**, including the Windows desktop and other open apps | **15.79 of 16.31 GB** |

Ollama's own `/api/ps` reported the model fully in VRAM (`size_vram` = `size`).
Recorded earlier with the same three resident: 15.3 of 16.3 GB (commit `24770e1`,
2026-10-12).

What makes it fit:

- **gemma3:12b with flash attention and an 8-bit KV cache** (`OLLAMA_FLASH_ATTENTION=1`,
  `OLLAMA_KV_CACHE_TYPE=q8_0`, set by `start-irene.ps1`), 16,384-token context,
  pinned with `keep_alive: -1`. Before the 8-bit cache the card sat at 97%: the driver
  paged, everything on the GPU stalled, and her face measured 37-39 fps with 53-58
  janks per 10 s while the model generated (commit `5f80462`, 2026-10-04).
- **Speaker verification on the CPU:** 114 ms per utterance, hidden behind the
  end-of-speech wait, 0 VRAM (commit `5f80462`).
- **The memory embedding model on the CPU:** ~92 MB of VRAM saved for ~1 ms per query
  (commit `d3fe54f`).
- **Whisper float16**, the smallest type that runs on this card (above).
- **Lecture capture unloads gemma** while it listens (7.9 GB freed, commit `930abfd`).

**The spill guard** (`irene/vram.py`). If another application grows while the model
is loaded, Ollama silently spills layers to system RAM; prefill drops and her first
audio goes from about 1 s to 3-4 s. The guard watches Ollama's `/api/ps` (size in VRAM
below model size), the prefill rate of real prompts, and first-audio time; when any of
them trips, it waits until she is idle, unloads and reloads the model, and checks
again. A cooldown stops it reloading in a loop when VRAM is genuinely full.

The margin is about 1 GB. Running another GPU-heavy application alongside her will
push the model out of VRAM; the guard recovers, but the turn during the spill is slow.

## Windows-only parts

- The OS-level hand pointer (`hud/src-tauri/src/pointer.rs`): Win32 `SendInput`.
- Media keys and volume (`tools/media.py`, pycaw), screens-off (`tools/power.py`:
  `SC_MONITORPOWER`, `SetThreadExecutionState`), bringing a window to the front
  (`tools/foreground.py`), capture-exclusion of her overlay (`tools/screen.py`).
- WASAPI loopback for lecture capture.

## What real sleep can't do

Waking the PC from real Windows sleep (S3, S0ix, hibernate) by voice is impossible:
the CPU is powered down and nothing listens. The achievable version is screens-off
mode: monitors off, the system kept awake, mic and wake phrase still running; a wake
phrase lights the displays and summons her. Hotkey Ctrl+Alt+Shift+O; its switch is
`config/power.yaml`.
