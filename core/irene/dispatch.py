# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Who answers his message: a strike calibration, shiai, keiko, study mode,
rock-paper-scissors, the chess game, a pre-rendered quick line, or the model
(Conversation.respond).

One order, used by the app (on_command) and by the evals (evals/harness.py), so an
eval never scores the model on a message the app would have answered another way.
Each check is a callable asked with the words, in turn, so the app's live state (the
game on, the quick lines rendered) and an eval's (none of it) go through the same
order.

While a mode is on (`mode`, modes.py) his orders still come first - the lock is for
her, never for him:
  EXIT      "cancel", "quit this", "stop the match": the mode on ends
  SWITCH    another mode's start ("let's do shiai" mid-chess), or an exit and then
            something else ("cancel the chess match then learn tenouchi"): the mode
            on ends, then the rest is answered as if nothing had been on
Its own commands are still its own. An explicit request for something the lock
refuses (`blocked`: research, a drawing, the panel) is BLOCKED - her brush-off, in
code. Everything else goes on to a quick line or the model, which then has only the
quiet tools.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import modes

STRIKES, SHIAI, KEIKO, STUDY, RPS, CHESS, QUICK, MODEL = "strikes", "shiai", "keiko", "study", "rps", "chess", "quick", "model"
BLOCKED, SWITCH, EXIT = "blocked", "switch", "exit"
CLAIMS = (STRIKES, SHIAI, KEIKO, STUDY, RPS, CHESS)

# a mode's claim: (his words, is that mode the one on?) -> what it matched, or None
Claim = Callable[[str, bool], object]


@dataclass(frozen=True)
class Switch:
    """Out of `left`, then `who` answers `said` with what it matched (`found`)."""

    left: str
    who: str
    found: object
    said: str


def _claimed(said: str, claims: dict[str, Claim], mode: str | None) -> tuple[str, object] | None:
    for who in CLAIMS:
        claim = claims.get(who)
        found = claim(said, who == mode) if claim else None
        if found is None:
            continue
        if mode is not None and who != mode and not modes.may_switch(who, said):
            continue  # named, not ordered (trash talk): not a switch
        return who, found
    return None


def _after(said: str, claims: dict[str, Claim], quick: Callable[[str], object]) -> tuple[str, object]:
    """Who answers `said` once no mode is on."""
    found = _claimed(said, claims, None)
    if found is not None:
        return found
    line = quick(said)
    return (QUICK, line) if line is not None else (MODEL, None)


def route(said: str, claims: dict[str, Claim], quick: Callable[[str], object] = lambda s: None,
          mode: str | None = None, blocked: Callable[[str], object] = lambda s: None) -> tuple[str, object]:
    """(who, what they matched) for his words `said`: the first of the mode claims
    (CLAIMS order) to take them, then a quick line, else the model. With a mode on
    (`mode`): his exit is (EXIT, mode); another mode's start, or an exit followed by
    more, is (SWITCH, Switch); an explicit request the lock refuses is (BLOCKED, what)."""
    if mode is not None:
        order = modes.order(said, mode)
        if order is not None:
            if order.rest is None:
                return EXIT, mode
            # a bare "stop and ..." leaves only for another mode; a named exit for anything
            then = _claimed(order.rest, claims, None) or ((MODEL, None) if modes.starts_lecture(order.rest) else None)
            if then is not None or order.named:
                who, found = then or _after(order.rest, claims, quick)
                return SWITCH, Switch(mode, who, found, order.rest)
    found = _claimed(said, claims, mode)
    if found is not None:
        who, what = found
        if mode is not None and who != mode:
            return SWITCH, Switch(mode, who, what, said)
        return who, what
    if mode is not None:
        if mode != "lecture" and modes.starts_lecture(said):
            # a lecture capture is a mode too: his order ends this one (the model's
            # fast path starts it, once nothing holds the display)
            return SWITCH, Switch(mode, MODEL, None, said)
        refused = blocked(said)
        if refused is not None:
            return BLOCKED, refused
    line = quick(said)
    if line is not None:
        return QUICK, line
    return MODEL, None
