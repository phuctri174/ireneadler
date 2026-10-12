"""Tests, evals and scripts must never synthesise OS-level input (CLAUDE.md).

Global shortcuts and keystrokes reach whichever app owns them; a test once typed
into another app's quick-entry box. The UI is driven only through the -Dev hooks.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEST_DIRS = ["core/tests", "core/evals", "core/scripts", "hud/tests"]
FORBIDDEN = re.compile(
    r"keybd_event|SendInput|mouse_event|pyautogui|pynput|SendKeys|sendKeys|robotjs|@nut-tree|"
    r"keyboard\.(press|write|send)|SetCursorPos"
)


def test_no_os_input_in_tests_evals_or_scripts():
    offenders = []
    for folder in TEST_DIRS:
        for path in (REPO / folder).rglob("*"):
            if path.suffix not in {".py", ".mjs", ".js", ".ts", ".ps1"} or path.name == Path(__file__).name:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if FORBIDDEN.search(line):
                    offenders.append(f"{path.relative_to(REPO)}:{number}: {line.strip()}")
    assert not offenders, "OS-level input in test code:\n" + "\n".join(offenders)
