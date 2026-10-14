"""Her long-term memory (irene/recall.py): kept, recalled within budget, forgotten
for real, expired by policy, and never mixed between his store and a test's."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime

import numpy as np
import pytest

from irene import recall

DAY = 86400


class BagEmbedder:
    """Deterministic stand-in for bge-small: a hashed bag of words, normalised."""

    ready = True

    def load(self):
        pass

    def encode(self, texts, query=False):
        out = np.zeros((len(texts), 384), np.float32)
        for row, text in enumerate(texts):
            for w in recall.words(text):
                out[row, int(hashlib.md5(w.encode()).hexdigest(), 16) % 384] += 1
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1, norms)


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = recall.Store(tmp_path / "memory.sqlite", BagEmbedder())
    monkeypatch.setattr(recall, "HIS", s)
    monkeypatch.setattr(recall, "DEV", s)
    yield s
    s.close()


def test_a_name_is_found_with_or_without_its_accent(store):
    store.add("fact", "Trác is my younger brother, he studies in Hanoi")
    store.add("fact", "my work project is a warehouse scheduling app")
    for query in ("what did I tell you about Trác", "what did I tell you about Trac"):
        found = store.search(query)
        assert found and "brother" in found[0].text


def test_recall_is_dated_and_within_budget(store, monkeypatch):
    now = time.time()
    for k in range(40):
        store.add("turn", f'He said: "question number {k} about kendo footwork" You said: "answer {k} " ' + "x" * 200, at=now - 8 * DAY + k * 60)
    r = recall.recall("what did we talk about last week about kendo", now=now)
    budget = recall.POLICY.recall_budget_tokens
    assert r.past and r.items
    assert sum(i.tokens() for i in r.items) <= budget
    assert len(r.section) / recall.CHARS_PER_TOKEN <= budget + 150  # the hint and heading on top
    assert "days ago" in r.section


def test_nothing_from_this_session(store):
    store.add("fact", "Trác is my younger brother", session="now")
    assert recall.recall("what did I tell you about Trác", session="now").items == []
    assert recall.recall("what did I tell you about Trác", session="other").items


def test_unrelated_message_gets_no_memory(store):
    store.add("fact", "Trác is my younger brother, he studies in Hanoi")
    assert recall.recall("set a timer for five minutes").section == ""


def test_standing_preference_always_comes_along(store):
    store.add("fact", "I prefer short answers, two sentences at most", at=time.time() - 20 * DAY)
    store.add("fact", "Trác is my younger brother")
    r = recall.recall("explain how a fridge works", session="new")
    assert any("short answers" in i.text for i in r.items)
    assert not any("Trác" in i.text for i in r.items)


def test_forgetting_deletes_the_bytes(store, tmp_path):
    secret = "Trác is my younger brother and he failed his driving test twice"
    store.add("fact", secret)
    store.add("fact", "I prefer short answers")
    raw = lambda: b"".join(p.read_bytes() for p in tmp_path.glob("memory.sqlite*"))  # noqa: E731
    assert "driving test twice".encode() in raw()
    items = recall.to_forget("Trác", store)
    assert [i.text for i in items] == [secret]
    recall.forget(items, store)
    assert "driving test twice".encode() not in raw()
    assert not any("Trác" in i.text for i in recall.recall("what did I tell you about Trác", store=store).items)
    # and it stays gone after a restart
    store.close()
    again = recall.Store(store.path, BagEmbedder())
    assert all("driving" not in i.text for i in again.items)
    again.close()


def test_forget_scrubs_logs_and_voice_turns(tmp_path):
    logs, voice = tmp_path / "logs", tmp_path / "voice"
    logs.mkdir()
    (voice / "2026-10-01").mkdir(parents=True)
    (logs / "turns.jsonl").write_text(json.dumps({"said": "Trác failed his driving test twice"}) + "\n" + json.dumps({"said": "set a timer"}) + "\n", encoding="utf-8")
    (logs / "core.log").write_text("2026-10-01 10:00:00,000 irene INFO heard: Trác failed his driving test twice\nother line\n", encoding="utf-8")
    (voice / "2026-10-01" / "a1.json").write_text(json.dumps({"text": "Trác failed his driving test twice"}), encoding="utf-8")
    (voice / "2026-10-01" / "a1.wav").write_bytes(b"RIFF")
    (voice / "2026-10-01" / "b2.json").write_text(json.dumps({"text": "set a timer"}), encoding="utf-8")
    out = recall.scrub({"Trac failed his driving test twice"}, logs, voice)
    assert out == {"log_lines": 2, "voice_turns": 1}
    assert "driving" not in (logs / "turns.jsonl").read_text(encoding="utf-8")
    assert "driving" not in (logs / "core.log").read_text(encoding="utf-8")
    assert not (voice / "2026-10-01" / "a1.wav").exists()
    assert (voice / "2026-10-01" / "b2.json").exists()


def test_policy_expires_by_kind(store):
    now = time.time()
    store.add("turn", "He said: \"old chat about tea\" You said: \"Green tea.\"", at=now - 100 * DAY)
    store.add("turn", "He said: \"new chat about tea\" You said: \"Oolong.\"", at=now - 5 * DAY)
    store.add("fact", "I'm allergic to peanuts", at=now - 400 * DAY)
    policy = recall.Policy(keep_days={"turn": 90, "fact": 0, "research": 365, "lecture": 0})
    assert store.prune(policy, now) == 1
    assert sorted(i.text[:20] for i in store.items) == sorted(['He said: "new chat a', "I'm allergic to pean"])


def test_policy_caps_the_oldest_turns(store):
    now = time.time()
    for k in range(5):
        store.add("turn", f'He said: "chat {k} about tea leaves" You said: "ok"', at=now - k * 60)
    store.add("fact", "I'm allergic to peanuts", at=now - 10 * DAY)
    assert store.prune(recall.Policy(max_items=3), now) == 3
    assert [i.kind for i in store.items].count("fact") == 1


def test_policy_file(tmp_path):
    path = tmp_path / "memory.yaml"
    path.write_text("budget_tokens: 200\nkeep_days:\n  turn: 30\n", encoding="utf-8")
    p = recall.load_policy(path)
    assert p.budget_tokens == 200 and p.keep_days["turn"] == 30 and p.keep_days["fact"] == 0


def test_when_names_spans():
    tue = datetime(2026, 10, 13, 15, 0)
    start, end, _ = recall.when("what did we talk about last week", tue)
    assert datetime.fromtimestamp(start) == datetime(2026, 10, 5) and datetime.fromtimestamp(end) == datetime(2026, 10, 12)
    start, end, _ = recall.when("what did I say yesterday", tue)
    assert datetime.fromtimestamp(start) == datetime(2026, 10, 12)
    start, _, _ = recall.when("the lecture on Monday", tue)
    assert datetime.fromtimestamp(start) == datetime(2026, 10, 12)
    start, _, _ = recall.when("what did we do on Tuesday", tue)
    assert datetime.fromtimestamp(start) == datetime(2026, 10, 6)  # a week ago, not today
    start, end, _ = recall.when("three days ago", tue)
    assert datetime.fromtimestamp(start) == datetime(2026, 10, 10)
    assert recall.when("set a timer for five minutes", tue) is None


def test_asks_past():
    for said in ("what did we talk about last week", "what did I tell you about Trác", "find that thing I researched about kendo",
                 "what did I say about my work project", "do you remember my brother's name", "what did we do yesterday?",
                 "what was the lecture on Monday about"):
        assert recall.asks_past(said), said
    for said in ("what's the weather", "research kendo history", "my Chrome keeps crashing lately", "set a timer",
                 "what should I cook tonight?", "what are we doing this week?"):
        assert not recall.asks_past(said), said


def test_his_store_and_the_test_store_never_mix(tmp_path, monkeypatch):
    from tools import sandbox

    his, dev = recall.Store(tmp_path / "his.sqlite", BagEmbedder()), recall.Store(tmp_path / "dev.sqlite", BagEmbedder())
    monkeypatch.setattr(recall, "HIS", his)
    monkeypatch.setattr(recall, "DEV", dev)
    sandbox.enter("socket")
    assert recall.current() is dev
    sandbox.enter("mic")
    assert recall.current() is his
    sandbox.enter("hud")
    assert recall.current() is his


def test_writes_happen_off_the_turn(store):
    recall.remember_fact("I'm allergic to peanuts", "s1", store)
    recall.remember_turn("ok", "Sure.", "s1", store)  # too short to keep
    recall.remember_turn("how do I sharpen a kitchen knife", "A whetstone.", "s1", store)
    recall.flush()
    assert sorted(i.kind for i in store.items) == ["fact", "turn"]
