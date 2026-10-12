"""The system prompt: config/persona.md plus facts only code knows.

The cue names are appended from the registry (config/cues.json via react.py)
rather than written into the persona, so the prompt can never offer a cue the
HUD doesn't have, and a new one reaches the model with no prompt edit.
"""
from __future__ import annotations

from pathlib import Path

from . import board, react

PERSONA = Path(__file__).resolve().parents[2] / "config" / "persona.md"


def reaction_catalogue() -> str:
    return "## Available cues\n\nOnly these exact names in <cue>. Anything else is ignored.\n\n" + react.catalogue()


FORMAT_REMINDER = (
    "## Reply format\n\n"
    "Every reply: <speak>...</speak> FIRST (short for commands, 3-5 sentences for an answer) - always - "
    "with a <cue>name</cue> before any sentence whose feeling shows; then "
    "<display>...</display> only for real content to read (a list, a table, code, details); "
    "then, when you explain how, why or what something is (steps, parts, history, a comparison, numbers), one <draw>{...}</draw> you compose "
    "(see Your drawing board) - never for chat, jokes, feelings, advice or a one-line fact. "
    "Never narrate or describe what you or your face are doing, in any tag."
)


def system_prompt(extra: str = "") -> str:
    parts = [PERSONA.read_text(encoding="utf-8").strip(), reaction_catalogue(), board.board_section(), FORMAT_REMINDER]
    if extra:
        parts.append(extra.strip())
    return "\n\n".join(parts)
