"""Research is kept for a day: past 24 h it is gone from her memory and the panel's
history rail by itself, and "Irene, clear your research" removes all of it now -
the files, the conversation's research results, the session notes' "already looked
up", and the panel if it shows one."""
import asyncio
import time

import irene.app  # noqa: F401 - core puts the repo's tools package on the path
from tools import research as R


def _save(rid: str, question: str) -> None:
    R.save(R.Research(rid, question, rid))


def _id(hours_ago: float) -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(time.time() - hours_ago * 3600))


def test_a_day_old_research_is_never_read_and_the_sweep_removes_it(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "STORE", tmp_path)
    monkeypatch.setattr(R, "EXPIRE_S", 24 * 3600)
    _save(_id(30), "old question")
    _save(_id(2), "fresh question")
    # nothing past a day is read again, even before the sweep
    assert [r.question for r in R.history()] == ["fresh question"]
    assert R.last().question == "fresh question"
    gone = []
    monkeypatch.setattr(R, "FORGET_HOOKS", [lambda ids, why: gone.append((ids, why))])
    removed = R.expire()
    assert len(removed) == 1 and not (tmp_path / f"{removed[0]}.json").exists()
    assert gone == [(removed, "expired after 24 h")]
    assert R.expire() == []  # nothing more to sweep


def test_the_dashboard_rail_shows_only_research_in_date(monkeypatch, tmp_path):
    from irene.dashboard import Dashboard

    monkeypatch.setattr(R, "STORE", tmp_path)
    monkeypatch.setattr(R, "EXPIRE_S", 24 * 3600)
    _save(_id(25), "yesterday's question")
    _save(_id(1), "today's question")
    d = Dashboard(None)
    d._research_list()
    assert [r["title"] for r in d.state["research"]] == ["Today's question"]


def test_clear_research_removes_it_everywhere(monkeypatch, tmp_path):
    from irene.app import Core

    monkeypatch.setattr(R, "STORE", tmp_path)
    _save(_id(3), "eiffel tower height")
    _save(_id(1), "heat pump how it works")
    core = Core()
    monkeypatch.setattr(R, "FORGET_HOOKS", [core._research_gone])
    shown = []

    async def show_panel(content):
        shown.append(content)

    core.show_panel = show_panel
    core.panel_content = {"title": "Heat pump", "blocks": [], "research": _id(1)}
    conv = core.conversation
    conv.history = [
        {"role": "user", "content": "how does a heat pump work"},
        {"role": "user", "content": "[tool result for research] Research for 'heat pump': [1] ..."},
        {"role": "assistant", "content": "<speak>It moves heat.</speak>"},
    ]
    conv.notes.looked_up("heat pump how it works", "It moves heat.")

    async def run():
        result = await R.clear_research(None)
        await asyncio.sleep(0)
        return result

    result = asyncio.run(run())
    assert "2 saved research removed" in result
    assert list(tmp_path.glob("*.json")) == []
    assert "no longer available" in conv.history[1]["content"] and "[1]" not in conv.history[1]["content"]
    assert conv.notes.lookups == []
    assert shown == [None], "the panel showing that research closes"
    assert asyncio.run(R.clear_research(None)) == "there was no saved research to clear"
