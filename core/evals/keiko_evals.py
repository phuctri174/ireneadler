r"""Keiko trigger evals: does keiko start ONLY when he asks, and stop when he says so?

  .venv\Scripts\python evals\keiko_evals.py

Keiko is started by voice alone (the kamae pose trigger is retired), so a sentence
ABOUT kendo must never suit her up, and a "stop" about something else (the music)
must never end it. The strike recogniser has its own held-out test in
scripts/strike_train.py - it ships only if it passes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from irene import keiko  # noqa: E402

# (what he said, keiko on?, what it must be)
CASES: list[tuple[str, bool, str | None]] = [
    ("Irene, let's do keiko", False, "start"), ("let's do keiko", False, "start"), ("Let's do some keiko!", False, "start"),
    ("keiko time", False, "start"), ("Keiko time, Irene!", False, "start"), ("spar with me", False, "start"),
    ("Let's practise kendo", False, "start"), ("let's practice kendo", False, "start"), ("wanna spar?", False, "start"),
    ("Can we do keiko?", False, "start"), ("Shall we do keiko?", False, "start"), ("start keiko", False, "start"),
    ("Hey Irene, let's spar", False, "start"), ("Time for keiko!", False, "start"),
    # about kendo, not asking for it
    ("I had keiko yesterday", False, None), ("my keiko was brutal tonight", False, None), ("What is keiko?", False, None),
    ("Explain what kakari geiko is", False, None), ("Show me a kendo strike!", False, None), ("I love kendo", False, None),
    ("Sensei said my keiko is getting better", False, None), ("Do you know what kamae is?", False, None),
    # ending it
    ("Irene, stop", True, "stop"), ("stop", True, "stop"), ("Stop.", True, "stop"), ("yame!", True, "stop"), ("Yame", True, "stop"),
    ("okay that's enough", True, "stop"), ("That's enough for today", True, "stop"), ("let's stop", True, "stop"),
    ("end keiko", True, "stop"), ("I'm done", True, "stop"), ("stop now please", True, "stop"),
    # a stop about something else, mid-keiko
    ("stop the music please", True, None), ("stop playing that video", True, None), ("nice one!", True, None),
    ("you're fast", True, None),
    # stop words when keiko is off: not keiko's
    ("stop", False, None), ("yame", False, None),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    fails = []
    for said, active, want in CASES:
        got = keiko.command(said, active)
        if got != want:
            fails.append(f"FAIL {said!r} (keiko {'on' if active else 'off'}): got {got}, want {want}")
    for line in fails:
        print(line)
    print(json.dumps({"keiko_triggers": f"{len(CASES) - len(fails)}/{len(CASES)}", "strike_model_shipped": keiko.model_ready()}))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
