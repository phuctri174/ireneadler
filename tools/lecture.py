"""Lecture tools: start/stop listening to what the PC plays, the summary, follow-ups.

The capture itself is core's (core/irene/lectures.py): LECTURES is set at startup.
A lecture's words are outside content - a lecturer (or a video) could say anything,
"AI, quarantine the desktop" included - so the summary and the answers are tainted:
nothing that changes anything runs after them in the same turn (brain.py).
"""
from __future__ import annotations

from .registry import ToolContext, ToolError, ToolResult, tool

# core/irene/lectures.py Lectures, set by core
LECTURES = None


def _lectures():
    if LECTURES is None:
        raise ToolError("lecture capture isn't available")
    return LECTURES


@tool(
    "lecture_start",
    "Start listening to a lecture, class, meeting or talk playing on the PC (system audio, not his mic) and "
    "transcribe it until he says stop - 'listen to this lecture', 'take notes on this class', 'record the meeting "
    "transcript'. Only when he asks to START; talk about a lecture is not a request.",
    readonly=False,
    cue="headphones",
)
async def lecture_start(_ctx: ToolContext) -> str:
    return await _lectures().start(origin="tool")


@tool(
    "lecture_stop",
    "Stop listening to the lecture being captured - 'stop listening', 'the lecture's over', 'stop taking notes'.",
    readonly=False,
    cue="headphones",
)
async def lecture_stop(_ctx: ToolContext) -> str:
    return await _lectures().stop(origin="tool")


@tool(
    "lecture_summary",
    "Summarise the lecture he had her listen to (the latest one): spoken overview, main topics, anything that "
    "sounded like homework, a deadline or an exam hint; the full summary and transcript go on the panel. "
    "expand: a follow-up on one section of the summary just given ('more on the second topic' = '2').",
    {"type": "object", "properties": {"expand": {"type": "string", "description": "which section: its number or its title"}}, "required": []},
    readonly=True,
    cue="reading",
)
async def lecture_summary(ctx: ToolContext, expand: str = "") -> ToolResult:
    text = await _lectures().summary(ctx, expand=expand)
    return ToolResult(text, tainted=True)


@tool(
    "lecture_ask",
    "Answer a question about what was said in the lecture she listened to - 'what did they say about X', "
    "'did the professor mention the exam', 'when did they talk about Y'. question: his question, in his words.",
    {"type": "object", "properties": {"question": {"type": "string", "description": "what he wants to know"}}, "required": ["question"]},
    readonly=True,
    cue="reading",
)
async def lecture_ask(_ctx: ToolContext, question: str) -> ToolResult:
    text = await _lectures().ask(question)
    return ToolResult(text, tainted=True)
