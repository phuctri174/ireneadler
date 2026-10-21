# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Personal config: config/<name> holds his own data (location, Chrome account,
music path, names) and is gitignored; config/<stem>.example<suffix> is committed.
A fresh clone has only the example, so every loader resolves through here and
runs on it until a real copy exists."""
from __future__ import annotations

import os
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "config"


def personal(name: str) -> Path:
    """config/<name> if it exists, else its committed example. With
    IRENE_EXAMPLE_CONFIG=1 (the test suite sets it) always the example: tests never
    read his own data, and pass the same on a fresh clone."""
    own = CONFIG / name
    if own.exists() and os.environ.get("IRENE_EXAMPLE_CONFIG") != "1":
        return own
    path = Path(name)
    return CONFIG / f"{path.stem}.example{path.suffix}"
