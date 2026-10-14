"""Screens-off mode: the monitors dark, the PC awake, Irene still listening.

Real Windows sleep can't be woken by voice - the CPU is powered down and nothing
listens (CLAUDE.md). This is the achievable version: the displays are switched
off (SC_MONITORPOWER) while the SYSTEM is kept awake (SetThreadExecutionState:
system required, display allowed to sleep), so the mic and the wake phrase keep
running. A wake phrase lights the displays again and brings her up.

Off unless config/power.yaml enables it. Never from a test or a script
(tools/sandbox.py): only his own commands - his voice, his HUD's hotkey.
"""
from __future__ import annotations

import ctypes
import logging
import queue
import threading
import time
from ctypes import wintypes
from pathlib import Path

import yaml

from . import sandbox
from .registry import ToolContext, ToolError, tool

log = logging.getLogger("irene.tools")

CONFIG = Path(__file__).resolve().parents[1] / "config" / "power.yaml"

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
HWND_BROADCAST = 0xFFFF
WM_SYSCOMMAND = 0x0112
SC_MONITORPOWER = 0xF170
MONITOR_OFF = 2
MONITOR_ON = -1

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001


class _MouseInput(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _Input(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("mi", _MouseInput)]  # 40 bytes on x64, as SendInput expects


class _LastInput(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_ms() -> int:
    """How long since his last mouse move or key press (GetLastInputInfo)."""
    info = _LastInput(ctypes.sizeof(_LastInput), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0
    return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class _PowerSetting(ctypes.Structure):
    _fields_ = [("PowerSetting", _GUID), ("DataLength", wintypes.DWORD), ("Data", ctypes.c_ubyte * 4)]


class DisplayWatch:
    """What Windows says about the displays (GUID_CONSOLE_DISPLAY_STATE: 0 off,
    1 on, 2 dimmed - "off" only when every display is off), from a hidden window's
    power notifications on its own thread. Proved live: OFF 0.7 s after the
    request, ON 0.3 s after a key press.

    That "on" is Windows' word, not the panel's: his OLED reports on seconds
    before it shows an image. So the watch also follows the display topology -
    WM_DISPLAYCHANGE and the monitor count (a DisplayPort monitor waking drops off
    and rejoins the desktop) - and stamps every change (changed_at), so a wake can
    wait until nothing has moved for the whole hold."""

    # {6fe69556-704a-47a0-8f24-c28d936fda47}
    GUID = _GUID(0x6FE69556, 0x704A, 0x47A0, (ctypes.c_ubyte * 8)(0x8F, 0x24, 0xC2, 0x8D, 0x93, 0x6F, 0xDA, 0x47))
    NAMES = {0: "off", 1: "on", 2: "dimmed"}

    def __init__(self):
        self.state: str | None = None
        self.changed_at = time.monotonic()
        self.working = False
        self._on = threading.Event()
        threading.Thread(target=self._run, name="display-watch", daemon=True).start()

    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32")
        kernel32 = ctypes.WinDLL("kernel32")
        proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.RegisterPowerSettingNotification.argtypes = [wintypes.HANDLE, ctypes.POINTER(_GUID), wintypes.DWORD]
        user32.RegisterPowerSettingNotification.restype = wintypes.HANDLE
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        def proc(hwnd, msg, wparam, lparam):
            if msg == 0x0218 and wparam == 0x8013:  # WM_POWERBROADCAST, PBT_POWERSETTINGCHANGE
                value = ctypes.cast(lparam, ctypes.POINTER(_PowerSetting)).contents.Data[0]
                self.state = self.NAMES.get(value, str(value))
                self.changed_at = time.monotonic()
                log.info("screens-off: Windows says the displays are %s (%d monitors on the desktop)", self.state.upper(), monitors())
                (self._on.set if value == 1 else self._on.clear)()
                return 1
            if msg == 0x007E:  # WM_DISPLAYCHANGE: a monitor joined, left or changed mode
                self.changed_at = time.monotonic()
                log.info("screens-off: display change - %d monitors on the desktop, %dx%d", monitors(), lparam & 0xFFFF, (lparam >> 16) & 0xFFFF)
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._proc = proc_type(proc)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", proc_type), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

        cls = WNDCLASS(0, self._proc, 0, 0, kernel32.GetModuleHandleW(None), None, None, None, None, "IreneDisplayState")
        user32.RegisterClassW(ctypes.byref(cls))
        hwnd = user32.CreateWindowExW(0, "IreneDisplayState", "display state", 0, 0, 0, 0, 0, None, None, cls.hInstance, None)
        if not hwnd or not user32.RegisterPowerSettingNotification(hwnd, ctypes.byref(self.GUID), 0):
            log.warning("screens-off: can't watch the display state - waking falls back to a fixed wait")
            return
        self.working = True
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def wait_on(self, timeout: float) -> bool:
        """Block until Windows reports the displays ON (True), or the timeout."""
        return self._on.wait(timeout)

    def is_on(self) -> bool:
        return self._on.is_set()


def monitors() -> int:
    """How many monitors are on the desktop right now (SM_CMONITORS)."""
    try:
        return int(ctypes.windll.user32.GetSystemMetrics(80))
    except (AttributeError, OSError):
        return 0


_watch: DisplayWatch | None = None


def display_watch() -> DisplayWatch:
    global _watch
    if _watch is None:
        _watch = DisplayWatch()
    return _watch


WAKE_DELAY_DEFAULT_S = 6.0


def wake_delay_s() -> float:
    """After a dark wake: how long the displays must have been on - unbroken, no
    monitor joining or leaving - before she appears."""
    try:
        cfg = (yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}).get("screens_off") or {}
        return float(cfg.get("wake_delay_s", WAKE_DELAY_DEFAULT_S))
    except (OSError, ValueError):
        return WAKE_DELAY_DEFAULT_S


def enabled() -> bool:
    try:
        return bool(((yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}).get("screens_off") or {}).get("enabled", False))
    except OSError:
        return False


class _Keeper:
    """SetThreadExecutionState lasts for the thread that set it: one long-lived
    thread holds it, and is told what to hold."""

    def __init__(self):
        self._jobs: queue.Queue = queue.Queue()
        threading.Thread(target=self._run, name="power-keeper", daemon=True).start()

    def _run(self) -> None:
        kernel32 = ctypes.WinDLL("kernel32")
        while True:
            flags = self._jobs.get()
            kernel32.SetThreadExecutionState(ctypes.c_uint32(flags))

    def hold(self, flags: int) -> None:
        self._jobs.put(flags)


_keeper: _Keeper | None = None


def _keep(flags: int) -> None:
    global _keeper
    if _keeper is None:
        _keeper = _Keeper()
    _keeper.hold(flags)


# who needs the system awake right now: "dark" (screens-off mode), "lecture" (a
# capture running - he may be asleep, the PC must not be). Any one keeps it up.
_AWAKE: set[str] = set()


def stay_awake(reason: str, on: bool) -> None:
    """Hold (or release) the system awake for `reason`; the displays may still sleep."""
    (_AWAKE.add if on else _AWAKE.discard)(reason)
    _keep(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if _AWAKE else 0))
    log.info("system kept awake for: %s", ", ".join(sorted(_AWAKE)) or "nothing - normal sleep allowed")


def awake_reasons() -> set[str]:
    return set(_AWAKE)


def displays_off() -> None:
    """The PC stays awake (system required), the monitors go dark."""
    stay_awake("dark", True)
    ctypes.windll.user32.PostMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, MONITOR_OFF)
    log.info("screens off: monitors dark, system kept awake")


def displays_on() -> None:
    """Light the monitors again, and let the system sleep normally again. Windows
    wakes displays on input: a zero-distance mouse nudge (moves nothing) plus the
    display-required flag and the monitor-power message."""
    _keep(ES_DISPLAY_REQUIRED)
    # the system may sleep again - unless something else (a lecture) still holds it
    stay_awake("dark", False)
    ctypes.windll.user32.PostMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, MONITOR_ON)
    nudge = _Input(type=INPUT_MOUSE, mi=_MouseInput(0, 0, 0, MOUSEEVENTF_MOVE, 0, 0))
    ctypes.windll.user32.SendInput(1, ctypes.byref(nudge), ctypes.sizeof(_Input))
    log.info("screens on: monitors lit")


def set_enabled(on: bool) -> None:
    """Turn screens-off mode on or off in her settings, keeping the file's notes."""
    import re

    text = CONFIG.read_text(encoding="utf-8")
    text, n = re.subn(r"(?m)^(\s*enabled:\s*)(true|false)\b", lambda m: m.group(1) + ("true" if on else "false"), text, count=1)
    if not n:
        text += f"\nscreens_off:\n  enabled: {'true' if on else 'false'}\n"
    CONFIG.write_text(text, encoding="utf-8")
    log.info("screens-off mode %s in config/power.yaml", "enabled" if on else "disabled")


@tool(
    "enable_screens_off",
    "Turn ON screens-off mode in her settings (config/power.yaml). Only when he asks to "
    "enable the mode itself - never for 'screens off' (screens_off always works).",
    # he authorised screens-off permanently (Round 11): nothing about it asks first
    confirm=False,
    readonly=False,
    cue="chip",
)
async def enable_screens_off(_ctx: ToolContext) -> str:
    if sandbox.launch_blocked():
        return "screens-off mode would be turned on (test - nothing changed)"
    set_enabled(True)
    return "screens-off mode is now ON in her settings. Now call screens_off to switch the screens off, as he asked."


@tool(
    "screens_off",
    "Turn his monitors off while the PC stays awake and Irene keeps listening - 'Irene, screens off', "
    "'turn the screens off', 'kill the monitors'. A wake phrase lights them again.",
    readonly=False,
    cue="chip",
)
async def screens_off(ctx: ToolContext) -> str:
    if not enabled():
        # he authorised screens-off permanently (Round 11): never a question - the
        # setting is turned on, logged, and on with it
        if sandbox.launch_blocked():
            return "screens off (test - nothing switched off)"
        log.info("screens-off mode was off in config/power.yaml - turned on (he authorised it permanently)")
        set_enabled(True)
    if sandbox.launch_blocked():
        log.info("test: screens off logged, not done")
        return "screens off (test - nothing switched off)"
    await ctx.screens_off()
    return "the screens go dark in a moment; she keeps listening for a wake phrase"
