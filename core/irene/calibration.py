# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Gesture calibration capture: per-frame hand metrics, labelled by step.

The HUD runs a capture profile from config/capture_profiles.json (summon,
zoom_near, zoom_mid, zoom_far, ...) and sends each recorded take here; every frame
becomes a JSON line in core/calibration/<profile>-<session>.jsonl, with the raw
landmarks so the gesture engine can be replayed offline. Input comes over the
socket, so profile, label, rep and every frame are validated before anything
touches the filesystem.

The zoom capture is split by distance - one profile each, about three minutes, run
separately - so the distance is a property of the profile rather than of every
label. load_family("zoom") merges all three, tagging each frame with the session
and the distance it was captured at.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "core" / "calibration"
PROFILES = ROOT / "config" / "capture_profiles.json"
MAX_FRAMES = 2000
MAX_LIST = 132  # hand: 21 landmarks x 3 = 63; pose: 33 x 4 = 132
_SESSION = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}$")


@lru_cache(maxsize=1)
def labels() -> dict[str, tuple[str, ...]]:
    """profile -> the step labels it may record."""
    profiles = json.loads(PROFILES.read_text(encoding="utf-8"))["profiles"]
    return {name: tuple(step["label"] for step in p["steps"]) for name, p in profiles.items()}


@lru_cache(maxsize=1)
def distances() -> dict[str, float]:
    """profile -> how far from the camera it is captured at, in metres."""
    profiles = json.loads(PROFILES.read_text(encoding="utf-8"))["profiles"]
    return {name: float(p["distanceM"]) for name, p in profiles.items() if "distanceM" in p}


def family(prefix: str) -> list[str]:
    """The profiles that make up one capture, in the order they are meant to be run:
    family("zoom") is zoom_near, zoom_mid, zoom_far - nearest first."""
    members = [n for n in labels() if n == prefix or n.startswith(prefix + "_")]
    return sorted(members, key=lambda n: (distances().get(n, 0.0), n))


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value), 5)


def _clean(frame: object) -> dict | None:
    if not isinstance(frame, dict) or len(frame) > 64:
        return None
    out = {}
    for key, value in frame.items():
        if not isinstance(key, str) or len(key) > 40:
            return None
        if isinstance(value, bool) or value is None:
            out[key] = value
        elif isinstance(value, (int, float)):
            out[key] = _number(value)
        elif isinstance(value, str) and len(value) <= 160:
            out[key] = value
        elif isinstance(value, list) and len(value) <= MAX_LIST:
            numbers = [_number(v) for v in value]
            if any(n is None for n in numbers):
                return None
            out[key] = numbers
        else:
            return None
    return out


def sessions(profile: str, directory: Path = DIR) -> list[Path]:
    """Every run of this profile, oldest first. A run never overwrites an earlier one,
    so captures accumulate: this is what the analysis reads."""
    return sorted(directory.glob(f"{profile}-*.jsonl"))


def load(profile: str, directory: Path = DIR) -> list[dict]:
    """Every frame of every session of a profile, merged, each tagged with the session
    it came from (so one can be held out for testing). Bad lines are skipped."""
    out: list[dict] = []
    for path in sessions(profile, directory):
        session = path.stem[len(profile) + 1 :]
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                frame = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(frame, dict):
                out.append({**frame, "session": frame.get("session") or session})
    return out


def incomplete(profile: str, directory: Path = DIR) -> dict[str, tuple[str, ...]]:
    """session -> the steps of `profile` it never recorded.

    A session that is missing steps was almost always captured against an older
    copy of config/capture_profiles.json - the HUD imports it once at startup, so
    a profile edited while the app is running does not reach it until a reload.
    That is silent at capture time and expensive to find later, so anything
    reading captures should say so."""
    want = set(labels().get(profile, ()))
    out: dict[str, tuple[str, ...]] = {}
    for path in sessions(profile, directory):
        session = path.stem[len(profile) + 1 :]
        got = {f.get("pose") for f in load(profile, directory) if f.get("session") == session}
        missing = tuple(sorted(want - got))
        if missing:
            out[session] = missing
    return out


def load_family(prefix: str, directory: Path = DIR) -> list[dict]:
    """Every frame of every session of every profile in a family, merged - the whole
    zoom capture in one list. Each frame keeps its profile, its session and the
    distance it was captured at, so any of the three can be held out for testing."""
    out: list[dict] = []
    for profile in family(prefix):
        distance = distances().get(profile)
        for frame in load(profile, directory):
            out.append({**frame, "distance_m": distance} if distance is not None else frame)
    return out


def write(message: dict, directory: Path = DIR) -> tuple[Path, int]:
    """Append one take's frames to its session file. Returns (path, frames written)."""
    profile = message.get("profile", "summon")
    session = str(message.get("session", ""))
    pose = message.get("pose")
    rep = message.get("rep", 0)
    frames = message.get("frames")
    if profile not in labels():
        raise ValueError(f"bad profile {profile!r}")
    if not _SESSION.match(session):
        raise ValueError(f"bad session id {session!r}")
    if pose not in labels()[profile]:
        raise ValueError(f"bad pose {pose!r} for {profile}")
    if isinstance(rep, bool) or not isinstance(rep, int) or not 0 <= rep < 20:
        raise ValueError(f"bad rep {rep!r}")
    if not isinstance(frames, list) or len(frames) > MAX_FRAMES:
        raise ValueError("frames must be a list of at most %d" % MAX_FRAMES)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{profile}-{session}.jsonl"
    written = 0
    with path.open("a", encoding="utf-8") as f:
        for i, raw in enumerate(frames):
            frame = _clean(raw)
            if frame is None:
                continue
            # a keiko frame carries its 33 body landmarks as "pose", which is also
            # the name of the step label: kept as "body" so the label survives
            if "pose" in frame:
                frame["body"] = frame.pop("pose")
            f.write(json.dumps({**frame, "profile": profile, "session": session, "pose": pose, "rep": rep, "i": i}) + "\n")
            written += 1
    return path, written
