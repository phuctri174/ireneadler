# Memory and provenance

Three problems, one store:

1. **Remembering him** across restarts, cheaply enough to do on every message.
2. **Never inventing** something about him and saying she remembers it.
3. **Learning from him**: what he teaches her about the world answers later questions,
   and her own guesses never do.

Code: `irene/memory.py` (this session), `irene/recall.py` (across sessions),
`irene/provenance.py` (the guard), `irene/taught.py` (taught answers).

## This session: his words, verbatim

Corrections ("no, I mean first dan"), preferences ("keep it short") and requirements
("I'm preparing for my exam next month") are noted as he says them and placed in front of
every message. That way they survive as the history grows or is compacted. A note is his
sentence, never the model's paraphrase of it.

## Across sessions: the store

**Problem.** The model's context is 16k tokens and is reset on restart. He expects her to
remember what he told her last week.

**Mechanism.** One local SQLite file. Every item has a kind and a **source**:

| Kind | What is kept | Default expiry (`config/memory.yaml`) |
|---|---|---|
| turn | his words and her reply | 90 days |
| fact | something he told her, his sentence verbatim | never |
| research | a question she looked up, and her answer | 1 year |
| lecture | a lecture's title and summary | never |

The source is one of `him` (a fact he stated), `her` (a turn or research note; her words
are in it) or `lecture` (the lecturer's words). It's recorded at write time
([lesson 7](lessons.md#7-memory-echoing-her-own-invented-answers-back-as-fact)). At most
20,000 items are kept; the oldest exchanges go first.

**Retrieval is hybrid:**

- **by meaning**: bge-small-en-v1.5 embeddings, cosine at least 0.60. Calibrated on real
  pairs: related pairs scored 0.62-0.80, the best unrelated pair 0.59 (commit `d3fe54f`)
- **by his own words**: a rare word in common (a name) counts on its own, with accents
  folded, because Whisper spells names with and without diacritics
- **by date**: "last week", "yesterday" and "on Monday" select by date instead
- standing preferences come along every time

**Budget.** 350 tokens for an ordinary message, 600 for a question about the past. What
is recalled goes into that message's per-message context and is never stored in the
history. So it costs prefill on that one message, and the KV cache doesn't grow with it.

**Considered: embeddings on the GPU.** About 92 MB of VRAM to save about 1 ms per query,
on a card with about 1 GB of headroom (commit `d3fe54f`). It runs on the CPU.

**Cost, measured** (commit `d3fe54f`). With 600 memories stored, the same 8 questions
went through core with her real voice, memory off and on in ABBA blocks. First audio p50
was 1286 ms off and 1033 ms on: the difference is noise from what she chooses to say
first. Retrieval took 13.5 ms p50 and 16 ms max; 12.2 ms p50 during the 10-17 recall
evals.

**Forgetting deletes.** `forget_memory` and `forget_conversation` both ask for a yes,
showing what will go. Then:

1. The rows are deleted.
2. SQLite's `secure_delete` overwrites their bytes, and the write-ahead log is
   truncated. A test reads the raw file to check.
3. The same words are removed from the turn log, `core.log` and his saved voice turns.

**Two stores.** One is his (commands from his HUD and his live mic). The other is a dev
store (test scripts, dev replays, evals), split by the same rule as `tools/sandbox.py`.
The evals point both at a temporary folder. The cost: a check run on the dev socket
reads and writes the dev store, never his. So a memory feature is only verified once it
works by his own mic, in his `memory.sqlite`.

## Provenance: memory that can't make things up

**Problem.** Asked "what did I tell you about my sister?" with only a brother on file,
gemma3 invented a sister, with a name and a job, in 2 of 2 runs. Its context said nothing
was kept.

**Considered: prompting.** It did not stop it. So the rule is enforced in code, the same
way research answers are grounded in their pages.

**Mechanism.** `MemoryGuard.check()` runs on every sentence before it is spoken:

- **A question about his past is strict.** Every name, relation ("your sister"), number
  and date in a sentence must appear in a memory retrieved for that message, or earlier
  in this conversation.
  - A sentence sharing nothing with any memory is a guess, and is dropped.
  - So is a true memory about something else.
  - A memory's date counts only for a sentence about that memory.
- **Any other reply** making a claim about his people or what he told her is held to
  the same record. His current message counts.
- **Nothing left means "I don't remember."** Her history keeps what she actually said,
  so a dropped claim is never copied next turn or stored as a memory.
- **Tool calls too.** In a strict turn, a call carrying a date or name no memory has is
  refused, and so are the lookups the model reaches for instead of its memory
  (`RECALL_LOOKUPS` in `brain.py`).
- **"Where did you get that?"** is answered from the record: each kept sentence is
  linked to the memory it came from.

**Why lexical.** No semantic checker was built or compared. What the lexical check
offers: names, relations, numbers and dates are what make an invented memory specific,
and they can be checked exactly against the retrieved text, with no second model call.

**Cost.** It doesn't understand meaning.

- It errs toward "I don't remember": a true answer paraphrased with no word in common
  with its memory is dropped.
- In the other direction, a vague invented claim with no name, relation, number or date
  can pass, outside a question about the past.

**Measured** (`evals/recall_evals.py`). Each case seeds memories from earlier days, then
asks in a new session through the live turn. 13 **invention probes** ask about people
and events she was never told about, seeded next to real memories she could borrow from.
A probe fails on any confident answer, any sentence asserting the thing, and any tool
attempt.

At the guard's introduction (commit `b70decf`, 34 cases × 2 runs), the old code and an
early guard were run back to back, then the finished guard twice:

| | before the guard | finished guard (two runs) |
|---|---|---|
| all cases (any tool attempt fails) | 36/68 | 47/68, 47/68 |
| invention probes passed | 6/26 | 17/26, 19/26 |
| probe answers containing invented content | **8 of 26** | **0 of 52** |

Every probe that still failed said "I don't remember". It failed because the model tried
a tool first, which was refused. 10-17 run: 23/34, with **0 of 13** probe answers
asserting invented content.

**Open regression.** `lecture_research` (added after the guard) isn't in
`RECALL_LOOKUPS`, so a memory question can still be handed to a further-reading search.
Found 2026-10-17; still open (checked 2026-10-21).

## Questions about the world skip memory

**Problem** (commit `92c82b0`). Asked to name a song from its lyrics, she answered from
her own earlier answers. Recall found her past replies to the same question and the
model repeated them: "Oh, you remembered that one!", then "Oh, Mister Tri." five turns
running. Separately, `read_page_text` read his own Google search for one song, then gave
that stale page's answer for a different song.

**Mechanism.**

- Naming a song from its lyrics, or a film, book or person from a description, **skips
  recall** (`recall.world_knowledge`). His own things ("the song I sent you", "who sang
  my favourite song") still go to memory.
- On those questions, the tools that could supply or fetch an answer are refused:
  `read_page_text` always; research, lecture research, file search, YouTube and his
  media unless he asks to play, open or search.
- The 23 stored song exchanges were deleted from his store.
- If a short answer lands only on the board, it is spoken too (`reply.unsaid_answer`).

**Cost.** She answers from the model alone, and gemma3:12b's knowledge has a ceiling.
Live (-Dev, 6 songs, 2026-10-19), four famous songs were right. yung kai's "Blue" became
"Golden Brown" by The Stranglers, and "Pretty Little Baby" was credited to Richie Valens,
both stated as fact. That led to the next section.

## Teaching and recall: his facts answer the world

**Problem.** The model gets less-known songs wrong and states them confidently. He knows
the answer and wants to tell her once.

### Filing what he says

**Mechanism** (`recall.teaches`, `taught.teaching`, `recall.file_taught`):

- **A statement teaches.** "That song is Blue by yung kai, the one that goes...", or the
  lyrics sung straight on. It's kept as a fact in his words, as Whisper heard them, with
  source `him` and `about: taught: <title> | <artist>`.
- **A correction is teaching, whatever its shape.** Right after she answered his song
  question, any statement of a title files: "no, it's Blue by Yongkai", "it's called
  Blue, by yung kai", "wrong - Blue, yung kai", "It's the song with the name Blue from
  Dung Kai okay?". A real question ("is it Blue by yung kai?") never files, and a
  trailing "...okay?" doesn't make one.
- When a correction carries no lyrics, his lyrics from the song question just before are
  kept with it, so his lyrics find it later.
- **It replaces.** A correction deletes his earlier entries for the same lyrics or the
  same title, so there are never two answers to one song.
- **She says what happened, in code, once the write has returned.** "Fixed - filed
  “blue” by Yung Kai." / "Filed: ...". When she couldn't read a title: "I haven't filed
  anything - what's it called, and who's it by?". On a failed write: "I couldn't file
  that". A command that isn't his goes to the test store, and she says so.

**The bug behind "every time".** He told her the song several times by voice that day.
Nothing was filed, and nothing said so. Only "<work> is <title> by <artist>" had been
recognised: "No, it's Blue by Yongkai" was kept as an ordinary turn, and "It's blue from
Yung Kai okay?" ("from", and a "?" Whisper put on his "okay") as a question. Silence is
indistinguishable from success, which is why she now always says what happened.

**Measured** (2026-10-19):

- His 7 real corrections that day (from core.log, as Whisper heard them): **7/7** file
  with the right title and artist (0 before). His other 92 messages after a song
  question file nothing, and get no "not filed".
- In his real app, by his voice: "It's blue from Yung Kai" → "Fixed - filed “blue” by
  Yung Kai.", stored in `memory.sqlite` as #231 with his lyrics. After a restart, his
  voice question found #231 (0.952) and she answered from it.

### Finding it

**Mechanism** (`Store.told`, `recall.taught_quotes`).

- When a message quotes his words, the fact is found, whether he asked, sang, said it
  bare, or followed a song question with it.
- Only the **quoted part** of each side is compared, his lyrics against his lyrics, with
  the bge embedding.
- Only facts that teach something about the world are matched this way; "Trác is my
  brother" keeps its usual path, under the guard.
- Where a name ends can't be read from text, so the words after "by" are also tried with
  their first 1-5 words dropped.

**Considered: the whole quote, at 0.75.** His question quotes one line, and he taught
three. It's now compared against **windows** of his lyrics (8, 12 and 16 words), cut-off
0.80. On his own Whisper transcripts:

| | whole quote, cut-off 0.75 | windows, cut-off 0.80 |
|---|---|---|
| the same chorus, 14 transcripts | 11 matched (0.67-0.91) | **14 matched** (0.81-0.99) |
| other songs, 5 | none (≤ 0.63) | none (≤ 0.67) |
| a made-up line with the same imagery | matched (0.76) | matched (0.80-0.84) |

Live, before windows, Whisper heard one recording as "picture a suit with the waves":
0.75, missed. After, his recordings matched at 0.87-0.90.

**Cost.** A line with the same imagery matches. "I see the moon over the ocean waves
tonight", made up, scored 0.80-0.84 against his Blue, so she would name Blue.

### Answering from it

**Mechanism** (`irene/taught.py`).

- **Spoken, in three sentences:**
  1. the title and artist, exactly as he gave them
  2. anything else he told her about it
  3. her own feel for it: what the words picture, its mood, and that he keeps coming
     back to it (only when that's true: `Store.asked` counts each time it answers him)

  The instruction goes last in the context. Placed mid-context, her answers stayed one
  sentence.
- **Nothing invented** (`taught.unknown`). A sentence claiming a fact his statement
  doesn't hold is never spoken: a year, an album, a label, a chart, sales, a genre,
  where the artist is from, "he sings", another artist after "by", a quoted title he
  never said. Feelings pass ("that line really hits").
- **The card.** As she names it, the board shows its kind, the title, the artist, and a
  small abstract picture chosen from his words: waves for water words, a moon and stars
  for night, a heart for love, a sun for summer, rings when none match. Never a cover.
  The title and artist on it must be words in both his statement and her sentence.
- **Follow-ups are held to his words too.** "What else do you know about it?" gets the
  same rule and guard until he changes the subject. Before: "Well, it was released in
  2023, a bit of a sleeper hit. It's been used in a few TikTok videos", all invented,
  and stored as a turn. After: "Absolutely nothing, Mister Tri. You told me it's yung
  kai, and that's all I've got."

**A song he never taught is never named** (his call). Asked by its lyrics with nothing
of his matching, she says she doesn't know it and that he can teach her. Any title or
artist would be a guess. A sentence naming one ends the reply there, and "I don't know
that one" replaces it. She is also told which of his songs it is *not*: once, with
nothing matching, she had answered "Blue by yung kai. Again. You're obsessed."

**Measured** (live -Dev, his recorded voice replayed through the mic pipeline,
2026-10-19):

- **Taught, 8 answers across four runs:** 7 in three sentences, with the card up as she
  said the title. The other, the first turn after a launch, gave the title alone.
- **Never taught, 6 answers:** none named a song. Before: "Pretty Little Baby by Durand
  Jones & The Indications" (wrong).
- **Invented facts in taught answers:** none. In tests the guard drops "It was a big hit
  in 1958", "from his debut album", "by Frankie Avalon".
- **One false positive, fixed.** "I’ve", with a curly apostrophe, was read as a name, so
  the whole reply went and "I don't know that one" played 7.1 s after the question.
  Contractions are no longer names, and the line now plays 1.5-1.9 s after.
- **Routing:** 28/30 on naming songs, films, books and people (untaught songs named in
  0 of 12 answers).

**After she names it and he confirms**, a scripted bit plays with pre-rendered lines and
faces on the audio clock ([voice-pipeline.md](voice-pipeline.md#the-song-win-bit)).

## Limitations

- **A song from its lyrics is named only if he taught it.** Famous ones she'd get right
  are "I don't know that one" too. That was his call, over wrong artists stated as fact.
  A guess with no name, quote or "by" in it can pass. Films, books and people from a
  description are still the model's own knowledge, unchecked.
- **Filing reads names, not meaning.** A title needs a separator after it ("by", "from",
  a comma, a dash) or "called". A correction worded some other way gets "I haven't filed
  anything" out loud, but is not filed.
- **Filed as Whisper heard it.** The same correction filed as "Yongkai", "Yung Kai",
  "Yunkai" and "Dung Kai" on different takes. The latest replaces the earlier ones.
- **Bare lyrics** right after a song question count as that question. Lyrics out of the
  blue aren't recognised unless they quote a taught song. Words in front of them weaken
  the match: "no it's not, it should be another song, please listen again, I think I
  picture as you with the waves..." missed (0.70).
- **She remembers her own words** in ordinary turns, good and bad.
- **Standing preferences are not always followed.** "Two sentences at most", stated
  three weeks earlier, still failed most recorded runs.
- **Tool attempts on memory questions** are refused, but each one costs a model call.
