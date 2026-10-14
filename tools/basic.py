"""Built-in tools that touch nothing on disk."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

from .registry import ToolContext, ToolError, tool

MAX_TIMER_MINUTES = 24 * 60
_timers: set[asyncio.Task] = set()
# what is running, for the dashboard: {"label", "ends" (epoch s), "minutes"}
ACTIVE: list[dict] = []


def _until(target: str, now: datetime) -> str:
    """How long from now until 'HH:MM' (next occurrence) or 'MM-DD' / 'YYYY-MM-DD'."""
    target = target.strip()
    try:
        if ":" in target:
            clock = datetime.strptime(target, "%H:%M").time()
            when = datetime.combine(now.date(), clock)
            if when <= now:
                when += timedelta(days=1)
            minutes = round((when - now).total_seconds() / 60)
            return f"{minutes // 60} h {minutes % 60} min until {when:%H:%M}" + (" tomorrow" if when.date() > now.date() else "")
        parts = [int(p) for p in target.split("-")]
        if len(parts) == 2:
            day = date(now.year, *parts)
            if day < now.date():
                day = date(now.year + 1, *parts)
        elif len(parts) == 3:
            day = date(*parts)
        else:
            raise ValueError(target)
    except ValueError as error:
        raise ToolError("until must be 'HH:MM', 'MM-DD' or 'YYYY-MM-DD'") from error
    days = (day - now.date()).days
    return f"{days} days until {day:%A %d %B %Y}" if days >= 0 else f"{day:%d %B %Y} was {-days} days ago"


@tool(
    "get_time",
    "Current local date and time; with `until`, exactly how long until a clock time or a date.",
    {
        "type": "object",
        "properties": {"until": {"type": "string", "description": "'HH:MM' 24h, or a date 'MM-DD' / 'YYYY-MM-DD' (Christmas = '12-25', New Year = '01-01')"}},
        "required": [],
    },
    cue="clock",
)
async def get_time(_ctx: ToolContext, until: str | None = None) -> str:
    now = datetime.now()
    stamp = now.strftime("%A %d %B %Y, %H:%M:%S")
    return f"{stamp}. {_until(until, now)}" if until else stamp


@tool(
    "set_timer",
    "Start a countdown; Irene says when it ends.",
    {
        "type": "object",
        "properties": {
            "minutes": {
                "type": "number",
                "description": "length in MINUTES, not hours: half an hour = 30, a quarter of "
                "an hour = 15, an hour = 60, an hour and a half = 90, two hours = 120, "
                "90 seconds = 1.5",
            },
            "label": {"type": "string", "description": "what it's for, e.g. 'tea'"},
        },
        "required": ["minutes"],
    },
    readonly=False,
    cue="clock",
)
async def set_timer(ctx: ToolContext, minutes: float, label: str = "") -> str:
    if not 0 < minutes <= MAX_TIMER_MINUTES:
        raise ToolError(f"minutes must be between 0 and {MAX_TIMER_MINUTES}")
    name = label.strip()[:40] or "your"

    async def ring() -> None:
        await asyncio.sleep(minutes * 60)
        await ctx.announce(f"Sir, {name} timer is done." if label else "Sir, your timer is done.")

    ends = datetime.now().timestamp() + minutes * 60
    entry = {"label": label.strip()[:40] or "Timer", "ends": ends, "minutes": minutes}
    task = asyncio.create_task(ring())
    _timers.add(task)
    ACTIVE.append(entry)
    task.add_done_callback(_timers.discard)
    task.add_done_callback(lambda _t: entry in ACTIVE and ACTIVE.remove(entry))
    return f"timer set for {minutes:g} minutes, ends at {datetime.fromtimestamp(ends):%H:%M}"


@tool(
    "forget_conversation",
    "Clear this conversation's history (and what your memory kept of it). Only when he explicitly asks you to forget it.",
    confirm=True,
    readonly=False,
    summary=lambda _args: "Forget everything said in this conversation",
)
async def forget_conversation(ctx: ToolContext) -> str:
    ctx.forget()
    return "conversation history cleared"
