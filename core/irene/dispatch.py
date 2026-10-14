"""Who answers his message: keiko, the chess game, a pre-rendered quick line, or
the model (Conversation.respond).

One order, used by the app (on_command) and by the evals (evals/harness.py), so an
eval never scores the model on a message the app would have answered another way.
Each check is a callable, asked in turn, so the app's live state (the game on, the
quick lines rendered) and an eval's (none of it) go through the same order.
"""
from __future__ import annotations

from typing import Callable

KEIKO, CHESS, QUICK, MODEL = "keiko", "chess", "quick", "model"


def route(keiko: Callable[[], object], chess: Callable[[], object], quick: Callable[[], object]) -> tuple[str, object]:
    """(who, what they matched): the first of keiko, chess, quick to claim the
    message, else the model."""
    for who, claims in ((KEIKO, keiko), (CHESS, chess), (QUICK, quick)):
        found = claims()
        if found is not None:
            return who, found
    return MODEL, None
