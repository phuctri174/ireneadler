import asyncio

from irene.brain import Conversation, StreamingReply, is_goodbye, now_section, parse_tool_call
from irene.reply import Reply


def feed_all(chunks, act=None):
    s = StreamingReply(act)
    lines = []
    for c in chunks:
        lines += s.feed(c)
    lines += s.finish()
    return s, [line.cue.name for line in lines if line.cue], [line.text for line in lines]


def texts(lines):
    return [line.text for line in lines]


def test_sentences_stream_as_they_complete():
    s = StreamingReply()
    assert texts(s.feed("<speak>First one. Sec")) == ["First one."]
    assert texts(s.feed("ond one! Thi")) == ["Second one!"]
    assert texts(s.finish()) == ["Thi"]


def test_react_arrives_before_speech_and_is_never_spoken():
    _, reacts, sentences = feed_all(["<react>thumb", "sUp</react><speak>Done, ", "sir.</speak>"])
    assert reacts == ["thumbsUp"]
    assert sentences == ["Done, sir."]


def test_display_is_never_spoken():
    _, _, sentences = feed_all(["<speak>Two files.</speak>\n<display>a.pdf\nb.pdf</display>"])
    assert sentences == ["Two files."]


def test_tool_call_is_not_spoken():
    s, _, sentences = feed_all(['<tool_call>{"name": "get_time", ', '"arguments": {}}</tool_call>'])
    assert sentences == []
    assert parse_tool_call(s.raw) == ("get_time", {})


def test_speech_capped_while_streaming():
    from irene.reply import MAX_SPOKEN_WORDS

    words = " ".join(f"w{i}." for i in range(MAX_SPOKEN_WORDS + 50))
    _, _, sentences = feed_all([f"<speak>{words}</speak>"])
    assert sum(len(x.split()) for x in sentences) <= MAX_SPOKEN_WORDS


def test_tool_call_parsing_variants():
    assert parse_tool_call('```json\n{"name": "set_timer", "arguments": {"minutes": 5}}\n```') == ("set_timer", {"minutes": 5})
    assert parse_tool_call("<speak>No tools here.</speak>") is None
    assert parse_tool_call("<tool_call>{not json}</tool_call>") is None


def test_goodbye():
    assert is_goodbye("ok goodbye Irene") and is_goodbye("Good night!") and is_goodbye("that's all for now")
    assert not is_goodbye("buy milk") and not is_goodbye("what's the time")


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    async def chat_stream(self, messages, temperature=0.6):
        self.seen.append(messages)
        text = self.replies.pop(0)
        for i in range(0, len(text), 7):
            yield text[i : i + 7]


class FakeSink:
    def __init__(self, host):
        self.host = host

    def line(self, line):
        if line.cue:
            self.host.events.append(("react", line.cue.name))
        self.host.events.append(("say", line.text))

    async def finish(self, reply: Reply):
        self.host.events.append(("finish", reply.speak))


class FakeHost:
    def __init__(self, answer=True):
        self.events = []
        self.answer = answer
        self.forgotten = False

    async def thinking(self):
        self.events.append(("thinking",))

    async def confirm(self, prompt):
        self.events.append(("confirm", prompt))
        return self.answer

    async def tool_status(self, name, status):
        self.events.append(("tool", name, status))

    def reply_sink(self):
        return FakeSink(self)

    async def announce(self, text):
        self.events.append(("announce", text))

    def forget(self):
        self.forgotten = True

    async def capture_shield(self, on):
        pass


def run(conv, text, host):
    return asyncio.run(conv.respond(text, host))


def test_tool_round_trip():
    llm = FakeLLM(['<tool_call>{"name": "get_time", "arguments": {}}</tool_call>', "<speak>It's noon, sir.</speak>"])
    host = FakeHost()
    turn = run(Conversation(llm), "what time is it, and is that late?", host)
    assert turn.tools_used == ["get_time"]
    assert ("tool", "get_time", "done") in host.events
    assert "[tool result for get_time]" in llm.seen[1][-1]["content"]
    assert ("say", "It's noon, sir.") in host.events


def test_confirm_tool_declined_does_not_run():
    llm = FakeLLM(['<tool_call>{"name": "forget_conversation", "arguments": {}}</tool_call>', "<speak>As you wish.</speak>"])
    host = FakeHost(answer=False)
    run(Conversation(llm), "forget this", host)
    assert any(e[0] == "confirm" for e in host.events)
    assert not host.forgotten
    assert "declined" in llm.seen[1][-1]["content"]


def test_confirm_tool_accepted_runs():
    llm = FakeLLM(['<tool_call>{"name": "forget_conversation", "arguments": {}}</tool_call>', "<speak>Forgotten.</speak>"])
    host = FakeHost(answer=True)
    run(Conversation(llm), "forget this", host)
    assert host.forgotten


def test_bad_arguments_go_back_to_the_model():
    llm = FakeLLM(['<tool_call>{"name": "set_timer", "arguments": {"secs": 5}}</tool_call>', "<speak>Let me fix that.</speak>"])
    run(Conversation(llm), "timer", FakeHost())
    assert "error" in llm.seen[1][-1]["content"]


def test_unknown_tool_goes_back_to_the_model():
    llm = FakeLLM(['<tool_call>{"name": "delete_everything", "arguments": {}}</tool_call>', "<speak>I can't do that.</speak>"])
    run(Conversation(llm), "delete", FakeHost())
    assert "no tool named" in llm.seen[1][-1]["content"]


def test_history_persists_and_goodbye_keeps_it():
    llm = FakeLLM(["<speak>Hello.</speak>", "<speak>Sure.</speak>", "<speak>Goodbye, sir.</speak>"])
    conv = Conversation(llm)
    run(conv, "hi", FakeHost())
    run(conv, "and again", FakeHost())
    assert [m["role"] for m in conv.history] == ["user", "assistant", "user", "assistant"]
    # a goodbye ends the listening, not the session: nothing is forgotten
    turn = run(conv, "ok goodbye", FakeHost())
    assert turn.ended and len(conv.history) == 6


def test_idle_resets_history(monkeypatch):
    llm = FakeLLM(["<speak>One.</speak>", "<speak>Two.</speak>"])
    conv = Conversation(llm)
    run(conv, "first", FakeHost())
    from irene.brain import IDLE_RESET_S

    assert IDLE_RESET_S >= 60 * 60, "a quiet few minutes never wipe the session"
    conv.last_active -= IDLE_RESET_S + 1
    run(conv, "later", FakeHost())
    assert [m["content"] for m in conv.history if m["role"] == "user"] == ["later"]


def test_tool_call_missing_bracket_or_fenced():
    assert parse_tool_call('```tool_call>{"name": "set_timer", "arguments": {"minutes": 25}}</tool_call>') == ("set_timer", {"minutes": 25})


def test_malformed_tool_call_is_retried_once_and_not_kept():
    llm = FakeLLM(["<tool_call>", "<speak>Here it is.</speak>"])
    conv = Conversation(llm)
    turn = run(conv, "summarize notes", FakeHost())
    assert turn.reply.speak == "Here it is."
    assert all(m["content"] != "<tool_call>" for m in conv.history)
    assert "incomplete or malformed" in llm.seen[1][-1]["content"]


def test_tool_result_carries_format_reminder_and_canonical_call():
    llm = FakeLLM(['```tool_call>{"name": "get_time", "arguments": {}}</tool_call>', "<speak>Noon.</speak>"])
    conv = Conversation(llm)
    run(conv, "time?", FakeHost())
    assert conv.history[1]["content"] == '<tool_call>{"name": "get_time", "arguments": {}}</tool_call>'
    assert "<speak>" in conv.history[2]["content"]


def test_the_system_prompt_is_static_and_the_clock_sits_right_before_his_message():
    llm = FakeLLM(["<speak>It's September, sir.</speak>", "<speak>Sure.</speak>"])
    conv = Conversation(llm)
    run(conv, "what month is it", FakeHost())
    run(conv, "thanks", FakeHost())
    first, second = llm.seen
    # the same system prompt every time, never the clock
    assert first[0]["content"] == second[0]["content"] and "local time" not in first[0]["content"]
    # the per-message block: right before his message
    assert "local time" in first[-2]["content"] and first[-1]["content"] == "what month is it"
    assert "local time" in second[-2]["content"] and second[-1]["content"] == "thanks"


def test_after_each_turn_the_clean_history_is_read_ahead_for_the_cache():
    """gemma3's sliding-window cache can only resume from a checkpoint before the
    first changed token: the clean history is sent ahead (warm_cache), so the next
    prompt starts exactly with it and only its own context and message are new."""
    import asyncio

    class Warming(FakeLLM):
        def __init__(self, replies):
            super().__init__(replies)
            self.prefilled = []

        async def prefill(self, messages):
            self.prefilled.append(messages)

    llm = Warming(["<speak>Hi!</speak>", "<speak>Sure.</speak>", "<speak>Bye.</speak>"])
    conv = Conversation(llm)

    async def main():
        for said in ("hello", "and again", "one more"):
            await conv.respond(said, FakeHost())
            await asyncio.sleep(0)

    asyncio.run(main())
    assert len(llm.prefilled) == 3
    for warmed, nxt in zip(llm.prefilled, llm.seen[1:]):
        assert nxt[: len(warmed)] == warmed
        assert "local time" not in " ".join(m["content"] for m in warmed), "the per-message context is never read ahead"


def test_a_long_history_is_compacted_in_whole_turns():
    from irene.brain import HISTORY_BUDGET_TOKENS, _tokens

    llm = FakeLLM(["<speak>" + "Words and more words. " * 60 + "</speak>"] * 40)
    conv = Conversation(llm)
    for n in range(40):
        run(conv, f"message {n}", FakeHost())
    assert _tokens(conv.history) <= HISTORY_BUDGET_TOKENS + 800
    # it starts on one of his messages, keeps the newest, and the old context blocks went
    first = next(m for m in conv.history if m["role"] != "system")
    assert first["role"] == "user" and conv.history[-2]["content"] == "message 39"


def test_the_router_offers_the_tools_a_message_may_need_in_full():
    from irene.router import tools_block

    timer = tools_block("set a timer for 10 minutes")
    assert "- set_timer(" in timer and "- capture_screen(" not in timer and "capture_screen" in timer
    chat = tools_block("tell me a joke")
    assert "most likely needs no tool" in chat and "get_time" in chat
    follow = tools_block("and the other one?", ["list_files"])
    assert "- list_files(" in follow


def test_countdown_questions_are_pointed_at_get_time():
    assert "call get_time with until" in now_section("How many days until Christmas?")
    assert "call get_time with until" in now_section("how long till 6pm")
    assert "countdown" not in now_section("How many minutes are in a day?")
    assert "countdown" not in now_section("how long does it take to boil an egg")


def test_asked_action_wins_over_the_models_pick():
    s, cues, _ = feed_all(["<react>thinking</react><speak>Hmm. "], act="chess")
    assert cues == ["chess"] and s.react.asked


def test_asked_action_stands_in_for_no_reaction():
    _, cues, _ = feed_all(["<speak>Hiii! "], act="wave")
    assert cues == ["wave"]
    _, cues, _ = feed_all(["<speak>Hiii! "])
    assert cues == []


def test_each_sentence_carries_its_own_cue():
    s, cues, said = feed_all(["<speak><cue>surpr", "ised</cue>Wait, what? <cue>giggle</cue>", "That's brilliant.</speak>"])
    assert cues == ["surprised", "giggle"]
    assert said == ["Wait, what?", "That's brilliant."]
    assert [c.name for c in s.cues] == ["surprised", "giggle"]


def test_a_cue_straight_after_a_full_stop_still_starts_the_next_sentence():
    _, cues, said = feed_all(["<speak>Done.<cue>happy</cue>Nice one! Okay.</speak>"])
    assert said == ["Done.", "Nice one!", "Okay."]
    assert cues == ["happy"]


def test_a_repeated_cue_back_to_back_is_dropped_and_unknown_ones_ignored():
    _, cues, said = feed_all(["<speak><cue>happy</cue>One. <cue>happy</cue>Two. <cue>cartwheel</cue>Three.</speak>"])
    assert cues == ["happy"]
    assert said == ["One.", "Two.", "Three."]


def test_react_before_speak_cues_the_first_sentence_only():
    _, cues, said = feed_all(["<react>wave</react><speak>Hi! How are you?</speak>"])
    assert cues == ["wave"] and said == ["Hi!", "How are you?"]


def test_the_opening_phrase_goes_to_the_voice_before_its_sentence_ends():
    s = StreamingReply()
    first = s.feed("<speak><cue>curious</cue>Hmm, good one, sir")
    assert [l.text for l in first] == ["Hmm,"] and first[0].cue.name == "curious"
    rest = s.feed(" - let me think about that for a second. ") + s.finish()
    assert [l.text for l in rest] == ["good one, sir - let me think about that for a second."]


def test_her_voice_starts_on_the_first_clause_however_long():
    s = StreamingReply()
    assert s.feed("<speak>The capital of Japan") == []
    assert s.feed(", as") == []  # "..., sir." is not worth splitting
    first = s.feed(" you probably")
    assert [l.text for l in first] == ["The capital of Japan,"]
    rest = s.feed(" know, is Tokyo. And it's huge.</speak>") + s.finish()
    assert [l.text for l in rest] == ["as you probably know, is Tokyo.", "And it's huge."]
    # a dash ends a clause too; a number's comma never does
    s = StreamingReply()
    assert [l.text for l in s.feed("<speak>Kendo - the way")] == ["Kendo -"]
    s = StreamingReply()
    assert s.feed("<speak>About 1,000 people") == []


def test_a_short_whole_sentence_is_not_split():
    s = StreamingReply()
    assert [l.text for l in s.feed("<speak>Ooh! That's great. ")] == ["Ooh!", "That's great."]


def test_voice_tags_are_spoken_but_never_shown():
    from irene.reply import parse_reply

    s = StreamingReply()
    lines = s.feed("<speak>Ha, that's a good one. [laugh] Really. ") + s.finish()
    assert any("[laugh]" in l.text for l in lines)
    assert "[laugh]" not in parse_reply("<speak>Ha, that's a good one. [laugh] Really.</speak>").speak


def test_a_simple_command_answers_from_its_template_with_one_llm_call():
    llm = FakeLLM(['<tool_call>{"name": "set_timer", "arguments": {"minutes": 10, "label": "tea"}}</tool_call>'])
    host = FakeHost()
    turn = run(Conversation(llm), "tea timer, 10 minutes", host)
    assert len(llm.seen) == 1  # no second call
    assert "10 minutes" in turn.reply.speak and turn.reply.react is not None


def test_a_command_with_more_to_it_still_goes_back_to_the_model():
    llm = FakeLLM(['<tool_call>{"name": "set_timer", "arguments": {"minutes": 10}}</tool_call>', "<speak>Done. Here's a joke...</speak>"])
    run(Conversation(llm), "set a timer for 10 minutes and tell me a joke", FakeHost())
    assert len(llm.seen) == 2


def test_optional_marks_copied_into_argument_names_are_dropped():
    raw = '<tool_call>{"name": "set_timer", "arguments": {"minutes": 60, "label?": "laundry"}}</tool_call>'
    assert parse_tool_call(raw) == ("set_timer", {"minutes": 60, "label": "laundry"})


def test_a_closed_speak_block_is_spoken_before_the_display_arrives():
    s = StreamingReply()
    lines = s.feed("<speak><cue>happy</cue>Tokyo, sir.</speak>\n<display>\nTokyo is")
    assert [l.text for l in lines] == ["Tokyo, sir."]


def test_an_interjection_written_before_speak_is_said_first():
    s = StreamingReply()
    lines = s.feed("Hmm, good one. \n\n<speak><cue>happy</cue>Tokyo, sir.</speak>\n<display>")
    assert [l.text for l in lines][:2] == ["Hmm, good one.", "Tokyo, sir."]
    assert s.finish() == []


def test_router_leaves_figurative_file_and_forget_talk_alone():
    from irene.router import groups_for

    for text in ["I need to organize my thoughts before the meeting.", "Ugh, delete that thought, it was silly.", "Ugh, never mind, forget it."]:
        assert groups_for(text) == [], text
    assert [g.name for g in groups_for("Delete the old tax file.")] == ["files"]
    assert [g.name for g in groups_for("Forget this conversation.")] == ["forget"]


def test_an_unmistakable_panel_command_needs_no_llm_call(tmp_path, monkeypatch):
    from tools import research as R

    monkeypatch.setattr(R, "STORE", tmp_path)
    found = R.Research("20260922-110000", "heat pumps", "2026-09-22 11:00")
    found.sources = [R.Source(1, "Heat pumps", "https://energy.gov/heat-pumps", "energy.gov", "They move heat.")]
    R.save(found)
    shown = []

    class PanelHost(FakeHost):
        async def show_panel(self, content):
            shown.append(content)

        def panel_answers(self):
            return []

    llm = FakeLLM([])  # any model call would fail: there are no replies
    turn = run(Conversation(llm), "Show me the sources.", PanelHost())
    assert turn.tools_used == ["show_panel"] and turn.calls == [] and llm.seen == []
    assert shown[0]["title"] == "Heat pumps"
    assert any(w in turn.reply.speak.lower() for w in ("panel", "up now"))


def test_direct_calls_only_for_clear_panel_commands():
    from irene.fast import direct_call

    assert '"what": "sources"' in direct_call("Actually, show me the sources.")
    assert '"what": "that"' in direct_call("Put that on the screen.")
    assert '"what": "close"' in direct_call("Close the panel please.")
    assert '"what": "videos"' in direct_call("Can you show me the videos you found?")
    for text in ["What's on my screen?", "Show me how to tie a tie.", "The solar panel is dirty.", "show me the sources of the Nile"]:
        assert direct_call(text) is None, text


def test_an_emotional_moment_opens_with_its_reaction():
    from irene import sentiment

    joke = sentiment.read("haha good one").cues
    # the model's cue doesn't fit the moment: the moment's cue plays instead
    s = StreamingReply(mood=joke)
    lines = s.feed("<speak><cue>thinking</cue>Ha! Good one, sir. <cue>proud</cue>I'll steal it.</speak>") + s.finish()
    assert [line.cue.name for line in lines if line.cue] == ["giggle", "proud"]
    # one that fits is kept; and never the one the last reply played
    s = StreamingReply(mood=joke)
    assert s.feed("<speak><cue>wink</cue>Ha, sir.</speak>")[0].cue.name == "wink"
    s = StreamingReply(mood=joke, avoid="giggle")
    assert s.feed("<speak>Ha, sir.</speak>")[0].cue.name == "wink"
    # an action he asked for still wins
    s = StreamingReply("wave", mood=joke)
    assert s.feed("<speak><cue>giggle</cue>Hi!</speak>")[0].cue.name == "wave"


def test_her_last_cue_is_in_the_next_context():
    conv = Conversation(FakeLLM(["<speak><cue>proud</cue>Done.</speak>", "<speak>Hi.</speak>"]))
    run(conv, "hello", FakeHost())
    assert conv.last_cue == "proud"
    assert "Your last reply showed <cue>proud</cue>" in conv.context("and now?")


def test_a_fitting_cue_that_just_played_swaps_within_the_moment():
    from irene import sentiment

    tired = sentiment.read("I'm so tired today").cues
    # the last reply ended on concerned; the model opens with concerned again
    s = StreamingReply(mood=tired, avoid="concerned")
    assert s.feed("<speak><cue>concerned</cue>Oh, sir. Long day?</speak>")[0].cue.name == "sad"
    s = StreamingReply(mood=tired, avoid="happy")
    cue = s.feed("<speak><cue>concerned</cue>Oh, sir.</speak>")[0].cue
    assert cue.name == "concerned" and cue.family == ("concerned", "sad")


def test_a_mood_cue_avoids_everything_the_last_reply_showed():
    from irene import sentiment

    tired = sentiment.read("I'm so tired today").cues
    # "my cat died" opened sad and ended concerned: tired can't be sad again
    s = StreamingReply(mood=tired, avoid=("sad", "concerned"))
    assert s.feed("<speak><cue>sad</cue>Oh, sir.</speak>")[0].cue.name == "concerned"


def test_everyday_commands_skip_the_model():
    from irene.fast import direct_call

    for said, name in [("pause", "media_play_pause"), ("next song", "media_next"), ("volume to 40", "set_volume"), ("turn it down a bit", "change_volume"), ("unmute", "mute"), ("what's the time?", "get_time")]:
        assert parse_tool_call(direct_call(said))[0] == name, said
    for said in ("last time you said kendo was fun", "play some jazz", "what time is it in Tokyo?", "stop talking about music"):
        assert direct_call(said) is None, said


def test_a_slow_tool_is_announced_while_its_call_is_still_streaming():
    llm = FakeLLM(['<tool_call>{"name": "research", "arguments": {"question": "kendo dan grades"}}</tool_call>', "<speak>Done.</speak>"])
    host = FakeHost()
    conv = Conversation(llm)
    real = conv._run_tool

    async def no_web(name, args, host):
        # the statuses as the real tool reports them, without the web
        await host.tool_status(name, "running")
        await host.tool_status(name, "done")
        return "ok"

    conv._run_tool = no_web
    run(conv, "tell me how kendo dan grades work", host)  # the model, not a direct call
    assert real is not None
    starting = host.events.index(("tool", "research", "starting"))
    running = next(i for i, e in enumerate(host.events) if e[:2] == ("tool", "research") and e[2] != "starting")
    assert starting < running


def test_malformed_tool_calls_are_read_and_never_shown_or_said():
    """core/evals/malformed_calls.jsonl: every spelling the model has produced (or
    could) is read as the call it meant, and nothing call-shaped reaches the panel
    or her voice."""
    import json as _json
    from pathlib import Path as _Path

    from irene.brain import parse_tool_call
    from irene.reply import parse_reply

    cases = [_json.loads(l) for l in (_Path(__file__).parents[1] / "evals" / "malformed_calls.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(cases) >= 10
    for case in cases:
        assert parse_tool_call(case["raw"]) == (case["name"], case["args"]), case["why"]
        reply = parse_reply(case["raw"])
        for text in (reply.display, reply.speak):
            assert "tool_call" not in text and '"name"' not in text, (case["why"], text)
