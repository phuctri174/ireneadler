"""Irene's tool registry. Every tool declares whether it needs a yes from the user
(confirm) and whether it only reads (readonly). See registry.py."""
from .registry import REGISTRY, Prepared, Tool, ToolError, ToolResult, tool

from . import basic, briefing, browser, dashboard, files, lecture, memory, power, media, panel, pdf, perform, research, screen, system  # noqa: E402,F401  - registers the built-in tools

__all__ = ["REGISTRY", "Prepared", "Tool", "ToolError", "ToolResult", "tool"]
