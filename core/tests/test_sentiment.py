import pytest

from irene import sentiment


@pytest.mark.parametrize("said,mood", [
    ("Looks a little cringy, Irene.", "teasing"),
    ("That was a bit much, showing off like that", "teasing"),
    ("Sure you are, Irene.", "teasing"),
    ("Good job, Irene!", "praising"),
    ("thanks, that's exactly right", "praising"),
    ("You're the best", "praising"),
    ("I'm so tired today", "complaining"),
    ("I am absolutely knackered", "complaining"),
    ("my back hurts", "complaining"),
    ("No, that's not what I asked for", "frustrated"),
    ("ugh, wrong again", "frustrated"),
    ("haha that's brilliant", "joking"),
    ("just kidding", "joking"),
    ("I wonder why they call it that", "curious"),
    ("what do you think, Irene?", "curious"),
    ("Open my downloads folder", "neutral"),
    ("What's the capital of France?", "neutral"),
])
def test_it_reads_how_he_said_it(said, mood):
    assert sentiment.read(said).mood == mood, said


@pytest.mark.parametrize("said", [
    "Hey Irene!", "hello", "how are you?", "how's it going", "What are you doing?",
    "are you bored?", "did you miss me?", "goodnight", "you're funny", "do you like me?",
])
def test_conversation_is_not_a_task(said):
    assert sentiment.read(said).smalltalk, said


@pytest.mark.parametrize("said", [
    "show me the sources", "open chrome", "what time is it",
    "search for kendo grips", "save that as a pdf",
])
def test_asking_for_work_is_never_small_talk(said):
    assert not sentiment.read(said).smalltalk, said


def test_a_question_is_not_by_itself_a_task():
    # "how are you?" is a question and pure conversation; the task test must not
    # simply treat a question mark as work
    assert sentiment.read("how are you?").smalltalk
    assert not sentiment.read("What's the capital of France?").smalltalk


@pytest.mark.parametrize("said", [
    "Anyway - what's tenouchi?",
    "By the way, did you see the news?",
    "forget that, something else",
    "never mind that, I have a question",
])
def test_topic_shifts_are_spotted(said):
    assert sentiment.read(said).topic_shift, said


def test_the_section_says_what_it_asks_of_her():
    teased = sentiment.read("that's a bit cringy").section()
    assert "teasing" in teased and "Never defensive" in teased
    chat = sentiment.read("how are you?").section()
    assert "not a task" in chat and "do not call a tool" in chat
    shift = sentiment.read("anyway, what's for dinner").section()
    assert "changed the subject" in shift


def test_a_plain_task_in_a_plain_mood_gets_no_coaching():
    # the note costs prompt tokens on every message; a neutral command earns none
    assert sentiment.read("open my downloads folder").section() == ""
    assert sentiment.read("").section() == ""


def test_every_mood_has_guidance_and_never_raises():
    for mood in ("teasing", "praising", "complaining", "frustrated", "joking", "curious"):
        assert sentiment.GUIDANCE[mood].strip()
    assert "neutral" not in sentiment.GUIDANCE
    for odd in ("", "   ", "?" * 400, "\n\n"):
        assert sentiment.read(odd).mood == "neutral"


@pytest.mark.parametrize("said,mood", [
    ("guess what, I got the job!", "surprising"),
    ("I passed my driving test", "surprising"),
    ("I'm engaged!", "surprising"),
    ("my cat died this morning", "bad_news"),
    ("I got fired today", "bad_news"),
    ("bad news, I didn't get the flat", "bad_news"),
])
def test_big_news_and_bad_news(said, mood):
    assert sentiment.read(said).mood == mood, said


@pytest.mark.parametrize("said,first", [
    ("haha that's brilliant", "giggle"),
    ("that was a bit much, showing off like that", "sulking"),
    ("Good job, Irene!", "sheepish"),
    ("guess what, I got the job!", "starryEyed"),
    ("my cat died this morning", "sad"),
])
def test_an_emotional_moment_names_its_reaction(said, first):
    read = sentiment.read(said)
    assert read.cues[0] == first
    assert f"<cue>{first}</cue>" in read.section()


def test_every_mood_reaction_is_a_real_cue_and_has_a_second_choice():
    from irene import react

    for mood, names in sentiment.MOOD_CUES.items():
        assert len(names) >= 2, f"{mood}: a second cue, so it never plays twice running"
        for name in names:
            assert name in react.ALL, f"{mood}: {name} is not a cue"
    assert sentiment.read("Open my downloads folder").cues == ()


def test_so_much_is_not_teasing():
    assert sentiment.read("Thank you, Irene. Honestly, you've made this week so much easier.").mood == "praising"
    assert sentiment.read("that was a bit much").mood == "teasing"


@pytest.mark.parametrize("said,mood", [
    ("Why did the scarecrow win an award? Because he was outstanding in his field.", "joking"),
    ("What do you call a fish with no eyes? A fsh.", "joking"),
    ("Put the thing from before into the other one, but not like last time.", "unclear"),
    ("Why did the build fail?", "neutral"),
    ("Open the other one", "neutral"),
])
def test_a_told_joke_and_a_muddled_request(said, mood):
    assert sentiment.read(said).mood == mood, said
