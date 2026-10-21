# Lecture capture

"Listen to this lecture" (or Ctrl+Alt+Shift+L) transcribes what the PC **plays** (a
lecture video, a meeting) and, on request, summarises it. It is never automatic.

```
WASAPI loopback ─► her-voice gate ─► chunker (18-30 s) ─► Whisper queue ─► transcript.jsonl (fsync per chunk)
  (lecture.py)      zero blocks         (lecture.py)       shared with the mic;      text only
                    while she speaks                       his turns go first
```

## Why it is a separate pipeline

The speaker check is the main defence on the mic path ([security-model.md](security-model.md#speaker-verification)).
On a lecture it would be fatal: the lecturer is not the owner, so the gate would
discard the whole lecture. So the loopback path never touches speaker verification,
the wake phrase or the echo canceller. Mic and loopback share exactly one thing, the
single Whisper model, through its queue. His own turns always go first, and there is
never a second Whisper in VRAM.

Recorded live (commit `930abfd`, 2026-10-12, MIT 6.006 lecture 1 played through the
room speakers with the mic live): the mic rejected every utterance (highest score
0.30 against the 0.35 threshold) while the loopback transcribed all of it.

## Privacy and durability

- **Text only.** Audio exists in memory for one chunk (at most 30 s) and is never
  written anywhere.
- **Written as it goes.** Each chunk's text is appended and fsynced at once; a crash
  loses at most the chunk in flight.
- **Her voice is not the lecture.** Blocks captured while she is audible are zeroed,
  keeping the timeline true.

## VRAM: the language model leaves while it listens

Whisper is all a capture needs, so gemma is unloaded when a capture starts
(`unload_llm: true`, `config/lecture.yaml`). Background warm-ups wait. A question
during the capture reloads it for that turn (a cold start), and it leaves again
after 120 s of quiet. It comes back when the capture stops, since the summary is
usually the next request.

## The summary: map-reduce with quote checks

A two-hour lecture (15-20k words) does not fit in the model's 16k context with the
persona in it, so it never goes to the model whole (`irene/lecture_summary.py`):

- **map:** each ~1,800-word window yields topics, key points, and anything that
  sounded like homework, a deadline or an exam hint, each **with a quote**.
- **check:** every quote is looked up in the transcript; an item whose quote isn't
  there is dropped.
- **reduce:** the windows' topics are merged into 3-8 sections in lecture order. The
  model names which windows each section covers, so the timestamps come from the
  transcript, never from the model.

Map and reduce calls use Ollama's JSON mode; without it the model closed brackets in
the wrong order often enough to lose parts. When a part could not be read, the reduce
step was once handed an empty placeholder and invented a lecture, so unreadable parts
now never reach it.

**Alerts are checked against the lecturer's words, not the model's labels.** A false
"deadline" (actually "read the collaboration policy") appeared in 2 of 3 runs. A
deadline must now name a time, homework must name the work, an exam hint must name a
quiz or exam; quotes are matched clause by clause, and what is kept is the
transcript's text. After the change, 3 runs on the same 17 minutes: the problem set
found 3/3, false alerts 0/3 (commit `80e0c22`, 2026-10-12).

**Follow-ups** ("what did they say about X?") retrieve transcript passages by BM25 and
answer only from them, with times. Lecture text is outside content: it sets the
[taint flag](security-model.md#taint-guard), so nothing that changes anything runs
after it in the same turn.

**The note.** The summary becomes a document (`irene/lecture_note.py`): overview, key
points, definitions with the lecturer's exact words, alerts with quotes and times,
sections each with a drawing she composed from that section's words (a label the
lecturer never said is dropped), and the full transcript. Further reading from the
web is added only when he asks, in a separately labelled section, so nothing she found
online can pass for what the lecturer taught.

## Measured

All from commit `930abfd` (2026-10-12) unless noted; MIT 6.006 lecture 1
(CC BY-NC-SA), played to a headset output.

| What | Result |
|---|---|
| longest continuous run | **17 minutes**, not a full lecture (see below) |
| word error rate against MIT's own transcript | 4.6% over the first 15 minutes |
| transcription time per 20-30 s chunk | 0.4-1 s; backlog 0 throughout |
| core's RAM over 17 minutes | 3.33 → 3.36 GB |
| total VRAM while listening | 6.4 GB (gemma unloaded: 7.9 GB freed) |
| core killed mid-capture, restarted by the keeper | transcribing again after a 12 s gap (commit `80e0c22`) |

**The 17-minute stop.** A planned 30-minute run ended at 17 minutes when core and the
HUD closed together, with no trace: no Python traceback, and nothing in the Windows
event log. The cause is still unknown. What changed so the next one is diagnosable
(`irene/lifeline.py`, `hud/src-tauri/src/lifeline.rs`, `core/scripts/keeper.py`):

- both processes write a heartbeat every 30 s and an exit record for every way they
  can end; a run with no exit record is written up at the next start, with its last
  heartbeat
- a keeper restarts core after any death it didn't choose, and a capture resumes into
  the same transcript with the downtime recorded as a gap
- the HUD does **not** restart itself

## Limitations

- Tested for 17 continuous minutes plus shorter runs, not a full lecture.
- Captures one output device. If it disappears (a monitor's speakers when screens-off
  turns the monitors off), the capture retries every 2 s and falls back to the
  default output; the gap is filled with silence so the timeline stays true, and what
  played on the lost device is not heard.
