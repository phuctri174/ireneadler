# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Why core stopped, written down - so a death in the night can be read the next day.

Round 13: core and the HUD both closed 17 minutes into a lecture capture with no
trace anywhere (no Python traceback, nothing in core-faults.log, nothing in the
Windows event log). This makes the next one diagnosable:

  logs/heartbeat.jsonl   every 30 s: uptime, core's RAM, system RAM, GPU memory,
                         threads, the lecture capture's state. The last line is the
                         last healthy moment.
  logs/exits.jsonl       one record per run: how it ended - an unhandled exception
                         (any thread), Ctrl+C/Break, the console window closed, log
                         off, Windows shutting down or suspending, a normal exit.
                         A run that ended with NO record was killed without warning
                         (TerminateProcess / a process-tree kill, power loss, a hard
                         native crash - faulthandler would have written that one to
                         core-faults.log): the next start writes that verdict for it,
                         with its last heartbeat, rather than leave nothing.
"""
from __future__ import annotations

import atexit
import ctypes
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

log = logging.getLogger("irene.lifeline")

LOGS = Path(__file__).resolve().parents[1] / "logs"
HEARTBEAT = LOGS / "heartbeat.jsonl"
EXITS = LOGS / "exits.jsonl"
EVERY_S = 30.0
# heartbeat file kept to about this size (the tail is what matters)
KEEP_BYTES = 2_000_000

# exits that were asked for: no auto-restart after these (core/scripts/keeper.py)
CHOSEN = ("normal exit", "ctrl+c", "ctrl+break", "console window closed", "log off", "windows shutting down",
          "windows ending the session")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _append(path: Path, record: dict) -> None:
    try:
        LOGS.mkdir(exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass


def _last(path: Path, where: Callable[[dict], bool] = lambda _r: True) -> dict | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for raw in reversed(lines):
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if where(record):
            return record
    return None


def gpu_used_gb() -> float | None:
    """The card's memory in use (nvidia-smi; a trend, not per process)."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return round(float(out.stdout.strip().splitlines()[0]) / 1024, 2)
    except Exception:  # noqa: BLE001 - a heartbeat never fails over this
        return None


class Lifeline:
    def __init__(self, name: str = "core", status: Callable[[], dict] | None = None,
                 heartbeat: Path = HEARTBEAT, exits: Path = EXITS):
        self.name = name
        self.status = status or (lambda: {})
        self.heartbeat_path = heartbeat
        self.exits_path = exits
        self.pid = os.getpid()
        # set by the keeper (scripts/keeper.py) for each core it starts: its records are
        # matched by this, not the pid (the venv's python.exe is a redirector process)
        self.run = os.environ.get("IRENE_RUN", "")
        self.started = time.time()
        self._exited = False
        self._lock = threading.Lock()
        self._stop = threading.Event()

    # ---- the record of how it ended ------------------------------------------------------

    def exit_record(self, reason: str, detail: str = "") -> None:
        """Once per run: how it ended. The first reason wins (a console close is
        followed by the interpreter's own exit)."""
        with self._lock:
            if self._exited:
                return
            self._exited = True
        record = {"at": _now(), "who": self.name, "pid": self.pid, "run": self.run, "event": "exit", "reason": reason,
                  "uptime_s": round(time.time() - self.started), "detail": detail[:2000]}
        try:
            record["state"] = self.status()
        except Exception:  # noqa: BLE001
            pass
        _append(self.exits_path, record)
        log.warning("lifeline: exiting - %s%s", reason, f" ({detail[:200]})" if detail else "")

    def previous_run(self) -> dict | None:
        """At start: how the run before this one ended. A run with heartbeats after its
        start but no exit record was killed without warning - that verdict is written
        now, with its last heartbeat."""
        start = _last(self.exits_path, lambda r: r.get("who") == self.name and r.get("event") == "start")
        if start is None:
            return None
        ended = _last(self.exits_path, lambda r: r.get("who") == self.name and r.get("event") == "exit" and r.get("pid") == start.get("pid"))
        if ended is not None:
            return ended
        beat = _last(self.heartbeat_path, lambda r: r.get("who") == self.name and r.get("pid") == start.get("pid"))
        verdict = {"at": _now(), "who": self.name, "pid": start.get("pid"), "run": start.get("run", ""), "event": "exit",
                   "reason": "unknown - no exit record",
                   "detail": "it was terminated without warning: TerminateProcess or a process-tree kill, power loss, "
                             "or a native crash (see core-faults.log). Its last heartbeat is attached.",
                   "last_heartbeat": beat, "found_at_next_start": True}
        _append(self.exits_path, verdict)
        return verdict

    # ---- starting ----------------------------------------------------------------------------

    def install(self) -> dict | None:
        before = self.previous_run()
        if before is not None:
            level = logging.INFO if before.get("reason") in CHOSEN else logging.WARNING
            log.log(level, "lifeline: the previous %s run ended: %s (at %s, up %s s)%s", self.name, before.get("reason"),
                    before.get("at"), before.get("uptime_s", "?"),
                    f"; last heartbeat {json.dumps(before.get('last_heartbeat'))}" if before.get("last_heartbeat") else "")
        _append(self.exits_path, {"at": _now(), "who": self.name, "pid": self.pid, "run": self.run, "event": "start"})
        self._hooks()
        threading.Thread(target=self._beat, name=f"{self.name}-heartbeat", daemon=True).start()
        if sys.platform == "win32":
            threading.Thread(target=self._session_window, name=f"{self.name}-session-watch", daemon=True).start()
        return before

    def _hooks(self) -> None:
        previous = sys.excepthook

        def on_exception(kind, value, tb):
            import traceback

            self.exit_record("unhandled exception", "".join(traceback.format_exception(kind, value, tb)))
            previous(kind, value, tb)

        sys.excepthook = on_exception

        def on_thread_exception(args):
            import traceback

            # a thread dying is logged, not an exit (the process may well carry on)
            log.error("lifeline: thread %s died: %s", getattr(args.thread, "name", "?"),
                      "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))[-1500:])

        threading.excepthook = on_thread_exception
        for name, sig in (("ctrl+c", signal.SIGINT), ("terminate signal", getattr(signal, "SIGTERM", None)),
                          ("ctrl+break", getattr(signal, "SIGBREAK", None))):
            if sig is None:
                continue
            try:
                default = signal.getsignal(sig)

                def handler(signum, frame, _name=name, _default=default):
                    self.exit_record(_name)
                    if callable(_default):
                        _default(signum, frame)
                    else:
                        raise SystemExit(128 + signum)

                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass  # not the main thread (tests)
        if sys.platform == "win32":
            self._console_handler()
        atexit.register(lambda: self.exit_record("normal exit"))

    def _console_handler(self) -> None:
        """The console's own events: its window closed, log off, shutdown. Windows
        gives a few seconds before it kills the process - enough for the record."""
        events = {0: "ctrl+c", 1: "ctrl+break", 2: "console window closed", 5: "log off", 6: "windows shutting down"}
        prototype = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)

        def handler(event: int) -> bool:
            self.exit_record(events.get(event, f"console event {event}"))
            return False  # let the default handling (the exit) go on

        self._console_cb = prototype(handler)  # kept alive: Windows calls it later
        try:
            ctypes.windll.kernel32.SetConsoleCtrlHandler(self._console_cb, True)
        except Exception:  # noqa: BLE001
            pass

    def _session_window(self) -> None:
        """A hidden window for what Windows tells top-level windows: the session
        ending, the PC suspending or resuming."""
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        WM_QUERYENDSESSION, WM_ENDSESSION, WM_POWERBROADCAST = 0x11, 0x16, 0x218
        PBT = {0x4: "suspending", 0x7: "resumed (suspend)", 0x12: "resumed (automatic)", 0xA: "power status changed"}
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t

        def proc(hwnd, msg, wparam, lparam):
            if msg == WM_QUERYENDSESSION:
                log.warning("lifeline: Windows asks to end the session (log off / shutdown / restart)")
                return 1
            if msg == WM_ENDSESSION and wparam:
                self.exit_record("windows ending the session")
                return 0
            if msg == WM_POWERBROADCAST:
                log.warning("lifeline: power event - %s", PBT.get(int(wparam), hex(int(wparam))))
                self._beat_once(f"power: {PBT.get(int(wparam), hex(int(wparam)))}")
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                        ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

        # 64-bit handles: every signature declared (an undeclared HINSTANCE overflows int)
        kernel32 = ctypes.windll.kernel32
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        user32.RegisterClassW.argtypes = [ctypes.c_void_p]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.GetMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.UINT]
        self._wndproc = WNDPROC(proc)
        cls = WNDCLASS()
        cls.lpfnWndProc = self._wndproc
        cls.lpszClassName = f"IreneLifeline{self.name}{self.pid}"
        cls.hInstance = kernel32.GetModuleHandleW(None)
        if not user32.RegisterClassW(ctypes.byref(cls)):
            return
        # a top-level (not message-only) hidden window: only those get the session messages
        hwnd = user32.CreateWindowExW(0, cls.lpszClassName, "Irene lifeline", 0, 0, 0, 0, 0, None, None, cls.hInstance, None)
        if not hwnd:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    # ---- the heartbeat ----------------------------------------------------------------------

    def sample(self, note: str = "") -> dict:
        import psutil

        me = psutil.Process(self.pid)
        vm = psutil.virtual_memory()
        record = {"at": _now(), "who": self.name, "pid": self.pid, "uptime_s": round(time.time() - self.started),
                  "rss_gb": round(me.memory_info().rss / 1e9, 2), "ram_used_gb": round((vm.total - vm.available) / 1e9, 2),
                  "ram_total_gb": round(vm.total / 1e9, 1), "gpu_used_gb": gpu_used_gb(), "threads": me.num_threads()}
        if note:
            record["note"] = note
        try:
            record["state"] = self.status()
        except Exception:  # noqa: BLE001
            pass
        return record

    def _beat_once(self, note: str = "") -> None:
        try:
            _append(self.heartbeat_path, self.sample(note))
            if self.heartbeat_path.stat().st_size > KEEP_BYTES:
                lines = self.heartbeat_path.read_text(encoding="utf-8").splitlines()
                self.heartbeat_path.write_text("\n".join(lines[len(lines) // 2:]) + "\n", encoding="utf-8")
        except Exception:  # noqa: BLE001 - never take core down
            log.exception("lifeline: heartbeat failed")

    def _beat(self) -> None:
        while True:
            self._beat_once()
            if self._stop.wait(EVERY_S):
                return
