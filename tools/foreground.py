# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Bring a window to the front - his Chrome after she opens something in it.

Windows only lets the foreground process raise a window; core is a background
process, so a tab she opened used to arrive behind whatever he had up. The
documented way round it without touching his keyboard: attach our input queue to
the foreground thread's for a moment, then raise. No keystrokes, no mouse input
(the no-OS-input rule) - only window-manager calls.
"""
from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes

log = logging.getLogger("irene.tools")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

SW_RESTORE = 9
SW_SHOW = 5
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOMOVE, SWP_NOSIZE, SWP_SHOWWINDOW = 0x2, 0x1, 0x40
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]


def _exe(hwnd: int) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        return buf.value.rsplit("\\", 1)[-1].lower()
    finally:
        kernel32.CloseHandle(handle)


def _class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def chrome_windows() -> list[int]:
    """His Chrome's browser windows, front-most first (EnumWindows is z-order)."""
    found: list[int] = []

    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd) and _class(hwnd) == "Chrome_WidgetWin_1" and _title(hwnd) and _exe(hwnd) == "chrome.exe":
            found.append(hwnd)
        return True

    user32.EnumWindows(_EnumProc(visit), 0)
    return found


def raise_window(hwnd: int) -> bool:
    """To the front and focused; True if Windows says it is now the foreground."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    else:
        user32.ShowWindow(hwnd, SW_SHOW)
    front = user32.GetForegroundWindow()
    ours = kernel32.GetCurrentThreadId()
    theirs = user32.GetWindowThreadProcessId(front, None) if front else 0
    attached = bool(theirs and theirs != ours and user32.AttachThreadInput(ours, theirs, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        # a topmost blink puts it above everything even if the focus is refused
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    finally:
        if attached:
            user32.AttachThreadInput(ours, theirs, False)
    return user32.GetForegroundWindow() == hwnd


def chrome_to_front(before: set[int] | None = None, wait_s: float = 4.0) -> None:
    """After a launch into his Chrome: its window (a new one, else the one the tab
    went to - the front-most Chrome window) is raised. Runs in the background."""

    def run():
        deadline = time.monotonic() + wait_s
        time.sleep(0.4)  # the tab lands in the profile's last-active window
        while time.monotonic() < deadline:
            windows = chrome_windows()
            target = next((w for w in windows if before is not None and w not in before), None) or (windows[0] if windows else None)
            if target:
                ok = raise_window(target)
                log.info("his Chrome to the front: %r (%s)", _title(target)[:60], "foreground" if ok else "raised, focus refused")
                return
            time.sleep(0.2)
        log.warning("his Chrome to the front: no Chrome window appeared in %.0f s", wait_s)

    threading.Thread(target=run, name="chrome-front", daemon=True).start()
