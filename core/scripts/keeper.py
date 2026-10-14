"""Keeps core running: if it dies of anything but a chosen exit, start it again.

start-irene.ps1 runs this in the "Irene core" window; core runs as its child in the
same window (its log scrolls there as before). When core exits, its exit record
(irene/lifeline.py, logs/exits.jsonl) says why:

  a chosen exit - Ctrl+C, the window closed, log off, Windows shutting down: stop
  anything else - an unhandled exception, a kill, no record at all: start it again
                  in 3 s. A lecture capture it was running resumes by itself
                  (lecture.py LectureCapture.resume).

A crash loop is not hidden behind restarts: after MAX_RESTARTS within WINDOW_S the
keeper gives up and says so. Everything it does goes to logs/keeper.log.

  .venv\\Scripts\\python scripts\\keeper.py
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid
import sys
import time
from datetime import datetime
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
LOGS = CORE / "logs"
EXITS = LOGS / "exits.jsonl"
LOG = LOGS / "keeper.log"
MAX_RESTARTS = 5
WINDOW_S = 600
PAUSE_S = 3

sys.path.insert(0, str(CORE))
from irene.lifeline import CHOSEN  # noqa: E402


def note(text: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')} keeper: {text}"
    print(line, flush=True)
    LOGS.mkdir(exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def exit_record(run: str) -> dict | None:
    """Core's own record of how the run the keeper started ended, if it wrote one."""
    try:
        lines = EXITS.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for raw in reversed(lines):
        try:
            r = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if r.get("who") == "core" and r.get("event") == "exit" and r.get("run") == run:
            return r
    return None


def should_restart(record: dict | None, code: int | None) -> tuple[bool, str]:
    """(restart?, why) from core's exit record and its exit code."""
    if record is None:
        return True, f"no exit record (exit code {code}) - killed without warning"
    reason = record.get("reason", "")
    if reason in CHOSEN:
        return False, reason
    return True, reason or f"exit code {code}"


def main() -> int:
    restarts: list[float] = []
    while True:
        run = uuid.uuid4().hex[:12]
        child = subprocess.Popen([sys.executable, "-m", "irene.app"], cwd=str(CORE), env={**os.environ, "IRENE_RUN": run})
        note(f"core started (pid {child.pid})")
        try:
            code = child.wait()
        except KeyboardInterrupt:
            # Ctrl+C reached both: core records it and exits; wait for that, then stop
            code = child.wait()
            note(f"Ctrl+C - core exited ({code}); keeper stops")
            return 0
        # the record is written before the process ends; give the file a moment
        time.sleep(0.5)
        again, why = should_restart(exit_record(run), code)
        if not again:
            note(f"core exited ({why}) - not restarting")
            return 0
        now = time.time()
        restarts = [t for t in restarts if now - t < WINDOW_S] + [now]
        if len(restarts) > MAX_RESTARTS:
            note(f"core died {len(restarts)} times in {WINDOW_S // 60} min (last: {why}) - a crash loop; giving up")
            return 1
        note(f"core died ({why}) - restarting in {PAUSE_S} s (restart {len(restarts)} in the last {WINDOW_S // 60} min)")
        time.sleep(PAUSE_S)


if __name__ == "__main__":
    raise SystemExit(main())
