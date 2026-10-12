"""Voice input without a microphone: the endpointer, wake phrases, word error rate,
the corpus checks, corrections, and what the voice loop does with what it heard."""
import asyncio

import numpy as np
import pytest

from irene import wake
from irene.corpus import TAKES, Progress, check_take, load_sentences
from irene.listen import BLOCK, BLOCK_S, SAMPLE_RATE, BargeGuard, Endpointer, complete_phrase, pitch_falls
from irene.stt import Heard, Transcriber, vocabulary
from irene.voice_data import VoiceData
from irene.wer import wer

SILENT = np.zeros(BLOCK, np.float32)


def voiced(freq=150.0, amp=0.2, i=0):
    t = (np.arange(BLOCK) + i * BLOCK) / SAMPLE_RATE
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def run(ep, blocks):
    """(event kinds with times, the end audio)"""
    out, end = [], None
    for k, (frame, prob) in enumerate(blocks):
        for e in ep.feed(frame, prob):
            out.append((e.kind, round(k * BLOCK_S, 2), round(e.remaining, 2)))
            if e.kind == "end":
                end = e.audio
    return out, end


def speech(seconds):
    return [(voiced(i=i), 0.9) for i in range(int(seconds / BLOCK_S))]


def quiet(seconds):
    return [(SILENT, 0.02)] * int(seconds / BLOCK_S)


# ---- end of speech -----------------------------------------------------------------

def test_he_gets_three_full_seconds_to_pause_mid_thought():
    ep = Endpointer()
    events, end = run(ep, speech(1.0) + quiet(2.5) + speech(0.8) + quiet(3.2))
    kinds = [k for k, _, _ in events]
    assert kinds[0] == "speech" and "resume" in kinds and kinds.count("end") == 1
    ended_at = next(t for k, t, _ in events if k == "end")
    # 1.0 + 2.5 + 0.8 speech, then 3 s of silence
    assert 4.3 + 2.9 <= ended_at <= 4.3 + 3.1
    assert len(end) >= int(4.3 * SAMPLE_RATE)  # both halves of what he said, in one turn


def test_the_countdown_is_reported_and_counts_down():
    ep = Endpointer()
    events, _ = run(ep, speech(0.6) + quiet(3.2))
    ticks = [r for k, _, r in events if k == "silence"]
    assert len(ticks) >= 20 and ticks[0] > 2.8 and ticks[-1] < 0.2
    assert all(a >= b for a, b in zip(ticks, ticks[1:]))


def test_a_clearly_finished_sentence_ends_sooner():
    ep = Endpointer()
    events = []
    for k, (frame, prob) in enumerate(speech(1.0) + quiet(3.2)):
        for e in ep.feed(frame, prob):
            events.append((e.kind, k * BLOCK_S))
            if e.kind == "check":
                ep.verdict(True, e.generation)
    ended_at = next(t for k, t in events if k == "end")
    assert ended_at <= 1.0 + 0.9 + 0.1


def test_a_stale_verdict_does_not_shorten_the_next_utterance():
    ep = Endpointer()
    run(ep, speech(0.6) + quiet(3.2))
    old = ep.generation
    run(ep, speech(0.6))
    ep.verdict(True, old)
    events, _ = run(ep, quiet(3.2))
    assert next(t for k, t, _ in events if k == "end") >= 2.9


def test_a_cough_is_not_speech():
    ep = Endpointer()
    events, _ = run(ep, speech(0.1) + quiet(1.0) + speech(0.12) + quiet(1.0))
    assert events == []


def test_the_first_word_is_not_clipped():
    ep = Endpointer()
    _, end = run(ep, quiet(1.0) + speech(0.5) + quiet(3.2))
    assert len(end) >= int((0.5 + 0.25) * SAMPLE_RATE)


@pytest.mark.parametrize("text,done", [
    ("What time is it?", True),
    ("Open my downloads folder.", True),
    ("I was thinking that maybe we could", False),
    ("Set a timer for ten, and", False),
    ("So the thing is...", False),
    ("Remind me to call, um.", False),
    # Whisper puts a full stop on a sentence he left hanging
    ("So I was thinking that maybe we could.", False),
    ("", False),
])
def test_a_complete_phrase(text, done):
    assert complete_phrase(text) is done


def glide(f0, f1, seconds=0.8):
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    f = np.linspace(f0, f1, len(t))
    return (0.3 * np.sin(2 * np.pi * np.cumsum(f) / SAMPLE_RATE)).astype(np.float32)


def test_falling_pitch_is_heard_and_level_or_rising_is_not():
    assert pitch_falls(glide(180, 110))
    assert not pitch_falls(glide(140, 142))
    assert not pitch_falls(glide(120, 190))
    assert not pitch_falls(np.zeros(SAMPLE_RATE, np.float32))
    # the check runs into the silence after he stopped: that silence is not his pitch
    assert pitch_falls(np.concatenate([glide(180, 110), np.zeros(int(0.5 * SAMPLE_RATE), np.float32)]))


def test_her_echo_does_not_barge_in_even_when_she_gets_louder_but_he_does():
    # the Victorian entrance, live: a quiet carriage bell, then her line much louder.
    # The echo follows what she plays, so loud is fine as long as it is HER loud.
    guard = BargeGuard(vad_threshold=0.8, min_speech_s=0.3, over_playback=1.6, coupling=0.3)
    bell = [(voiced(amp=0.02, i=i), 0.3, 0.06) for i in range(40)]
    line = [(voiced(amp=0.12, i=i), 0.95, 0.4) for i in range(60)]
    assert not any(guard.feed(f, p, playing) for f, p, playing in bell + line), "her own voice through the speakers"
    him = [(voiced(amp=0.2, i=i) + voiced(amp=0.12, freq=230, i=i), 0.97, 0.4) for i in range(20)]
    assert any(guard.feed(f, p, playing) for f, p, playing in him), "him, over her, clearly louder than her echo"


def test_he_barges_in_between_her_words_too():
    guard = BargeGuard()
    quiet_gap = [(voiced(amp=0.15, i=i), 0.95, 0.0) for i in range(20)]
    assert any(guard.feed(f, p, playing) for f, p, playing in quiet_gap)


def test_playback_level_is_what_she_played_a_moment_ago():
    from irene.listen import Playback

    pb = Playback()
    pb.push(np.full(480, 0.3, np.float32), now=10.0)
    assert pb.level(now=10.1) == pytest.approx(0.3, abs=1e-6)  # heard through the room ~100 ms later
    assert pb.level(now=10.0) == 0.0  # not yet out of the speaker
    assert pb.level(now=11.0) == 0.0  # long gone


# ---- wake phrases ------------------------------------------------------------------

@pytest.mark.parametrize("text,phrase,rest", [
    ("Hey Irene.", "hey", ""),
    ("Hey, Irene, what time is it?", "hey", "what time is it?"),
    ("Hi Irene open my downloads", "hey", "open my downloads"),
    ("Irene Adler.", "adler", ""),
    ("Hey Irene Adler!", "adler", ""),
    ("Irene Adla, are you there?", "adler", "are you there?"),
])
def test_wake_phrases_always_wake_her(text, phrase, rest):
    found = wake.find(text)
    assert found is not None and found.phrase == phrase and found.rest == rest


def test_bare_irene_only_while_awake_and_only_if_enabled():
    assert wake.find("Irene, what's the weather?") is None
    assert wake.find("Irene, what's the weather?", awake=True).rest == "what's the weather?"
    assert wake.find("Irene, what's the weather?", awake=True, bare_while_awake=False) is None


@pytest.mark.parametrize("text", ["I read about Irene Joliot-Curie", "hey there", "They're in Ireland", "The irony is"])
def test_things_that_are_not_for_her(text):
    assert wake.find(text) is None


# ---- speech to text ----------------------------------------------------------------

def test_whisper_refuses_anything_but_float16():
    config = {"stt": {"model_dir": "models/x", "compute_type": "int8"}}
    with pytest.raises(ValueError, match="float16"):
        Transcriber(config)


def test_his_vocabulary_is_in_the_hotwords():
    terms = vocabulary()
    for word in ("Irene", "Tri", "kendo", "shinai", "men", "kote", "dou", "gyaku-dou", "tsuki", "kamae", "keiko", "sensei"):
        assert word in terms
    assert "Irene" in Transcriber().hotwords


def test_a_guess_is_not_confident():
    assert Heard("Open my downloads.", -0.2, 0.01, 1.2, 80).confident(-0.85, 0.6)
    assert not Heard("Oh pen my down lords.", -1.4, 0.05, 1.2, 80).confident(-0.85, 0.6)
    assert not Heard("", -0.1, 0.0, 1.2, 80).confident(-0.85, 0.6)
    assert not Heard("Thanks for watching.", -0.3, 0.9, 1.2, 80).confident(-0.85, 0.6)


# ---- word error rate ---------------------------------------------------------------

@pytest.mark.parametrize("ref,hyp,rate", [
    ("Set a timer for twenty-five minutes.", "Set a timer for 25 minutes.", 0.0),
    ("Set the volume to thirty percent.", "Set the volume to 30%.", 0.0),
    ("It costs three hundred and forty-nine dollars and ninety-nine cents.", "It costs $349.99.", 0.0),
    ("My flight leaves at six fifteen a.m.", "My flight leaves at 6:15 a.m.", 0.0),
    ("Good morning, Mister Tri.", "Good morning, Mr. Tree.", 0.25),
    ("Open my downloads folder.", "", 1.0),
])
def test_word_error_rate_counts_words_not_formatting(ref, hyp, rate):
    assert wer(ref, hyp) == pytest.approx(rate)


# ---- the corpus --------------------------------------------------------------------

def test_the_corpus_has_a_fixed_fifth_held_out():
    sentences = load_sentences()
    assert 350 <= len(sentences) <= 450
    test = [s for s in sentences if s["split"] == "test"]
    assert len(test) == len(sentences) // 5
    assert all(s["split"] == ("test" if i % 5 == 4 else "train") for i, s in enumerate(sentences))
    topics = {s["topic"] for s in sentences}
    for want in ("software", "tech", "news", "games", "names", "everyday", "work", "conversation", "commands", "research", "numbers", "sounds", "kendo", "chess", "products", "vietnam", "people"):
        assert want in topics
    # the terms he asked for are a real share now, but general speech stays the bulk
    kendo_chess = sum(s["topic"] in ("kendo", "chess") for s in sentences)
    assert kendo_chess <= len(sentences) * 0.16
    sounds = {x for s in sentences for x in s.get("sounds", [])}
    assert {"th", "final consonants", "s/z endings", "clusters", "-ed endings", "l/n", "r/l"} <= sounds


# the terms Whisper gets wrong from him ("first dan"): each in at least three
# different natural sentences, across the corpus
TERMS = (
    "iPhone", "macOS", "NVIDIA", "GitHub", "Docker", "Kubernetes", "TypeScript", "Claude", "ChatGPT",
    "Yu-Gi-Oh", "Pokemon", "Nintendo Switch", "Zelda", "Splatoon", "Elden Ring",
    "dan", "kyu", "tenouchi", "oji waza", "debana", "suriage", "kaeshi", "shiai", "keiko", "sensei", "dojo", "bogu",
    "shinai", "men", "kote", "do", "tsuki",
    "Sicilian", "Najdorf", "en passant", "zugzwang", "fianchetto", "Carlsen",
    "Da Lat", "Ho Chi Minh City", "Saigon", "Hanoi", "Hoi An", "Ha Long Bay", "Da Nang", "Hue", "Nha Trang", "Sapa",
    "Phu Quoc", "Xuan Huong Lake", "Langbiang",
    "pho", "banh mi", "bun cha", "com tam", "banh xeo", "bun bo Hue", "goi cuon", "ca phe sua da", "banh trang nuong",
    "cao lau", "mi Quang", "che",
    "Elon Musk", "Tesla", "SpaceX", "Jensen Huang", "Sam Altman", "OpenAI", "Anthropic", "Dario Amodei", "Google",
    "Sundar Pichai", "Microsoft", "Satya Nadella", "Apple", "Tim Cook", "Meta", "Mark Zuckerberg", "Samsung",
    "VinFast", "Vingroup", "Hideo Kojima", "Shigeru Miyamoto",
)


def test_every_hard_term_is_in_at_least_three_sentences():
    import re

    texts = [s["text"] for s in load_sentences()]
    thin = {}
    for term in TERMS:
        n = sum(1 for text in texts if re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", text, re.I))
        if n < 3:
            thin[term] = n
    assert not thin, f"these need more sentences: {thin}"




def tone(seconds, amp=0.2):
    return voiced(amp=amp) if seconds == 0 else (amp * np.sin(np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE * 2 * np.pi * 180)).astype(np.float32)


def test_a_take_is_checked_for_level_clipping_length_and_words():
    target = "Open my downloads folder."
    assert check_take(tone(2.0), target, "Open my downloads folder.").ok
    assert check_take(tone(2.0, amp=0.003), target, target).reason == "quiet"
    loud = tone(2.0, amp=1.4).clip(-1, 1)
    assert check_take(loud, target, target).reason == "clipped"
    assert check_take(tone(0.3), target, target).reason == "short"
    assert check_take(tone(2.0), target, "Close the panel please.").reason == "words"


def test_progress_resumes_from_the_files_three_takes_a_sentence(tmp_path):
    sentences = [{"id": "a", "text": "One."}, {"id": "b", "text": "Two."}]
    progress = Progress(sentences, tmp_path)
    assert progress.next() == (0, sentences[0], 1)
    good = check_take(tone(1.0), "One.", "One.")
    for take in range(1, TAKES + 1):
        progress.save(sentences[0], take, tone(1.0), good, "s1")
    assert (tmp_path / "a" / "take3.wav").exists() and (tmp_path / "a" / "take3.json").exists()
    # a new session (a new Progress) picks up at the next sentence
    again = Progress(sentences, tmp_path)
    assert again.done() == 1 and again.next() == (1, sentences[1], 1)
    # redo throws away the newest take
    assert again.undo_last("a") == 3 and again.next() == (0, sentences[0], 3)


# ---- corrections -------------------------------------------------------------------

def test_a_retyped_sentence_is_his_correction(tmp_path):
    data = VoiceData(tmp_path)
    data.save_turn(tone(1.0), "Set a timer for fifteen minutes on the coat.", {})
    assert data.correction_for("what time is it", "typed") is None  # a new command, not a fix
    assert data.correction_for("Set a timer for fifteen minutes on the kote.", "typed") == "Set a timer for fifteen minutes on the kote."
    lines = (tmp_path / "corrections.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and '"heard": "Set a timer for fifteen minutes on the coat."' in lines[0]
    assert len(list((tmp_path / "turns").rglob("*.wav"))) == 1


def test_no_i_said_is_a_spoken_correction(tmp_path):
    data = VoiceData(tmp_path)
    data.save_turn(tone(1.0), "Open my down lords.", {})
    assert data.correction_for("No, I said open my downloads", "spoken") == "open my downloads"


def test_a_correction_only_counts_for_a_minute(tmp_path):
    data = VoiceData(tmp_path)
    data.save_turn(tone(1.0), "Open my down lords.", {})
    assert data.correction_for("Open my downloads.", "typed", now=data.last.at + 61) is None


# ---- what the voice loop does with what it heard ---------------------------------

class FakeBridge:
    def __init__(self):
        self.sent = []
        self.state_listeners = []

    def send_threadsafe(self, message):
        self.sent.append(message)

    async def send(self, message):
        self.sent.append(message)


class FakeCore:
    def __init__(self):
        self.bridge = FakeBridge()
        self.said, self.commands, self.summons = [], [], []
        self.last_react = None

    async def say(self, text, react=None):
        self.said.append((text, react.name if react else None))

    async def on_command(self, message):
        self.commands.append(message)

    async def summon_entrance(self, name=None):
        self.summons.append(name)

    async def summon_by_voice(self, adler):
        self.summons.append("victorian" if adler else None)


def voice(tmp_path):
    from irene.voice_loop import Voice

    v = Voice(FakeCore())
    v.data = VoiceData(tmp_path)
    return v


def hear(v, text, awake=False, sure=True):
    heard = Heard(text, -0.2 if sure else -1.5, 0.02, 1.0, 50)
    asyncio.run(v.on_heard(heard, tone(1.0), awake))


def test_asleep_only_a_wake_phrase_counts(tmp_path):
    v = voice(tmp_path)
    hear(v, "What time is it?")
    assert v.core.commands == [] and v.core.summons == []
    assert not list(tmp_path.rglob("*.wav")), "room talk that was not for her is not kept"


def test_hey_irene_alone_summons_a_random_entrance_and_irene_adler_the_victorian(tmp_path):
    v = voice(tmp_path)
    hear(v, "Hey Irene.")
    hear(v, "Irene Adler.")
    assert v.core.summons == [None, "victorian"]
    assert v.awake


def test_a_wake_phrase_with_a_command_just_answers_through_the_typed_path(tmp_path):
    v = voice(tmp_path)
    hear(v, "Hey Irene, what time is it?")
    assert v.core.commands == [{"text": "what time is it?", "via": "voice", "_origin": "mic"}]
    assert v.core.summons == []
    saved = list((tmp_path / "turns").rglob("*.json"))
    assert len(saved) == 1 and len(list((tmp_path / "turns").rglob("*.wav"))) == 1


def test_awake_a_follow_up_needs_no_wake_word(tmp_path):
    v = voice(tmp_path)
    hear(v, "And how long until Christmas?", awake=True)
    hear(v, "Irene, set a timer for five minutes.", awake=True)
    assert [c["text"] for c in v.core.commands] == ["And how long until Christmas?", "set a timer for five minutes."]


def test_a_guess_is_never_acted_on(tmp_path):
    v = voice(tmp_path)
    hear(v, "Hey Irene, quarantine the whole desktop", sure=False)
    assert v.core.commands == []
    from irene.voice_loop import SAY_AGAIN

    assert v.core.said and v.core.said[0][0] in SAY_AGAIN
    assert v.core.said[0][1] in ("headTilt", "sheepish", "confused"), "a puzzled cue, never none"
    assert v.awake, "and she keeps listening for the retry"


def test_other_people_talking_in_the_room_is_never_acted_on_or_kept(tmp_path):
    # a real capture: Vietnamese conversation nearby, heard while she was listening
    v = voice(tmp_path)
    hear(v, "Ngày nào cũng ăn như cơm bữa mà sao con dính nó chết nhỉ em nhỉ", awake=True)
    hear(v, "Game of hạt hả nấy chư?", awake=True, sure=False)
    assert v.core.commands == [] and v.core.said == []
    assert not list(tmp_path.rglob("*.wav"))
    hear(v, "Play some music by Phở Restaurant", awake=True)  # an accented word in English is fine
    assert len(v.core.commands) == 1


def test_her_own_voice_is_never_taken_for_his(tmp_path):
    # live: the Victorian line came back through the speakers as a wake phrase
    v = voice(tmp_path)
    v.heard_her("Irene Adler. Charmed, I'm sure.")
    assert v.is_her("Irene Adler, charmed, I'm sure.")
    assert v.is_her("charmed I'm sure")  # a fragment of it
    assert not v.is_her("Irene Adler, what time is it?")
    hear(v, "Irene Adler. Charmed, I'm sure.")
    assert v.core.summons == [] and v.core.said == [] and v.core.commands == []


def test_his_speech_counts_even_when_it_flickers():
    # live: his words over her went 0.90, 0.52, 0.84, 0.92, 0.99 on the VAD - a
    # stop consonant is not him stopping
    guard = BargeGuard(vad_threshold=0.8, min_speech_s=0.3)
    probs = [0.9, 0.52, 0.84, 0.92, 0.99, 0.6, 0.95, 0.97, 0.88, 0.5, 0.93, 0.96, 0.91, 0.94]
    fired = [guard.feed(voiced(amp=0.2, i=i), p, 0.05) for i, p in enumerate(probs)]
    assert any(fired)
    # but a scatter of loud blips in a quiet room is not speech
    guard.reset()
    blips = [0.95 if i % 4 == 0 else 0.1 for i in range(40)]
    assert not any(guard.feed(voiced(amp=0.2, i=i), p, 0.0) for i, p in enumerate(blips))


def test_the_mic_callbacks_the_listener_is_built_with_all_exist(tmp_path):
    # a refactor once deleted Voice._event: the mic then failed to open on every
    # start ("no attribute '_event'") and no test noticed
    import inspect

    from irene.listen import MicListener

    v = voice(tmp_path)
    params = list(inspect.signature(MicListener.__init__).parameters)[2:]
    assert params[:3] == ["on_event", "on_barge", "on_level"]
    for callback in (v._event, v._barge, v._level):
        assert callable(callback)


def test_mic_events_reach_the_conversation_and_the_corpus(tmp_path):
    from irene.listen import Event

    v = voice(tmp_path)
    handled = []

    async def handle(event):
        handled.append(("conversation", event.kind))

    v._handle = handle

    class Corpus:
        active = False

        async def on_event(self, event):
            handled.append(("corpus", event.kind))

    v.core.corpus = Corpus()

    async def main():
        v.loop = asyncio.get_running_loop()
        v._event(Event("speech"))
        v.core.corpus.active = True
        v._event(Event("end"))
        await asyncio.sleep(0.05)

    asyncio.run(main())
    assert handled == [("conversation", "speech"), ("corpus", "end")]


def test_whisper_noise_phrases_are_never_commands(tmp_path):
    # live, from his room with nobody talking to her: "Thank you.", "Outro Music",
    # "I'm not sure what I'm doing."
    v = voice(tmp_path)
    for text in ("Thank you.", "Outro Music", "I'm not sure what I'm doing.", "Thanks for watching!"):
        hear(v, text, awake=True)
    assert v.core.commands == [] and v.core.said == []
    hear(v, "Thank you, that was perfect.", awake=True)  # a real sentence still counts
    assert len(v.core.commands) == 1


def test_wake_up_phrases_summon_and_ordinary_talk_does_not():
    from irene import wake

    for said in ("Wake up Irene.", "Wake up, Irene!", "Wakeup Irene", "Wake up, daddy's home.", "Wake up! Daddy's home.", "Wake up daddy is home"):
        found = wake.find(said)
        assert found is not None and found.phrase == "wakeup" and found.rest == "", said
    assert wake.find("Wake up, daddy's home, what time is it?").rest == "what time is it?"
    assert wake.find_within("so anyway wake up daddy's home and then").phrase == "wakeup"
    for said in ("I need to wake up early", "My daddy's home now", "wake up the dog"):
        assert wake.find(said) is None, said
