"""A dark wake holds her boot until the displays have really been on: Windows'
"on" (his OLED says it seconds before an image), every monitor back on the
desktop, and nothing changing for the whole hold - any drop starts it again.
Round 9: with a 3 s hold after Windows' word, the boot still ran into dark panels."""
import asyncio
import time

from irene.app import power_tool as power  # tools/power.py, as core imports it


class _Bridge:
    def __init__(self):
        self.sent = []
        self.current_state = "listening"

    async def send(self, m):
        self.sent.append((time.monotonic(), m))

    def send_threadsafe(self, m):
        # Core() hangs a global hook on this (his Chrome opening) - later tests call it
        self.sent.append((time.monotonic(), m))


class _Watch:
    """Windows' display state on a script: (seconds after the wake, on?, monitors)."""

    def __init__(self, script):
        self.script = script
        self.start = time.monotonic()
        self.working = True
        self.changed_at = self.start
        self._last = None

    def _now(self):
        t = time.monotonic() - self.start
        state = next((s for s in reversed(self.script) if s[0] <= t), (0, False, 1))
        if state != self._last:
            self._last = state
            self.changed_at = time.monotonic()
        return state

    def wait_on(self, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self._now()[1]:
                return True
            time.sleep(0.01)
        return False

    def is_on(self):
        return self._now()[1]

    def monitors(self):
        return self._now()[2]


def _wake(monkeypatch, script, delay=0.4):
    from irene.app import Core

    core = Core()
    core.bridge = _Bridge()
    core.dark = True
    core._dark_since = time.monotonic()
    core._dark_monitors = 2
    watch = _Watch(script)
    monkeypatch.setattr(power, "display_watch", lambda: watch)
    monkeypatch.setattr(power, "displays_on", lambda: None)
    monkeypatch.setattr(power, "monitors", watch.monitors)
    monkeypatch.setattr(power, "wake_delay_s", lambda: delay)
    start = time.monotonic()
    asyncio.run(core.exit_dark("a wake phrase"))
    return time.monotonic() - start, core.bridge.sent


def test_the_default_hold_is_six_seconds():
    assert power.WAKE_DELAY_DEFAULT_S == 6.0
    assert power.wake_delay_s() >= 6.0


def test_steady_displays_boot_after_the_full_hold(monkeypatch):
    took, sent = _wake(monkeypatch, [(0.0, False, 1), (0.1, True, 2)])
    assert 0.45 <= took < 0.9, took
    # the warm-up surfaces went up first, and the counter starts at Windows' "on"
    warm = [m for _, m in sent if m.get("type") == "warmup"]
    assert warm[0]["onAt"] is None and warm[1]["onAt"]


def test_a_drop_or_a_missing_monitor_restarts_the_hold(monkeypatch):
    # on at 0.1, the second monitor rejoins only at 0.35, then the displays blink
    # off at 0.5 and back at 0.6: the hold has to run 0.4 s from 0.6
    took, sent = _wake(monkeypatch, [(0.0, False, 1), (0.1, True, 1), (0.35, True, 2), (0.5, False, 2), (0.6, True, 2)])
    assert took >= 0.95, took
    # the counter is never reset: one "on" stamp, from the first report
    stamps = [m["onAt"] for _, m in sent if m.get("type") == "warmup" and m.get("onAt")]
    assert len(stamps) == 1
