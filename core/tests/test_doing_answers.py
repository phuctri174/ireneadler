"""'What are you doing?' after a signature entrance: the line's own cue and sound
ALWAYS play - all of them, full body - enforced in code, whatever the previous
reply showed and however he phrases it. Round 10: one cue of each line played, a
repeat-avoider could swap or filter it, an expression only moved her face, and
"Wait what are you doing?" missed the match and went to the model."""
import json
import random
from pathlib import Path

import pytest

from irene.quick import _DOING, QuickReplies, normalise

ENTRIES = json.loads((Path(__file__).resolve().parents[2] / "config" / "entrances.json").read_text(encoding="utf-8"))["entrances"]
SIGNATURE = [e for e in ENTRIES if e.get("doing_answers")]


@pytest.mark.parametrize("said", [
    "What are you doing?", "Wait what are you doing?", "Wait, what are you doing?", "So what were you doing?",
    "What the f** are you doing?", "What the fuck are you doing?", "What on earth are you doing?",
    "Irene, what are you doing?", "What are you doing there?", "What are you up to, Irene?",
    "What were you doing just now?", "What are you playing?", "Hey what have you been up to?",
])
def test_every_way_he_asks_is_the_doing_answer(said):
    assert _DOING.match(normalise(said)), said


@pytest.mark.parametrize("said", ["What are you doing tomorrow at noon with my files?", "What should I be doing?", "What is he doing?"])
def test_other_questions_are_not(said):
    assert not _DOING.match(normalise(said))


@pytest.mark.parametrize("entry", SIGNATURE, ids=lambda e: e["name"])
def test_the_answer_keeps_every_own_cue_and_its_sound_and_never_opens_on_the_last_cue(entry):
    own = {d["line"]: d for d in entry["doing_answers"]}
    for k, last in enumerate(c for d in own.values() for c in d["cues"]):
        # a fresh round each time: the whole bag to choose from
        q = QuickReplies(ENTRIES, rng=random.Random(k))
        a = q.answer("Wait, what are you doing?", 10, entrance=entry["name"], avoid=("happy", last))
        assert a is not None and a.attached and a.text in own
        # never filtered by what the last reply showed: the line's own cues, all of them
        assert list(a.cues) == own[a.text]["cues"] and a.sfx == own[a.text]["sfx"]
        # and it is one that doesn't repeat the cue the last reply ended on
        assert last not in a.cues or all(last in d["cues"] for d in own.values())


@pytest.mark.parametrize("entry", SIGNATURE, ids=lambda e: e["name"])
def test_every_answer_plays_all_its_cues_big_and_full_body(entry):
    from irene.app import Core
    from irene.quick import Answer

    core = Core()
    for d in entry["doing_answers"]:
        core.last_react = d["cues"][0]  # the previous reply ended on this answer's own cue
        answer = Answer("doing", d["line"], tuple(d["cues"]), False, None, d["sfx"], attached=True)
        timeline, last = core.attached_shows(answer)
        played = [m["value"] for _, m in timeline]
        # every one of the line's own cues, none swapped out
        assert set(d["cues"]) <= set(played), (d["line"], d["cues"], played)
        body = [m for _, m in timeline if m["type"] in ("reaction", "activity")]
        assert body, f"{d['line']!r}: nothing moves her body"
        assert all(m.get("big") for m in body if m["type"] == "reaction")
        # the body cues one after another, not all at once
        times = [at for at, m in timeline if m["type"] in ("reaction", "activity")]
        assert len(set(times)) == len(times)
        assert last is not None and core.last_react == last.name
        assert d["sfx"], "every signature answer has its sound"


def test_the_answer_really_plays_its_sound_and_every_cue_and_says_so_in_the_log(caplog):
    """The whole path (_respond_quick), with a speaker that plays at once: the clip
    goes out with its sound under it, every cue reaches the HUD, the turn ends, and
    the log names the cues and the sound. Round 10: a patch slip left the clip
    unplayed and the turn hung until the watchdog - no unit test went this far."""
    import asyncio
    import logging
    import threading
    import time

    import numpy as np

    from irene.app import Core
    from irene.quick import Answer

    class Bridge:
        def __init__(self):
            self.sent = []
            self.current_state = "listening"
            self.hud_connected = True

        async def send(self, m):
            self.sent.append(m)

        def send_threadsafe(self, m):
            self.sent.append(m)

        async def state(self, v):
            self.current_state = v

        async def emotion(self, v):
            self.sent.append({"type": "emotion", "value": v})

        async def transcript(self, *_a):
            pass

    class Speaker:
        engine = "turbo"

        def __init__(self):
            self.played = []

        def play(self, audio, levels, marks=(), done=None):
            self.played.append(audio)

            def run():
                for _, fn in marks:
                    fn()
                time.sleep(0.05)
                if done:
                    done(True)

            threading.Thread(target=run, daemon=True).start()

        def speak(self, *_a, **_k):
            raise AssertionError("a rendered line is played, not said live")

        def stop(self):
            pass

        def progress(self):
            return (0.0, sum(len(a) for a in self.played) / 24000)

    entry = next(e for e in SIGNATURE if e["name"] == "kendo")
    d = next(x for x in entry["doing_answers"] if len(x["cues"]) >= 2)
    line = np.full(4800, 0.1, np.float32)
    answer = Answer("doing", d["line"], tuple(d["cues"]), False, line, d["sfx"], attached=True)

    async def run():
        core = Core()
        core.bridge = Bridge()
        core.speaker = Speaker()
        core.muted = False
        core.last_entrance = "kendo"
        await asyncio.wait_for(core._respond_quick("Wait, what are you doing?", answer, time.perf_counter()), 5)
        await asyncio.sleep(max(a for a in (2.0, 2.6)))  # the later cues land
        return core

    with caplog.at_level(logging.INFO, logger="irene"):
        core = asyncio.run(run())
    played = core.speaker.played
    assert len(played) == 1 and len(played[0]) > len(line), "the clip, with its sound in front"
    shown = [m.get("value") for m in core.bridge.sent if m.get("type") in ("reaction", "activity", "emotion")]
    assert set(d["cues"]) <= set(shown), (d["cues"], shown)
    assert any(m.get("big") for m in core.bridge.sent if m.get("type") == "reaction")
    logged = [r.getMessage() for r in caplog.records if "doing answer" in r.getMessage()]
    assert logged and d["sfx"] in logged[0] and all(c in logged[0] for c in d["cues"])
