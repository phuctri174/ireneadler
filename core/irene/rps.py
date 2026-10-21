# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Rock-paper-scissors with Irene - his hand on the camera, her throw from a dice roll.

The round, in order (app.py runs it):

  1. COMMIT    her throw is drawn (os-level randomness), and BEFORE his hand is read it
               is written down: core.log and core/data/games/rps-<session>.jsonl get the
               round, the time to the millisecond, and sha256(throw:nonce). The panel
               shows that hash during the count, so on camera the commitment is visible
               before the shoot - and anyone can check it against the reveal.
  2. COUNT     "Rock... paper... scissors... shoot!" - one pre-rendered clip; a mark on
               the first sample of "shoot" (as it reaches the speaker) tells the HUD
               the instant (game_shoot), and the HUD sends back the camera's frames
               around it (game_frames)
  3. READ      his throw from a FIXED window of those frames (WINDOW_MS after the shoot
               instant, chosen by the trainer from his captures) - not continuously,
               not a hold timer: the frames in the window are classified and averaged
  4. REVEAL    both throws at once - the panel and her line - and the score

The classifier (rps_model.json, written by core/scripts/rps_train.py) is a softmax
regression over hand-shape features below - trained on his guided captures, judged
on a whole session it never saw, and shipped only if it clears the bar and beats the
finger-count baseline. No model file: the game is off and she says why.

While a game runs the HUD is in game mode (hud/src/tracking/gameMode.ts): every
normal gesture is suspended. "Exit game" or a timeout ends it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml

from . import rps_stakes
from .rps_stakes import Stakes

log = logging.getLogger("irene.rps")

ROOT = Path(__file__).resolve().parents[2]
MODEL = Path(__file__).resolve().parent / "rps_model.json"
GAMES = ROOT / "core" / "data" / "games"
CONFIG = ROOT / "config" / "rps.yaml"

THROWS = ("rock", "paper", "scissors")
BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
VERB = {("rock", "scissors"): "rock blunts scissors", ("paper", "rock"): "paper covers rock", ("scissors", "paper"): "scissors cut paper"}
# the HUD sends this much around the shoot instant; the classifier uses only its window
SEND_BEFORE_MS = 600
SEND_AFTER_MS = 1400
# nothing from him for this long and the game ends by itself (the HUD's own deadline is longer)
IDLE_END_S = 90.0
HUD_MODE_MS = 150_000
# she has read the stakes back (or asked for them) and waits this long for his answer
AWAIT_S = 90.0


def load_config(path: Path = CONFIG) -> dict:
    """config/rps.yaml - the confidence bars (plain and with stakes on the game)."""
    out = {"min_confidence": None, "min_confidence_staked": 0.85}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        out.update({k: raw[k] for k in out if k in raw})
    except (OSError, yaml.YAMLError) as e:
        log.warning("rps: %s unreadable (%s) - default bars", path, e)
    return out


# ---- his hand as numbers ------------------------------------------------------------------------

FINGERS = {"thumb": (1, 2, 3, 4), "index": (5, 6, 7, 8), "middle": (9, 10, 11, 12), "ring": (13, 14, 15, 16), "pinky": (17, 18, 19, 20)}
FEATURE_NAMES: list[str] = []
for _f in FINGERS:
    FEATURE_NAMES += [f"{_f}_reach", f"{_f}_tip_palm", f"{_f}_bend_pip", f"{_f}_bend_mcp"]
FEATURE_NAMES += ["gap_thumb_index", "gap_index_middle", "gap_middle_ring", "gap_ring_pinky", "gap_index_pinky", "spread_index_middle"]


def _angle(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine of the angle between two bones (1 = straight on)."""
    n = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / n) if n > 1e-9 else 1.0


def features(lm) -> np.ndarray | None:
    """One frame's hand shape, independent of where the hand is, how big it looks and
    how it is turned: distances over the palm's size, and joint angles."""
    if lm is None or len(lm) < 63:
        return None
    p = np.asarray(lm[:63], float).reshape(21, 3)
    wrist = p[0]
    scale = np.linalg.norm(p[9] - wrist)
    if scale < 1e-6:
        return None
    palm = p[[0, 5, 9, 13, 17]].mean(axis=0)
    out: list[float] = []
    for name, (mcp, pip, dip, tip) in FINGERS.items():
        base = p[5] if name == "thumb" else wrist  # a thumb reaches away from the index knuckle
        out.append(np.linalg.norm(p[tip] - base) / max(np.linalg.norm(p[mcp] - base), 1e-6))
        out.append(np.linalg.norm(p[tip] - palm) / scale)
        out.append(_angle(p[pip] - p[mcp], p[tip] - p[pip]))
        out.append(_angle(p[mcp] - (wrist if name != "thumb" else p[0]), p[pip] - p[mcp]))
    tips = {n: p[t[3]] for n, t in FINGERS.items()}
    for a, b in (("thumb", "index"), ("index", "middle"), ("middle", "ring"), ("ring", "pinky"), ("index", "pinky")):
        out.append(np.linalg.norm(tips[a] - tips[b]) / scale)
    out.append(_angle(p[8] - p[5], p[12] - p[9]))
    return np.asarray(out, float)


def baseline(lm) -> str | None:
    """The simple rule a model has to beat: count the fingers whose tip is farther from
    the wrist than their middle joint (thumb aside) - 0-1 rock, 2 scissors, 3-4 paper."""
    if lm is None or len(lm) < 63:
        return None
    p = np.asarray(lm[:63], float).reshape(21, 3)[:, :2]
    up = sum(np.linalg.norm(p[t] - p[0]) > np.linalg.norm(p[pip] - p[0]) for _, pip, _, t in list(FINGERS.values())[1:])
    return "rock" if up <= 1 else "scissors" if up == 2 else "paper"


# ---- the trained classifier ------------------------------------------------------------------------


@dataclass
class Model:
    classes: list[str]
    mean: list[float]
    scale: list[float]
    coef: list[list[float]]
    intercept: list[float]
    window_ms: list[int]  # [from, to] after the shoot instant
    min_confidence: float
    report: dict = field(default_factory=dict)

    def proba(self, x: np.ndarray) -> np.ndarray:
        z = (np.atleast_2d(x) - np.asarray(self.mean)) / np.asarray(self.scale)
        logits = z @ np.asarray(self.coef).T + np.asarray(self.intercept)
        logits -= logits.max(axis=1, keepdims=True)
        e = np.exp(logits)
        return e / e.sum(axis=1, keepdims=True)


def load_model(path: Path = MODEL) -> Model | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Model(**{k: raw[k] for k in Model.__dataclass_fields__ if k in raw})
    except (OSError, ValueError, KeyError, TypeError):
        return None


@dataclass
class Read:
    """His throw as read from the window: the throw (or None), how sure, and the evidence."""

    throw: str | None
    confidence: float
    frames: int
    probs: dict[str, float]
    why: str = ""


def in_window(frames: list[dict], window_ms) -> list[dict]:
    a, b = window_ms
    return [f for f in frames if a <= f.get("t", -1e9) <= b and isinstance(f.get("lm"), list) and len(f["lm"]) >= 63]


def read(frames: list[dict], model: Model, min_confidence: float | None = None) -> Read:
    """The fixed window's frames, classified and averaged into one throw - None below
    the bar: the model's own, or `min_confidence` if that is higher (a staked game)."""
    used = in_window(frames, model.window_ms)
    xs = [x for x in (features(f["lm"]) for f in used) if x is not None]
    if not xs:
        return Read(None, 0.0, 0, {}, "no hand in the window")
    probs = model.proba(np.vstack(xs)).mean(axis=0)
    k = int(np.argmax(probs))
    out = {c: round(float(v), 3) for c, v in zip(model.classes, probs)}
    if probs[k] < max(model.min_confidence, min_confidence or 0.0):
        return Read(None, float(probs[k]), len(xs), out, "not sure what that was")
    return Read(model.classes[k], float(probs[k]), len(xs), out)


# ---- the round ----------------------------------------------------------------------------------------


def outcome(his: str, hers: str) -> str:
    if his == hers:
        return "draw"
    return "him" if BEATS[his] == hers else "her"


def commitment(throw: str, nonce: str) -> str:
    return hashlib.sha256(f"{throw}:{nonce}".encode()).hexdigest()


@dataclass
class Round:
    n: int
    id: str
    hers: str
    nonce: str
    commit: str
    committed_at: str  # ISO time, ms
    committed_ts: float
    capture: bool = False  # a training capture, not a game round
    label: str = ""  # the capture's asked-for throw
    shoot_at: str = ""
    read_at: str = ""
    his: str | None = None
    confidence: float = 0.0
    result: str = ""


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


class RPS:
    """One sitting of rock-paper-scissors (or a guided capture): the score, the rounds,
    and the fairness log."""

    def __init__(self, games: Path = GAMES, rng=None):
        self.games = games
        self.rng = rng or secrets.SystemRandom()
        self.active = False
        self.capturing = False
        self.session = ""
        self.score = {"him": 0, "her": 0, "draw": 0}
        self.rounds: list[Round] = []
        self.pending: Round | None = None
        self.last_activity = 0.0
        self.model: Model | None = load_model()
        # a guided capture's plan: the throws still to ask for, and the session
        self.plan: list[str] = []
        self.capture_session = ""
        # stakes (rps_stakes.py): held for the game once he has said yes to them; a
        # series is first to best_of // 2 + 1 counted rounds (draws replayed)
        self.stakes: Stakes | None = None
        self.best_of = 1
        self.config = load_config()
        # before the game: stakes read back and waiting for his yes ("confirm"), or
        # asked for ("stakes"); what he said so far, and which side was missing
        self.awaiting: str | None = None
        self.awaiting_at = 0.0
        self.offered: Stakes | None = None
        self.said = ""
        self.asked = ""
        # what happened before the game had a log (the parse, the asks): written into
        # it as it starts, so the record has the whole story
        self.prelog: list[dict] = []

    # -- the log ------------------------------------------------------------------------------------

    def _write(self, event: dict) -> None:
        self.games.mkdir(parents=True, exist_ok=True)
        with (self.games / f"rps-{self.session}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    # -- the sitting ------------------------------------------------------------------------------

    def start(self, capture: bool = False, reps: int = 12, stakes: Stakes | None = None, best_of: int = 1) -> None:
        self.model = load_model()
        self.config = load_config()
        self.active, self.capturing = True, capture
        self.stakes, self.best_of = (None, 1) if capture else (stakes, max(1, best_of))
        self.awaiting, self.offered = None, None
        self.session = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        self.score = {"him": 0, "her": 0, "draw": 0}
        self.rounds, self.pending = [], None
        self.last_activity = time.monotonic()
        if capture:
            # each throw `reps` times, shuffled, never the same three in a row
            plan = [t for t in THROWS for _ in range(reps)]
            self.rng.shuffle(plan)
            self.plan, self.capture_session = plan, self.session
        self._write({"event": "start", "session": self.session, "capture": capture, "at": _now_iso(),
                     "model": (self.model.report.get("trained") if self.model else None),
                     "stakes": self.stakes.to_json() if self.stakes else None, "best_of": self.best_of,
                     "min_confidence": self.threshold()})
        for event in self.prelog:
            self._write(event)
        self.prelog = []
        log.info("rps: %s started, session %s", "guided capture" if capture else "game", self.session)

    def threshold(self) -> float:
        """The confidence bar this game reads his hand against."""
        own = self.model.min_confidence if self.model else 0.0
        plain = self.config.get("min_confidence")
        bar = max(own, float(plain) if plain is not None else 0.0)
        if self.stakes:
            bar = max(bar, float(self.config.get("min_confidence_staked") or 0.0))
        return round(bar, 3)

    def needed(self) -> int:
        """Counted rounds to take the game (1, or 2 in a best of three)."""
        return self.best_of // 2 + 1

    def decided(self) -> str | None:
        """Who has taken the game - "him" or "her" - by the code's score; None yet."""
        for side in ("him", "her"):
            if self.score[side] >= self.needed():
                return side
        return None

    def settle(self, outcome: str, line: str, source: str) -> None:
        """The bet, settled: the code's outcome and the consequence it maps to, in the
        log next to every sealed throw and read that led to it."""
        c = rps_stakes.consequence(self.stakes, outcome) if self.stakes else None
        self._write({"event": "settled", "outcome": outcome, "consequence": c, "stakes": self.stakes.to_json() if self.stakes else None,
                     "score": dict(self.score), "best_of": self.best_of, "line": line, "narration": source, "at": _now_iso()})
        log.info("rps: SETTLED %s -> %r (score him %d her %d, narration: %s)", outcome, c, self.score["him"], self.score["her"], source)

    # -- before the game: the stakes ----------------------------------------------------------

    def note(self, event: dict) -> None:
        """A stakes event from before the game's log exists."""
        self.prelog.append({**event, "at": _now_iso()})

    def wait_for(self, what: str | None) -> None:
        self.awaiting = what
        self.awaiting_at = time.monotonic()

    def awaiting_now(self) -> str | None:
        """What she is waiting to hear about the stakes - None once it has gone stale."""
        if self.awaiting and time.monotonic() - self.awaiting_at > AWAIT_S:
            self.awaiting, self.offered = None, None
        return self.awaiting

    def stop(self, why: str) -> None:
        if self.active:
            self._write({"event": "end", "why": why, "score": self.score, "rounds": len(self.rounds), "at": _now_iso()})
            log.info("rps: ended (%s) - him %d, her %d, draws %d over %d rounds", why, self.score["him"], self.score["her"], self.score["draw"], len(self.rounds))
        self.active = self.capturing = False
        self.pending = None
        self.plan = []
        self.stakes, self.best_of = None, 1

    def commit(self) -> Round:
        """Her throw for the next round, drawn and WRITTEN DOWN before his hand is read."""
        self.last_activity = time.monotonic()
        n = len(self.rounds) + 1
        hers = self.rng.choice(THROWS)
        nonce = secrets.token_hex(8)
        rnd = Round(n, f"{self.session}#{n}", hers, nonce, commitment(hers, nonce), _now_iso(), time.time(), capture=self.capturing)
        if self.capturing:
            rnd.label = self.plan.pop(0) if self.plan else self.rng.choice(THROWS)
        self._write({"event": "commit", "round": n, "id": rnd.id, "commit": rnd.commit, "committed_at": rnd.committed_at,
                     "hers": None if not self.capturing else rnd.hers, "label": rnd.label or None,
                     "stakes": self.stakes.to_json() if self.stakes else None, "series": dict(self.score), "best_of": self.best_of})
        # core.log: her throw in the clear, timestamped before the count even starts
        log.info("rps round %d COMMITTED at %s: Irene throws %s (sha256 %s) - his hand not read yet", n, rnd.committed_at, hers.upper(), rnd.commit[:16])
        self.pending = rnd
        return rnd

    def shot(self, rnd: Round) -> None:
        rnd.shoot_at = _now_iso()
        log.info("rps round %d: SHOOT heard at %s (committed %s earlier)", rnd.n, rnd.shoot_at,
                 f"{(time.time() - rnd.committed_ts) * 1000:.0f} ms")

    def resolve(self, rnd: Round, frames: list[dict]) -> Read:
        """His hand, read after the commitment: the round's result, logged with the reveal."""
        self.last_activity = time.monotonic()
        rnd.read_at = _now_iso()
        bar = self.threshold()
        got = read(frames, self.model, bar) if self.model else Read(None, 0.0, 0, {}, "no model")
        rnd.his, rnd.confidence = got.throw, got.confidence
        if got.throw:
            rnd.result = outcome(got.throw, rnd.hers)
            self.score[rnd.result] += 1
        self.rounds.append(rnd)
        self.pending = None
        self._write({"event": "reveal", "round": rnd.n, "id": rnd.id, "hers": rnd.hers, "nonce": rnd.nonce, "commit": rnd.commit,
                     "committed_at": rnd.committed_at, "shoot_at": rnd.shoot_at, "read_at": rnd.read_at,
                     "his": got.throw, "confidence": round(got.confidence, 3), "probs": got.probs, "frames": got.frames,
                     "why": got.why, "result": rnd.result, "score": dict(self.score), "min_confidence": bar,
                     "stakes": self.stakes.to_json() if self.stakes else None, "best_of": self.best_of})
        log.info("rps round %d READ at %s: he threw %s (p=%.2f, %d frames) vs her %s (committed %s) -> %s; score him %d her %d draws %d",
                 rnd.n, rnd.read_at, (got.throw or "?").upper(), got.confidence, got.frames, rnd.hers.upper(), rnd.committed_at,
                 rnd.result or got.why, self.score["him"], self.score["her"], self.score["draw"])
        return got

    def idle(self) -> bool:
        return self.active and time.monotonic() - self.last_activity > IDLE_END_S

    # -- the panel ---------------------------------------------------------------------------------

    def panel(self, rnd: Round | None = None, reveal: bool = False, settled: str | None = None) -> dict:
        """Both throws (once revealed - before, only her sealed commitment) and the score."""
        s = self.score
        series = f"Best of {self.best_of} · first to {self.needed()}: " if self.best_of > 1 else ""
        blocks: list[dict] = [{"kind": "heading", "text": f"{series}You {s['him']} - {s['her']} Irene" + (f"  ·  {s['draw']} draws" if s["draw"] else "")}]
        if self.stakes:
            st = self.stakes
            blocks.append({"kind": "box", "tone": "points", "title": "The stakes" + (" (on the series)" if self.best_of > 1 else ""),
                           "blocks": [{"kind": "text", "text": f"You win: {st.win}\nYou lose: {st.lose}\nDraw: {st.draw or 'replay, same stakes'}\n"
                                                              f"Agreed at {st.confirmed_at[11:19]} - your words: \"{st.said}\""}]})
        if rnd is not None:
            if reveal:
                his = (rnd.his or "?").upper()
                verdict = {"him": "You win the round", "her": "Irene wins the round", "draw": "Draw"}.get(rnd.result, "No throw seen - replay")
                blocks.append({"kind": "box", "tone": "points", "title": f"Round {rnd.n}",
                               "blocks": [{"kind": "text", "text": f"You: {his}    Irene: {rnd.hers.upper()}\n{verdict}"}]})
                blocks.append({"kind": "text", "text": f"Sealed before the count at {rnd.committed_at[11:]}: sha256 {rnd.commit[:24]}…\n"
                                                       f"Revealed: \"{rnd.hers}:{rnd.nonce}\" - hash it and it matches. "
                                                       f"Your hand was read at {rnd.read_at[11:]}."})
            else:
                blocks.append({"kind": "box", "tone": "research", "title": f"Round {rnd.n} - Irene's throw is sealed",
                               "blocks": [{"kind": "text", "text": f"Committed at {rnd.committed_at[11:]}\nsha256 {rnd.commit[:24]}…\n(revealed after your hand is read)"}]})
        if settled:
            who = {"him": "You won", "her": "Irene won", "draw": "A draw"}[settled]
            c = rps_stakes.consequence(self.stakes, settled) if self.stakes else None
            blocks.insert(1, {"kind": "box", "tone": "points", "title": f"Settled: {who}" + (" the bet" if self.stakes and settled != "draw" else ""),
                              "blocks": [{"kind": "text", "text": c[:1].upper() + c[1:] + "." if c else f"{who} the series."}]})
        history = [f"{r.n}. you {(r.his or '?')}, Irene {r.hers} - {({'him': 'you', 'her': 'Irene', 'draw': 'draw'}).get(r.result, 'no throw')}"
                   for r in self.rounds if not r.capture][-8:]
        if history:
            blocks.append({"kind": "heading", "level": 3, "text": "Rounds"})
            blocks.append({"kind": "text", "text": "\n".join(reversed(history))})
        return {"title": "Rock · Paper · Scissors", "subtitle": f"session {self.session} · every throw sealed before the shoot (core/data/games)", "blocks": blocks}


# ---- what he says --------------------------------------------------------------------------------------

_RPS = r"rock[\s,.-]*paper[\s,.-]*(?:and\s+)?scissors?"
# "train" as Whisper also writes it ("turn"), and asking for the next session ("do
# the section 2 of the rock paper scissors" - live 2026-10-15, taken for "play")
_CAPTURE_WORD = r"(?:train(?:ing|ed)?|turn|calibrat\w*|capture|record\w*|teach\s+you|session|section)"
_CAPTURE = re.compile(rf"\b{_CAPTURE_WORD}\b.{{0,40}}{_RPS}|{_RPS}.{{0,25}}\b{_CAPTURE_WORD}\b", re.I)
_START = re.compile(rf"{_RPS}|\brps\b", re.I)
_AGAIN = re.compile(r"\b(?:again|another(?:\s+(?:one|round|go))?|one\s+more|next\s+(?:one|round)|go\s+again|rematch|let'?s\s+go|ready|shoot"
                    r"|yes|yeah|yep|yup|sure|ok(?:ay)?|go)\b", re.I)
# his answer to the stakes read back: no first ("no, I'm ready" is a no), then yes
_NO = re.compile(r"^\W*(?:no|nope|nah|wrong|wait|not\s+quite|hold\s+on)\b|\b(?:other\s+way\s+round|backwards|swapped|that'?s\s+(?:wrong|not\s+right)|you\s+got\s+it\s+wrong)\b", re.I)
_YES = re.compile(r"\b(?:yes|yeah|yep|yup|ready|correct|right|confirm(?:ed)?|deal|let'?s\s+(?:go|do\s+it)|go|sure|ok(?:ay)?|do\s+it|that'?s\s+it|exactly)\b", re.I)
_CANCEL = re.compile(r"\b(?:cancel|forget\s+(?:it|the\s+bet)|never\s*mind|no\s+bet|no\s+stakes|just\s+play)\b", re.I)
_EXIT = re.compile(
    r"\b(?:exit|quit|leave|end|stop|finish)\s+(?:the\s+)?(?:game|games|game\s+mode|rock\s+paper\s+scissors|playing)\b|\bexit\b|\bquit\b|"
    r"\bi'?m\s+done\b|\bthat'?s\s+enough\b|\bno\s+more\b|^\W*stop\W*$",
    re.I,
)
_SCORE = re.compile(r"\b(?:what'?s|what\s+is|tell\s+me)\s+the\s+score\b|\bscore\b", re.I)


def command(text: str, active: bool, awaiting: str | None = None) -> str | None:
    """His words as a game command: "capture", "start", "round", "exit", "score" - None
    when they're not for the game. While she waits on the stakes (`awaiting`): his
    answer is "confirm", "deny", "cancel" or more "stakes"."""
    said = (text or "").strip()
    if awaiting and not active:
        if _CANCEL.search(said) or _EXIT.search(said):
            return "cancel"
        if awaiting == "confirm":
            if _NO.search(said):
                return "deny"
            if _YES.search(said):
                return "confirm"
        return "stakes"
    if _CAPTURE.search(said):
        return "capture"
    if not active:
        return "start" if _START.search(said) else None
    if _EXIT.search(said):
        return "exit"
    if _START.search(said) or _AGAIN.search(said):
        return "round"
    if _SCORE.search(said):
        return "score"
    return None


def describe(his: str, hers: str) -> str:
    """ "paper covers rock" for whichever won (or "" on a draw)."""
    if his == hers:
        return ""
    win = (his, hers) if BEATS[his] == hers else (hers, his)
    return VERB[win]


def to_json(rnd: Round) -> dict:
    return asdict(rnd)


# ---- what she says ------------------------------------------------------------------------------------

LINES: dict[str, tuple[str, ...]] = {
    "start": (
        "Rock paper scissors? You're on. My throw's sealed before every shoot - no peeking, I promise.",
        "Ooh, rock paper scissors! Hands ready. I lock my throw in before you even move.",
        "You're on! I seal my throw first, so you can't accuse me of cheating. Ready?",
    ),
    "no_model": (
        "I can't read your throws yet - my rock paper scissors eyes aren't trained. Say train rock paper scissors and we'll record them.",
    ),
    "capture_start": (
        "Training time. I'll ask for a throw, count you in, and you throw it on shoot - like a real game. About thirty-six throws.",
    ),
    "capture_ask": ("Throw {label}.", "{label} this time.", "Next: {label}.", "Give me {label}."),
    "capture_again": ("I didn't see your hand there - again: {label}.", "Missed that one. {label}, please."),
    "capture_done": ("That's the set - all saved. Do one more session another time and I can test myself on it.",),
    "win_him": ("{his}! Ugh - {verb}. Your point.", "{his} beats my {hers}. Fine. Point to you.", "No! {verb}. You got me."),
    "win_her": ("{hers}! {verb} - my point!", "Ha! My {hers} beats your {his}.", "{verb}! Point to me, sir."),
    "draw": ("{his} and {hers}. Draw!", "Both {his}! Great minds.", "A draw - we both threw {his}."),
    "unseen": ("I didn't see your hand on shoot - let's redo that one.", "Your hand wasn't in view on shoot. Again?",
               "Wait - where did your hand go? Again?", "I blinked at the worst moment. Again?"),
    "unsure": ("I couldn't tell what that was - redo?", "Hmm, half a throw? Let's go again.",
               "Was that a rock or a very relaxed paper? Again?", "I honestly couldn't read that one. Again?"),
    "tally": ("That's {him} to {her}.", "Score: you {him}, me {her}.", "{him}-{her}."),
    "tally_draws": ("That's {him} to {her}, with {draws}.",),
    "score": ("You've got {him}, I've got {her}{draws}.",),
    "end": ("Game over - you {him}, me {her}. Hands are yours again.", "That's the game: {him} to {her}. Gestures back on."),
    "timeout": ("No more throws? I'll call it there - {him} to {her}. Gestures back on.",),
    # stakes (rps_stakes.py)
    "deal": ("Deal. Sealed. Here we go!", "Then it's a bet. Hands ready!", "Locked in. No take-backs. Ready..."),
    "confirm_again": ("Is that a yes? Say yes to lock it in - or tell me the stakes again.",),
    "no_bet": ("No bet, then. Say rock paper scissors whenever you want a game.", "Okay, bet's off."),
    "unsure_staked": ("Your throw wasn't clear - and with a bet on it, I won't guess. Again?",
                      "Not clear enough to call with stakes on the line. Again?",
                      "I'd rather redo it than get your bet wrong. Again?"),
    "draw_replay": ("Draw! Same stakes - again!", "A draw - nothing settled. Same bet, go again!", "Even! The bet still stands. Again!"),
    "series_next": ("That's {him}-{her}. Next round!", "{him}-{her} in the series. Again!", "Series: you {him}, me {her}. Next!"),
    "series_won_her": ("That's the series, {her}-{him} to me.",),
    "series_won_him": ("That's the series, {him}-{her} to you.",),
}

CUES: dict[str, tuple[str, ...]] = {
    # the game's own hand (the HUD's LED glyph, led/gameHand.ts) does the counting
    # and the throwing, so these are her FACE: no gesture's hands drawn over it
    "start": ("firedUp", "excited"),
    "no_model": ("sheepish", "shrug"),
    "capture_start": ("takeNotes", "focused"),
    "capture_ask": ("rpsCount", "focused"),
    "capture_again": ("headTilt", "confused"),
    "capture_done": ("pinNote", "proud"),
    # the result: she beat him, he beat her, a draw - each its own face
    "win_her": ("triumphant", "proud"),
    "win_him": ("outplayed", "sulking"),
    "draw": ("standoff", "smug"),
    # a misread: a shrug and "again?" - a beat, not a dead moment
    "unseen": ("oops", "confused"),
    "unsure": ("oops", "confused"),
    "score": ("countOff", "smug"),
    "end": ("wave", "bow"),
    "timeout": ("shrug", "wave"),
    # the stakes read back, his hand out to shake on it
    "confirm": ("shakeOnIt", "focused"),
    "ask_stakes": ("headTilt", "curious"),
    "deal": ("firedUp", "excited"),
    "no_bet": ("shrug", "sheepish"),
    "unsure_staked": ("oops", "confused"),
    "draw_replay": ("standoff", "smug"),
}
THROW_CUE = {"rock": "throwRock", "paper": "throwPaper", "scissors": "throwScissors"}


class Lines:
    """Her lines, never the same one twice running."""

    def __init__(self, rng=None):
        import random

        self.rng = rng or random.Random()
        self._last: dict[str, str] = {}

    def pick(self, kind: str, **fill) -> str:
        pool = LINES[kind]
        options = [line for line in pool if line != self._last.get(kind)] or list(pool)
        line = self.rng.choice(options)
        self._last[kind] = line
        text = line.format(**fill)
        return text[:1].upper() + text[1:]


def reveal_line(lines: Lines, rnd: Round, score: dict, tally: bool = True) -> tuple[str, str]:
    """(her line, its kind - a CUES key) for a revealed round: the throws, who won,
    the tally (not on a bet or a series: those say their own). Her throw itself was
    shown by the game hand on shoot."""
    his, hers = rnd.his or "", rnd.hers
    kind = {"him": "win_him", "her": "win_her", "draw": "draw"}[rnd.result]
    line = lines.pick(kind, his=his, hers=hers, verb=describe(his, hers))
    if not tally:
        # "Your point." / "my point!" belong to a running tally, not a bet's last word
        return re.sub(r"\s*(?:Your point\.|Point to you\.|Point to me, sir\.|- my point!|my point!)", "", line).strip(" -"), kind
    count = lines.pick("tally_draws" if score["draw"] else "tally", draws="1 draw" if score["draw"] == 1 else f"{score['draw']} draws", **score)
    return f"{line} {count}", kind
