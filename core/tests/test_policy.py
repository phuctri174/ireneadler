import subprocess
import sys
from pathlib import Path

import pytest

from tools.policy import Policy, PolicyError


@pytest.fixture()
def pol(tmp_path: Path) -> Policy:
    desk = tmp_path / "Desktop"
    down = tmp_path / "Downloads"
    for d in (desk, down, desk / "irene", desk / "Projects"):
        d.mkdir(parents=True)
    (desk / "Projects" / "a.txt").write_text("hi")
    return Policy(
        roots={"desktop": desk.resolve(), "downloads": down.resolve()},
        deny=[(desk / "irene").resolve()],
        quarantine=(tmp_path / "Quarantine").resolve(),
    )


def test_resolves_inside_root(pol: Policy, tmp_path: Path):
    assert pol.resolve("desktop", "Projects/a.txt") == (tmp_path / "Desktop" / "Projects" / "a.txt").resolve()
    assert pol.resolve("Desktop", "") == pol.roots["desktop"]  # root names are case-insensitive
    assert pol.resolve("downloads", "./") == pol.roots["downloads"]


@pytest.mark.parametrize(
    "rel",
    [
        "../secret.txt",
        "Projects/../../secret.txt",
        "..\\..\\Windows",
        "C:/Windows/System32",
        "C:Windows",
        "/etc/passwd",
        "\\\\server\\share\\x",
        "//server/share/x",
        "Projects/a.txt:hidden",
        "CON",
        "nul.txt",
        "Projects/COM1",
        "evil. ",
        "trailing.",
        "a\x00b",
    ],
)
def test_rejects_escapes_and_tricks(pol: Policy, rel: str):
    with pytest.raises(PolicyError):
        pol.resolve("desktop", rel)


def test_unknown_root(pol: Policy):
    with pytest.raises(PolicyError):
        pol.resolve("documents", "x")
    with pytest.raises(PolicyError):
        pol.resolve("C:/", "x")


def test_denied_folder(pol: Policy):
    with pytest.raises(PolicyError):
        pol.resolve("desktop", "irene")
    with pytest.raises(PolicyError):
        pol.resolve("desktop", "IRENE/core/app.py")  # case-insensitive on Windows


@pytest.mark.skipif(sys.platform != "win32", reason="directory junctions are Windows")
def test_junction_out_of_root_is_refused(pol: Policy, tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "loot.txt").write_text("x")
    link = pol.roots["desktop"] / "sneaky"
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
    if made.returncode != 0:
        pytest.skip("could not create a junction")
    with pytest.raises(PolicyError):
        pol.resolve("desktop", "sneaky/loot.txt")
    # and walking never follows it
    assert not any("loot" in str(p) for p, _ in pol.walk(pol.roots["desktop"], 5))


def test_walk_skips_denied(pol: Policy):
    (pol.roots["desktop"] / "irene" / "secret.py").write_text("x")
    seen = [str(p) for p, _ in pol.walk(pol.roots["desktop"], 5)]
    assert not any("irene" in s.lower() for s in seen)


def test_real_policy_loads():
    real = Policy.load()
    assert set(real.roots) == {"desktop", "downloads"}
    assert real.quarantine is not None
    assert not any(real.quarantine.as_posix().lower().startswith(r.as_posix().lower()) for r in real.roots.values())
    assert any(d.name.lower() == "irene" for d in real.deny)
