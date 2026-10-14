r"""Publish: HEAD of this repository to the public one, never anything personal.

  1. export HEAD (git archive: tracked files only - never the working tree, never
     an ignored file) into a temporary folder
  2. scan the export against config/publish.yaml (gitignored - the patterns are
     his name and his home): every file's text, every file name, and the commit
     message about to be written. One match and nothing is published.
  3. only then: the public clone's files are replaced by the export, committed as
     one commit ("Irene as of <sha>", with the local subjects since the last
     publish), and pushed
  4. the local tag `published` moves to HEAD: the next publish lists from there

The public history is one commit per publish on top of the first squashed one;
the local history (and its messages) never leaves this machine.

Run (from core/):  .venv\Scripts\python scripts\publish.py            scan, commit, push
                   .venv\Scripts\python scripts\publish.py --dry-run  scan and show what would change
"""
from __future__ import annotations

import argparse
import io
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "config" / "publish.yaml"
TAG = "published"
# the first publish (2026-10-12) was this commit's tree, squashed
FIRST = "9e863cc"


@dataclass
class Rules:
    public_dir: Path
    branch: str = "main"
    names: list[str] = field(default_factory=list)
    text: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)


def load(path: Path = CONFIG) -> Rules:
    if not path.exists():
        sys.exit(f"no {path.relative_to(REPO)}: copy config/publish.example.yaml and fill in what must never be published")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules = Rules(
        (REPO / raw.get("public_dir", "../ireneadler")).resolve(),
        raw.get("branch", "main"),
        [str(n) for n in raw.get("names") or []],
        [str(t) for t in raw.get("text") or []],
        [str(e).lower() for e in raw.get("extensions") or []],
    )
    if not rules.names and not rules.text:
        sys.exit(f"{path.name} has no patterns: refusing to publish unscanned")
    return rules


def fold(text: str) -> str:
    """Lowercase, accents off ("Dóe" is "doe"; đ is d)."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c)).replace("đ", "d")


def squash(text: str) -> str:
    """Folded, letters and digits only: "Jane_Q Doe" and "janeqdoe@" meet."""
    return re.sub(r"[^a-z0-9]", "", fold(text))


@dataclass
class Hit:
    where: str
    what: str
    line: str = ""


class Scanner:
    def __init__(self, rules: Rules):
        self.rules = rules
        self.names = [(n, squash(n)) for n in rules.names if squash(n)]
        self.text = [(t, fold(t)) for t in rules.text if t]

    def scan_text(self, where: str, text: str) -> list[Hit]:
        hits = []
        for number, line in enumerate(text.splitlines(), 1):
            folded = fold(line)
            squashed = squash(line)
            for raw, pattern in self.text:
                if pattern in folded:
                    hits.append(Hit(f"{where}:{number}", raw, line.strip()[:120]))
            for raw, pattern in self.names:
                if pattern in squashed:
                    hits.append(Hit(f"{where}:{number}", raw, line.strip()[:120]))
        return hits

    def scan_tree(self, root: Path) -> list[Hit]:
        hits = []
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            rel = path.relative_to(root).as_posix()
            if path.suffix.lower() in self.rules.extensions:
                hits.append(Hit(rel, f"a {path.suffix} file"))
            hits += [Hit(rel, h.what, "(file name)") for h in self.scan_text(rel, rel)]
            data = path.read_bytes()
            if b"\0" in data[:8192]:
                # binary (images, models): its name is checked; its bytes for the
                # plain-text patterns, the way they would show in a hex dump
                text = data.decode("latin-1")
                hits += [Hit(rel, h.what, "(inside a binary file)") for h in self.scan_text(rel, text)]
                continue
            hits += self.scan_text(rel, data.decode("utf-8", errors="replace"))
        return hits


def git(*args: str, cwd: Path = REPO, check: bool = True) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if check and out.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed in {cwd}:\n{out.stderr.strip()}")
    return out.stdout


def export(dest: Path) -> None:
    """HEAD's tracked files, as git has them - nothing ignored, nothing uncommitted."""
    data = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=REPO, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(dest, filter="data")


def since_last() -> tuple[str, list[str]]:
    """(the last published commit, the local subjects since)."""
    base = git("rev-parse", "--verify", "--quiet", TAG, check=False).strip() or git("rev-parse", FIRST).strip()
    subjects = [s for s in git("log", "--format=%s", "--reverse", f"{base}..HEAD").splitlines() if s.strip()]
    return base, subjects


def message(head: str, subjects: list[str]) -> str:
    lines = [f"Irene as of {head[:7]}", ""]
    if subjects:
        lines.append("Changes since the last publish:")
        lines += [f"- {s}" for s in subjects]
    return "\n".join(lines) + "\n"


def sync(src: Path, public: Path) -> None:
    """The public clone's files become exactly the export's (its .git untouched)."""
    for item in public.iterdir():
        if item.name == ".git":
            continue
        shutil.rmtree(item) if item.is_dir() else item.unlink()
    for item in src.iterdir():
        target = public / item.name
        shutil.copytree(item, target) if item.is_dir() else shutil.copy2(item, target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="scan and show the change; commit and push nothing")
    args = parser.parse_args()
    rules = load()
    public = rules.public_dir
    if not (public / ".git").exists():
        sys.exit(f"{public} is not the public clone (no .git)")
    if git("status", "--porcelain", cwd=public).strip():
        sys.exit(f"{public} has uncommitted changes: resolve them first")
    dirty = git("status", "--porcelain", "--untracked-files=no").strip()
    if dirty:
        print("note: uncommitted local changes are NOT published - only HEAD is:\n" + dirty)

    head = git("rev-parse", "HEAD").strip()
    _, subjects = since_last()
    msg = message(head, subjects)
    scanner = Scanner(rules)
    with tempfile.TemporaryDirectory(prefix="irene-publish-") as tmp:
        out = Path(tmp) / "export"
        out.mkdir()
        export(out)
        hits = scanner.scan_tree(out) + scanner.scan_text("(commit message)", msg)
        files = sum(1 for p in out.rglob("*") if p.is_file())
        if hits:
            print(f"REFUSED: {len(hits)} match(es) in the export of {head[:7]} - nothing was published.")
            for h in hits:
                print(f"  {h.where}: {h.what!r}  {h.line}")
            return 1
        print(f"scan: {files} files and the commit message, {len(scanner.names)} name and {len(scanner.text)} text patterns, "
              f"{len(rules.extensions)} file types - clean")
        if args.dry_run:
            # what would change: copied into the (clean, checked above) public clone,
            # listed, and put back exactly as it was
            sync(out, public)
            print(git("status", "--short", cwd=public) or "(no change)")
            git("checkout", "--", ".", cwd=public)
            git("clean", "-fdq", cwd=public)
            print("dry run: public clone restored; nothing committed or pushed\n\n" + msg)
            return 0
        sync(out, public)
    git("add", "-A", cwd=public)
    if not git("status", "--porcelain", cwd=public).strip():
        print("the public repository already matches HEAD - nothing to publish")
        git("tag", "-f", TAG, head)
        return 0
    stat = git("diff", "--cached", "--shortstat", cwd=public).strip()
    subprocess.run(["git", "commit", "-q", "-F", "-"], cwd=public, input=msg, text=True, encoding="utf-8", check=True)
    pushed = subprocess.run(["git", "push", "origin", rules.branch], cwd=public, capture_output=True, text=True, encoding="utf-8")
    if pushed.returncode != 0:
        print(f"committed in {public} but the push failed - run `git push` there:\n{pushed.stderr.strip()}")
        return 1
    git("tag", "-f", TAG, head)
    remote = git("remote", "get-url", "origin", cwd=public).strip()
    print(f"published {head[:7]} -> {remote} ({rules.branch}): {stat}")
    print(git("log", "-1", "--format=%h %s", cwd=public).strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
