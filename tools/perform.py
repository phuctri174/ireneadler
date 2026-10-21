# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""perform(sequence): a little show on her LED face - expressions, hand gestures and
scenes one after another, each with its sound. "What can you do? Perform some for
me" is answered by doing, not by listing. The cues come from config/cues.json;
core plays them (ToolContext.perform) and reports what it played.
"""
from __future__ import annotations

import re

from .registry import ToolContext, ToolError, tool

MAX_STEPS = 6


def steps(sequence: str) -> list[str]:
    """'wave, starry eyed then kendo' -> ['wave', 'starry eyed', 'kendo']; 'surprise' -> []."""
    parts = [p.strip() for p in re.split(r",|;|\bthen\b|\band\b|->|\n", sequence or "") if p.strip()]
    if not parts or all(re.fullmatch(r"(a )?(surprise|random|anything|whatever|your (pick|choice)|some|all|everything)", p, re.I) for p in parts):
        return []
    return parts[: MAX_STEPS * 2]


@tool(
    "perform",
    "Perform a little show on your LED face: expressions, hand gestures and scenes one after "
    "another. For 'what can you do - show me', 'perform for me', 'show me your faces/tricks'. "
    "Do it with this tool; never just list them.",
    {"type": "object", "properties": {"sequence": {"type": "string", "description": "3-6 cue names in order, e.g. 'wave, starryEyed, kendo, giggle' - or 'surprise' for your own pick"}}, "required": ["sequence"]},
)
async def perform(ctx: ToolContext, sequence: str) -> str:
    played = await ctx.perform(steps(sequence))
    if not played:
        raise ToolError("none of those are things I can show")
    return f"performed: {', '.join(played)}"
