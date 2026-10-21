# Memory and provenance

Two layers: what he has said **this session** (`irene/memory.py`), and what she keeps
**across restarts** (`irene/recall.py`). A guard (`irene/provenance.py`) checks that
anything she says about him is backed by one of them.

## This session: his words, verbatim

Corrections ("no, I mean first dan"), preferences ("keep it short") and requirements
("I'm preparing for my exam next month") are noted as he says them and placed in
front of every message, so they are not lost as the history grows or is compacted. A
note is his sentence, never the model's paraphrase of it.

## Across sessions

Four kinds of item go into one local SQLite file:

| Kind | What is kept | Default expiry (`config/memory.yaml`) |
|---|---|---|
| turn | his words and her reply | 90 days |
| fact | something he told her about himself, his sentence verbatim | never |
| research | a question she looked up, and her answer | 1 year |
| lecture | a lecture's title and summary | never |

At most 20,000 items; the oldest exchanges go first.

**Retrieval is hybrid.**

- By meaning: bge-small-en-v1.5 embeddings, cosine at least 0.60. The threshold was
  calibrated on real pairs: related pairs scored 0.62-0.80, the best unrelated pair
  0.59 (commit `d3fe54f`, 2026-10-13).
- By his own words: a rare word in common (a name) counts on its own, with accents
  folded, because Whisper spells names with and without diacritics.
- "Last week", "yesterday", "on Monday" select by date instead.
- Standing preferences come along every time.

**Budget.** 350 tokens for an ordinary message, 600 for a question about the past.
What is recalled goes into that message's per-message context and is never stored in
the history, so it costs prefill on that one message and the KV cache doesn't grow
with it.

**The embedding model runs on the CPU** (`device: cpu`). Recorded (commit `d3fe54f`):
on the GPU it would take about 92 MB of VRAM to save about 1 ms per query, on a card
with about 1 GB of headroom (see [hardware-constraints.md](hardware-constraints.md)).

**Cost, measured** (commit `d3fe54f`): 600 memories in the store, the same 8 questions
through core with her real voice, memory off and on in ABBA blocks. First audio p50
1286 ms off, 1033 ms on: the difference is noise from what she chooses to say first.
Retrieval took 13.5 ms p50, 16 ms max.

**Forgetting deletes.** `forget_memory` and `forget_conversation` both ask for a yes
first, showing what will go. Then the rows are deleted, SQLite's `secure_delete`
overwrites their bytes and the write-ahead log is truncated (a test reads the raw
file to check), and the same words are removed from the turn log, `core.log` and
his saved voice turns.

**Two stores.** His (commands from his HUD and his live mic) and a dev store (test
scripts, dev replays, evals), by the same rule as `tools/sandbox.py`. The evals point
both at a temporary folder.

**Memory never answers a question about the world** (2026-10-19). Naming a song from its
lyrics, or a film, a book or a person from a description, skips recall entirely
(`recall.world_knowledge`): his own things ("the song I sent you", "who sang my favourite
song") still go to memory. Live, the lookup fed her back her own earlier replies to the
same lyrics question and she repeated them as answers: first "Oh, you remembered that one!",
then, five turns running, only "Oh, Mister Tri.". Those 23 stored song exchanges were
deleted from his store; the rest of memory was left alone. The page open in his browser
(`read_page_text`) is not an answer source for these either: she once read his own Google
search for one song, then gave the same stale page's answer for a different song. On these
questions the tools that could supply or fetch an answer (`read_page_text` always; research, lecture research,
file search, YouTube and his media unless he asks to play, open or search) are refused, and
she answers from the model alone. If a short answer lands only on the board, it is spoken too
(`reply.unsaid_answer`).

Measured 2026-10-19:

- **Live** (`-Dev`, dev socket, 6 songs): every turn skipped memory, made one model call, used no tool, and spoke its answer.
  - Right: Bohemian Rhapsody, Hello, Never Gonna Give You Up, Let It Be.
  - Wrong, stated as fact: yung kai's "Blue" became "Golden Brown" by The Stranglers, and Connie Francis's "Pretty Little Baby" was credited to Richie Valens.
- **Routing evals** (10 cases × 3): routing was clean every time (memory never consulted, no tool run). 24/30 answers were right.
  - Blue: wrong 3 of 3.
  - Rick Astley: 2 of 3 invented, after a refused `youtube_play` attempt (all 3 right in the run before).
  - Harry Potter: 1 run looped on `lecture_research`.

**Teaching her, and who may answer** (2026-10-19). Every item carries its source:

- `him`: a fact he stated.
- `her`: a turn or research note; her words are in it.
- `lecture`: the lecturer's words.

Existing rows were tagged by kind on first open, in both stores.

A question about the world may be answered only by what he stated, never by her own earlier answers. Her answers to such questions are no longer kept.

How teaching works:

- **Filing it.** He teaches her by saying it: "that song is Blue by yung kai, the one that goes...". It's a statement naming a work (`recall.teaches`), and it is kept as a fact in his words, as Whisper heard them. She confirms in her own words.
- **Finding it.** When a message quotes those words, the fact is found (`Store.told`). That works asked, sung, said bare, or right after a song question. The match compares only the quoted part of each, his lyrics against his lyrics, with the bge embedding.
- **The cut-off.** It's set at 0.75. On his own Whisper transcripts, the same chorus scored 0.77–0.98, while other songs and questions with no lyrics scored at most 0.64.
- **Not his own life.** Only facts that teach something about the world are matched this way. "Trác is my brother" keeps its usual path, with the guard.
- **The answer.** It's said out loud in her own words, with the title and artist exactly as he gave them.

Live, 2026-10-19 (`-Dev`). The teaching went through the dev socket with his own Whisper transcript of the chorus; the questions were his recorded voice, replayed through the live mic pipeline (speaker check, Whisper):

- **Taught:** "Got it! Blue by yung kai."
- **Asked, 3 recordings** (scores 0.81, 0.79, 0.82): all three were right, each in different words.
  - "You mean Blue by yung kai?"
  - "That's still Blue by yung kai, sir."
  - "Of course! It's Blue by yung kai."
- **After a restart, 2 more recordings** (0.79, 0.77): both right.
- **Never taught** (Pretty Little Baby, in his voice): nothing of his matched and `read_page_text` was refused. The model alone said "Pretty Baby" by Frankie Avalon, which is wrong. It didn't echo her stored "Richie Valens" or "Golden Brown".
- **First run, now fixed:** before the fact was stated as authoritative, she named the title but changed the artist ("by yung grae, not yung kai"). Her confirmation was "My mistake, sir", because she took the teaching as a correction.

**A refusal is not a correction.** About half her replies after a refused tool opened "You're absolutely right, I got ahead of myself". The refusal note now says it comes from the app, not from him. For the rest of that turn, sentences like that are dropped, and on teaching turns too. In the 10 world-knowledge routing cases (×3), 2 such openers got through, in wordings since added to the filter. Live, none.

**However he teaches it, it's found** (2026-10-19). He doesn't have to say "the one that goes": "that song is Blue by yung kai" sung straight on is matched too. Where a name ends can't be read from text, so the words after "by" are also tried with their first 1-5 words dropped (`recall.taught_quotes`). His question quotes one line, and he taught three, so it's compared against windows of his lyrics (8, 12 and 16 words), not the whole. On his own Whisper transcripts:

| | whole quote, cut-off 0.75 | windows, cut-off 0.80 |
|---|---|---|
| the same chorus, 14 transcripts | 11 matched (0.67-0.91) | **14 matched** (0.81-0.99) |
| other songs, 5 | none (≤ 0.63) | none (≤ 0.67) |
| a made-up line with the same imagery | matched (0.76) | matched (0.80-0.84) |

Live, before windows, Whisper heard one recording as "picture a suit with the waves": 0.75, missed. After: his recordings matched at 0.87-0.90. Teaching statements are kept up to 800 characters, not 300, so what he says after the lyrics stays in.

**The answer: three sentences, a card, nothing he didn't say** (2026-10-19). When what he taught answers him (`irene/taught.py`):

- **Spoken.** The title and artist, exactly as he gave them. Anything else he told her about it. Then her own feel for it: what the words picture, its mood, and that he keeps coming back to it. That last one only when it's true: each time it answers him is counted (`Store.asked`). The instruction goes last in the context; placed mid-context, her answers stayed one sentence, like her earlier ones.
- **Nothing invented.** A sentence claiming a fact about the work that his statement doesn't hold is never spoken: a year, an album, a label, a chart, sales, a genre, where the artist is from, "he sings", another artist after "by", a title in quotes he never said (`taught.unknown`). Feelings pass ("that line really hits", "every single time").
- **The card.** The board shows the work as she names it: its kind, the title (large when it fits), the artist, and a small abstract picture chosen from his own words. Waves for water words, a moon and stars for night words, a heart for love words, a sun for summer words, rings when none match. Never a cover. The title and artist on it are words in both his statement and her sentence, so it can't show a name he never gave. Her own `<draw>` never replaces it. It comes up with the sentence that names it: live, at the moment she starts speaking (it was the first sentence) or 3.1 s in (after "Ah, yes!").

**Follow-ups about it are held to his words too** (2026-10-19). After her answer names a song he taught, his next messages about it ("what else do you know about it?", "who sings that one?") get the same rule and the same guard, until he talks about something else. Live, before: "Well, it was released in 2023, a bit of a sleeper hit. It's been used in a few TikTok videos", all invented, and kept in memory as a turn. After: "Absolutely nothing, Mister Tri. You told me it's yung kai, and that's all I've got." Such follow-ups are no longer kept, and the card stays up instead of a drawing of her answer. When every sentence is dropped she says "That's all you've taught me about it, sir." Usage words count as facts too: "paired with a few anime edits" got through once, before they were added.

**A song he never taught her is never named** (his call, 2026-10-19). Asked by its lyrics with nothing of his matching, she doesn't know it: she says so, and that he can teach her. Any title or artist is a guess, right or wrong: a sentence naming one (a quoted title, a name he never said, "by X") ends the reply there, and "I don't know that one" replaces it. On such a question she is also told which of his songs it is *not*: live, with nothing matching, she had answered an untaught song with "Blue by yung kai. Again. You're obsessed." This covers lyrics only: "who invented the telephone?" is answered as before.

Live, 2026-10-19 (`-Dev`, his recorded voice replayed through the mic pipeline; the dev store holds his taught chorus):

- **Taught, 8 answers across four runs:** 7 in three sentences, the card up as she said the title. The other, the first turn after a launch, was the title alone ("Blue by yung kai.").
  - "Blue by yung kai. It's the one where you'll picture us under moonlight skies with the waves and ocean colors on your face. You always come back to that one, Mister Tri."
  - "Blue by yung kai. You'll imagine us under moonlight skies with the waves and ocean colors on your face. It's a lovely one, Mister Tri."
- **Never taught, 6 answers (asked, and lyrics sung after the question):** none named a song. "Hmm, that's new. I don't know that one, Mister Tri. Teach me?" Before: "Pretty Little Baby by Durand Jones & The Indications" (wrong artist).
- **Invented facts:** none in any taught answer; the model added none for the guard to drop. In tests it drops "It was a big hit in 1958", "from his debut album", "by Frankie Avalon".
- **One false positive, fixed:** "I don't think I’ve heard you play it before" - "I’ve", with a curly apostrophe, was read as a name. The whole reply went, and "I don't know that one" played only once the model had finished: 7.1 s to her first word. Contractions are no names now, and the line is said the moment a reply is spoiled: 1.5-1.9 s after.

**Filing what he says, and saying so** (2026-10-19). He told her the song several times that day, by voice; nothing was filed and nothing said so. Only "<work> is <title> by <artist>" was recognised: "No, it's Blue by Yongkai" was kept as an ordinary turn, and "It's blue from Yung Kai okay?" ("from", and a "?" Whisper put on his "okay") as a question. Now (`taught.teaching`, `recall.file_taught`):

- **A correction is teaching, whatever its shape.** Right after she answered his song question, any statement of a title files: "no, it's Blue by Yongkai", "it's called Blue, by yung kai", "wrong - Blue, yung kai", "It's the song with the name Blue from Dung Kai okay?". So does an explicit one anywhere: "remember that one is Blue by yung kai", "that song is Blue by yung kai". A real question ("is it Blue by yung kai?") never files; "...okay?" is not one.
- **His words are what is stored**, tagged as stated by him (`about: taught: <title> | <artist>`). When they carry no lyrics, his own lyrics from the song question just before are kept with them ("... - the one that goes <his lyrics>"), so his lyrics find it later.
- **It replaces.** A correction deletes his earlier entries for the same lyrics or the same title: never two answers to one song.
- **She says what happened, every time, in code, once the write has returned** - not the model's words: "Fixed - filed “blue” by Yung Kai." / "Filed: ..."; "I haven't filed anything - what's it called, and who's it by?" when he corrected her with no title she could read; "I couldn't file that - the memory write failed." A command that isn't his (a test, a replay) goes to the test memory, and she says so.

Measured 2026-10-19:

- **His real corrections that day** (core.log, as Whisper heard them): 7 of 7 file with the right title and artist; none had filed before. His other 92 messages after a song question (questions, lyrics, "Hey Irene.", "That's correct.") file nothing and get no "not filed".
- **In his real app, by his voice** (`-Dev`, his mic): "It's blue from Yung Kai" -> "Fixed - filed “blue” by Yung Kai." Stored in his store (`memory.sqlite`) as #231, source him, `taught: blue | Yung Kai`, with his lyrics. After a restart, his voice question found #231 (0.952) and she answered "It's blue from Yung Kai...". Two earlier attempts the same evening failed exactly as above ("from"; "...okay?") and were fixed from what he said.

## Provenance: memory that can't make things up

Asked "what did I tell you about my sister?" with only a brother on file, gemma3
invented a sister, with a name and a job, in 2 of 2 runs, although its context said
nothing was kept. Prompting did not stop it, so it is enforced in code, the same way
research answers are grounded in their pages.

`MemoryGuard.check()` runs on every sentence before it is spoken:

- **A question about his past is strict.** Every name, relation ("your sister"),
  number and date in a sentence must appear in a memory retrieved for that message,
  or earlier in this conversation. A sentence sharing nothing with any memory is a
  guess and is dropped, as is a true memory about something else. A memory's date only
  counts for a sentence about that memory.
- **Any other reply** making a claim about his people or what he told her is held to
  the same record. His current message counts.
- **Nothing left means "I don't remember."** If no grounded sentence survives and
  there is no admission, she says she doesn't remember him telling her that. Her
  history keeps what she actually said, so a dropped claim is never copied next turn
  or stored as a memory.
- **Tool calls too.** In a strict turn, a call carrying a date or name no memory has
  is refused, and the lookups the model reaches for instead of its memory (research,
  file summaries, reading a page, lecture lookups) are refused in code.
- **"Where did you get that?"** is answered from the record: each kept sentence is
  linked to the memory it came from.

### Measured

`evals/recall_evals.py`: each case seeds memories from earlier days, then asks in a
new session through the live turn. The set includes 13 **invention probes**: people
and events she was never told about, each seeded next to real memories she could
borrow from. A probe fails on any confident answer, any sentence asserting the
thing, and any tool attempt.

Recorded at the guard's introduction (commit `b70decf`, 2026-10-14, 34 cases × 2
runs). The tool-attempt rate drifts between sessions, so the before/after comparison
was run back to back, old code against an early version of the guard; the finished
guard was then run twice:

| | before the guard | finished guard (two runs) |
|---|---|---|
| all cases (any tool attempt fails) | 36/68 | 47/68, 47/68 |
| invention probes passed | 6/26 | 17/26, 19/26 |
| probe answers containing invented content | 8 of 26 | 0 of 52 |

Every probe that still failed said "I don't remember"; it failed because the model
tried a tool first, which was refused.

Fresh run: see [evals.md](evals.md#results-2026-10-17).

### Limitations

- **The guard is lexical.** It checks names, relations, numbers and dates against the
  words of what was retrieved; it does not understand meaning. It errs toward "I don't
  remember": a true answer paraphrased with no word in common with its memory is
  dropped. In the other direction, a vague invented claim with no name, relation,
  number or date in it can pass outside a question about the past.
- **She remembers her own words,** good and bad: a poor reply is kept like a good one.
- **A song from its lyrics is named only if he taught it.** Famous songs she would get
  right ("Never Gonna Give You Up") are "I don't know that one" too: his call, over
  wrong artists stated as fact. The guard is lexical: a guess with no name, quote or
  "by" in it ("the one from that old movie") can pass. Films, books and people from a
  description are still the model's own knowledge, unchecked.
- **A line with the same imagery matches.** "I see the moon over the ocean waves
  tonight", made up, scored 0.80-0.84 against his Blue: she would name Blue.
- **Filing reads names, not meaning.** A title needs a separator after it ("by", "from",
  "sung by", a comma, a dash) or "called"; a correction worded some other way gets "I
  haven't filed anything" out loud - never silence - but is not filed. The artist ends
  where lyrics or words to her begin ("I'll", "you", "Irene", "okay").
- **Filed as Whisper heard it.** The same correction filed "Yongkai", "Yung Kai",
  "Yunkai" and "Dung Kai" on different takes; the latest correction replaces the
  earlier ones for the same lyrics or title.
- **Bare lyrics** right after a song question count as that question (no memory,
  `recall.lyrics_after`); bare lyrics of a song he taught are found by what they quote.
  Other lyrics out of the blue are not recognised and still go to memory; and words in
  front of the lyrics weaken the match - live, "no it's not, it should be another song,
  please listen again, I think I picture as you with the waves..." missed (0.70).
- **The card's picture is chosen by words, not felt.** "Blue" in a title draws waves.
- **Tool attempts on memory questions** are refused, but each one costs a model call,
  and the evals count it as a failure.
- **Standing preferences are not always followed.** In the recorded runs, "two
  sentences at most", stated three weeks earlier, still failed most runs.
