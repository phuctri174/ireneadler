"""The publish scan (scripts/publish.py) stops anything personal from leaving: a
name however it is written, a coordinate, a path, a file type - in text, in a
file name, inside a binary. Placeholder patterns only: his real ones live in the
gitignored config/publish.yaml."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import publish  # noqa: E402

RULES = publish.Rules(Path("."), names=["Jane Q Doe"], text=["12.3456", "Some Song", "C:/Users/you"], extensions=[".npy"])


def scan(tmp_path, files: dict[str, bytes]):
    for name, data in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return publish.Scanner(RULES).scan_tree(tmp_path)


def test_a_name_is_caught_in_any_spelling(tmp_path):
    hits = scan(tmp_path, {
        "a.md": "by Jâne Q. Dóe\n".encode(),
        "b.txt": b"janeqdoe1999@example.com",
        "jane_q_doe_cv.txt": b"nothing",
    })
    assert {h.where.split(":")[0] for h in hits} == {"a.md", "b.txt", "jane_q_doe_cv.txt"}


def test_text_file_types_and_binaries(tmp_path):
    hits = scan(tmp_path, {
        "c.py": b"LAT = 12.3456\nplay('SOME SONG')\nroot = 'C:/Users/you/x'\n",
        "voice.npy": b"x",
        "img.png": b"\x00\x00\x00 12.3456",
        "fine.txt": b"12.345 and 2.3456 are not it\n",
    })
    found = sorted((h.where, h.what) for h in hits)
    assert found == [("c.py:1", "12.3456"), ("c.py:2", "Some Song"), ("c.py:3", "C:/Users/you"), ("img.png", "12.3456"), ("voice.npy", "a .npy file")]


def test_the_commit_message_is_scanned_too():
    assert publish.Scanner(RULES).scan_text("(commit message)", "Fix the Jane Q Doe bug")


def test_no_patterns_no_publish(tmp_path):
    empty = tmp_path / "publish.yaml"
    empty.write_text("public_dir: x\n", encoding="utf-8")
    try:
        publish.load(empty)
    except SystemExit as stop:
        assert "no patterns" in str(stop)
    else:
        raise AssertionError("published unscanned")


def test_the_example_config_has_the_shape():
    rules = publish.load(publish.REPO / "config" / "publish.example.yaml")
    assert rules.names and rules.text and ".npy" in rules.extensions
