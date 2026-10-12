"""The daily briefing (tools/briefing.py), its board (drawing.sections) and her
considerate greetings (greeting.py, presence.py). No network: sources are faked."""
import random
from datetime import datetime, timedelta

import pytest

from irene import drawing, fast, greeting, illustrate
from irene.presence import Presence, clock_words, topic_of
from tools import briefing as B


def _call(text, recent=()):
    return fast.direct_call(text, list(recent))


@pytest.mark.parametrize("said", ["What's new today?", "brief me", "What's happening?", "anything new, Irene?", "Good morning! What's new?",
                                  "give me my morning briefing", "catch me up", "what's happening in the world today"])
def test_every_trigger_goes_straight_to_the_briefing(said):
    assert '"daily_briefing"' in _call(said)
    assert '"expand"' not in _call(said)


@pytest.mark.parametrize("said", ["anything new in my downloads?", "what's new in Python 3.13?", "how are you today?", "what's up?"])
def test_near_misses_never_call_it(said):
    assert "daily_briefing" not in (_call(said) or "")


def test_follow_ups_expand_only_after_a_briefing():
    assert '"expand": "2"' in _call("Tell me more about the second one.", ["daily_briefing"])
    assert '"expand": "gold"' in _call("more on the gold", ["daily_briefing"])
    assert '"expand": "last"' in _call("tell me more about the last one", ["daily_briefing"])
    assert _call("Tell me more about the second one.") is None


def _ms(when):
    return f"/Date({int(when.timestamp() * 1000)})/"


def test_gold_is_the_sjc_bar_and_its_day_change():
    now = datetime(2026, 10, 6, 10, 0, tzinfo=B.VN)
    bar = "Vàng SJC 1L, 10L, 1KG"
    rows = [
        {"TypeName": bar, "BranchName": "Hồ Chí Minh", "BuyValue": 141e6, "SellValue": 144e6, "GroupDate": _ms(now - timedelta(days=1))},
        {"TypeName": bar, "BranchName": "Miền Bắc", "BuyValue": 1e6, "SellValue": 1e6, "GroupDate": _ms(now)},
        {"TypeName": bar, "BranchName": "Hồ Chí Minh", "BuyValue": 140.5e6, "SellValue": 143.5e6, "GroupDate": _ms(now - timedelta(hours=1))},
    ]
    g = B.parse_sjc(rows, now)
    assert (g["buy"], g["sell"], g["change_sell"]) == (140.5e6, 143.5e6, -500000)
    item = B.gold_item(g)
    assert item.say.startswith("Gold's down 500,000 a lượng") and "143.5 million" in item.say
    assert item.board["up"] is False and item.board["change"] == "-500K"


def test_the_fallback_gold_page_claims_no_change():
    page = "x <td>Giá vàng Miếng</td><td>Mua vào</td><td>140.500</td><td>x1000đ/lượng</td><td>Bán ra</td><td>143.500</td><td>x1000đ/lượng</td>"
    g = B.parse_fallback(page)
    assert (g["buy"], g["sell"], g["change_sell"]) == (140.5e6, 143.5e6, 0.0)
    assert B.gold_item(g) is None and "not known" in B.gold_detail(g)


def _found():
    return {
        "weather": {"city": "Da Lat", "sky": "Showers", "days": [{"day": "Tue", "high": 22, "low": 14, "rain": 90, "sky": "Showers", "mm": 9}], "rain_streak": 3},
        "markets": [
            {"symbol": "NVDA", "title": "NVIDIA", "price": 230.1, "currency": "USD", "change": -3.4, "spark": [240, 236, 230.1], "kind": "stock", "url": "u1"},
            {"symbol": "MSFT", "title": "Microsoft", "price": 500.0, "currency": "USD", "change": 0.1, "spark": [499, 500], "kind": "stock", "url": "u2"},
        ],
        "world": [{"title": "Watch: Big summit agrees climate deal", "url": "w", "source": "BBC", "also": ["NYT", "NPR"]}],
    }


def test_the_briefing_picks_what_moved_and_says_what_failed():
    b = B.build(_found(), ["gold"], "07:00", random.Random(1))
    kinds = [i.kind for i in b.items]
    assert len(b.items) == 3 and "market" in kinds and "weather" in kinds and "world" in kinds
    assert not any("Microsoft" in i.say for i in b.items), "a flat stock is not reported"
    assert any("NVIDIA had a rough night" in i.say for i in b.items)
    assert any("couldn't reach SJC" in s for s in b.speech), "a failed source is said, never guessed"
    assert b.speech[-1].endswith("?")
    assert all(not s.startswith("Watch") and "Watch:" not in s for s in b.speech)
    kinds = [blk["kind"] for blk in b.content["blocks"]]
    assert {"weather", "price", "story"} <= set(kinds)


def test_the_spoken_briefing_opens_on_the_newsreader_cue():
    B.LAST = B.build(_found(), [], "07:00", random.Random(1))
    raw = fast.reply("daily_briefing", {}, "briefing given at 07:00", "what's new")
    assert raw.startswith("<speak><cue>newsDesk</cue>")
    assert raw.count("<cue>") == len(B.LAST.speech)


def test_the_board_draws_one_section_per_sentence():
    B.LAST = B.build(_found(), [], "07:00", random.Random(1))
    board = illustrate.briefing_board()
    assert isinstance(board, drawing.SectionBoard) and len(board.drawn.elements) == 3
    first = board.snapshot()
    assert first["spec"]["shapes"] and not board.shown
    board.step(B.LAST.speech[0])
    assert board.shown == {"e0"}
    board.step(B.LAST.speech[1])
    assert board.shown == {"e0", "e1"}
    board.finish()
    assert board.shown == {"e0", "e1", "e2"}
    headers = [s["text"] for s in board.drawn.shapes() if s["type"] == "label" and s.get("color") == "amber"]
    assert "ĐÀ LẠT" in headers and "NVDA" in headers


def test_a_greeting_notices_the_rain_and_keeps_his_name():
    ctx = greeting.Context(datetime(2026, 10, 6, 8, 0), weather={"sky": "Rain", "temp": 16, "rain_streak": 3, "days": [{"rain": 90}]}, since_last_s=12 * 3600)
    g = greeting.Greeter(random.Random(4))
    lines = [g.considerate(ctx) for _ in range(20)]
    assert all(greeting.NAME in line for line in lines)
    assert all(a != b for a, b in zip(lines, lines[1:]))
    assert sum("rain" in line.lower() for line in lines) >= 10


def test_nothing_notable_is_the_plain_greeting():
    ctx = greeting.Context(datetime(2026, 10, 7, 14, 0), weather={"sky": "Partly cloudy", "temp": 21, "days": [{"rain": 10}]}, since_last_s=6 * 3600)
    assert greeting.Greeter(random.Random(1)).considerate(ctx) is None


def test_presence_remembers_across_restarts(tmp_path):
    path = tmp_path / "presence.json"
    p = Presence(path)
    t0 = datetime(2026, 10, 6, 6, 0).timestamp()
    p.heard(t0)
    p.topic("Explain the Sicilian Defence?", t0)
    seen = Presence(path).seen(t0 + 3600)
    assert seen.since_last_s == 3600 and seen.first_today.hour == 6 and seen.topic == "the Sicilian Defence"
    assert topic_of("research kendo dan grades") == "kendo dan grades"
    assert clock_words(datetime(2026, 1, 1, 6, 0)) == "six" and clock_words(datetime(2026, 1, 1, 7, 30)) == "half past seven"


def test_an_expansion_is_spoken_from_the_readings_and_drawn_alone():
    B.LAST = B.build(_found(), [], "07:00", random.Random(1))
    n = next(k for k, i in enumerate(B.LAST.items, 1) if i.kind == "market")
    B.LAST_EXPANSION = B.expansion_speech(B.LAST.items[n - 1], B.LAST)
    raw = fast.reply("daily_briefing", {"expand": str(n)}, "item 1 of the briefing", "tell me more")
    assert "NVIDIA is at 230.10 dollars, down 3.4 percent" in raw and "230.10 dollars to 240.00 dollars" in raw
    board = illustrate.briefing_board(str(n))
    assert len(board.drawn.elements) == 1
