import asyncio

from irene import react as cues
from irene.app import Core
from irene.brain import Conversation
from tools import perform as P
from tests.test_brain import FakeHost, FakeLLM, run


def test_a_sequence_is_split_into_steps_and_surprise_means_her_pick():
    assert P.steps("wave, starry eyed then kendo and giggle") == ["wave", "starry eyed", "kendo", "giggle"]
    assert P.steps("surprise") == [] and P.steps("") == [] and P.steps("your pick") == []


def test_the_show_resolves_names_drops_props_and_her_pick_shows_the_newest():
    core = Core()
    assert [r.name for r in core.show_order(["Wave", "starry-eyed", "magnifier", "nonsense", "kendo"])] == ["wave", "starryEyed", "kendo"]
    for _ in range(10):
        picked = core.show_order([])
        names = [r.name for r in picked]
        assert 4 <= len(names) <= 5 and "starryEyed" in names
        assert all(r.kind != "prop" for r in picked) and len(set(names)) == len(names)


def test_perform_plays_every_step_in_order(monkeypatch):
    core = Core()
    sent = []

    async def send(message):
        sent.append(message)

    async def no_wait(_s):
        return None

    monkeypatch.setattr(core.bridge, "send", send)
    monkeypatch.setattr("irene.app.asyncio.sleep", no_wait)
    played = asyncio.run(core.perform(["wave", "wave", "starryEyed", "chess"]))
    assert played == ["wave", "wave", "starryEyed", "chess"]
    shown = [m.get("value") for m in sent if m["type"] in ("reaction", "emotion", "activity")]
    # asked-for steps play even back to back; a scene is stopped after its turn
    assert shown[:5] == ["wave", "wave", "starryEyed", "chess", None]


def test_perform_some_for_me_performs_with_no_model_call():
    class ShowHost(FakeHost):
        async def perform(self, names):
            self.events.append(("perform", tuple(names)))
            return ["wave", "starryEyed", "giggle"]

    host = ShowHost()
    llm = FakeLLM([])
    turn = run(Conversation(llm), "What can you do? Perform some for me.", host)
    assert turn.tools_used == ["perform"] and llm.seen == []
    assert ("perform", ()) in host.events
    assert turn.reply.speak and turn.reply.react is not None


def test_the_new_cue_is_in_the_pool():
    assert cues.resolve("starry eyed").name == "starryEyed" and cues.resolve("stretch").kind == "gesture"
    assert "starryEyed" in cues.catalogue() and cues.act_out("show me your starry eyes") == "starryEyed"
