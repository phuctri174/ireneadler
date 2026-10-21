# Voice pipeline

```
mic 16 kHz ─► echo canceller ─► Silero VAD ─► end-of-speech ─► speaker check ─► Whisper ─► wake phrase? ─► dispatch
 (listen.py)    (aec.py)          (CPU)       (listen.py)     (ECAPA, CPU)    (GPU fp16)   (wake.py)     (dispatch.py)
                                                                                                              │
speaker ◄── levelling + limiter ◄── TTS per sentence ◄── <speak> only ◄── reply parser ◄── model or fast path ◄┘
            (levels.py)            (tts.py, voice.py)     (reply.py)
```

The order matters. The speaker check runs **before** Whisper, so a voice that isn't his
is never transcribed at all. The wake phrase is matched **after** Whisper, on text.

## Hearing

**Voice activity.** Silero VAD on the CPU, 32 ms blocks at 16 kHz (`irene/listen.py`).

**End of speech.**

- *Problem.* Too short a wait cuts him off mid-thought; too long makes every reply
  feel slow.
- *Mechanism.* By default it waits a full 3.0 s of silence. It shortens to 0.9 s only
  when the words so far are a complete phrase (Whisper's punctuation, not ending on
  "and" or "um") **and** his pitch fell, or it was a question (`config/voice.yaml`
  `end_of_speech`).
- *Cost.* A trailing-off sentence waits the full 3 s.
- The endpointer is pure (frames in, events out), so its rules are unit-tested without
  a microphone.

**Speaker verification, before transcription.**

- *Problem.* TV, videos, other people in the room and her own voice all reach the mic.
  Only his voice may be acted on.
- *Mechanism.* Every utterance is scored against his voiceprints (ECAPA-TDNN from
  SpeechBrain, vendored, on the CPU). Below 0.35 it is never transcribed, never a turn,
  and never reaches the model.
- *Why the CPU.* No VRAM left on the GPU. It costs 114 ms per utterance, hidden behind
  the end-of-speech wait.
- *Why 0.35.* His held-out takes scored 0.55-0.88; her own TTS at most 0.27 (commit
  `b04f80f`).
- Details: [security-model.md](security-model.md#speaker-verification).

**Speech to text.** faster-whisper large-v3-turbo on the GPU, **float16 only**
(`irene/stt.py` raises on any other compute type; see
[hardware-constraints.md](hardware-constraints.md#blackwell-sm_120-float16-only-for-whisper)).
It runs with beam size 3, in English, with his vocabulary passed as hotwords.

- **The hotword budget is full** (223 tokens). Words Whisper reliably mishears in a mode
  command ("shiai" as "CI") are put back in code where the command stands
  ([modes.md](modes.md#entering-a-mode-matched-in-code)), not added as hotwords.
- **Unsure transcripts aren't acted on.** If the average log-probability is below
  -0.85, or the no-speech probability above 0.6, she asks him to say it again.

**Wake phrase.**

- *Problem.* She should act only when addressed.
- *Considered: openWakeWord*, the stack's planned wake-word engine. It has no "Irene"
  model. The config key `wake.engine` still lists it, but nothing implements it.
- *Mechanism.* A phrase match at the start of a transcript that already passed the
  speaker check: "Hey Irene", "Irene Adler", "Wake up Irene" and one more
  (`irene/wake.py`). It accepts sound-alike spellings Whisper produces ("Hey Eileen",
  "Irene Adla"). After she speaks she stays awake for 8 s, with no wake phrase needed.
- *Cost.* Every utterance goes through Whisper before it's known to be addressed to her,
  which is GPU time on talk she ignores. A trained wake-word model for "Irene" is on the
  roadmap.

## Talking over her

**Problem.** Her voice comes back through the speakers into the mic. Without a defence
she interrupts herself; with a crude one he can't interrupt her.

**Mechanism.** Two defences:

1. **Echo cancellation** (`irene/aec.py`). A partitioned-block frequency-domain NLMS
   filter (512-sample blocks, a 0.5 s echo path in 16 partitions) predicts what she
   played and subtracts it. It freezes its learning while he talks over her, so it
   never learns to cancel him.
2. **Barge-in needs more than the echo.** While she speaks, speech only counts as him if
   it is surer (VAD 0.8), longer, and clearly louder than the echo she has been hearing.
   It must also pass the speaker check.

**Measured** (commit `b04f80f`). 78 s of her speaking with the mic live produced 0
barge-ins. Him talking over her (score 0.50) still stopped her.

## Speaking

**The engine.**

- *Mechanism.* Chatterbox-Turbo (Resemble AI, MIT), cloned at startup from
  `core/assets/voice/af_bella_ref.wav`. That clip is a render of Kokoro's stock
  `af_bella` voice, not a recording of a person. The clone is computed in memory and
  never saved. Kokoro-82M is the fallback, loaded only if Turbo fails to load or runs
  out of memory mid-conversation; then it stays (`irene/voice.py`).
- *Why Turbo over Kokoro.* It's expressive, and performs `[laugh] [sigh] [gasp]
  [chuckle]` written in the text. The project's CLAUDE.md lists Kokoro as the TTS; the
  code uses Turbo first.
- *Cost.* Turbo doesn't stream: a sentence is synthesised whole. It's installed
  `--no-deps` because it pins torch 2.6, which has no kernels for this GPU.

**Streaming.**

- Only `<speak>` content reaches TTS. `<display>` is screen-only, and text outside the
  tags is never read aloud (`irene/reply.py`).
- Sentences go to TTS as each one completes, while the model is still writing.
- Because Turbo synthesises a whole chunk at a time, long sentences are split at commas,
  and each chunk is synthesised while the previous one plays. First audio went from
  1.26 s to 0.49 s on a 3-sentence reply (commit `38839c8`).

**Lines that need no synthesis.**

- Short openers ("Ooh!", "Hmm...") and everyday exchanges (hello, thanks, goodbye) are
  rendered ahead of time in her voice and play from memory (`irene/openers.py`,
  `irene/quick.py`).
- A quick reply needs the whole message to match, so "thanks, and set a timer" still
  goes to the model.
- Everything she is ever asked to say goes through `config/pronunciation.yaml`, applied
  in `voice.py` in the form the engine understands: Kokoro gets a phoneme override,
  Turbo a respelling. It used to be applied only to live replies, so a cached line
  ("Mister Tri!") was said "Try".

**Levels.** Each sentence is normalised to the same loudness, and everything she plays
goes through one master gain and a soft limiter (`irene/levels.py`).

**Her face follows what is heard,** not what was written: a sentence can carry a mark
that fires as its first sample reaches the speaker.

### The song-win bit

`irene/songwin.py`, `config/songwin.yaml`.

**What it is.** After she names a song he taught her
([memory-and-provenance.md](memory-and-provenance.md#teaching-and-recall-his-facts-answer-the-world)):

1. If his very next message only confirms ("Yes, it's correct"), she says "Haha, GG
   fucking easy Mr Tri" with her smug face.
2. If he then objects ("Hey, don't say that"), she answers "Oh really?" caught off guard,
   holds that face through 2 s of silence, then says "FUGGING EASY", arrogant.

These are his words, exactly. Any other message ends the bit, and it never starts
anywhere else.

**The problem it solved: timing.** The rock-paper-scissors bonk had lost its timing to
a line synthesised on demand.

**Mechanism.**

- The lines are rendered at startup through the same path as the skits
  (`skit.render_line` → `voice.take`: the pronunciation map, the silence check, the
  cache).
- "Oh really?", the hold and "FUGGING EASY" are **one clip**, and each face is a mark on
  that clip. Neither can drift from the audio.
- The command bar shows each line as it's said, not before.

**The pace is configurable** (`config/songwin.yaml`, commit `f8ab4c0`, after "the three
lines rush together"):

- each line's speaking rate (stretched at the same pitch: 0.82, 0.85, 0.68)
- every gap: 650 ms before the gloat, 0 before "Oh really?", 600 ms after it, the 2000 ms
  hold, 400 ms before "FUGGING EASY", the last face held 1500 ms

A gap is silence from the **last sample of the previous take** (its tail included) to
the first sample of the next. The file is read each time the bit plays. A changed speed
is re-rendered in the background and heard the time after.

**A bug found by listening.** Rendered in capitals, Turbo said "ding easy". The
pronunciation map now respells FUGGING; the text stays as he wrote it.

## Measured

| What | Result | Source |
|---|---|---|
| speaker check, his held-out corpus takes | scores 0.55-0.88 (threshold 0.35) | commit `b04f80f`, 2026-10-04 |
| speaker check, her own TTS | at most 0.27 | commit `b04f80f` |
| a TED talk played aloud for 60 s, her window up | 2 utterances scored (0.13, 0.07), no turn | commit `b04f80f` |
| speaker check cost on the CPU | 114 ms per utterance | commit `5f80462`, 2026-10-04 |
| Whisper word error rate on held-out corpus sentences (96 takes, 32 sentences), before/after his vocabulary as hotwords | 8.4% → 7.9% | commit `b04f80f` |
| first sentence ready for TTS, p50 / p95 | 885 / 1435 ms | evals, 2026-10-17 |
| first audio through core, p50, memory off / on (ABBA, 600 memories) | 1286 / 1033 ms (the difference is noise) | commit `d3fe54f`, 2026-10-13 |
| the song-win bit, live -Dev, 3 full runs, at the fixed timing before the pace config | his confirmation to her voice and smug face: 20-40 ms. The hold: 2000 ms of silence; the arrogant face 2.54-2.58 s into the clip, on the first sample of "FUGGING EASY" | socket timestamps, core.log, `skit.silences`, 2026-10-19 |

**Not measured.** The configurable pace (`f8ab4c0`) is unit-tested (`tests/test_songwin.py`)
but has **no recorded live run**. The Whisper LoRA fine-tune (`scripts/whisper_lora.py`)
exists but has not been run to completion.

## Lecture audio is a separate path

System audio for [lecture capture](lecture-capture.md) is captured through WASAPI
loopback and never goes through the speaker check, the wake phrase or the echo canceller.
The two paths share only the one Whisper instance, through its queue, with his turns
first.
