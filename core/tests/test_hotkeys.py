"""Irene's global hotkeys never take a key another app needs (hud/HOTKEYS.md).

Ctrl+Alt+R started the corpus recorder, and it is the screenshot shortcut on his
PC; bare F6-F11 took browser and Office keys system-wide."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = (ROOT / "hud" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
DOC = (ROOT / "hud" / "HOTKEYS.md").read_text(encoding="utf-8").lower()

# known to belong to someone else: checked on this PC or documented by common apps
NEVER = {
    "ctrl+alt+r": "the screenshot tool on this PC",
    "ctrl+alt+space": "the Claude desktop app's quick entry",
    "ctrl+alt+c": "Word's (c)",
    **{f"ctrl+alt+{d}": "Docs/Word headings" for d in "12345"},
    **{f"f{n}": "a browser or Office key" for n in range(1, 13)},
}


def registered() -> list[str]:
    block = LIB[LIB.index("let global = app.global_shortcut();\n            for (name, shortcut) in [") :]
    block = block[: block.index("] {")]
    return re.findall(r'\("([^"]+)",', block)


def test_no_hotkey_takes_a_key_that_belongs_to_another_app():
    keys = registered()
    assert "ctrl+alt+i" in keys and "ctrl+alt+shift+r" in keys
    taken = {k: NEVER[k] for k in keys if k in NEVER}
    assert not taken, f"these belong to another app: {taken}"


def test_every_hotkey_is_documented():
    def doc_form(key: str) -> str:
        # as the doc writes them: "esc", and the capture digits as one range
        key = key.replace("escape", "esc")
        return re.sub(r"\+[1-5]$", "+1..5", re.sub(r"\+[67]$", "+6..7", key))

    missing = [k for k in registered() if doc_form(k) not in DOC.replace(" ", "")]
    assert not missing, f"add these to hud/HOTKEYS.md: {missing}"


def test_what_is_registered_is_what_is_handled():
    # a key registered but matched with other modifiers would never fire
    for n in range(6, 12):
        assert f"shortcut.matches(operator(), Code::F{n})" in LIB
        assert f"Modifiers::empty(), Code::F{n})" not in LIB
    assert "shortcut.matches(operator(), Code::KeyR)" in LIB
    assert "shortcut.matches(operator(), Code::KeyC)" in LIB
