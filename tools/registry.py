"""Tool registry.

A tool is an async function plus metadata the model sees (name, description,
JSON-schema parameters) and metadata only the runtime enforces:

  confirm   the user must answer y before it runs - shown in the command bar
  readonly  it changes nothing; the only kind allowed while research runs
  creates_only  it only ever makes a new file (never overwrites, moves or deletes),
            so it may run after outside content was read (save_panel_pdf)
  cue       the prop Irene shows while it runs (a magnifier, a clock) - a "prop"
            in config/cues.json; the model never picks it

Arguments come from the model, so they are validated here against the declared
schema before the function ever sees them.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol


class ToolError(Exception):
    """A tool failed in a way the model should be told about."""


class ToolContext(Protocol):
    """What a tool may ask of the running assistant. Passed as the first argument."""

    async def announce(self, text: str) -> None:
        """Say something out of turn (a timer going off)."""

    def forget(self) -> None:
        """Drop the conversation history."""

    async def capture_shield(self, on: bool) -> None:
        """Hide (or show again) Irene's own overlay from screen captures."""

    async def show_panel(self, content: dict | None) -> None:
        """Put content (hud/src/ui/content.ts PanelContent) on the panel, or close it."""

    def panel_answers(self) -> list[dict]:
        """Her earlier detailed answers as panel content, newest first (with "at")."""

    def panel_content(self) -> dict | None:
        """What the panel shows right now, or None."""

    async def confirm(self, prompt: str) -> bool:
        """Ask him yes or no (the system's confirm prompt); True on his yes."""

    async def screens_off(self) -> None:
        """Screens-off mode: her windows away, tracking paused, the monitors dark;
        she keeps listening for a wake phrase (tools/power.py)."""

    async def perform(self, names: list[str]) -> list[str]:
        """Play these cues one after another on her face ([] = her own pick); returns
        the names actually played."""


@dataclass
class ToolResult:
    """A result with attachments: `images` (base64) go to the model with the next
    call and are dropped from history once it has answered. `tainted`: it carries
    outside content (a web page, his screen) that may try to steer the model."""

    text: str
    images: list[str] = field(default_factory=list)
    tainted: bool = False


@dataclass
class Prepared:
    """What a confirm tool will do, worked out before asking.

    `text` is shown with the confirmation (a dry-run plan); `payload` is handed to
    run() so it does exactly what was shown and nothing more. With nothing to do,
    `needs_confirm` is False and `text` is the result.
    """

    text: str
    payload: Any = None
    needs_confirm: bool = True


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    run: Callable[..., Awaitable[Any]]
    confirm: bool = False
    readonly: bool = True
    # how to describe a pending call to the user, from its arguments
    summary: Callable[[dict], str] | None = None
    # confirm tools: compute the plan first; run() then receives `prepared=`
    prepare: Callable[..., Awaitable[Prepared]] | None = None
    cue: str | None = None
    creates_only: bool = False

    def describe(self, args: dict) -> str:
        if self.summary:
            return self.summary(args)
        shown = ", ".join(f"{k}={v!r}" for k, v in args.items())
        return f"{self.name}({shown})"

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


REGISTRY: dict[str, Tool] = {}

_JSON_TYPES = {"string": str, "number": (int, float), "integer": int, "boolean": bool, "object": dict, "array": list}


def tool(
    name: str,
    description: str,
    parameters: dict | None = None,
    *,
    confirm: bool = False,
    readonly: bool = True,
    summary: Callable[[dict], str] | None = None,
    prepare: Callable[..., Awaitable[Prepared]] | None = None,
    cue: str | None = None,
    creates_only: bool = False,
):
    """Register an async function as a tool."""
    schema = parameters or {"type": "object", "properties": {}, "required": []}

    def register(fn):
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(f"tool {name} must be async")
        if name in REGISTRY:
            raise ValueError(f"tool {name} registered twice")
        REGISTRY[name] = Tool(name, description, schema, fn, confirm, readonly, summary, prepare, cue, creates_only)
        return fn

    return register


def validate(tool_: Tool, args: object) -> dict:
    """Model-supplied arguments -> checked kwargs, or ToolError explaining why not."""
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ToolError("arguments must be an object")
    props = tool_.parameters.get("properties", {})
    missing = [k for k in tool_.parameters.get("required", []) if k not in args]
    if missing:
        raise ToolError(f"missing argument(s): {', '.join(missing)}")
    unknown = [k for k in args if k not in props]
    if unknown:
        raise ToolError(f"unknown argument(s): {', '.join(unknown)}")
    clean = {}
    for key, value in args.items():
        want = _JSON_TYPES.get(props[key].get("type", "string"), object)
        # JSON has no int/float split and models write "5" for 5; coerce the obvious cases
        if want == (int, float) and isinstance(value, str):
            try:
                value = float(value)
            except ValueError as error:
                raise ToolError(f"{key} must be a number") from error
        if isinstance(value, bool) and want != bool:
            raise ToolError(f"{key} has the wrong type")
        if not isinstance(value, want):
            raise ToolError(f"{key} must be {props[key].get('type', 'string')}")
        allowed = props[key].get("enum")
        if allowed is not None:
            match = next((a for a in allowed if str(a).lower() == str(value).strip().lower()), None)
            if match is None:
                raise ToolError(f"{key} must be one of: {', '.join(map(str, allowed))}")
            value = match
        clean[key] = value
    return clean


def _signature(t: Tool) -> str:
    props = t.parameters.get("properties", {})
    required = set(t.parameters.get("required", []))
    params = []
    for name, spec in props.items():
        kind = "|".join(f'"{v}"' for v in spec["enum"]) if "enum" in spec else spec.get("type", "string")
        note = f" ({spec['description']})" if spec.get("description") and "enum" not in spec else ""
        params.append(f"{name}{'' if name in required else '?'}: {kind}{note}")
    flags = " [asks his yes first]" if t.confirm else ""
    return f"- {t.name}({', '.join(params)}){flags} - {t.description}"


def catalogue(names: list[str] | None = None) -> str:
    """The tool list as the model sees it: one compact signature per tool - the
    same information as JSON schema in well under half the tokens."""
    tools = [REGISTRY[n] for n in (names or sorted(REGISTRY))]
    return "\n".join(_signature(t) for t in tools)
