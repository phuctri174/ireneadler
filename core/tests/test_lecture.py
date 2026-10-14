"""Lecture capture (irene/lecture.py, lectures.py, lecture_summary.py, tools/lecture.py):
system audio written down as it goes, a pipeline apart from his mic - no speaker
check anywhere on it - sharing his Whisper, text only on disk; the summary
map-reduced with every quoted alert found in the transcript."""
import asyncio
import json
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from irene import fast, lecture, lecture_summary, stt, vram
from irene.lecture import Chunker, LectureCapture, Writer, Session, clean, clock
from irene.stt import Segment

RATE = 16000


def tone(seconds: float, amp: float = 0.1) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


# ---- chunks -------------------------------------------------------------------------------------


def test_chunks_are_cut_at_a_pause_between_min_and_max_and_keep_the_timeline():
    c = Chunker(min_s=4, max_s=6)
    # speech, a pause at 4.8-5.2 s, speech
    audio = np.concatenate([tone(4.8), np.zeros(int(0.4 * RATE), np.float32), tone(4.8)])
    chunks = []
    for i in range(0, len(audio), 8000):
        chunks += c.feed(audio[i:i + 8000])
    tail = c.flush()
    chunks += [tail] if tail else []
    assert 4.8 <= len(chunks[0].audio) / RATE <= 5.2  # cut inside the pause
    assert chunks[0].start_s == 0.0
    assert chunks[1].start_s == pytest.approx(len(chunks[0].audio) / RATE)
    assert sum(len(ch.audio) for ch in chunks) == len(audio)  # nothing lost, nothing doubled


def test_a_chunk_never_exceeds_max_even_without_a_pause():
    c = Chunker(min_s=4, max_s=6)
    out = c.feed(tone(13))
    assert all(len(ch.audio) <= 6 * RATE for ch in out) and len(out) == 2


# ---- what Whisper wrote -------------------------------------------------------------------------


def test_clean_keeps_speech_with_session_times_and_drops_whispers_inventions():
    segs = [
        Segment(0.0, 4.0, " Today we start with binary search.", -0.2, 0.01, 1.3),
        Segment(4.0, 6.0, "Thank you.", -0.4, 0.2, 1.0),  # its stock caption on noise
        Segment(6.0, 9.0, "the the the the the the the the the the", -0.3, 0.1, 3.4),  # a loop
        Segment(9.0, 12.0, "mumble", -1.6, 0.8, 1.1),  # it was sure there was no speech
    ]
    lines = clean(segs, offset_s=600.0)
    assert lines == [{"t": 600.0, "end": 604.0, "text": "Today we start with binary search.", "lp": -0.2}]


def test_clock():
    assert clock(65) == "01:05" and clock(3725) == "1:02:05"


# ---- on disk: text only, the moment it exists -----------------------------------------------------


def test_lines_are_on_disk_at_once_and_a_torn_last_line_is_skipped(tmp_path):
    s = Session("x", tmp_path / "x", time.time())
    w = Writer(s)
    w.append([{"t": 0.0, "end": 2.0, "text": "hello", "lp": -0.1}])
    # read back while still open: a crash now loses nothing written
    assert json.loads((s.dir / "transcript.jsonl").read_text(encoding="utf-8").splitlines()[0])["text"] == "hello"
    with open(s.dir / "transcript.jsonl", "a", encoding="utf-8") as f:
        f.write('{"t": 3.0, "text": "torn')  # the process died mid-line
    _meta, lines = lecture.load(s.dir)
    assert [x["text"] for x in lines] == ["hello"]
    w.close()


class FakeSource:
    """A loopback that plays `audio` as fast as it can, in 0.5 s blocks."""

    def __init__(self, audio):
        self.audio = audio

    def __call__(self, device, on_block):
        self.on_block = on_block
        return self

    def start(self):
        for i in range(0, len(self.audio), 8000):
            self.on_block(self.audio[i:i + 8000], time.perf_counter())

    def stop(self):
        pass


class FakeTranscriber:
    def __init__(self):
        self.calls = []

    def transcribe_background(self, audio, prompt="", beam_size=None):
        self.calls.append((len(audio), prompt))
        n = len(self.calls)
        return [Segment(0.0, len(audio) / RATE, f"Lecturer sentence number {n} about graphs.", -0.25, 0.02, 1.2)]


def capture_of(tmp_path, audio, monkeypatch):
    monkeypatch.setattr(lecture, "settings", lambda: {"chunk_min_s": 4, "chunk_max_s": 6, "silence_rms": 0.004, "beam_size": 3})
    tr = FakeTranscriber()
    cap = LectureCapture(lambda: tr, source_factory=FakeSource(audio), store=tmp_path)
    return cap, tr


def test_someone_elses_voice_is_written_down_whole_and_no_audio_is_kept(tmp_path, monkeypatch):
    cap, tr = capture_of(tmp_path, tone(14), monkeypatch)
    session = cap.start()
    done = cap.stop()
    _meta, lines = lecture.load(done.dir)
    # every chunk of the lecture reached Whisper and the transcript: nothing was gated away
    assert len(tr.calls) == 3 and len(lines) == 3 and done.words == sum(len(x["text"].split()) for x in lines)
    # the previous line goes in as Whisper's prompt (continuity across chunks)
    assert tr.calls[1][1].startswith("Lecturer sentence number 1")
    assert sorted(p.name for p in session.dir.iterdir()) == ["meta.json", "transcript.jsonl"]


def test_the_lecture_pipeline_never_touches_the_speaker_check():
    """The lecturer is not him: the speaker check would discard the whole lecture.
    Nothing on the lecture path imports or calls it."""
    root = Path(lecture.__file__).parent
    for name in ("lecture.py", "lectures.py", "lecture_summary.py"):
        src = (root / name).read_text(encoding="utf-8")
        code = [line for line in src.splitlines() if line.strip().startswith(("import ", "from ")) or "(" in line]
        imports = " ".join(line for line in code if line.strip().startswith(("import ", "from ")))
        assert "speaker_id" not in imports, name
        assert not any(call in line for line in code for call in ("is_him(", ".score(", "verifier.", "SpeakerCheck(")), name


def test_silence_is_never_sent_to_whisper(tmp_path, monkeypatch):
    cap, tr = capture_of(tmp_path, np.zeros(14 * RATE, np.float32), monkeypatch)
    cap.start()
    done = cap.stop()
    assert tr.calls == [] and done.words == 0


def test_her_own_voice_through_the_speakers_is_zeroed_not_transcribed(tmp_path, monkeypatch):
    cap, tr = capture_of(tmp_path, tone(14), monkeypatch)
    # she is audible for the whole capture
    cap.her.tap(np.full(24000, 0.3, np.float32), time.perf_counter() + 60)
    cap.start()
    done = cap.stop()
    assert tr.calls == [] and done.dropped_s == pytest.approx(14.0)


def test_a_silent_tap_block_is_not_her_speaking():
    her = lecture._HerVoice()
    her.tap(np.zeros(1024, np.float32), time.perf_counter() + 5)
    assert not her.overlaps(time.perf_counter(), 0.5)


# ---- one Whisper, his turns first ------------------------------------------------------------------


class SlowModel:
    def __init__(self):
        self.order = []

    def transcribe(self, audio, **kw):
        self.order.append("mic" if kw.get("without_timestamps") else "lecture")
        time.sleep(0.05)
        return iter([]), None


def test_a_lecture_chunk_waits_while_his_turn_is_being_transcribed():
    tr = stt.Transcriber.__new__(stt.Transcriber)
    tr.__init__.__func__  # noqa: B018 - built by hand: no model on disk in a test
    tr.language, tr.beam_size, tr.hotwords, tr.prompt = "en", 3, "", ""
    tr._lock = threading.Lock()
    tr._foreground = 0
    tr._foreground_lock = threading.Lock()
    tr._foreground_clear = threading.Event()
    tr._foreground_clear.set()
    model = SlowModel()
    tr._model = model
    tr._front(+1)  # his turn is queued for the model
    t = threading.Thread(target=lambda: tr.transcribe_background(np.zeros(RATE, np.float32)))
    t.start()
    time.sleep(0.1)
    assert model.order == []  # the lecture waits
    tr._front(-1)
    t.join(2)
    assert model.order == ["lecture"]


# ---- the summary: map-reduce, every quote checked -------------------------------------------------


def transcript(n=60):
    lines, t = [], 0.0
    for i in range(n):
        text = f"Sentence {i} about hashing and tables with chaining and probing."
        if i == 40:
            text = "Problem set two is due next Thursday, so start early."
        lines.append({"t": t, "end": t + 20, "text": text, "lp": -0.2})
        t += 20
    return lines


class FakeChat:
    def __init__(self):
        self.prompts = []

    async def __call__(self, messages):
        p = messages[0]["content"]
        self.prompts.append(p)
        if p.startswith("Below are the topics"):
            ids = [line.split(" ")[0] for line in p.split("Topics:\n", 1)[1].splitlines() if line.strip()]
            return json.dumps({"overview": "It was all about hashing.",
                               "sections": [{"title": "Hash tables", "ids": ids[:1], "points": ["Chaining resolves collisions."]},
                                            {"title": "Open addressing", "ids": ids[1:], "points": ["Probing finds a free slot."]}]})
        alerts = []
        if "Problem set two" in p:
            alerts = [{"kind": "deadline", "text": "Problem set 2 due Thursday.", "quote": "problem set two is due next Thursday"},
                      {"kind": "exam", "text": "Hashing is on the final.", "quote": "hashing will definitely be on the final exam"}]
        return "Sure! ```json\n" + json.dumps({"topics": [{"title": "Hashing", "start": "00:00", "points": ["Tables map keys."]}], "alerts": alerts}) + "\n```"


def test_summary_is_map_reduced_and_a_quote_not_in_the_transcript_is_dropped():
    chat = FakeChat()
    lines = transcript()
    s = asyncio.run(lecture_summary.summarize(lines, {"id": "s1", "seconds": 1200}, chat, window_words=200))
    maps = [p for p in chat.prompts if p.startswith("You are reading part")]
    assert len(maps) > 2  # never the whole lecture at once
    assert all(len(p.split()) < 600 for p in maps)
    # the deadline is really in the transcript; the "exam" quote was made up
    assert [a["kind"] for a in s.alerts] == ["deadline"] and s.alerts[0]["at"] == 800.0
    # times come from the transcript (the ids), not from the model
    assert s.sections[0]["start"] == 0.0 and s.sections[1]["start"] > 0


def test_speech_says_topics_and_what_to_act_on_and_the_panel_has_the_transcript():
    s = asyncio.run(lecture_summary.summarize(transcript(), {"id": "s1", "seconds": 1200, "started": 1760000000}, FakeChat(), window_words=200))
    spoken = " ".join(lecture_summary.speech(s))
    assert "Hash tables and Open addressing" in spoken and "Problem set 2 due Thursday" in spoken and "13:20" in spoken
    panel = lecture_summary.panel_content(s, transcript())
    texts = [b.get("text", "") for b in panel["blocks"]]
    assert any(t.startswith("[00:00] Sentence 0") for t in texts)  # the full transcript
    assert any(b["kind"] == "quote" and "problem set two" in b["text"].lower() for b in panel["blocks"])


def test_nothing_to_act_on_is_said_plainly():
    s = lecture_summary.Summary("Overview.", [{"title": "A", "start": 0, "end": 1, "points": []}], [], {"grade": "good"}, {})
    assert "didn't hear anything that sounded like homework" in " ".join(lecture_summary.speech(s))


def test_an_unreadable_part_becomes_an_honest_gap():
    async def junk(_messages):
        return "I can't do JSON today"

    s = asyncio.run(lecture_summary.summarize(transcript(20), {}, junk, window_words=200))
    assert s.gaps and s.sections  # the parts' own placeholders, never invented content
    assert any("couldn't" in x for x in lecture_summary.speech(s))


def test_quality_is_graded_from_whispers_own_confidence():
    good = lecture_summary.quality([{"t": 0, "end": 60, "text": "word " * 150, "lp": -0.2}], {})
    rough = lecture_summary.quality([{"t": 0, "end": 60, "text": "word " * 150, "lp": -1.1}], {})
    assert good["grade"] == "good" and rough["grade"] == "rough"


def test_retrieval_finds_where_it_was_said_and_says_so_when_it_wasnt():
    lines = transcript()
    lines[25] = {"t": 500.0, "end": 520.0, "text": "Universal hashing picks a random hash function from a family.", "lp": -0.2}
    found = lecture_summary.retrieve(lines, "what did they say about universal hashing?")
    assert any("Universal hashing" in p["text"] for p in found[:5])
    assert "doesn't seem to have come up" in lecture_summary.ask_text("quantum", lecture_summary.retrieve(lines, "quantum entanglement"))


def test_which_section_by_number_ordinal_or_title():
    s = lecture_summary.Summary("", [{"title": "Hash tables", "start": 0, "end": 1, "points": []},
                                     {"title": "Open addressing", "start": 1, "end": 2, "points": []}], [], {}, {})
    assert lecture_summary.which_section("2", s) == 2
    assert lecture_summary.which_section("the second one", s) == 2
    assert lecture_summary.which_section("open addressing", s) == 2
    assert lecture_summary.which_section("9", s) is None


# ---- the fast path ---------------------------------------------------------------------------------


@pytest.mark.parametrize("said,tool", [
    ("Listen to this lecture", "lecture_start"),
    ("Irene, take notes on this class for me", "lecture_start"),
    ("stop listening to the lecture", "lecture_stop"),
    ("the meeting's over", "lecture_stop"),
    ("summarize the lecture", "lecture_summary"),
    ("what was the lecture about?", "lecture_summary"),
])
def test_plain_lecture_commands_need_no_model(said, tool):
    assert f'"name": "{tool}"' in fast.direct_call(said)


@pytest.mark.parametrize("said", ["the lecture was boring", "I have a lecture tomorrow", "stop listening", "my professor talks too fast"])
def test_talk_about_lectures_is_not_a_command(said):
    assert fast.direct_call(said) is None


def test_bare_stop_listening_is_the_lecture_only_while_capturing(monkeypatch):
    from tools import lecture as lecture_tool

    monkeypatch.setattr(lecture_tool, "LECTURES", type("L", (), {"active": True})())
    assert '"lecture_stop"' in fast.direct_call("stop listening")


# ---- the PC kept awake; the model parked ------------------------------------------------------------


def test_the_lecture_keeps_the_pc_awake_after_the_screens_come_back(monkeypatch):
    from tools import power

    held = []
    monkeypatch.setattr(power, "_keep", held.append)
    monkeypatch.setattr(power, "_AWAKE", set())
    power.stay_awake("lecture", True)
    power.stay_awake("dark", True)
    power.stay_awake("dark", False)  # he woke the screens
    assert held[-1] & power.ES_SYSTEM_REQUIRED
    power.stay_awake("lecture", False)
    assert not held[-1] & power.ES_SYSTEM_REQUIRED


def test_the_vram_guard_leaves_a_parked_model_alone():
    calls = []

    class LLM:
        model = "gemma3:12b"

        async def placement(self):
            calls.append("ps")
            return None

        async def warm(self):
            calls.append("warm")
            return True

    g = vram.VramGuard(LLM(), idle=lambda: True)
    g.parked = "lecture"
    assert asyncio.run(g.check()) is False and calls == []


def test_background_warmups_never_load_a_parked_model():
    """A lecture holds gemma out of VRAM: the prompt-cache warm-up (after a turn)
    must not load it back - only a real request may (Round: it did, twice, live)."""
    from irene.llm import Ollama

    llm = Ollama()
    sent = []

    class Client:
        async def post(self, *a, **k):
            sent.append(a)
            raise AssertionError("prefill reached Ollama while parked")

    llm._client = Client()
    llm.parked = True
    asyncio.run(llm.prefill([{"role": "user", "content": "hi"}]))
    assert sent == []


def test_the_summary_counts_as_a_slow_tool_and_every_model_call_is_a_sign_of_life():
    """Live, the watchdog cancelled a summary 15 s into its first map call as "stuck"."""
    from irene import app, lectures

    assert "lecture_summary" in app.SLOW_TOOLS

    class Core:
        _progress_at = 0.0

        class llm:
            @staticmethod
            async def chat(messages, temperature=0.6, json_mode=False):
                return "{}"

    lec = lectures.Lectures.__new__(lectures.Lectures)
    lec.core = Core()
    asyncio.run(lec._chat([{"role": "user", "content": "x"}]))
    assert lec.core._progress_at > 0


def test_gemmas_misordered_brackets_are_repaired():
    raw = ('```json\n{"topics": [{"title": "Defining Algorithms", "start": "02:21", "points": ["a", "b."}]}, "alerts": []}\n```')
    found = lecture_summary._json(raw)
    assert found == {"topics": [{"title": "Defining Algorithms", "start": "02:21", "points": ["a", "b."]}], "alerts": []}


def test_a_lecture_nothing_could_be_summarised_from_gets_no_invented_overview():
    """Live: the only part was unreadable, the reduce got an empty "Part 1" and made up
    a lecture on the history of AI. Now nothing reaches the reduce and nothing is said
    about the content."""
    reduce_calls = []

    async def chat(messages):
        if messages[0]["content"].startswith("Below are the topics"):
            reduce_calls.append(1)
            return '{"overview": "We covered the history of AI.", "sections": []}'
        return "not json at all"

    s = asyncio.run(lecture_summary.summarize(transcript(10), {}, chat, window_words=2000))
    assert reduce_calls == [] and s.overview == ""
    assert "history of AI" not in " ".join(lecture_summary.speech(s))
    assert all(sec["title"].endswith("(not summarised)") for sec in s.sections)


def test_a_failed_model_call_is_a_gap_not_a_crash():
    calls = []

    async def flaky(messages):
        calls.append(1)
        if len(calls) <= 2:
            raise RuntimeError("500 Internal Server Error")
        return await FakeChat()(messages)

    s = asyncio.run(lecture_summary.summarize(transcript(10), {}, flaky, window_words=2000))
    assert s.gaps and s.overview == ""  # both tries of the only part failed: said, not invented


@pytest.mark.parametrize("kind,quote,want", [
    # live false positives (the 17-minute MIT run): general advice, a policy to read
    ("deadline", "you want to make sure your code runs in a reasonable amount of time on large inputs", None),
    ("deadline", "please read the collaboration policy on the course website", None),
    ("exam", "we expect you to know asymptotic complexity from 6.042", None),
    # real ones
    ("deadline", "problem set two is due next Thursday at midnight", "deadline"),
    ("deadline", "the problem set has to be in by the 14th", "deadline"),
    ("deadline", "the first problem set goes out today", "homework"),  # work named, no time: homework
    ("homework", "there's a problem set that's going to go out today as well", "homework"),
    ("exam", "this will definitely be on the midterm", "exam"),
])
def test_an_alerts_kind_must_be_in_the_lecturers_own_words(kind, quote, want):
    assert lecture_summary.checked_kind(kind, quote) == want


def test_a_lecture_capture_starts_only_when_his_words_are_about_listening():
    """It parks the model and listens for hours: the model once called lecture_start
    for "what can you do about my slow computer?" - core refuses that."""
    from irene import brain

    assert not brain._LISTEN_WORDS.search("What can you do about my slow computer?")
    for asked in ("Listen to this lecture", "transcribe the meeting", "take notes on this class", "record the webinar"):
        assert brain._LISTEN_WORDS.search(asked), asked
