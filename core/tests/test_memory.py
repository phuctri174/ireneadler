"""She remembers the whole session: his corrections and preferences stay in front
of her, what she said before being cut off stays in the history, and compaction
drops a page of search results before it drops anything he said."""
import asyncio

from irene.brain import Conversation, is_goodbye
from irene.memory import SessionNotes
from tests.test_brain import FakeHost, FakeLLM, run


def test_corrections_and_lasting_things_are_noted_in_his_words():
    n = SessionNotes()
    assert n.hear("Some information about first dance in kendo", "", "") is None
    c = n.hear("No, I mean first dan, D A N", "Some information about first dance in kendo", "")
    assert c.kind == "correction" and "first dance" in c.about
    assert n.hear("Keep your answers short from now on.").kind == "lasting"
    assert n.hear("My exam is on the 12th of November.").kind == "lasting"
    assert n.hear("You got that wrong, try again", "", "The first dan exam has a written test.").about.startswith("The first dan")
    for chatter in ("Thanks!", "okay", "No thanks", "What time is it?", "Tell me a joke"):
        assert n.hear(chatter) is None, chatter
    section = n.section()
    assert '"No, I mean first dan, D A N"' in section and "Keep your answers short" in section


def test_the_notes_are_in_front_of_every_later_message():
    llm = FakeLLM(["<speak>Sure.</speak>"] * 8)
    conv = Conversation(llm)
    run(conv, "I prefer answers in metric units.", FakeHost())
    for said in ("hello", "what's the weather like on Mars", "how tall is Everest"):
        run(conv, said, FakeHost())
    assert "I prefer answers in metric units." in llm.seen[-1][-2]["content"]


def test_what_she_looked_up_stays_in_front_of_her():
    llm = FakeLLM(['<tool_call>{"name": "research", "arguments": {"question": "kendo first dan exam"}}</tool_call>', "<speak>It has kata and a written test.</speak>", "<speak>Yes.</speak>"])
    conv = Conversation(llm)

    async def canned(name, args, host):
        return "results"

    conv._run_tool = canned
    run(conv, "research the kendo first dan exam", FakeHost())
    run(conv, "ok", FakeHost())
    assert conv.notes.lookups[0].question == "kendo first dan exam"
    assert "kata and a written test" in llm.seen[-1][-2]["content"]


def test_a_goodbye_ends_the_listening_not_the_session_and_is_a_whole_message():
    assert is_goodbye("bye!") and is_goodbye("Good night, Irene.") and is_goodbye("okay, that's all for now")
    assert not is_goodbye("that's all I know about it, but tell me more")
    assert not is_goodbye("say bye to the old laptop")


def test_a_reply_cut_off_keeps_what_she_already_said():
    class Slow(FakeLLM):
        async def chat_stream(self, messages, temperature=0.6):
            self.seen.append(messages)
            yield "<speak>The first dan exam has three parts. "
            await asyncio.sleep(10)
            yield "Then more.</speak>"

    conv = Conversation(Slow([]))

    async def main():
        task = asyncio.ensure_future(conv.respond("what's in the first dan exam?", FakeHost()))
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            conv.cut_off()

    asyncio.run(main())
    assert conv.history[-1]["role"] == "assistant"
    assert "three parts" in conv.history[-1]["content"] and "cut you off" in conv.history[-1]["content"]


def test_compaction_squeezes_old_search_results_before_dropping_his_words():
    conv = Conversation(FakeLLM([]))
    conv.history = [
        {"role": "user", "content": "My exam is in November, remember that."},
        {"role": "assistant", "content": "<tool_call>{}</tool_call>"},
        {"role": "user", "content": "[tool result for research] " + "page text " * 3000},
        {"role": "assistant", "content": "<speak>Noted.</speak>"},
        {"role": "user", "content": "thanks"},
        {"role": "assistant", "content": "<speak>Anytime.</speak>"},
    ]
    conv.compact()
    assert conv.history[0]["content"].startswith("My exam is in November"), "his words stay"
    assert "trimmed" in conv.history[2]["content"] and len(conv.history[2]["content"]) < 800


def test_a_recall_answer_is_never_an_apology():
    from irene.brain import StreamingReply
    from irene.reply import drop_apologies

    s = StreamingReply(no_apology=True)
    lines = s.feed("<speak>Oh dear. November 12th, sir. I apologize for the slip-up earlier.</speak>") + s.finish()
    assert [l.text for l in lines] == ["November 12th, sir."]
    assert drop_apologies("Sorry about that! Takahashi, sir.") == "Takahashi, sir."
    llm = FakeLLM(["<speak>Tanaka, noted.</speak>", "<speak>Takahashi, got it.</speak>", "<speak>Oh dear. Takahashi, sir. My apologies for the mix-up.</speak>"])
    conv = Conversation(llm)
    for said in ("My sensei is Tanaka.", "No, it's Takahashi."):
        run(conv, said, FakeHost())
    turn = run(conv, "What's my sensei's name?", FakeHost())
    assert turn.reply.speak == "Takahashi, sir."
    assert "apolog" not in conv.history[-1]["content"].lower(), "not kept for next time either"


def test_room_talk_she_is_unsure_of_never_interrupts_her(tmp_path):
    import numpy as np

    from irene.stt import Heard
    from irene.voice_data import VoiceData
    from irene.voice_loop import Voice
    from tests.test_voice_available import _Core

    v = Voice(_Core())
    v.data = VoiceData(tmp_path)
    v.available = True
    v.set_visible(True)
    said = []

    async def say(text, **_k):
        said.append(text)

    v.core.say = say
    unsure = Heard("Show.", -1.76, 0.0, 6.8, 300)
    assert asyncio.run(v.on_heard(unsure, np.zeros(16000, np.float32), v.awake)) == "ignored"
    assert said == [], "on screen but not addressed: silence, no 'say that again'"
    v.wake_for(8)  # right after she spoke: that one was for her
    assert asyncio.run(v.on_heard(unsure, np.zeros(16000, np.float32), v.awake)) == "say_again"


def test_hiding_her_ends_the_follow_up_window(tmp_path):
    from irene.voice_data import VoiceData
    from irene.voice_loop import Voice
    from tests.test_voice_available import _Core

    v = Voice(_Core())
    v.data = VoiceData(tmp_path)
    v.set_visible(True)
    v.wake_for(60)
    v.set_visible(False)
    assert not v.awake


def test_an_apology_is_dropped_even_behind_its_cue_and_a_shortlist_is_noted():
    from irene.reply import drop_apologies

    assert drop_apologies("<cue>sad</cue>Oh dear... The MacBook Air, sir.") == "The MacBook Air, sir."
    n = SessionNotes()
    assert n.hear("I'm choosing between three laptops: the ThinkPad X1, the MacBook Air and the Dell XPS.").kind == "lasting"
