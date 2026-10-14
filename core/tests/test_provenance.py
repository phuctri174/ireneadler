"""Her memory never invents: a claim about his people or his past is spoken only
when a retrieved memory (or this conversation) says it, and she can say which
memory it came from."""
import time
from datetime import datetime

from irene import recall
from irene.brain import Conversation
from irene.provenance import Evidence, LastAnswer, MemoryGuard, asks_source, names, where_from
from irene.recall import Item
from tests.test_brain import FakeHost, FakeLLM, run

NOW = time.time()
TRAC = Item(1, "fact", NOW - 9 * 86400, "", "Trác is my younger brother, he just started university in Hanoi")
LECTURE = Item(2, "lecture", NOW - 3 * 86400, "MATH 221, lecture 5", "Eigenvalues. Homework: problems 4.2 to 4.9, due Friday.")


def guard(items=(), strict=True, asked="", session=()):
    return MemoryGuard(Evidence(list(items), list(session), NOW), strict, asked)


def test_a_relation_no_memory_names_is_never_said():
    g = guard([TRAC], asked="What did I tell you about my sister?")
    assert g.check("You told me your sister just started university in Hanoi.") is None
    assert g.check("I don't remember you telling me about a sister.")
    # true, but not what he asked: the brother is no answer about a sister
    assert g.check("You mentioned your brother Trác is studying in Hanoi.") is None
    assert guard([TRAC], asked="What did I tell you about my brother?").check("You mentioned your brother Trác is studying in Hanoi.")
    # a guess with no name in it is still a guess (live: "Was it about her cats?")
    assert g.check("Was it about her cats, or the new job?") is None
    assert g.check("I don’t remember a sister.")
    assert g.dropped == [
        "You told me your sister just started university in Hanoi.",
        "You mentioned your brother Trác is studying in Hanoi.",
        "Was it about her cats, or the new job?",
    ]


def test_a_name_number_or_day_from_nowhere_is_dropped():
    g = guard([LECTURE], asked="what was the homework?")
    assert g.check("Problems 4.2 to 4.9, due Friday.")
    assert g.check("Problems 3.1 to 3.5, due Monday.") is None
    assert g.check("Professor Nguyen set it.") is None


def test_a_memorys_date_is_no_evidence_for_another_date():
    # live eval: "Tuesday, October 8th" for his birthday, made of an unrelated
    # memory's date label ("Tue 6 Oct, 8 days ago")
    knife = Item(4, "turn", NOW - 8 * 86400, "", 'He said: "how do I sharpen a kitchen knife" You said: "A whetstone at 15 degrees."')
    g = guard([knife], asked="When's my birthday? I told you last week.")
    assert g.check("Your birthday is October 8th.") is None
    assert g.check("Tuesday, October 8th.") is None
    # its own date, said about it, is fine
    when = datetime.fromtimestamp(knife.at)
    asked = guard([knife], asked="When did I ask you about my knife?")
    assert asked.check(f"You asked me about sharpening a kitchen knife on {when:%A}.")
    assert g.check(f"Your birthday is {when:%A}, {when:%B} {when.day}.") is None


def test_a_true_memory_about_something_else_is_no_answer():
    knife = Item(4, "turn", NOW - 8 * 86400, "", 'He said: "how do I sharpen a kitchen knife" You said: "A whetstone at about 15 degrees."')
    assert guard([knife], asked="When's my birthday? I told you last week.").check("A whetstone at about 15 degrees, a few strokes each side.") is None
    assert guard([knife], asked="What angle should I sharpen my knife at?").check("A whetstone at about 15 degrees.")
    assert guard([knife], asked="What did we talk about last week?").check("You asked how to sharpen a kitchen knife.")


def test_oh_right_alone_is_not_an_answer():
    recall.HIS.add("fact", "Trác is my younger brother, he just started university in Hanoi", at=NOW - 9 * 86400, session="earlier")
    turn = run(Conversation(FakeLLM(["<speak><cue>happy</cue>Oh, right!</speak>"])), "What's my sister's name again?", FakeHost())
    assert "don't" in turn.reply.speak.lower() or "nothing" in turn.reply.speak.lower()


def test_a_tool_call_carries_nothing_made_up():
    work = Item(5, "fact", NOW - 6 * 86400, "", "my work project is a warehouse scheduling app, the deadline is the end of November")
    g = guard([work], asked="Remind me, when is my cousin's wedding?")
    assert g.unsupported({"until": "2026-11-23"})
    assert not guard([work], strict=False).unsupported({"until": "2026-11-23"})


def test_no_you_didnt_is_saying_she_doesnt_know():
    g = guard([TRAC], asked="Did I ever tell you what my mom does for work?")
    assert g.check("No, you didn’t! Tell me!")
    assert g.check("You never mentioned your mom.")


def test_his_people_and_dates_are_questions_about_the_past():
    for q in ("What's my boss called again?", "What's my sister's name?", "When is my cousin's wedding?", "Who's my sensei?", "When's my birthday?"):
        assert recall.asks_past(q), q
    for q in ("What's my IP address?", "What's the capital of Canada?", "What should I cook tonight?"):
        assert not recall.asks_past(q), q


def test_with_nothing_retrieved_only_i_dont_know_is_said():
    g = guard([], asked="What did I tell you about Minh?")
    assert g.check("You told me Minh is your cousin from Saigon.") is None
    assert g.check("Hmm.") == "Hmm."
    assert g.check("I don't remember you mentioning Minh.")


def test_his_question_lends_days_but_not_people():
    # "on Monday" may be said back; "my sister" in the question is no sister on file
    g = guard([TRAC], asked="what did I tell you about my sister on Monday?")
    assert g.check("Your sister started on Monday.") is None
    lecture = Item(3, "lecture", NOW - 2 * 86400, "a lecture", "Linear algebra: eigenvalues")
    assert guard([lecture], asked="what did the lecture on Monday cover?").check("It covered eigenvalues on Monday.")


def test_outside_recall_only_claims_about_his_people_are_checked():
    g = guard([], strict=False, asked="How's it going?")
    assert g.check("Good! How's your sister doing?") is None
    assert g.check("You mentioned your exam last time - how did it go?") is None
    assert g.check("The capital of Canada is Ottawa.")
    assert g.check("I'm always your friend.")
    # he just said it: hers to say back
    told = guard([], strict=False, asked="My sister Lan is visiting this weekend.")
    assert told.check("Is Lan staying with you?") and told.check("How long is your sister here?")
    # earlier this session counts
    assert guard([], strict=False, session=["my sister Lan is visiting"]).check("How's your sister Lan?")


def test_names_are_capitalised_words_not_opening_a_sentence():
    assert names("Trác lives in Hanoi with Le Guin.") == ["hanoi", "le", "guin"]
    assert names('Oh, I said "Hello" to Irene, okay?') == []


def test_where_from_names_the_memory():
    g = guard([TRAC], asked="which city is my brother in?")
    g.check("Your brother Trác is studying in Hanoi.")
    said = where_from(LastAnswer(True, g.sources, g.dropped), NOW)
    assert "you told me on" in said and "Trác is my younger brother" in said
    assert "no memory" in where_from(LastAnswer(True, [], ["x"]), NOW)
    assert "general" in where_from(None, NOW)
    for q in ("Where did you get that?", "Which memory is that from?", "How do you know that?", "Did I really tell you that?"):
        assert asks_source(q), q
    for q in ("Where did you get those shoes in the game?", "What's the weather?"):
        assert not asks_source(q), q


def test_a_made_up_sister_is_never_spoken_and_never_kept():
    recall.HIS.add("fact", "Trác is my younger brother, he just started university in Hanoi", at=NOW - 9 * 86400, session="earlier")
    llm = FakeLLM(["<speak><cue>happy</cue>You told me your sister Mai just started university in Hanoi.</speak>"])
    conv = Conversation(llm)
    host = FakeHost()
    turn = run(conv, "What did I tell you about my sister?", host)
    assert "sister Mai" not in turn.reply.speak and "Hanoi" not in turn.reply.speak
    assert "don't" in turn.reply.speak.lower()
    assert "Mai" not in conv.history[-1]["content"]


def test_his_question_is_never_kept_as_a_fact():
    conv = Conversation(FakeLLM(["<speak>I don't remember you telling me about that.</speak>"]))
    run(conv, "When's my birthday? I told you last week.", FakeHost())
    recall.flush()
    assert not [i for i in recall.HIS.items if i.kind == "fact"]


def test_live_gaps_which_city_a_cut_name_and_a_correction():
    # live 2026-10-14: "which city is my brother studying in?" was researched
    assert recall.asks_past("Which city is my brother studying in?")
    # "It's Mr." then the made-up name as its own sentence
    assert guard([TRAC], asked="What's my boss called again?").check("It's Mr.") is None
    # "No, that's not what I asked for." right after -> "Right, sorry. Mr. <a made-up name>, then."
    work = "my work project is a warehouse scheduling app, the deadline is the end of November"
    recall.HIS.add("fact", work, at=NOW - 6 * 86400, session="earlier")
    llm = FakeLLM(["<speak>I don't remember you telling me that.</speak>", "<speak><cue>sheepish</cue>Right, sorry. Mr. Quang, then.</speak>"])
    conv = Conversation(llm)
    run(conv, "What's my boss called again?", FakeHost())
    turn = run(conv, "No, that's not what I asked for.", FakeHost())
    assert "Quang" not in turn.reply.speak and "don't" in turn.reply.speak.lower()


def test_she_says_which_memory_it_came_from():
    recall.HIS.add("fact", "Trác is my younger brother, he just started university in Hanoi", at=NOW - 9 * 86400, session="earlier")
    llm = FakeLLM(["<speak><cue>happy</cue>Trác is studying in Hanoi.</speak>", "<speak>From your diary.</speak>"])
    conv = Conversation(llm)
    run(conv, "Which city is my brother Trác studying in?", FakeHost())
    turn = run(conv, "Where did you get that?", FakeHost())
    assert "you told me on" in turn.reply.speak and "Trác is my younger brother" in turn.reply.speak
    assert len(llm.seen) == 1  # answered from the record, not by the model
