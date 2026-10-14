"""Forgetting, on his word: what she kept about something, deleted for real
(core/irene/recall.py). She shows exactly what will go and asks first."""
from __future__ import annotations

import time

from .registry import Prepared, ToolContext, ToolError, tool


async def _plan_forget(_ctx: ToolContext, about: str) -> Prepared:
    from irene import recall

    about = " ".join((about or "").split())
    if not about:
        raise ToolError("forget what? say what it was about")
    items = recall.to_forget(about)
    if not items:
        return Prepared(f"nothing kept about {about!r} - there is nothing to forget", needs_confirm=False)
    shown = "\n".join(f"- {i.line(time.time())[2:][:140]}" for i in items[:8])
    more = f"\n... and {len(items) - 8} more" if len(items) > 8 else ""
    return Prepared(f"Delete {len(items)} memor{'y' if len(items) == 1 else 'ies'} about {about!r} for good (and the same words from the logs):\n{shown}{more}",
                    payload=[i.id for i in items])


@tool(
    "forget_memory",
    "Permanently delete what you remember from EARLIER sessions about something - only when he asks you to forget "
    "a thing ('forget what I told you about X', 'delete what you know about my project'). about: the topic, in his words.",
    {"type": "object", "properties": {"about": {"type": "string", "description": "what to forget, in his words (a name, a topic)"}}, "required": ["about"]},
    confirm=True,
    readonly=False,
    prepare=_plan_forget,
    cue="chip",
)
async def forget_memory(_ctx: ToolContext, about: str, prepared: Prepared | None = None) -> str:
    from irene import recall

    store = recall.current()
    ids = set(prepared.payload if prepared is not None else [i.id for i in recall.to_forget(about)])
    items = [i for i in store.items if i.id in ids]
    out = recall.forget(items, store)
    return f"forgotten: {out['deleted']} memor{'y' if out['deleted'] == 1 else 'ies'} about {about!r} deleted for good"
