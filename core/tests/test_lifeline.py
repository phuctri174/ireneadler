"""Why core stopped is always written down (irene/lifeline.py), core comes back after a
death it didn't choose (scripts/keeper.py), and a lecture it was capturing resumes."""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

from irene import lecture, lifeline
from irene.lecture import LectureCapture, Session, Writer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keeper  # noqa: E402


def lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_an_exit_is_recorded_once_with_the_first_reason(tmp_path):
    life = lifeline.Lifeline("core", status=lambda: {"lecture": {"words": 12}}, heartbeat=tmp_path / "hb.jsonl", exits=tmp_path / "ex.jsonl")
    life.exit_record("console window closed")
    life.exit_record("normal exit")  # the interpreter's own exit follows a console close
    (record,) = lines(tmp_path / "ex.jsonl")
    assert record["reason"] == "console window closed" and record["state"] == {"lecture": {"words": 12}}


def test_a_run_that_left_no_exit_record_is_written_down_as_unknown_with_its_last_heartbeat(tmp_path):
    hb, ex = tmp_path / "hb.jsonl", tmp_path / "ex.jsonl"
    ex.write_text(json.dumps({"who": "core", "pid": 111, "event": "start"}) + "\n", encoding="utf-8")
    hb.write_text(json.dumps({"who": "core", "pid": 111, "uptime_s": 1020, "rss_gb": 3.36}) + "\n", encoding="utf-8")
    verdict = lifeline.Lifeline("core", heartbeat=hb, exits=ex).previous_run()
    assert verdict["reason"] == "unknown - no exit record"
    assert verdict["last_heartbeat"]["uptime_s"] == 1020
    assert lines(ex)[-1]["found_at_next_start"] is True


def test_a_run_that_said_how_it_ended_is_left_as_it_said(tmp_path):
    ex = tmp_path / "ex.jsonl"
    ex.write_text("\n".join(json.dumps(r) for r in [{"who": "core", "pid": 5, "event": "start"},
                                                    {"who": "core", "pid": 5, "event": "exit", "reason": "ctrl+c"}]) + "\n", encoding="utf-8")
    assert lifeline.Lifeline("core", heartbeat=tmp_path / "hb", exits=ex).previous_run()["reason"] == "ctrl+c"
    assert len(lines(ex)) == 2


def test_a_heartbeat_has_the_numbers_a_post_mortem_needs(tmp_path, monkeypatch):
    monkeypatch.setattr(lifeline, "gpu_used_gb", lambda: 6.4)
    sample = lifeline.Lifeline("core", status=lambda: {"state": "listening"}, heartbeat=tmp_path / "hb", exits=tmp_path / "ex").sample()
    assert {"uptime_s", "rss_gb", "ram_used_gb", "gpu_used_gb", "threads", "state"} <= set(sample)
    assert sample["threads"] >= 1 and sample["gpu_used_gb"] == 6.4


# ---- the keeper ----------------------------------------------------------------------------------


def test_the_keeper_restarts_after_a_death_core_did_not_choose():
    assert keeper.should_restart(None, 1)[0]  # killed without a word
    assert keeper.should_restart({"reason": "unhandled exception"}, 1)[0]
    assert keeper.should_restart({"reason": "terminate signal"}, 1)[0]


def test_the_keeper_lets_a_chosen_exit_stand():
    for reason in ("ctrl+c", "console window closed", "windows shutting down", "normal exit"):
        assert not keeper.should_restart({"reason": reason}, 0)[0], reason


# ---- a lecture core was capturing when it died -----------------------------------------------------


class Source:
    def __init__(self, device, on_block):
        self.on_block = on_block

    def start(self):
        pass

    def stop(self):
        pass


class Whisper:
    def transcribe_background(self, audio, prompt="", beam_size=None):
        from irene.stt import Segment

        return [Segment(0.0, 2.0, "resumed words", -0.2, 0.01, 1.1)]


def died_mid_capture(tmp_path, monkeypatch, minutes_ago=2, heard_s=600.0):
    monkeypatch.setattr(lecture, "settings", lambda: {"chunk_min_s": 4, "chunk_max_s": 6})
    started = time.time() - minutes_ago * 60 - heard_s
    s = Session("2026-10-12_192426", tmp_path / "2026-10-12_192426", started, device="ONIKUMA", words=2217, lines=144, seconds=heard_s)
    w = Writer(s)
    w.append([{"t": 595.0, "end": 599.0, "text": "the last line before it died", "lp": -0.2}])
    w.meta()
    (tmp_path / lecture.ACTIVE).write_text(json.dumps({"id": s.id}), encoding="utf-8")
    meta = s.dir / "meta.json"
    os.utime(meta, (time.time() - minutes_ago * 60, time.time() - minutes_ago * 60))
    return LectureCapture(lambda: Whisper(), source_factory=Source, store=tmp_path)


def test_an_interrupted_capture_resumes_the_same_transcript_with_the_gap_recorded(tmp_path, monkeypatch):
    cap = died_mid_capture(tmp_path, monkeypatch)
    session, quiet = cap.interrupted()
    assert session.id == "2026-10-12_192426" and 100 < quiet < 140
    assert session.last_text == "the last line before it died"  # Whisper's prompt carries on
    cap.resume(session)
    cap._on_block(np.full(6 * 16000, 0.1, np.float32), time.perf_counter())
    done = cap.stop()
    meta, got = lecture.load(done.dir)
    assert got[0]["text"] == "the last line before it died" and got[-1]["text"] == "resumed words"
    # the new words sit at wall-clock time after the gap, not back at 10:00
    assert got[-1]["t"] > 600 + 100
    (gap,) = meta["gaps"]
    assert gap[0] == 600.0 and gap[1] > 700
    assert not (tmp_path / lecture.ACTIVE).exists()


def test_a_capture_interrupted_long_ago_is_closed_not_resumed(tmp_path, monkeypatch):
    cap = died_mid_capture(tmp_path, monkeypatch, minutes_ago=45)
    assert cap.interrupted() is None
    meta, _ = lecture.load(tmp_path / "2026-10-12_192426")
    assert meta["stopped"] and not (tmp_path / lecture.ACTIVE).exists()


def test_a_cleanly_stopped_capture_leaves_nothing_to_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(lecture, "settings", lambda: {"chunk_min_s": 4, "chunk_max_s": 6})
    cap = LectureCapture(lambda: Whisper(), source_factory=Source, store=tmp_path)
    cap.start()
    assert (tmp_path / lecture.ACTIVE).exists()
    cap.stop()
    assert not (tmp_path / lecture.ACTIVE).exists() and cap.interrupted() is None
