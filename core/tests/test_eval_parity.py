"""The evals must see the prompt the app ships (evals/harness.py).

A conversation is played through the live path - Conversation.respond(), turn by
turn, with a scripted model - and its last message is then played again the way
the evals play a case: the earlier turns as the case's history (restore()), the
last one through harness.live_turn. The model must be sent exactly the same
messages, byte for byte. A prompt built any other way fails here.

(2026-10-13: "My Chrome keeps crashing" passed in the eval and failed live - the
eval built its prompt with Conversation.prompt() on a bare history, without the
notes, cues and recent tools a live turn carries.)
"""
from __future__ import annotations

import asyncio
import random
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))

import harness  # noqa: E402
from irene import brain  # noqa: E402
from irene.brain import Conversation  # noqa: E402

NOW = datetime(2026, 10, 13, 20, 15)


class ScriptedLLM:
    """Answers by what it was sent: a tool result gets a short reply; his message
    gets what the script says for it. Records every prompt."""

    def __init__(self, script: dict[str, list[str]]):
        self.script = {k: list(v) for k, v in script.items()}
        self.seen: list[list[dict]] = []

    async def chat_stream(self, messages, temperature=0.6):
        self.seen.append([dict(m) for m in messages])
        last = messages[-1]["content"]
        said = next((m["content"] for m in reversed(messages) if m["role"] == "user" and not m["content"].startswith("[")), "")
        if last.startswith("[tool result") and "] error:" in last and self.script.get(said):
            replies = self.script[said]  # refused: the script's next try
            text = replies.pop(0) if len(replies) > 1 else replies[0]
        elif last.startswith("[tool result"):
            text = "<speak><cue>proud</cue>Found it - kendo grew out of kenjutsu in the Edo period.</speak>"
        else:
            replies = self.script.get(said) or ["<speak><cue>curious</cue>Oh, tell me more.</speak>"]
            text = replies.pop(0) if len(replies) > 1 else replies[0]
        for i in range(0, len(text), 9):
            yield text[i : i + 9]


class Host:
    async def thinking(self):
        pass

    async def tool_status(self, name, status):
        pass

    async def confirm(self, prompt):
        return False

    def reply_sink(self):
        class Sink:
            def line(self, line):
                pass

            async def finish(self, reply):
                pass

        return Sink()


SCRIPT = {
    "I prefer short answers from now on.": ["<speak><cue>salute</cue>Short it is.</speak>"],
    "Can you look up the history of kendo?": ['<tool_call>{"name": "research", "arguments": {"question": "history of kendo"}}</tool_call>'],
    "No, I meant the modern sport, not the old history.": ["<speak><cue>sheepish</cue>Got it - the modern sport.</speak>"],
}
TURNS = list(SCRIPT)
LAST = "My Chrome keeps crashing lately."


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    real = brain.now_section
    monkeypatch.setattr(brain, "now_section", lambda text="", now=None: real(text, NOW))


async def _research_result(name, args, host):
    return "Kendo descends from kenjutsu; the All Japan Kendo Federation was founded in 1952."


def _live() -> tuple[Conversation, ScriptedLLM, list[dict], list[dict]]:
    llm = ScriptedLLM(SCRIPT)
    conv = Conversation(llm)
    conv._run_tool = _research_result
    for said in TURNS:
        asyncio.run(conv.respond(said, Host()))
    past = [dict(m) for m in conv.history]
    before = len(llm.seen)
    asyncio.run(conv.respond(LAST, Host()))
    return conv, llm, llm.seen[before], past


def _fresh_memory(monkeypatch, tmp_path):
    """What the live run kept is its own session's (never recalled in it); an eval
    case starts from an empty memory, as the evals do."""
    from irene import recall

    store = recall.Store(tmp_path / "fresh.sqlite")
    monkeypatch.setattr(recall, "HIS", store)
    monkeypatch.setattr(recall, "DEV", store)


def test_eval_turn_sends_the_live_prompt(monkeypatch, tmp_path):
    live, _, live_prompt, past = _live()
    _fresh_memory(monkeypatch, tmp_path)
    llm = ScriptedLLM(SCRIPT)
    case = {"say": LAST, "history": [[m["role"], m["content"]] for m in past], "expect": [None]}
    t = asyncio.run(harness.live_turn(llm, case))
    assert t.who == "model"
    assert llm.seen, "the eval never asked the model"
    assert llm.seen[0] == live_prompt


def test_restored_past_is_the_live_state():
    """What respond() keeps about past turns comes back from the history alone."""
    live, _, _, past = _live()
    restored = Conversation(ScriptedLLM({}))
    restored.restore(past)
    probe = Conversation(ScriptedLLM(SCRIPT))
    probe._run_tool = _research_result
    for said in TURNS:
        asyncio.run(probe.respond(said, Host()))
    assert restored.history == probe.history
    assert restored.notes.section() == probe.notes.section()
    assert restored.recent_tools == probe.recent_tools
    assert restored.last_cues == probe.last_cues
    assert restored._panel_offer == probe._panel_offer
    assert "short answers" in restored.notes.section() and "modern sport" in restored.notes.section()


def test_entrance_case_sends_the_live_prompt(monkeypatch, tmp_path):
    from irene.entrances import load_registry

    entry = next(e for e in load_registry() if e.get("backstory"))
    llm = ScriptedLLM({})
    live = Conversation(llm)
    live._rng = random.Random(7)
    live.entered(entry)
    live.greeted("Oh! You caught me.")
    asyncio.run(live.respond("That looked like fun.", Host()))

    _fresh_memory(monkeypatch, tmp_path)
    eval_llm = ScriptedLLM({})
    case = {"say": "That looked like fun.", "entrance": entry["name"], "history": [["assistant", "<speak>Oh! You caught me.</speak>"]]}
    conv = harness.conversation_for(eval_llm, case)
    conv._rng = random.Random(7)
    asyncio.run(harness.live_turn(eval_llm, case, conv))
    assert eval_llm.seen[0] == llm.seen[0]


def test_eval_takes_the_apps_dispatch():
    """A message the app answers with a quick line never reaches the model in an eval."""
    llm = ScriptedLLM({})
    t = asyncio.run(harness.live_turn(llm, {"say": "Thanks, Irene!"}))
    assert t.who == "quick" and not llm.seen


def test_eval_scores_the_call_the_turn_hands_over():
    """A call is scored with the arguments it would run with; a refused one is not it."""
    llm = ScriptedLLM({"How did kendo start, historically?": [
        '<tool_call>{"name": "research", "arguments": {"query": "kendo"}}</tool_call>',
        '<tool_call>{"name": "research", "arguments": {"question": "history of kendo"}}</tool_call>',
    ]})
    t = asyncio.run(harness.live_turn(llm, {"say": "How did kendo start, historically?"}))
    assert t.called == ("research", {"question": "history of kendo"})
    assert [n for n, _ in t.attempts] == ["research", "research"]  # the schema refused the first
    assert t.llm_calls == 2
    # an unmistakable command: no model at all (fast.direct_call)
    llm = ScriptedLLM({})
    t = asyncio.run(harness.live_turn(llm, {"say": "Set a timer for 5 minutes."}))
    assert t.called[0] == "set_timer" and float(t.called[1]["minutes"]) == 5 and not llm.seen


def test_no_eval_builds_its_own_prompt():
    """Only respond() builds a prompt: no eval reaches past it."""
    assert not hasattr(Conversation, "prompt"), "Conversation.prompt() was the eval-only prompt builder"
    evals = Path(__file__).resolve().parents[1] / "evals"
    # measures a protocol the app does NOT ship (Ollama's native tools, for other
    # models): its numbers are never the app's
    elsewhere = {"native_routing.py"}
    for path in evals.glob("*.py"):
        if path.name in elsewhere:
            continue
        text = path.read_text(encoding="utf-8")
        for builder in (".begin(", ".messages()", "system_prompt(", ".context(", "_messages("):
            assert builder not in text, f"{path.name} builds a prompt itself ({builder})"
