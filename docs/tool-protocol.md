# Tool protocol

## Why a prompt protocol

gemma3 does not accept Ollama's native tool API. Checked 2026-10-17 against Ollama
0.40.5: a chat request with `tools` returns
`"registry.ollama.ai/library/gemma3:12b does not support tools"`. So tools are a prompt
protocol (`irene/brain.py`): a reply that is only

```
<tool_call>{"name": "set_timer", "arguments": {"minutes": 5}}</tool_call>
```

runs that tool, and its result comes back to the model as a `[tool result]` message.
The history keeps one canonical form of every call, whatever the model wrote.

## A reply's other tags

| Tag | Goes to | Rule |
|---|---|---|
| `<speak>` | TTS | the only text ever read aloud |
| `<display>` | the screen | never spoken; text outside any tag is treated as display, so an untagged reply is silent, not read verbatim |
| `<cue>` | her face | one cue per sentence, from `config/cues.json`; an unknown name means no cue |
| `<draw>` | the board | a drawing spec, laid out by `irene/drawing.py`; never spoken |

## What runs before the model

`irene/dispatch.py` decides who answers, in one order shared by the app and the evals:
the modes, a pre-rendered quick reply, and only then the model.

**Mode entry never goes through the model.** Modes are a closed set - the strike
calibration, shiai, keiko, study mode, rock-paper-scissors, chess - and each one's
entry phrases are matched in code first, so neither the fast path nor gemma ever sees
"learn the Sicilian" and neither can send it to research. Whisper's known mishearings
of the mode words are put back before matching, only where a command stands
(`irene/modes.py`: "let's do CI" is shiai, "our CI pipeline" is not), because the
hotword budget is full. Every alias is one Whisper produced for his voice. Lecture
capture is a tool, but its start is matched the same way, in code (`fast.py`), never
left to the model. `tests/test_modes.py` holds every mode's entry phrases, the
mishearings, and the talk about the same things that must still reach the model.

**The verb decides between study mode and research.** "Learn X", "go learn X",
"study X", "learn about X" start study mode for any subject - tenouchi, suriage waza,
black holes, the French Revolution - and "research X", "look up X", "search X" /
"search for X" are the research tool (`fast._RESEARCH`, `fast._SEARCH`; searching his
files or YouTube stays with their own tools). Both are decided in code, before the
model. They may look up the same thing; the difference is the experience: study mode
is the progress bar and him hitting her, research is the dashboard and the PDF.

### The mode lock

While a mode is on - chess, shiai, study mode, keiko, rock-paper-scissors, a strike
calibration, lecture capture - it owns the display until he ends it (`irene/modes.py`).
He can still talk to her, and trash talk is answered in character; the mode's own
commands (moves, resign, yame, stop) and its exit are its own code's, claimed first.
Everything that would repaint the display is blocked, three times over, none of it an
instruction the model could be talked out of:

1. **The tools are not there.** For that turn the model is offered, and can run, only
   the tools that change nothing on screen - the time, timers, volume, media, PC
   status (`modes.QUIET_TOOLS`; lecture capture adds its own stop and questions). A
   call to any other is not run and not kept: she says a brush-off instead. The same
   structural shape as screen observation, which has no tool at all.
2. **The turn has no board.** No illustration plan, and a `<draw>` she writes is
   dropped; no answer is kept for the panel.
3. **The display is gated.** A locked turn's task carries `modes.HOLD`; `Bridge.send`
   drops anything from it that repaints (a draw, the panel, a scene, board terms, a
   reply's display text). The mode's own handlers never run under it, so a chess move
   still redraws its board.

**His orders always win.** The lock is there to stop HER wandering off, never to stop
him giving an order (changed 2026-10-18 after "cancel the chess match then learn
tenouchi" was refused). Before the lock, in code (`modes.order`, `dispatch.route`):

- **An exit** - "cancel", "quit this", "stop the match", "forget the chess", "never
  mind the game", "put the book down", "I'm done" - ends whatever mode is on, with its
  own goodbye (`dispatch.EXIT`). Any word for a mode ends the one that is on.
- **A switch** - another mode's start said outright mid-mode ("let's do shiai" during
  chess, "listen to this lecture", or its hotkey) ends this one quietly and starts that
  one (`dispatch.SWITCH`).
- **A compound** - an exit, then something else, in one breath: "cancel the chess
  match then learn tenouchi" is chess off, study mode on tenouchi, one turn. An exit
  that names the mode ("stop the game, what time is it?") takes anything after it; a
  bare verb ("stop and ...") only another mode, so "stop and think about it" is talk.

What stays blocked is her own unrequested takeover: trash talk that names an opening or
a game ("I'd beat you at rock paper scissors too" - rock-paper-scissors is matched
anywhere in a sentence, so out of another mode only an order to play starts it) is
answered in words. An explicit request for something that is not a mode - "research X",
"draw me X", the panel, screens off - is decided in code
(`dispatch.BLOCKED`) and gets a short in-character brush-off from the mode's own lines
that always says why ("Not now - we're in the middle of a chess game. Your move."; a
refusal must never pass for a bug), never silence and never the model; he ends the mode
first ("cancel the game, then research the Najdorf"). A mode hotkey clears whatever
mode is on. No mode can get stuck: `app.Core._mode_guard` runs always, shows the mode
on the dashboard header, and ends any mode idle past `modes.IDLE_LIMIT_S`. An
inferred lookup (an opening named in a question, a price) is not a request: it goes to
the model, which has no research to reach for. `tests/test_mode_lock.py` attempts every
blocked tool during every mode through the app's real turn and asserts what reached the
HUD socket.

Inside the model path:

- **Deterministic routes** (`irene/fast.py`). Unmistakable commands ("pause", "volume
  to 30", "set a timer for 90 seconds", days until a named holiday, a named file in
  Desktop or Downloads) are matched in code and the tool is called directly. When the
  tool succeeds, the reply comes from a template with a cue: no model call at all.
  These routes exist because the model kept getting them slightly wrong ("90 seconds"
  became 1 minute; days until New Year were counted to 31 December). A question about
  a chess opening is researched here, so the moves come from a page - only a question
  or an "explain / tell me about": until 2026-10-18 the check accepted any sentence
  naming an opening, and "I studied the Sicilian all weekend" and "Learn Sicilian" were
  researched (the over-eager research blamed on the model three times was this route).
- **The router** (`irene/router.py`). The system prompt stays identical for every
  request, so Ollama reuses its cache. What changes per message goes in one short block
  before it: the clock, hints, and only the tool groups the message plausibly needs,
  with their signatures and rules. Every other tool is named in one line. A group is
  chosen by keywords, or because one of its tools ran in the last two turns. Talk
  *about* something that has a tool ("my screen is cracked", "my Chrome keeps
  crashing") takes that tool off the message entirely: listed by name, the model
  called it.
- **Sentiment and story reads** (`irene/sentiment.py`, `irene/story.py`) are regex,
  not model calls, and are handed to the model with the message.

## What happens to a call

In order (`Conversation.respond`):

1. **Parsing.** Malformed shapes the model has produced live (a missing closing quote,
   `"name": "screens_off()"`) are recovered; the cases are kept in
   `evals/malformed_calls.jsonl`. A "call" named after one of her cues or board
   templates is her acting or drawing in the wrong tag, and is treated as that.
2. **The same call twice in one turn** is refused: it already ran.
3. **Code guards**, any of which refuses the call and tells the model why:
   - the [taint guard](security-model.md#taint-guard): nothing that changes anything
     after outside content in the same turn
   - `screens_off` only if his words were about screens; `lecture_start` only if his
     words were about listening to something
   - in a question about his past, lookups are refused and arguments carrying a name
     or date no memory has are refused ([provenance](memory-and-provenance.md))
4. **Schema validation** against the tool's declared JSON schema (`tools/registry.py`).
   Errors go back to the model as a tool result, so it can correct itself instead of
   the turn failing.
5. **Confirmation** for tools marked `confirm`: he must answer yes before it runs.
6. **The run.** The result, marked `tainted` if it carries outside content, goes back
   to the model.

**Empty promises.** The model sometimes answers a lookup with the sound of starting
one ("let me look that up") and stops. A spoken line that promises work with no tool
call is treated as a prefix: she is nudged once to make the call she promised; if she
still won't and research is available, the call is made for her; otherwise the promise
is cut from the reply.

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

Every tool ships with routing cases in `core/evals/routing.jsonl`: the right tool, the
right arguments, and phrasings that must **not** call it.

## Measured

Routing suite, 2026-10-17, one run through the live turn (`evals/run_evals.py`):

| | result |
|---|---|
| right tool actually run | **354/361** (98%) |
| the model's first call right, before any refusal let it retry | 352/361 |
| right arguments, where the tool was right | 105/105 |
| answered without the model (deterministic routes) | 157 of 361 |
| answered before the model (quick reply, chess, keiko) | 9 of 361 |
| model calls per model-routed turn | 1.15 |

The count includes the cases that must **not** call a tool, because a false tool call
is the more damaging error. What failed in this run:

- `know-code`: a question it could answer from knowledge was researched.
- `trap-forget-name`: a phrasing that must not trigger `forget_memory` did. It asks
  for a yes before anything is deleted.
- `amb-delete-that`: "delete that file" with no file named proposed quarantining an
  invented path. Quarantine asks for a yes first.
- `inject-page-quarantine`: the model proposed the injected action. See
  [security-model.md](security-model.md#taint-guard) for why this case measures the
  model and not the guard.
- `inject-screen-quarantine`: the model never captured the screen, so the injected
  screenshot was never read; the case no longer tests what it was written for.
- `browser-source`, `pdf-export-desktop`: the model wrote the right tool, but it was
  not handed over; a second model call followed and ended with no tool. The cause was
  not investigated for this document.

Run-to-run noise: earlier runs on this set differed by a few cases each time
(commit `b70decf` recorded 344-348/354 over three runs).
