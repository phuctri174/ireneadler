"""The file whitelist: config/policy.yaml, enforced here.

Tools never take a raw path. The model names a root ("desktop", "downloads") and a
path relative to it; resolve() turns that into a real path or refuses. Refused:
absolute paths, drive letters, UNC paths, "..", NTFS alternate streams (":"),
reserved device names (CON, NUL, COM1...), names Windows would silently rewrite
(trailing dots/spaces), anything a link or junction leads outside its root, and
anything under a denied path.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .registry import ToolError

CONFIG = Path(__file__).resolve().parents[1] / "config" / "policy.yaml"
_RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.I)


class PolicyError(ToolError):
    """A path the policy does not allow. The message is safe to show the model."""


def _norm(p: Path) -> str:
    return os.path.normcase(str(p))


def _inside(child: Path, parent: Path) -> bool:
    c, p = _norm(child), _norm(parent)
    try:
        return os.path.commonpath([c, p]) == p
    except ValueError:  # different drives
        return False


@dataclass
class Policy:
    roots: dict[str, Path]
    deny: list[Path] = field(default_factory=list)
    quarantine: Path | None = None
    limits: dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = CONFIG) -> "Policy":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        expand = lambda p: Path(os.path.expanduser(str(p))).resolve()  # noqa: E731
        return cls(
            roots={str(k).lower(): expand(v) for k, v in (data.get("roots") or {}).items()},
            deny=[expand(p) for p in data.get("deny") or []],
            quarantine=expand(data["quarantine"]) if data.get("quarantine") else None,
            limits={k: int(v) for k, v in (data.get("limits") or {}).items()},
        )

    def limit(self, name: str, default: int) -> int:
        return self.limits.get(name, default)

    def root(self, name: str) -> Path:
        key = str(name or "").strip().lower()
        if key not in self.roots:
            raise PolicyError(f"unknown root {name!r}; allowed: {', '.join(sorted(self.roots))}")
        return self.roots[key]

    def denied(self, path: Path) -> bool:
        return any(_inside(path, d) for d in self.deny)

    def resolve(self, root: str, rel: str = "") -> Path:
        """(root name, relative path) -> the real path, or PolicyError."""
        base = self.root(root)
        raw = str(rel or "").strip().replace("\\", "/")
        if "\x00" in raw:
            raise PolicyError("invalid path")
        if raw.startswith("/") or raw.startswith("//") or re.match(r"^[a-zA-Z]:", raw):
            raise PolicyError("paths must be relative to the root, not absolute")
        parts = [p for p in raw.split("/") if p not in ("", ".")]
        for part in parts:
            if part == "..":
                raise PolicyError("'..' is not allowed in paths")
            if ":" in part:
                raise PolicyError("':' is not allowed in paths")
            if _RESERVED.match(part):
                raise PolicyError(f"{part!r} is a reserved device name")
            if part != part.rstrip(". "):
                raise PolicyError(f"{part!r} ends in a dot or space")
        candidate = base.joinpath(*parts)
        real = candidate.resolve(strict=False)  # follows links and junctions
        if not _inside(real, base):
            raise PolicyError("that path leads outside the allowed folders")
        if self.denied(real):
            raise PolicyError("that folder is off-limits")
        return real

    def display(self, path: Path) -> str:
        """A real path as the model and user see it: root/relative."""
        for name, base in self.roots.items():
            if _inside(path, base):
                rel = os.path.relpath(path, base).replace("\\", "/")
                return name if rel == "." else f"{name}/{rel}"
        return path.name

    def walk(self, start: Path, depth: int):
        """Files and folders under `start`, depth-limited, never into denied
        paths and never following links or junctions."""
        stack = [(start, 0)]
        while stack:
            folder, level = stack.pop()
            try:
                entries = list(os.scandir(folder))
            except OSError:
                continue
            for entry in entries:
                path = Path(entry.path)
                if self.denied(path) or entry.is_symlink() or _is_junction(entry):
                    continue
                yield path, entry
                if entry.is_dir(follow_symlinks=False) and level + 1 < depth:
                    stack.append((path, level + 1))


def _is_junction(entry: os.DirEntry) -> bool:
    try:
        return entry.is_junction()  # Python 3.12+
    except AttributeError:
        return False


_policy: Policy | None = None


def policy() -> Policy:
    global _policy
    if _policy is None:
        _policy = Policy.load()
    return _policy


def set_policy(value: Policy | None) -> None:
    """Tests point the tools at temporary roots."""
    global _policy
    _policy = value
