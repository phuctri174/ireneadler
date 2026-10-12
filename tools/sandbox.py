"""Whether a command may reach his apps: real for HIM, never for a test.

Round 6 found the old guard backwards. IRENE_DEV meant "media keys and his Chrome
are logged, not used" - but he runs Irene with -Dev every day, so "pause" never
paused and a panel link never opened, for him. What matters is who asked:

  his own commands     the HUD (command bar, panel clicks) and the live mic
                       -> real: media keys, volume, his Chrome, his files open
  anything else        a test script on the socket, a dev voice replay
                       -> OS input (keys, volume) is never sent (CLAUDE.md);
                          launching a page or file, or his media session
                          (Windows' API, not a keystroke), only when the script
                          asks for it explicitly ("real_launch": a live check of
                          "open chess.com" or pausing the song it put on)

Set per command (app.on_command) in a ContextVar, so every tool the turn runs
sees it. With nothing set - a path that forgot - dev mode means sandboxed.
"""
from __future__ import annotations

import os
from contextvars import ContextVar

# True: no OS input from this turn. None: not set (falls back to dev mode)
OS_INPUT_BLOCKED: ContextVar[bool | None] = ContextVar("irene_os_input_blocked", default=None)
# True: pages and files may open on his screen from this turn
LAUNCH_ALLOWED: ContextVar[bool | None] = ContextVar("irene_launch_allowed", default=None)

HIS = ("hud", "mic")


def _dev() -> bool:
    return bool(os.environ.get("IRENE_DEV"))


def os_input_blocked() -> bool:
    value = OS_INPUT_BLOCKED.get()
    return _dev() if value is None else value


def launch_blocked() -> bool:
    value = LAUNCH_ALLOWED.get()
    return os_input_blocked() if value is None else not value


def enter(origin: str | None, real_launch: bool = False) -> None:
    """For the command being handled, from where it came."""
    his = origin in HIS
    OS_INPUT_BLOCKED.set(not his)
    LAUNCH_ALLOWED.set(his or real_launch)


def describe() -> str:
    return f"os input {'blocked' if os_input_blocked() else 'allowed'}, launch {'blocked' if launch_blocked() else 'allowed'}"
