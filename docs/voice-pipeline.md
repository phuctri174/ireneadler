# Voice pipeline

```
mic 16 kHz ─► echo canceller ─► Silero VAD ─► end-of-speech ─► speaker check ─► Whisper ─► wake phrase? ─► dispatch
 (listen.py)    (aec.py)          (CPU)       (listen.py)     (ECAPA, CPU)    (GPU fp16)   (wake.py)     (dispatch.py)
                                                                                                              │
speaker ◄── levelling + limiter ◄── TTS per sentence ◄── <speak> only ◄── reply parser ◄── model or fast path ◄┘
            (levels.py)            (tts.py, voice.py)     (reply.py)
```

## Hearing

- **VAD.** Silero VAD on the CPU, 32 ms blocks at 16 kHz (`irene/listen.py`).
- **End of speech.** By default it waits a full 3.0 s of silence, so he can pause
  mid-thought. It shortens to 0.9 s only when the words so far are a complete phrase
  (Whisper's punctuation, not ending on "and" or "um") and his pitch fell, or it was
  a question (`config/voice.yaml` `end_of_speech`). The endpointer is pure (frames
  in, events out), so its rules are unit-tested without a microphone.
- **Speaker verification, before transcription.** Every utterance is scored against
  the owner's voiceprints (ECAPA-TDNN from SpeechBrain, vendored, on the CPU). Below
  0.35 it is never transcribed, never a turn and never reaches the model. Details
  and measurements are in [security-model.md](security-model.md#speaker-verification).
- **Speech to text.** faster-whisper large-v3-turbo on the GPU, **float16 only**
  (`irene/stt.py` raises on any other compute type; see
  [hardware-constraints.md](hardware-constraints.md)). Beam size 3, English, and the
  owner's vocabulary passed as hotwords. The hotword budget is full (223 tokens), so
  words Whisper reliably mishears in a mode command ("shiai" as "CI") are put back in
  code where the command stands (`irene/modes.py`), not added as hotwords. A transcript Whisper was unsure of (average
  log-probability below -0.85, or no-speech probability above 0.6) is not acted on:
  she asks him to say it again.
- **Wake phrase.** Stock openWakeWord has no "Irene" model, so the wake word is a
  phrase match at the start of a transcript that already passed the speaker check:
  "Hey Irene", "Irene Adler", "Wake up Irene" and one more (`irene/wake.py`,
  `config/voice.yaml`). The match accepts sounds-alike spellings Whisper produces
  ("Hey Eileen", "Irene Adla"). After she speaks she stays awake for 8 s, during
  which no wake phrase is needed. openWakeWord is **not used**; the config key
  `wake.engine` still lists it as an option, but nothing in the code implements it.

## Talking over her

Her voice comes back through the speakers into the mic. Two defences:

1. **Echo cancellation** (`irene/aec.py`): a partitioned-block frequency-domain NLMS
   filter (512-sample blocks, a 0.5 s echo path in 16 partitions) predicts and
   subtracts what she played. It freezes its learning while he talks over her, so it
   never learns to cancel him.
2. **Barge-in needs more than the echo.** While she speaks, speech only counts as
   him if it is surer (VAD 0.8), longer and clearly louder than the echo she has
   been hearing, and it must pass the speaker check.

Recorded (commit `b04f80f`, 2026-10-04): 78 s of her speaking with the mic live
produced 0 barge-ins; him talking over her (score 0.50) still stopped her.

## Speaking

- **Engine.** Chatterbox-Turbo (Resemble AI, MIT), cloned from a reference clip of
  Kokoro's `af_bella` voice. Kokoro-82M is the fallback: loaded only if Turbo fails
  to load or runs out of memory mid-conversation (`irene/voice.py`). The project's
  CLAUDE.md lists Kokoro as the TTS; the code uses Turbo first.
- **Streaming.** Only `<speak>` content reaches TTS; `<display>` is screen-only, and
  text outside the tags is never read aloud (`irene/reply.py`). Sentences go to TTS
  as each completes, while the model is still writing. Turbo synthesises a whole
  chunk at a time, so long sentences are split at commas and each chunk is
  synthesised while the previous one plays.
- **Things that need no synthesis.** Short openers ("Ooh!", "Hmm...") and everyday
  exchanges (hello, thanks, goodbye) are rendered ahead of time in her voice and play
  from memory (`irene/openers.py`, `irene/quick.py`). A quick reply needs the whole
  message to match, so "thanks, and set a timer" still goes to the model.
- **The song-win bit** (`irene/songwin.py`, 2026-10-19). After she names a song he
  taught her, his very next message, if it only confirms ("Yes, it's correct"), gets
  "Haha, GG fucking easy Mr Tri" with her smug face. If his next message after that
  objects ("Hey, don't say that"), she answers "Oh really?" caught off guard, holds
  that face through 2 s of silence, then "FUGGING EASY", arrogant. His wording,
  exactly. Any other message and the bit is over; it never starts anywhere else.
  The three lines are rendered at startup through the same chokepoint as the skits
  (`skit.render_line` -> `voice.take`: the pronunciation map, the silence check, the
  cache). "Oh really?", the silence and "FUGGING EASY" are one clip, and the second
  face is a mark on that clip, so neither can drift (the RPS bonk lost its timing to a
  line synthesised on demand). The command bar gets each line's text as it is said,
  not before. Rendered in capitals, Turbo said "ding easy"; the pronunciation map now
  says "fugging" for FUGGING (the text stays as he wrote it).
- **Levels.** Each sentence is normalised to the same loudness, and everything she
  plays goes through one master gain and a soft limiter (`irene/levels.py`).
- **Her face follows what is heard,** not what was written: a sentence can carry a
  mark that fires as its first sample reaches the speaker.

## Measured

| What | Result | Source |
|---|---|---|
| speaker check, owner's held-out corpus takes | scores 0.55-0.88 (threshold 0.35) | commit `b04f80f`, 2026-10-04 |
| speaker check, her own TTS | at most 0.27 | commit `b04f80f` |
| a TED talk played aloud for 60 s, her window up | 2 utterances scored (0.13, 0.07), no turn | commit `b04f80f` |
| speaker check cost on the CPU | 114 ms per utterance | commit `5f80462`, 2026-10-04 |
| Whisper word error rate on held-out corpus sentences (96 takes, 32 sentences), before/after adding his vocabulary as hotwords | 8.4% → 7.9% | commit `b04f80f` |
| first audio through core, p50, 8 questions with 600 memories stored, memory off / on in ABBA blocks | 1286 ms / 1033 ms (difference is noise) | commit `d3fe54f`, 2026-10-13 |
| the song-win bit, live `-Dev` (his Blue question replayed, then typed), 3 full runs | his confirmation to her voice and smug face: 20-40 ms. The hold: 2000 ms of silence, last voiced sample to the next; the arrogant face 2.54-2.58 s into the clip, on the first sample of "FUGGING EASY". Never fired on a confirmation when she had named nothing, or after a non-objection | socket timestamps, core.log, `skit.silences` on the played clip, 2026-10-19 |
| the bit's lines, transcribed by Whisper | "Haha, GG fucking easy, Mr. Tree." / "Oh, really?" / FUGGING EASY: "Ah, ding easy." in capitals, "fucking easy." respelled (Whisper can't tell "fugging" from it) | `faster-whisper` on the cached takes, 2026-10-19 |

Not done: `core/scripts/whisper_lora.py` (LoRA fine-tuning on his training takes,
adopted only if held-out WER improves) exists but has not been run to completion.

## Lecture audio is a separate path

System audio for [lecture capture](lecture-capture.md) is captured through WASAPI
loopback and never goes through the speaker check, the wake phrase or the echo
canceller. The two paths share only the one Whisper instance, through its queue, with
his turns first.
