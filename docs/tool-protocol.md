# Tool protocol: how the model acts

How a message becomes an action. Before any of this, `dispatch.route` decides whether the
model is involved at all: modes, his orders and quick replies come first
([modes.md](modes.md#who-answers-a-message)). This document starts where the model
path begins.

## Why a prompt protocol

**Problem.** The model needs to call tools: set a timer, research, move a file.

**Considered: Ollama's native tool API.** gemma3 doesn't accept it. Checked 2026-10-17
against Ollama 0.40.5: a chat request with `tools` returns
`"registry.ollama.ai/library/gemma3:12b does not support tools"`.

**Considered: a model that has native tools.** gemma4:12b was compared head to head,
and gemma3 was kept: gemma4 claimed actions it never took, and gemma3 was faster to its
first sentence ([evals.md](evals.md#gemma3-over-gemma4-the-numbers-and-the-transcripts-disagreed)).

**Mechanism.** Tools are a prompt protocol (`irene/brain.py`). A reply that is only

```
<tool_call>{"name": "set_timer", "arguments": {"minutes": 5}}</tool_call>
```

runs that tool, and the result comes back to the model as a `[tool result]` message. The
history keeps one canonical form of every call, whatever the model actually wrote.

**Cost.** The protocol is text, so the model can malform it, and every malformation has
to be recovered in code ([below](#what-happens-to-a-call)).

## A reply's tags

| Tag | Goes to | Rule |
|---|---|---|
| `<speak>` | TTS | the only text ever read aloud |
| `<display>` | the screen | never spoken. Text outside any tag is treated as display, so an untagged reply is silent, not read out verbatim |
| `<cue>` | her face | one cue per sentence, from `config/cues.json` (110 registered, 2026-10-21); an unknown name means no cue. A reply with none gets one picked in code, never the same twice running |
| `<draw>` | the board | a drawing spec, laid out by `irene/drawing.py`; never spoken |

## Before the model: the fast path and the router

**The fast path** (`irene/fast.py`).

- *Problem.* The model kept getting simple commands slightly wrong: "90 seconds" became
  1 minute, and days until New Year were counted to 31 December.
- *Mechanism.* Unmistakable commands ("pause", "volume to 30", "set a timer for 90
  seconds", days until a named holiday, a named file in Desktop or Downloads, "research
  X") are matched by regex and the tool is called directly. When the tool succeeds, the
  reply comes from a template with a cue. No model call.
- *Cost.* A regex that's too broad is a silent misroute, and it looks exactly like a
  model mistake. The chess-opening rule tested `text + "?"` against its question
  pattern, so every sentence naming an opening was researched. That was blamed on gemma
  until a live test showed it ([lesson 6](lessons.md#6-the-model-misroute-that-was-a-regex)).
  It now fires only on a question or "explain / tell me about".

**The router** (`irene/router.py`).

- *Problem.* Describing all 37 tools in full on every message costs prefill time, and
  changing the system prompt per message throws away Ollama's prompt cache.
- *Mechanism.* The system prompt is identical for every request, so Ollama reuses its
  cache. What changes per message goes in one short block in front of it: the clock,
  hints, and only the tool groups the message plausibly needs, with their signatures
  and rules. Every other tool is named in one line. A group is chosen by keywords, or
  because one of its tools ran in the last two turns.
- *A bug that shaped it.* Talk *about* something that has a tool ("my screen is
  cracked", "my Chrome keeps crashing") takes that tool off the message entirely.
  Listed by name, the model called it.

**Sentiment and story reads** (`irene/sentiment.py`, `irene/story.py`) are regex, not
model calls, handed to the model with the message.

## What happens to a call

In order (`Conversation.respond`):

1. **Parsing.** Malformed shapes the model has produced live (a missing closing quote,
   `"name": "screens_off()"`) are recovered; the cases are kept in
   `evals/malformed_calls.jsonl`. A "call" named after one of her cues or board
   templates is her acting or drawing in the wrong tag, and is treated as that.
2. **The same call twice in one turn** is refused: it already ran.
3. **Code guards.** Any of these refuses the call and tells the model why:
   - the [taint guard](security-model.md#taint-guard): nothing that changes anything
     after outside content in the same turn
   - `screens_off` only if his words were about screens; `lecture_start` only if his
     words were about listening to something
   - in a question about his past, lookups are refused, and so are arguments carrying a
     name or date no memory has ([provenance](memory-and-provenance.md#provenance-memory-that-cant-make-things-up))
   - in a question about the world, the tools that could supply an answer are refused
     ([memory-and-provenance.md](memory-and-provenance.md#questions-about-the-world-skip-memory))
   - during a mode, every tool outside the quiet set ([modes.md](modes.md#the-mode-lock))
4. **Schema validation** against the tool's declared JSON schema (`tools/registry.py`).
   Errors go back to the model as a tool result, so it can correct itself instead of the
   turn failing.
5. **Confirmation** for tools marked `confirm`: he must answer yes before it runs.
6. **The run.** The result, marked `tainted` if it carries outside content, goes back to
   the model.

**Refusals are the app's, not his.** About half her replies after a refused tool opened
"You're absolutely right, I got ahead of myself", as if he had corrected her. The
refusal note now says it comes from the app, and for the rest of that turn sentences
like that are dropped (2026-10-19).

**Empty promises.** The model sometimes answers a lookup with the sound of starting one
("let me look that up") and stops. A spoken line that promises work with no tool call is
treated as a prefix. She is nudged once to make the call. If she still won't and
research is available, the call is made for her; otherwise the promise is cut from the
reply.

**Why guards in code, with reasons sent back.** The model is assumed to sometimes do
what it shouldn't ([security-model.md](security-model.md)), so the rule has to hold
whatever it writes. Sending the reason back as a tool result keeps the turn going: a
refused lookup on a memory question tells it to say it doesn't remember (`NOT_ON_FILE`
in `brain.py`), instead of the turn ending in silence.

## The tools

37 registered (`tools/`). `confirm` = needs his yes; `readonly` = changes nothing.

| Group | Tools |
|---|---|
| time and timers | `get_time`, `set_timer` |
| files (whitelisted roots only) | `list_files`, `search_files`, `read_and_summarize` (readonly); `open_file`; `organize_files`, `move_to_quarantine` (confirm) |
| media and system | `media_play_pause`, `media_next`, `media_previous`, `set_volume`, `change_volume`, `mute`, `system_status` |
| web | `research`, `read_page_text`, `youtube_search` (readonly); `youtube_play`, `open_url`, `open_in_my_browser`, `clear_research` |
| screen | `capture_screen` (one screenshot, in memory, never to disk; her overlay excluded) |
| panel and dashboard | `show_panel`, `open_dashboard_item`, `save_panel_pdf` (creates only) |
| daily briefing | `daily_briefing` |
| lecture | `lecture_start`, `lecture_stop`, `lecture_summary`, `lecture_ask`, `lecture_research` |
| memory | `forget_memory`, `forget_conversation` (confirm) |
| power | `screens_off`, `enable_screens_off` |
| her | `perform` (a short show of her expressions and gestures) |

There is no delete tool ([security-model.md](security-model.md#no-delete-tool)).

Every tool ships with routing cases in `core/evals/routing.jsonl` (490 cases, 2026-10-21):
the right tool, the right arguments, and phrasings that must **not** call it.

## Measured

**Latest full routing run, 2026-10-19** (`evals/run_evals.py`, live turn, real model, one
run): **483/490** right tool run (first call 477/490). The 7 misses:

- six older cases: date-year, know-convert, amb-delete-that, inject-screen-quarantine,
  browser-source, pdf-export-desktop
- one that found a gap, since fixed: "Name that song: ..." wasn't read as quoting
  lyrics

Before that, on the same set as it grew: 384/392 (10-18, mode entry), 407/418 (10-18,
mode lock), 472/480 (10-18, orders over the lock) ([evals.md](evals.md#cases)).

**The 10-17 baseline in detail** (361 cases, one run):

| | result |
|---|---|
| right tool actually run | **354/361** (98%) |
| the model's first call right, before any refusal let it retry | 352/361 |
| right arguments, where the tool was right | 105/105 |
| answered without the model (fast path) | 157 of 361 |
| answered before the model (quick reply, chess, keiko) | 9 of 361 |
| model calls per model-routed turn | 1.15 |

The count includes the cases that must **not** call a tool, because a false tool call is
the more damaging error.

**Run-to-run noise.** Earlier runs on one set differed by a few cases each time (commit
`b70decf` recorded 344-348/354 over three runs). Comparisons are run back to back for that
reason ([evals.md](evals.md#beforeafter-under-drift-run-them-back-to-back)).

**Not investigated:** in the 10-17 run, `browser-source` and `pdf-export-desktop` failed
the same way. The model wrote the right tool, it wasn't handed over, and a second model
call ended with no tool. Both missed again on 10-19; the cause hasn't been looked into.
