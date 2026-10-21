"""Her board for a lecture: a drawing per topic from that topic's own words (nothing
the lecturer didn't say), shown as she reaches the topic, and the same drawing kept
as a picture in the note - rendered only by the HUD."""
import asyncio
import base64
import json

from irene import drawing, lecture_board, lecture_summary


SAID = lecture_board.Said("An empirical approach means you implement the algorithm and measure its execution time. "
                          "A theoretical approach makes assumptions about CPU operations.")


def test_a_label_the_lecturer_never_said_stays_off_the_board():
    raw = {"layout": "compare", "items": [{"label": "Empirical approach", "items": ["Implement", "Measure", "Big-O notation"]},
                                         {"label": "Theoretical approach", "items": ["CPU operations", "Memory usage"]}],
           "links": [["Empirical approach", "Theoretical approach", "versus"]]}
    spec, dropped = lecture_board.ground(raw, SAID)
    assert dropped == ["Big-O notation", "Memory usage"]
    flat = [x if isinstance(x, str) else x["label"] for x in lecture_board._flat(spec["items"])]
    assert "Measure" in flat and "Implement" in flat  # "measure"/"implement" were said
    assert spec["links"] == [["Empirical approach", "Theoretical approach"]]  # "versus" never was


def test_numbers_and_dates_need_the_lecture_too():
    raw = {"layout": "timeline", "items": [{"label": "Empirical approach", "at": "1965"}, {"label": "CPU operations", "value": 42}]}
    spec, dropped = lecture_board.ground(raw, SAID)
    assert dropped == ["Empirical approach"] and "value" not in spec["items"][0]


def test_compose_grounds_each_topic_and_varies_the_form():
    sections = [{"title": "Measuring", "start": 0, "end": 60, "points": ["Empirical approach."]},
                {"title": "Theory", "start": 60, "end": 120, "points": ["CPU operations."]}]
    lines = [{"t": 0, "end": 30, "text": "An empirical approach: implement it and measure execution time."},
             {"t": 60, "end": 90, "text": "A theoretical approach counts CPU operations and memory."}]
    prompts = []

    async def chat(messages):
        prompts.append(messages[0]["content"])
        if len(prompts) == 1:
            return json.dumps({"layout": "flow", "items": ["Implement", "Measure", "Execution time", "Profit"]})
        return json.dumps({"layout": "radial", "items": ["Unicorns", "Rainbows"]})

    plans = asyncio.run(lecture_board.compose(sections, lines, chat))
    assert plans[0]["layout"] == "flow" and plans[0]["dropped"] == ["Profit"]
    assert plans[1] == {"outline": True}  # nothing in it was said: her points instead
    assert "Already drawn for earlier topics: flow" in prompts[1]
    # only that topic's words, never the next topic's
    assert "theoretical" not in prompts[0].split("The lecturer's words")[1]


def plan_and_boards():
    s = lecture_summary.Summary("It was about two approaches. Both matter.",
                                [{"title": "Measuring", "start": 0, "end": 60, "points": ["You implement it and time it."]},
                                 {"title": "Theory", "start": 60, "end": 120, "points": ["You count CPU operations."]}],
                                [], {"grade": "good"}, {})
    plan = lecture_summary.speech_plan(s)
    topics = [drawing.compile(drawing.Spec("flow", "A", [drawing.Item(x) for x in ("One", "Two", "Three", "Four")])),
              drawing.compile(drawing.Spec("row", "B", [drawing.Item(x) for x in ("Five", "Six")]))]
    first = lecture_board.overview(s.sections, "Lecture")
    return plan, lecture_board.TopicBoards(first, topics, plan)


def test_the_spoken_summary_walks_the_topics_each_with_its_board():
    plan, _ = plan_and_boards()
    said = [t for t, _ in plan]
    assert said[:4] == ["It was about two approaches.", "Both matter.", "The main topics were Measuring and Theory.", "First, Measuring."]
    assert [k for _, k in plan][3:7] == [0, 0, 1, 1] and plan[-1][1] == lecture_summary.STAY


def test_each_topic_board_comes_up_as_she_reaches_it_and_builds_up():
    plan, boards = plan_and_boards()
    assert boards.snapshot()["spec"]  # the topics' overview while she gives it
    messages = [boards.step(t) for t, _ in plan]
    first, point = messages[3], messages[4]
    assert "spec" in first  # topic 1 replaces the overview
    shown_first = len({s["id"].split(".")[0] for s in first["spec"]["shapes"] if s.get("id")})
    shown_after = len({s["id"].split(".")[0] for s in point["set"]["shapes"] if s.get("id")})
    assert shown_first < shown_after  # half, then all of it
    assert "spec" in messages[5]  # topic 2: a new drawing
    assert messages[-1] is None  # the closing line keeps the last board up


def test_only_the_hud_may_hand_back_a_picture():
    renders = lecture_board.Renders()
    png = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 40).decode()

    class Bridge:
        hud_connected = True

        def __init__(self):
            self.sent = []

        async def send(self, message):
            self.sent.append(message)
            # a dev socket answers first, then the HUD
            asyncio.ensure_future(renders.on_rendered({"type": "board_rendered", "id": message["id"], "png": "data:image/png;base64,AAAA", "_origin": "script"}))
            asyncio.ensure_future(renders.on_rendered({"type": "board_rendered", "id": message["id"], "png": png, "_origin": "hud"}))

    drawn = drawing.compile(drawing.Spec("flow", "A", [drawing.Item("One"), drawing.Item("Two")]))
    bridge = Bridge()
    got = asyncio.run(renders.render(bridge, drawn))
    assert got == png and bridge.sent[0]["type"] == "board_render" and bridge.sent[0]["spec"]["shapes"]


def test_no_hud_no_picture():
    class Away:
        hud_connected = False

    drawn = drawing.compile(drawing.Spec("flow", "A", [drawing.Item("One"), drawing.Item("Two")]))
    assert asyncio.run(lecture_board.Renders().render(Away(), drawn)) == ""


def test_the_vocabulary_comes_from_the_persona():
    text = lecture_board.vocabulary()
    assert "flow" in text and "compare" in text and "Spec:" in text
