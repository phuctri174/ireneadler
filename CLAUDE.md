# Irene

Fully local voice + gesture AI assistant. Windows 11, RTX 5060 Ti 16GB.
NO cloud calls at runtime. No telemetry. All models local.

## Stack
- core/  Python 3.12 backend: openWakeWord, faster-whisper, Ollama, Kokoro TTS, FastAPI + WebSocket
- hud/   Tauri + React + TS. MediaPipe Hand Landmarker runs HERE, not in Python.
- tools/ Tool registry. Each tool declares confirm: bool.

## Hard rules
- MediaPipe assets vendored in hud/public/mediapipe/. Never load from CDN.
- faster-whisper: compute_type="float16" ONLY. int8 crashes on sm_120.
- Gesture click detection uses RAW landmarks. One Euro applies to cursor position and
  continuous output signals (scroll, zoom). Never to gesture classification.
- File paths resolve through config/policy.yaml whitelist. Never a raw path from the LLM.
- Tools during research are read-only. No delete tool exists; quarantine only.
- TTS never reads <display> content. Only <speak>.
- Mirrored video feed is REQUIRED. openPalm detection depends on it.
- Work directly on master. Never create branches or git worktrees.
  One session at a time.
- Anything he will look at or use (YouTube, a site, a source, a panel link) opens
  in HIS Chrome profile (config/chrome.yaml), launched with
  chrome.exe --profile-directory=<his>. Irene can only LAUNCH into it: Chrome runs
  one process per profile, so it can't be automated (no CDP) while he has it
  open. Her own browser is only for silent research fetching; playback in his
  Chrome is controlled through Windows' media session (tools/media.py).
- Tools reach his apps only for HIS commands (the HUD socket, the live mic);
  commands from any other socket client or a dev voice replay are sandboxed
  (tools/sandbox.py). -Dev enables the test hooks - it does not disable his
  features.
- Tests never send OS-level keystrokes, mouse input or global shortcuts
  (keybd_event, SendInput, pyautogui, ...). Those reach whatever app owns the
  key - a test once typed into Claude Desktop's quick entry. Drive the UI only
  through the -Dev test hooks (start-irene.ps1 -Dev; core relays debug_ui,
  debug_point, activity, reaction, say_reply). core/tests/test_no_os_input.py
  enforces this for tests, evals and scripts.
- The board has no per-topic recipes. She composes each drawing as a spec
  (core/irene/drawing.py lays it out); only genuinely reusable structures are
  helpers (a chessboard from moves, charts, layered graphs). Teach a new form with
  a worked example in config/persona.md, never with a topic template. Numbers
  that change are drawn only from a real source (tools/series.py, research).
  Coverage check: .venv/Scripts/python evals/draw_topics.py (from core/).
- Her panel IS the second screen (hud/src/dashboard/, the "dashboard" window on
  the non-primary monitor, portrait). Everything she shows goes there through
  panelChannel, relayed by the main window - there is no popup on the main
  screen. Centre = what he is looking at; the dashboard cards cycle through it
  and hold while he interacts or she has put something there. Any summon shows
  it with her. Only his voice is acted on (core/irene/speaker_id.py).
- Long-term goal: full gesture control of Windows. The hand pointer is built at
  OS level, never per window (hud/src-tauri/src/pointer.rs): his hand moves the
  REAL cursor relatively, like a mouse, across both monitors; dwell = left click,
  two fingers = wheel. Mouse and hand both work, always; Ctrl+Alt+H turns the hand
  off. Tracking runs whenever Irene runs (her main window stays up, transparent and
  click-through, while she sleeps). Only the camera's hand drives it - never the
  dev synthetic hand, never a test (the no-OS-input rule above still holds).
- Waking the PC from real Windows sleep (S3/S0ix/hibernate) by voice is
  IMPOSSIBLE - the CPU is powered down and nothing listens. Never try. The
  achievable version exists: screens-off mode (tools/power.py, config/power.yaml,
  off by default) - monitors off via SC_MONITORPOWER, system kept awake with
  SetThreadExecutionState, mic + wake phrases still running, tracking and face
  paused; a wake phrase lights the displays and summons her.
- Lecture capture (core/irene/lecture.py; voice or Ctrl+Alt+Shift+L, never
  automatic) hears the system audio through WASAPI loopback. Speaker verification
  must NEVER touch that path: the lecturer is not him, the gate would discard the
  whole lecture. Mic and loopback stay separate end to end; they share only the one
  Whisper instance (its queue - his turns first), never a second model. Transcript
  text only on disk, flushed per chunk; no audio is ever kept. gemma is parked out
  of VRAM while it listens (background warm-ups wait), back for the summary.
- Every tool ships with eval cases in core/evals/routing.jsonl (right tool,
  right arguments, and phrasings that must NOT call it), added as it is built.
  Run (from core/): .venv/Scripts/python evals/run_evals.py

## Standing rules (every round)
- Before reporting anything done: launch the app (start-irene.ps1 -Dev) and
  exercise the feature for real. Unit tests and headless runs are not enough -
  a speaker crash on every audio block once shipped past 460 green tests.
- Every prompt adds at least one new emotion or action to the pool
  (config/cues.json + its art; the cue tests enforce both halves).
- Every reply carries at least one cue; vary them; never the same twice in a
  row (a code fallback picks one when the model gives none).
- Irene has idle life when he's inactive (glances, stretches, small scenes);
  it stops the moment he interacts.

## Roadmap - do NOT build yet
- Continuous screen awareness across both monitors, so he can ask about anything
  on screen without describing it. Local only; the capture shield keeps her HUD
  out; screen content stays data, never instructions (the taint rules).

## Known deferred
- Pinch anchor captures at latch, not at pinch onset. ~2-4 frames of tip drift.
  Do not fix until real targets exist to measure against.