"""Story mode (irene/story.py): he tells her about his life and she is his friend -
reacting, never fixing unless he asks."""
from irene import story
from irene.brain import STORY_WORDS, StreamingReply


def test_stories_are_stories():
    for said in (
        "So today at work my coworker Trác took credit for my slides in front of the whole team.",
        "You won't believe what my sister did at dinner.",
        "Okay so I kind of yelled at my roommate because she ate my leftovers.",
        "Lan asked me out today!",
        "Nobody showed up to my birthday dinner.",
        "So I sat in the wrong lecture for forty minutes today before I realised.",
    ):
        assert story.read(said), said


def test_requests_and_questions_are_not_stories():
    for said in (
        "Open my downloads folder.",
        "What's the weather in Da Lat?",
        "Who won the 2026 Ballon d'Or?",
        "Tell me about the French revolution.",
        "I'm so tired today.",
        "I think she said the meeting is at 3, can you set a reminder?",
        "Hey Irene, how are you?",
    ):
        assert story.read(said) is None, said


def test_the_beat_fits_the_story():
    assert story.read("My manager yelled at me in the hallway because HE forgot the invoice.").beat == "wronged"
    assert story.read("So I kind of yelled at my roommate because she ate my leftovers.").beat == "his_fault"
    assert story.read("Turns out my sensei was a national champion and never told anyone.").beat == "shock"
    assert story.read("Nobody showed up to my birthday dinner.").beat == "sad"
    # a machine dying is not grief
    assert story.read("The projector died right when he started presenting my slides lol").beat != "sad"


def test_thanks_corrections_and_questions_are_not_stories():
    # each was a story once (eval parity: 13/49 reaction cases claimed): a capitalised
    # "anyone did anything" matched every word under re.I
    for said in (
        "Thank you, Irene. Honestly, you've made this week so much easier.",
        "That's the old one. I said report.pdf.",
        "No, that's not what I asked for.",
        "That's wrong - it's a strike to the opponent's left dou.",
        "The backup script failed again last night.",
        "I've got kendo practice tonight, working on my men strikes.",
        "Anyway - my teacher told me to improve my tenouchi. What's that?",
        # his own news, one thing that happened: the plain emotional read
        "I lost three chess games in a row today. My openings are terrible.",
        "I just got accepted into my dream university!",
    ):
        assert story.read(said) is None, said
    told = ["So my manager yelled at me in the hallway today because HE forgot to send the invoice."]
    for said in ("Thanks, that helps.", "No, I meant the other manager.", "Anyway, what's the weather tomorrow?"):
        assert story.read(said, told) is None, said


def test_a_story_is_still_a_story():
    for said in (
        "So this girl I was talking to for two weeks just ghosted me. Like completely, no reply.",
        "So my best friend Duy and his girlfriend broke up today, out of nowhere, in the middle of dinner.",
        "My boss stopped by my desk today and said my report was the best one this quarter.",
        "My sister deleted all our group photos from the shared folder and then said it was an accident.",
        "Okay so I kind of yelled at my roommate because she ate my leftovers.",
        "My keiko was brutal tonight, sensei had us doing kakari geiko.",
    ):
        assert story.read(said) is not None, said
    told = ["So today at work my coworker Trác took credit for my slides in front of the whole team."]
    assert story.read("What should I do about him?", told).advice_asked


def test_a_continuation_keeps_the_story_and_its_beat():
    told = ["So my manager yelled at me in the hallway today because HE forgot to send the invoice."]
    tale = story.read("And then he acted like nothing happened in the meeting after.", told)
    assert tale and tale.beat == "wronged"
    # a task after the story ends it
    assert story.read("Can you open YouTube and play some lofi?", told) is None


def test_people_are_remembered_with_or_without_diacritics():
    told = ["So today at work my coworker Trác took credit for my slides.", "And the manager thanked him for them."]
    tale = story.read("And Trac did it AGAIN with my spreadsheet.", told)
    trac = [p for p in tale.cast if story._fold(p.name) == "trac"]
    assert len(trac) == 1
    assert trac[0].role == "coworker" and trac[0].pronoun == "he" and trac[0].mentions == 2
    assert "Trác (his coworker) - a man: he/him" in tale.section()


def test_advice_only_when_asked():
    told = ["So today at work my coworker Trác took credit for my slides in front of the whole team."]
    assert story.read("What should I do about him?", told).advice_asked
    assert not story.read(told[0]).advice_asked
    for advice in ("You should talk to HR.", "Maybe try telling him how you feel.", "Have you tried talking to him?", "Don't let it slide, sir.", "Tell him you noticed."):
        assert story.is_advice(advice), advice
    for reaction in ("No WAY!", "Your own slides?!", "Tell me everything!", "Did you tell him?", "What did he say?"):
        assert not story.is_advice(reaction), reaction


def _say(stream: StreamingReply, raw: str) -> list[str]:
    return [line.text for line in [*stream.feed(raw), *stream.finish()]]


def test_the_guard_drops_unasked_advice():
    tale = story.read("So today my coworker took credit for my slides in front of everyone.")
    stream = StreamingReply(tale=tale)
    said = _say(stream, "<speak><cue>fuming</cue>Your own slides?! You should report him to HR. <cue>curious</cue>What did he say?</speak>")
    assert said == ["Your own slides?!", "What did he say?"]
    assert stream.edited and stream.advice_dropped


def test_asked_for_advice_it_stays():
    told = ["So today at work my coworker Trác took credit for my slides in front of the whole team."]
    stream = StreamingReply(tale=story.read("What should I do?", told))
    assert "You should say it out loud next meeting." in _say(stream, "<speak><cue>thinking</cue>Honestly? You should say it out loud next meeting.</speak>")


def test_a_story_reply_is_short():
    tale = story.read("So today my coworker took credit for my slides in front of everyone.")
    stream = StreamingReply(tale=tale)
    said = " ".join(_say(stream, "<speak>" + "No way, that is so unfair. " * 20 + "</speak>"))
    assert len(said.split()) <= STORY_WORDS


def test_a_repeated_opener_is_dropped():
    tale = story.read("And then he did it again!", ["So today my coworker took credit for my slides in front of everyone."])
    stream = StreamingReply(tale=tale, stale=("Seriously?!",))
    assert _say(stream, "<speak><cue>fuming</cue>Seriously?! <cue>curious</cue>What did he take this time?</speak>") == ["What did he take this time?"]


def test_she_about_a_man_is_put_right():
    told = ["So today at work my coworker Trác took credit for my slides.", "And the manager thanked him and he just smiled."]
    tale = story.read("What should I do about Trác?", told)
    assert tale.men_only
    stream = StreamingReply(tale=tale)
    assert _say(stream, "<speak>Tell her privately you saw her taking credit.</speak>") == ["Tell him privately you saw his taking credit."]
    # he mentioned a woman: nothing is touched
    assert not story.read("And my sister said she hates him.", told).men_only


def test_fallback_never_repeats():
    lines = [story.fallback("shock") for _ in range(10)]
    assert all(a != b for a, b in zip(lines, lines[1:]))


def test_her_question_after_the_speak_tag_is_said():
    tale = story.read("So today my coworker took credit for my slides in front of everyone.")
    stream = StreamingReply(tale=tale)
    assert _say(stream, "<speak><cue>fuming</cue>The MANAGER?! He thanked him?</speak> What did you say?") == ["The MANAGER?!", "He thanked him?", "What did you say?"]
    assert story.asks_back(stream.said)


def test_no_question_back_gets_one():
    assert not story.asks_back(["Your own SLIDES?!"])
    assert story.asks_back(["What did he say?"])
    assert story.asks_back(["No way!", "Then what?"])
    assert story.follow_up("wronged").endswith("?")


def test_forgetting_is_a_command_not_a_story():
    """Live 2026-10-13: "Forget what I told you about Trác" was taken as a story about
    Trác - no tool offered, and she only said "consider it forgotten"."""
    for said in ("Forget what I told you about Trác.", "Erase what you know about my kendo grading.",
                 "Remember that my locker code is 4412."):
        assert story.read(said) is None, said
    assert story.read("My younger brother Trác just started university in Hanoi.") is not None
