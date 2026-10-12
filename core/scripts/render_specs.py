r"""Her drawing specs as PNGs, through the real compiler (irene/drawing.py) and the
HUD's own drawing code (hud/scripts/render_frames.mjs) - no app, no window.

  .venv\Scripts\python scripts\render_specs.py specs.jsonl <out dir>

specs.jsonl: one {"name": ..., "spec": {...}, "question"?: ...} per line. Prints
each spec's outcome (kind, or why it can't be drawn); a PNG per drawable one.
Needs the HUD's compiled modules (node tests/run.mjs in hud/ builds them).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from irene import drawing, illustrate  # noqa: E402

HUD = Path(__file__).resolve().parents[2] / "hud"


def board_of(spec: dict, question: str = "") -> tuple[dict | None, str]:
    """(the HUD draw spec, what it is) - everything revealed, as at the answer's end."""
    try:
        read = drawing.read(spec, title=question)
        if read.layout == "chess":
            chess = illustrate.chess_board(read, question, "")
            if chess is None:
                return None, "invalid: no legal line of moves"
            msg = chess.snapshot()
            chess.finish()
            return {**msg["spec"], "reveal": [{"key": f"ply:{len(chess.moves)}", "at": 0}]}, f"chess {' '.join(chess.moves)}"
        drawn = drawing.compile(read)
    except drawing.SpecError as error:
        return None, f"invalid: {error}"
    fixed = f" (fixed: {'; '.join(read.fixed)})" if read.fixed else ""
    return {"shapes": drawn.shapes()}, f"{drawn.kind}, {len(drawn.elements)} elements, {len(drawn.shapes())} shapes{fixed}"


def render(shots: list[dict], out: Path) -> str:
    out.mkdir(parents=True, exist_ok=True)
    (out / "shots.json").write_text(json.dumps(shots), encoding="utf-8")
    done = subprocess.run(["node", "scripts/render_frames.mjs", str(out / "shots.json"), str(out)], cwd=HUD, capture_output=True, text=True)
    return (done.stdout.strip() or done.stderr.strip())[-300:]


def main() -> int:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    shots = []
    for line in src.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        board, what = board_of(row["spec"], row.get("question", ""))
        print(f"{row['name']:28} {what}")
        if board is not None:
            shots.append({"name": row["name"], "draw": board, "t": 60000})
    print(render(shots, out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
