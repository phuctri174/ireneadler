"""Repair a keiko capture written before calibration.write kept its labels.

A keiko frame carries its 33 body landmarks as "pose" - the same key as the step
label - so every row of those sessions lost its label. The takes are still there
in recording order, each restarting its frame index at 0, so the labels come back
from the profile: step by step, one take per rep. Only a file whose take count
matches its profile exactly is repaired; the original is kept beside it as
<name>.jsonl.unlabelled (not a .jsonl, so nothing reads it by accident).

Run (from core/): .venv/Scripts/python scripts/keiko_relabel.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from irene.calibration import DIR, PROFILES, sessions  # noqa: E402


def plan(profile: str) -> list[tuple[str, int]]:
    steps = json.loads(PROFILES.read_text(encoding="utf-8"))["profiles"][profile]["steps"]
    return [(s["label"], rep) for s in steps for rep in range(s.get("reps", 1))]


def relabel(path: Path, profile: str) -> str:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows or not isinstance(rows[0].get("pose"), list):
        return "already labelled"
    takes: list[list[dict]] = []
    for row in rows:
        if row["i"] == 0:
            takes.append([])
        takes[-1].append(row)
    want = plan(profile)
    if len(takes) != len(want):
        return f"NOT repaired: {len(takes)} takes, profile has {len(want)} (a redo or a newer profile)"
    for (label, rep), take in zip(want, takes):
        if any(r["rep"] != rep for r in take):
            return f"NOT repaired: take {label} expected rep {rep}, found {take[0]['rep']}"
    out = []
    for (label, _), take in zip(want, takes):
        for row in take:
            body = row.pop("pose")
            out.append({**row, "body": body, "pose": label})
    backup = path.with_name(path.name + ".unlabelled")
    path.rename(backup)
    path.write_text("".join(json.dumps(r) + "\n" for r in out), encoding="utf-8")
    return f"repaired {len(out)} frames in {len(takes)} takes (original kept as {backup.name})"


def main() -> None:
    for profile in ("keiko_near", "keiko_mid"):
        for path in sessions(profile, DIR):
            print(f"{path.name}: {relabel(path, profile)}")


if __name__ == "__main__":
    main()
