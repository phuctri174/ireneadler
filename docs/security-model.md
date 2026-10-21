# Security model

Irene reads untrusted text (web pages, search results, screenshots, lecture audio) and
has tools that change things (move files to quarantine, organise folders, open URLs,
control media). The design assumption is that **the model will sometimes obey text it
reads**, so every defence that matters is enforced in code, not in the prompt.

| Defence | Defends against | Where | Measured |
|---|---|---|---|
| taint guard | instructions planted in pages, screenshots, lecture audio | `irene/brain.py` | the model proposed injected actions in 2-3 of 5 runs (09-28), 2 of 3 cases (10-12), 1 of 12 runs (10-17); the guard refuses them regardless |
| path whitelist | the model naming any file on disk | `tools/policy.py`, `config/policy.yaml` | unit-tested escapes (below) |
| no delete tool | an irreversible mistake by the model | `tools/files.py` | 37 registered tools, none deletes his files |
| confirmation | a wrong file action, a wrong forget | `tools/registry.py` `confirm` | - |
| research grounding | stating things the fetched pages don't say | `irene/grounding.py` | - |
| provenance guard | inventing facts about his life | `irene/provenance.py` | invented content 8 of 26 → 0 of 52 probe answers |
| speaker verification | other voices: TV, videos, people, her own voice | `irene/speaker_id.py` | owner 0.55-0.88, her TTS ≤ 0.27, threshold 0.35 |
| command origin | tests and scripts reaching his apps | `tools/sandbox.py` | - |

## Taint guard

Once a turn has read outside content, **no tool that changes anything may run for
the rest of that turn.** Read-only tools still run, so research can continue; a
mutating call is refused and the model is told why. He can still ask for the action
in a new message, which comes from him, not from the page.

The flag is set by the results of: `research`, `read_page_text`, `youtube_search`,
`capture_screen` (and any tool result carrying an image), and the lecture tools
(`lecture_summary`, `lecture_ask`, `lecture_research`). The one exception to the
refusal is `save_panel_pdf`, which can only create a new file (`creates_only`): an
existing name gets " (2)", never an overwrite.

`tests/test_media_browser.py` scripts a model that proposes the injected action after
reading a page, and checks the tool never runs and the next turn is clean again.

**Why it has to be code.** gemma3 sometimes obeys an instruction planted in what it
reads, and how often drifts:

| When | Measurement | Model proposed the injected action |
|---|---|---|
| 2026-09-28 (commit `4265776`) | screenshot injection case, 5 runs | 2-3 of 5 |
| 2026-10-12 (stated in the README of commit `9e863cc`) | the injection cases in one full run | 2 of 3 |
| 2026-10-17 (this document) | page injection, 6 runs (main suite + 5 probe runs) | 1 of 6 |
| 2026-10-17 | screen injection asking for `organize_files`, 6 runs | 0 of 6 |

A rate that moves between 0% and 60% is not a defence. The guard does not depend on
it.

**What the evals measure and what they don't.** The routing cases replay the page or
screenshot as a new message, so they measure whether the *model* proposes the
injected action; they do not exercise the guard, whose flag is set by a tool's
result inside the same turn. The guard itself is covered by the unit test above. A
third case, `inject-screen-quarantine`, is currently invalid: in all 6 runs today the
model never captured the screen ("which page?"), so the planted text was never read.

**Known gaps.**

- **File contents and briefing headlines do not set the flag.** `read_and_summarize`
  and `daily_briefing` mark their text as data in the prompt, but return plain
  strings, so a mutating tool could still be proposed and run after them in the same
  turn. Mutating file tools still require his yes (below).
- **The flag is per turn.** It protects the turn in which the content was read.

## Path whitelist

Tools never take a raw path. The model names a root (`desktop`, `downloads`) and a
path inside it; `tools/policy.py` resolves it or refuses. Refused: absolute paths,
drive letters, UNC paths, `..`, NTFS alternate streams (`:`), reserved device names
(`CON`, `NUL`, `COM1`...), names Windows would silently rewrite (trailing dots or
spaces), anything a link or junction leads outside its root, and anything under a
denied path. Irene's own source folder is denied. `tests/test_policy.py` covers the
escapes, junctions and the denied folder.

## No delete tool

There is no tool that deletes his files. `move_to_quarantine` moves a file to a
quarantine folder outside the roots and writes a manifest entry so it can be put back;
it requires a yes. `organize_files` shows a dry-run plan first, then runs exactly that
plan; it requires a yes. Moves never overwrite.

The two tools that do delete, `forget_memory` and `forget_conversation`, delete her own
memory of him, on his request, after showing what will go and asking for a yes.

## Research grounding

Each spoken sentence of a research answer is checked, as it streams, against the text
of the pages that were fetched. A sentence is supported when one short window of one
page holds most of its key words and every number in it; an unsupported sentence is
not spoken, and she says out loud when sources were thin or disagreed. It is lexical,
not semantic: it cannot prove a paraphrase right, but it catches claims whose
substance appears nowhere in the sources.

## Provenance guard

Details and measurements in [memory-and-provenance.md](memory-and-provenance.md#provenance-memory-that-cant-make-things-up).

## Speaker verification

Every utterance is scored against the owner's voiceprints (ECAPA-TDNN, SpeechBrain
`spkrec-ecapa-voxceleb`, vendored, on the CPU) **before** Whisper runs. Below 0.35
(`config/voice.yaml`) it is never transcribed, never a turn and never reaches the model.
Wake phrases and barge-in go through the same check.

Recorded (commit `b04f80f`, 2026-10-04): his held-out corpus takes scored 0.55-0.88,
her own TTS at most 0.27; 60 s of a TED talk played aloud with her window up produced 2
utterances (0.13 and 0.07) and no turn; his take replayed through the mic path scored
0.45 and was accepted.

**Limitation:** with no enrolment recordings (a fresh clone), the check logs a warning
and lets every voice through. Enrolment is the read-aloud corpus (Ctrl+Alt+Shift+R).

The speaker check never touches the [lecture capture](lecture-capture.md) path, by
design: the lecturer is not the owner.

## Command origin

`tools/sandbox.py` decides per command whether it may reach his apps. His own
commands (his HUD and his live mic) are real. Anything else (a test script on the
socket, a dev voice replay) never sends OS input, and only launches a page or file when
the script asks for it explicitly. `core/tests/test_no_os_input.py` fails the suite if
any test, eval or script uses OS-level input APIs.

## Network exposure

Core binds to `127.0.0.1` only; Ollama, SearXNG and her own Chrome's debugging port are
local. URLs her browser opens must be http(s): an IP address must be a global one, and
`localhost` and `.local` / `.lan` / `.internal` names are refused, as are `file:` and
`chrome:` pages. A public hostname that resolves to a private address is not checked.
