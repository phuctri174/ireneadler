"""Rock-paper-scissors (irene/rps.py, scripts/rps_train.py): the throw is sealed and
logged before his hand is read, the hand is read from a fixed window, and the
classifier ships only when it clears the bar on a held-out session.

The trainer is exercised on SYNTHETIC captures here (a test must never need his
hand); the real numbers come from his captures - see the trainer's report."""
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from irene import calibration, rps

CORE = Path(__file__).resolve().parents[1]


def hand(throw: str, rng: np.random.Generator, angle: float = 0.0, scale: float = 1.0, at=(0.5, 0.6), noise: float = 0.004) -> list[float]:
    """A plausible 21-landmark hand making `throw`, turned, sized and placed anywhere."""
    ext = {"rock": [0.15, 0.1, 0.1, 0.1, 0.1], "paper": [0.9, 1, 1, 1, 1], "scissors": [0.15, 1, 1, 0.1, 0.1]}[throw]
    ext = [min(1.0, max(0.0, e + rng.normal(0, 0.06))) for e in ext]
    pts = [(0.0, 0.0)]
    # thumb: out to the side
    for j in range(1, 5):
        reach = 0.05 * j * (0.5 + 0.5 * ext[0])
        pts.append((-0.06 - reach * 0.9, -0.03 - reach * 0.5 * (0.3 + ext[0])))
    for f, x in enumerate((-0.035, -0.01, 0.015, 0.04)):
        e = ext[f + 1]
        mcp = (x, -0.15)
        pts.append(mcp)
        # straight up when extended; folded back down toward the palm when curled
        pts.append((x, -0.15 - 0.05 * (0.3 + 0.7 * e)))
        pts.append((x, -0.15 - 0.09 * e + 0.02 * (1 - e)))
        pts.append((x, -0.15 - 0.12 * e + 0.06 * (1 - e)))
    c, s = math.cos(angle), math.sin(angle)
    out = []
    for x, y in pts:
        X, Y = (x * c - y * s) * scale + at[0], (x * s + y * c) * scale + at[1]
        out += [X + rng.normal(0, noise), Y + rng.normal(0, noise), rng.normal(0, noise)]
    return out


def test_features_ignore_where_how_big_and_turned():
    rng = np.random.default_rng(1)
    a = rps.features(hand("scissors", np.random.default_rng(5), noise=0))
    b = rps.features(hand("scissors", np.random.default_rng(5), angle=0.5, scale=1.6, at=(0.2, 0.3), noise=0))
    assert np.allclose(a, b, atol=1e-6)
    assert rps.features([0.0] * 10) is None
    for t in rps.THROWS:
        assert rps.baseline(hand(t, rng, noise=0)) == t


def test_commands():
    assert rps.command("rock paper scissors", False) == "start"
    assert rps.command("Let's play rock, paper, scissors!", False) == "start"
    assert rps.command("train rock paper scissors", False) == "capture"
    # live 2026-10-15: how the second session was asked for
    assert rps.command("Hey Irene. Do the section 2 of the rock paper scissors please.", False) == "capture"
    assert rps.command("Hey, turn rock paper scissors", False) == "capture"
    assert rps.command("rock paper scissors session two", False) == "capture"
    assert rps.command("what time is it", False) is None
    assert rps.command("I like rock music", False) is None
    assert rps.command("again", True) == "round"
    assert rps.command("one more", True) == "round"
    assert rps.command("exit game", True) == "exit"
    assert rps.command("stop", True) == "exit"
    assert rps.command("what's the score?", True) == "score"
    assert rps.command("again", False) is None


def test_outcomes():
    assert rps.outcome("rock", "scissors") == "him"
    assert rps.outcome("rock", "paper") == "her"
    assert rps.outcome("paper", "paper") == "draw"
    assert rps.describe("scissors", "paper") == "scissors cut paper"
    assert rps.describe("rock", "paper") == "paper covers rock"


class FakeModel(rps.Model):
    pass


def model_that_says(throw: str) -> rps.Model:
    k = rps.THROWS.index(throw)
    n = len(rps.FEATURE_NAMES)
    intercept = [-5.0, -5.0, -5.0]
    intercept[k] = 5.0
    return rps.Model(classes=list(rps.THROWS), mean=[0.0] * n, scale=[1.0] * n, coef=[[0.0] * n] * 3, intercept=intercept,
                     window_ms=[100, 400], min_confidence=0.5)


def test_her_throw_is_sealed_and_logged_before_his_hand_is_read(tmp_path):
    game = rps.RPS(games=tmp_path)
    game.start()
    game.model = model_that_says("rock")
    rnd = game.commit()
    lines = [json.loads(x) for x in (tmp_path / f"rps-{game.session}.jsonl").read_text().splitlines()]
    sealed = lines[-1]
    # in the log BEFORE any frame exists: the commitment, not the throw
    assert sealed["event"] == "commit" and sealed["hers"] is None and sealed["commit"] == rnd.commit
    frames = [{"t": t, "lm": hand("rock", np.random.default_rng(t + 1000))} for t in range(-500, 1300, 33)]
    got = game.resolve(rnd, frames)
    reveal = json.loads((tmp_path / f"rps-{game.session}.jsonl").read_text().splitlines()[-1])
    assert reveal["event"] == "reveal" and got.throw == "rock"
    assert reveal["committed_at"] < reveal["read_at"]
    # the reveal proves the seal: sha256(throw:nonce) is what was committed
    assert hashlib.sha256(f"{reveal['hers']}:{reveal['nonce']}".encode()).hexdigest() == sealed["commit"]
    # only frames in the fixed window were read
    assert got.frames == len([f for f in frames if 100 <= f["t"] <= 400])
    assert game.score[rnd.result] == 1


def test_no_hand_in_the_window_is_a_redo_not_a_guess(tmp_path):
    game = rps.RPS(games=tmp_path)
    game.start()
    game.model = model_that_says("paper")
    rnd = game.commit()
    got = game.resolve(rnd, [{"t": 900, "lm": hand("paper", np.random.default_rng(0))}])
    assert got.throw is None and got.why == "no hand in the window" and sum(game.score.values()) == 0


def test_every_rps_cue_exists():
    from irene import react

    for family in rps.CUES.values():
        for name in family:
            assert react.resolve(name) is not None, name
    for name in rps.THROW_CUE.values():
        assert react.resolve(name) is not None, name


def _capture(directory: Path, session: str, rng, flip: bool = False) -> None:
    for throw in rps.THROWS:
        for rep in range(12):
            label = rps.THROWS[(rps.THROWS.index(throw) + rep) % 3] if flip else throw
            frames = []
            for t in range(-600, 1400, 33):
                # the hand arrives ~200 ms after shoot: before that, a fist pumping
                shape = throw if t > 200 else "rock"
                frames.append({"t": t, "lm": hand(shape, rng, angle=rng.normal(0, 0.3), scale=rng.uniform(0.8, 1.3)), "handed": "Right"})
            calibration.write({"profile": "rps", "session": session, "pose": label, "rep": rep, "frames": frames}, directory)


def _train(tmp_path, captures):
    out = tmp_path / "model.json"
    r = subprocess.run([sys.executable, "scripts/rps_train.py", "--dir", str(captures), "--out", str(out), "--report", str(tmp_path / "report.json")],
                       cwd=CORE, capture_output=True, text=True)
    return r, out


def test_the_trainer_ships_a_good_model_and_holds_out_a_session(tmp_path):
    captures = tmp_path / "cal"
    rng = np.random.default_rng(3)
    _capture(captures, "2026-10-15T10-00-00", rng)
    _capture(captures, "2026-10-16T10-00-00", rng)
    r, out = _train(tmp_path, captures)
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["holdout"] == "2026-10-16T10-00-00" and report["holdout_throws"] == 36 and report["ships"]
    model = rps.load_model(out)
    # the window is after the hand arrives - learned, not set
    assert model.window_ms[0] >= 200
    frames = [{"t": t, "lm": hand("scissors", rng)} for t in range(-600, 1400, 33)]
    assert rps.read(frames, model).throw == "scissors"


def test_the_trainer_refuses_a_model_that_misses_the_bar(tmp_path):
    captures = tmp_path / "cal"
    rng = np.random.default_rng(4)
    _capture(captures, "2026-10-15T10-00-00", rng)
    _capture(captures, "2026-10-16T10-00-00", rng, flip=True)  # labels that don't match the hands
    r, out = _train(tmp_path, captures)
    assert r.returncode == 1 and "NOT SHIPPED" in r.stdout and not out.exists()


def test_the_trainer_needs_two_sessions(tmp_path):
    captures = tmp_path / "cal"
    _capture(captures, "2026-10-15T10-00-00", np.random.default_rng(5))
    r, out = _train(tmp_path, captures)
    assert r.returncode == 2 and not out.exists()


# ---- her hand on the HUD (app.py _rps_count, hud/src/led/gameHand.ts) -------------------------------


class _Bridge:
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, message: dict) -> None:
        self.sent.append(dict(message))

    async def transcript(self, role: str, text: str) -> None:
        self.sent.append({"type": "transcript", "role": role, "text": text})

    async def state(self, value: str) -> None:
        self.sent.append({"type": "state", "value": value})


class _Speaker:
    """Plays a clip by firing its marks in order, as the audio thread would."""

    def __init__(self):
        self.marks_at: list[float] = []

    def play(self, audio, levels, marks=(), done=None):
        self.marks_at = [t for t, _ in marks]
        for _, fire in sorted(marks, key=lambda m: m[0]):
            fire()
        done(True)


def _count_messages(sealed: str, speaker: bool) -> list[dict]:
    """Every message _rps_count sends for a round where she sealed `sealed`."""
    import asyncio
    import types

    from irene.app import Core

    async def go() -> list[dict]:
        game = rps.RPS(games=Path("unused"), rng=_Fixed(sealed))
        game._write = lambda event: None
        game.active = True
        game.session = "test"
        host = types.SimpleNamespace(bridge=_Bridge(), rps=game, _rps_frames={}, muted=not speaker, speaker=_Speaker() if speaker else None)

        async def clip():
            return np.zeros(24000 * 3, np.float32), np.zeros(60), 1.92

        host._rps_count_clip = clip
        rnd = game.commit()
        assert rnd.hers == sealed
        task = asyncio.ensure_future(Core._rps_count(host, rnd))
        for _ in range(200):
            await asyncio.sleep(0.01 if not speaker else 0)
            if rnd.id in host._rps_frames:
                host._rps_frames[rnd.id].set_result([])
                break
        await task
        if speaker:
            assert host.speaker.marks_at == pytest.approx([0.0, 0.64, 1.28, 1.92]), "a pump on each word, shoot on the fourth"
        return [{k: v for k, v in m.items() if k != "id"} for m in host.bridge.sent]

    return asyncio.run(go())


class _Fixed:
    def __init__(self, throw):
        self.throw = throw

    def choice(self, options):
        return self.throw if self.throw in options else options[0]


@pytest.mark.parametrize("speaker", [True, False], ids=["voice", "muted"])
def test_the_count_never_shows_her_throw(speaker):
    """Fairness: everything the HUD is sent before shoot - every pump - is the same
    whatever she sealed; her throw is first sent inside the shoot message itself."""
    runs = {sealed: _count_messages(sealed, speaker) for sealed in rps.THROWS}
    before = {}
    for sealed, sent in runs.items():
        shoot = next(i for i, m in enumerate(sent) if m["type"] == "game_shoot")
        before[sealed] = sent[:shoot]
        beats = [m for m in sent[:shoot] if m["type"] == "game_hand"]
        assert [m.get("beat") for m in beats] == [0, 1, 2] and all(m["glyph"] == "neutral" for m in beats), beats
        assert sealed not in json.dumps(sent[:shoot]).lower().replace("rock... paper... scissors", ""), "her throw leaked before shoot"
        assert sent[shoot]["throw"] == sealed, "her throw rides on the shoot message"
        assert not any(m["type"] == "game_hand" for m in sent[shoot + 1:]), "no hand message after shoot reveals anything else"
    assert before["rock"] == before["paper"] == before["scissors"]
