"""The board illustrates what she explains with the drawing she composes (Round 8).

Round 7 anticipated pictures (a composer per kind, equipment templates per topic).
Now she writes the spec herself; illustrate.py turns it into the board he watches:
chess from ANY legal line (hers, or the pages she read), everything else laid out
by drawing.py, each element as she names it - and her keywords when her drawing
can't be drawn, logged, never a crash."""
import asyncio
import json

import pytest

from irene import drawing, illustrate
from irene.illustrate import BoardFeed, Chess, Live, board_for, for_question, legal_line
from tests.test_research_summary import research


@pytest.fixture(autouse=True)
def spec_log(tmp_path, monkeypatch):
    path = tmp_path / "draw-specs.jsonl"
    monkeypatch.setattr(drawing, "LOG_PATH", path)
    return path


def shapes_of(message):
    spec = message.get("set") or message.get("spec")
    return spec.get("shapes", [])


def labels(message):
    return [s["text"] for s in shapes_of(message) if s["type"] == "label"]


# ---- chess: derived from moves, never a table ------------------------------------------


def test_there_is_no_table_of_openings_or_topic_recipes_any_more():
    assert not hasattr(illustrate, "OPENING_LINES")
    assert not hasattr(illustrate, "EQUIPMENT") and not hasattr(illustrate, "plan")


def test_a_line_is_read_from_text_and_checked_legal():
    assert legal_line("The Italian Game starts 1. e4 e5 2. Nf3 Nc6 3. Bc4 and then...") == ["e4", "e5", "Nf3", "Nc6", "Bc4"]
    assert legal_line("King's Indian: 1.d4 Nf6 2.c4 g6 3.Nc3 Bg7 4.e4 d6") == ["d4", "Nf6", "c4", "g6", "Nc3", "Bg7", "e4", "d6"]
    assert legal_line("It starts with d4, d5, then c4.") == ["d4", "d5", "c4"]
    assert legal_line("1.e4 e5 2.Ke3") == ["e4", "e5"], "an illegal move ends the line"
    assert legal_line("The e4 square matters.") == []


def test_any_opening_she_writes_is_played_from_its_moves():
    """The Ruy Lopez was never wired up in any table - its moves are enough."""
    board, spec = board_for({"chess": ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"], "title": "Ruy Lopez"}, "Explain the Ruy Lopez", None)
    assert isinstance(board, Chess) and board.moves == ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]
    assert board.snapshot()["spec"]["title"] == "RUY LOPEZ"
    # "1. e4" and a PGN string are moves too
    board, _ = board_for({"chess": "1. d4 d5 2. Bf4 Nf6 3. e3", "title": "London"}, "the London System", None)
    assert board.moves == ["d4", "d5", "Bf4", "Nf6", "e3"]


def test_moves_she_wrote_as_labels_are_still_a_chessboard():
    """Live probe: the Ruy Lopez came back as a sequence of "1. e4" boxes."""
    spec = {"title": "Ruy Lopez", "layout": "flow", "items": ["1. e4", "e5", "2. Nf3", "Nc6", "3. Bb5"]}
    board, read = board_for(spec, "Explain the Ruy Lopez opening.", None)
    assert isinstance(board, Chess) and board.moves == ["e4", "e5", "Nf3", "Nc6", "Bb5"]


def test_the_pages_she_researched_win_over_moves_she_misremembers():
    pages = "The Ruy Lopez begins 1.e4 e5 2.Nf3 Nc6 3.Bb5, the Spanish bishop."
    board, _ = board_for({"chess": ["e4", "e5", "Nf3", "Nf6", "Bb5"]}, "Research the Ruy Lopez", pages)
    assert board.moves == ["e4", "e5", "Nf3", "Nc6", "Bb5"]
    with pytest.raises(drawing.SpecError):
        board_for({"chess": ["e5", "Ke2"]}, "a chess line", None)


def test_an_opening_she_researched_is_drawn_from_the_pages_before_her_drawing_arrives():
    pages = "The Italian Game is a chess opening that begins with the moves 1.e4 e5 2.Nf3 Nc6 3.Bc4."
    live = Live("Research the Italian Game", "Italian Game", pages)
    assert isinstance(live.inner, Chess)
    first = live.hear("The Italian Game starts with e4 and e5.", ["Italian Game"])[0]
    assert first["spec"] == {"template": "chessboard", "moves": ["e4", "e5", "Nf3", "Nc6", "Bc4"], "title": "ITALIAN GAME", "sync": True}
    assert first["add"]["reveal"] == [{"key": "ply:2"}], "each move as she says it"
    assert live.hear("Then Nc6 and Bc4, aiming at f7.")[0]["add"]["reveal"] == [{"key": "ply:5"}]
    # her drawing of the same line, longer: the board grows, it does not restart
    grew = live.adopt(Chess("Italian Game", ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"]))
    assert grew == {"type": "board_sync", "set": {"moves": ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"]}}


def test_an_opening_she_only_says_becomes_a_chessboard_from_her_words():
    live = for_question("Explain the London System.")
    assert live.hear("The London System is a solid opening for White.") == []
    msg = live.hear("It goes 1.d4 d5 2.Bf4, then e6 for Black.")[0]
    assert isinstance(live.inner, Chess)
    assert msg["spec"]["moves"] == ["d4", "d5", "Bf4", "e6"] and msg["add"]["reveal"] == [{"key": "ply:4"}]


def test_a_move_said_past_the_known_line_is_added_only_if_legal():
    board = Chess("Queen's Gambit", ["d4", "d5", "c4"])
    board.step("It starts with d4.")
    grew = board.step("After c4, Black can play e6.")
    assert grew["set"] == {"moves": ["d4", "d5", "c4", "e6"]}
    assert board.step("Then Ke8 somewhere.") is None, "illegal: nothing changes"


# ---- her drawing, as he hears it ----------------------------------------------------------------


CYCLE = {"title": "Water cycle", "layout": "cycle", "items": ["Evaporation", "Condensation", "Precipitation", "Collection"]}


def test_a_drawing_arriving_mid_answer_shows_what_she_said_then_the_rest_as_she_says_it():
    live = for_question("How does the water cycle work?")
    assert live.hear("Water keeps moving around the planet.") == []
    live.hear("First, evaporation lifts it from the sea.")
    board, _ = board_for(CYCLE, live.question, None)
    first = live.adopt(board)
    assert "spec" in first and "EVAPORATION" in labels(first) and "CONDENSATION" not in labels(first)
    later = live.hear("Then it cools: condensation makes clouds.")[0]
    assert "CONDENSATION" in labels(later) and "PRECIPITATION" not in labels(later)
    old = {s["id"] for s in shapes_of(first)}
    assert old <= {s["id"] for s in shapes_of(later)}, "what was shown keeps its id: nothing replays"
    last = live.finish()
    assert {"PRECIPITATION", "COLLECTION"} <= set(labels(last)), "the rest as the answer ends"


def test_a_step_named_reveals_the_steps_before_it_in_a_flow():
    board, _ = board_for({"title": "Compiler", "layout": "flow", "items": ["Lexer", "Parser", "Optimizer"]}, "how a compiler works", None)
    board.snapshot()
    shown = labels(board.step("Then the optimizer tidies it."))
    assert {"LEXER", "PARSER", "OPTIMIZER"} <= set(shown)


def test_the_feed_finishes_the_board_as_the_last_sentence_starts():
    sent = []
    feed = BoardFeed(sent.append)
    feed.start(for_question("How does the water cycle work?"))
    for text in ("Water moves.", "Evaporation lifts it.", "Rain brings it back."):
        feed.line()
    feed.heard("Water moves.")
    board, _ = board_for(CYCLE, "water cycle", None)
    feed.adopt(board)
    feed.close()
    assert "COLLECTION" not in labels(sent[-1]), "not yet: two sentences still to come"
    feed.heard("Evaporation lifts it.")
    feed.heard("Rain brings it back.")
    assert "COLLECTION" in labels(sent[-1])


# ---- live numbers are real, or not drawn --------------------------------------------------------

GOLD = {"chart": "line", "title": "Gold this month", "unit": "$", "points": [["Sep 1", 2650.4], ["Sep 15", 2702.9], ["Sep 26", 2724.5]]}


def test_a_live_chart_needs_research_and_its_numbers_must_be_on_the_pages():
    with pytest.raises(illustrate.LiveDataError):
        board_for(GOLD, "gold price this month", None)
    with pytest.raises(illustrate.LiveDataError):
        board_for(GOLD, "gold price this month", "Gold rose this month, analysts said.")
    pages = "Gold opened September at $2,650.40 an ounce, hit 2,702.90 mid-month and closed Friday at $2,724.52."
    board, _ = board_for(GOLD, "gold price this month", pages)
    assert board.kind == "line"


def test_numbers_that_do_not_change_may_be_charted_from_what_she_knows():
    moons = {"chart": "bar", "title": "Moons", "points": [["Saturn", 146], ["Jupiter", 95]]}
    board, _ = board_for(moons, "which planets have the most moons", None)
    assert board.kind == "bar"


def test_a_plain_question_gets_a_board_but_chat_does_not():
    assert for_question("How does photosynthesis work?") is not None
    assert for_question("What are the kendo scoring targets?") is not None
    assert for_question("How are you today?") is None
    assert for_question("tell me a joke") is None


def test_a_stray_bracket_token_is_never_read_out():
    """Live, explaining the shinai: "it's the striking point [draw]"."""
    from irene.reply import spoken

    assert spoken("The kensen is the tip [draw]. It strikes [1, 2]. Ha [laugh] ok.") == "The kensen is the tip. It strikes. Ha [laugh] ok."


# ---- through the conversation ---------------------------------------------------------------------


class BoardSink:
    """A sink that hears every sentence at once, with the app's board feed."""

    def __init__(self, host, boards):
        self.host = host
        self.feed = BoardFeed(boards.append)

    def line(self, line):
        self.host.events.append(("say", line.text))
        self.feed.line()
        self.feed.heard(line.text, line.terms)

    def illustrate(self, plan):
        self.feed.start(plan)

    def adopt(self, board):
        self.feed.adopt(board)

    def close_board(self):
        self.feed.close()

    def draw(self, found):
        self.host.events.append(("draw", found.spec))

    async def finish(self, reply):
        self.host.events.append(("finish", reply.speak, reply.display))


def converse(replies, text, monkeypatch=None, tool=None):
    from irene.brain import Conversation
    from tests.test_brain import FakeHost, FakeLLM

    boards = []
    host = FakeHost()
    host.reply_sink = lambda: BoardSink(host, boards)
    llm = FakeLLM(replies)
    conv = Conversation(llm)
    asyncio.run(conv.respond(text, host))
    return host.events, boards, llm


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_her_drawing_in_the_reply_is_the_board(spec_log):
    reply = (
        "<speak>Water goes round and round. Evaporation lifts it, condensation makes clouds.</speak>"
        '<draw>{"title": "Water cycle", "layout": "cycle", "items": ["Evaporation", "Condensation", "Precipitation", "Collection"]}</draw>'
    )
    events, boards, _ = converse([reply], "How does the water cycle work?")
    assert boards and "spec" in boards[0]
    assert "COLLECTION" in labels(boards[-1])
    assert [r["outcome"] for r in rows(spec_log)] == ["ok"]


def test_a_spec_written_as_display_is_drawn_and_never_shown_as_text(spec_log):
    reply = '<speak>Four strokes, sir.</speak><display>{"title": "Engine", "layout": "cycle", "items": ["Intake", "Compression", "Power", "Exhaust"]}</display>'
    events, boards, _ = converse([reply], "How does an engine work?")
    assert boards and "INTAKE" in labels(boards[-1])
    finish = next(e for e in events if e[0] == "finish")
    assert "{" not in finish[2]


def test_no_drawing_in_the_reply_she_is_asked_for_it_once(spec_log):
    events, boards, llm = converse(
        ["<speak>A tree keeps smaller keys on the left.</speak>", '<draw>{"title": "BST", "layout": "tree", "items": [{"label": "8", "items": ["3", "10"]}]}</draw>'],
        "What is a binary search tree?",
    )
    assert "10" in labels(boards[-1])
    assert "Your board needs the drawing" in llm.seen[-1][-1]["content"]
    assert [(r["origin"], r["outcome"]) for r in rows(spec_log)] == [("follow-up", "ok")]


def test_a_spec_that_cannot_be_drawn_is_logged_and_the_board_falls_back_to_her_keywords(spec_log):
    events, boards, llm = converse(
        ["<speak>Photosynthesis turns sunlight into sugar. Chlorophyll catches the light.</speak><draw>{\"title\": \"Photo\", \"layout\": </draw>",
         "<draw>{\"items\": []}</draw>"],
        "How does photosynthesis work?",
    )
    log = rows(spec_log)
    assert [(r["origin"], r["outcome"]) for r in log] == [("reply", "invalid"), ("follow-up", "invalid"), ("fallback", "keywords")]
    assert "couldn't be drawn" in llm.seen[-1][-1]["content"], "the follow-up says what was wrong"
    assert boards and labels(boards[-1]), "her keywords, never nothing"


def test_a_live_chart_from_memory_is_never_drawn_she_says_so(spec_log, monkeypatch):
    from irene import brain

    async def offline(self, name, args, host):
        return "error: research is offline"

    monkeypatch.setattr(brain.Conversation, "_run_tool", offline)
    reply = '<speak>Gold climbed this month.</speak><draw>{"chart": "line", "title": "Gold", "points": [["Sep 1", 2650], ["Sep 26", 2724]]}</draw>'
    events, boards, _ = converse([reply], "How has the gold price done this month?")
    said = [e[1] for e in events if e[0] == "say"]
    assert any("chart" in s for s in said[1:]), said
    assert [r["outcome"] for r in rows(spec_log)] == ["refused", "keywords"]
    assert all(s["type"] != "dot" for b in boards for s in shapes_of(b) if b.get("spec") or b.get("set")), "no chart drawn"


def test_a_widget_she_draws_is_drawn_as_it_is():
    reply = '<speak>Here is your month.</speak><draw>{"template": "calendar", "month": "2026-09"}</draw>'
    events, boards, _ = converse([reply], "Show me the calendar")
    assert ("draw", {"template": "calendar", "month": "2026-09"}) in events and not boards


def test_a_queens_gambit_research_answer_draws_the_position_as_she_explains(tmp_path, monkeypatch):
    """Through Conversation.respond: the line comes from the page she fetched."""
    from irene import brain
    from tools import research as R
    from tools.registry import ToolResult

    found = research(tmp_path, monkeypatch)
    monkeypatch.setattr(R, "last", lambda: found)

    async def run_tool(self, name, args, host):
        return ToolResult(R.for_model(found), tainted=True)

    monkeypatch.setattr(brain.Conversation, "_run_tool", run_tool)
    events, boards, _ = converse([
        '<tool_call>{"name": "research", "arguments": {"question": "the Queen\'s Gambit opening in chess"}}</tool_call>',
        "<speak><cue>thinking</cue>The Queen's Gambit is a chess opening that starts with the moves d4, d5 and c4 [1]. "
        "White offers a pawn to lure Black's d-pawn away from the centre [1]. "
        "It is not a true gambit, because Black cannot keep the extra pawn without making concessions [2].</speak>",
    ], "Research the Queen's Gambit opening.")
    first = boards[0]
    assert first["spec"]["template"] == "chessboard" and first["spec"]["moves"][:3] == ["d4", "d5", "c4"]
    plies = [r["key"] for b in boards for r in b.get("add", {}).get("reveal", [])]
    assert "ply:3" in plies, "the moves go up with the sentence that says them"


def test_old_drawings_leave_the_history_and_a_bigger_prompt_shrinks_its_budget():
    """Live, Round 8: sixteen answers each carrying a spec filled the 16k context
    and the seventeenth ran out before its drawing."""
    from irene import brain
    from irene.brain import Conversation
    from tests.test_brain import FakeLLM

    conv = Conversation(FakeLLM([]))
    spec = '<draw>{"title": "X", "layout": "flow", "items": ["a", "b"]}</draw>'
    for k in range(3):
        conv.history += [{"role": "user", "content": f"q{k}"}, {"role": "assistant", "content": f"<speak>a{k}</speak>{spec}"}]
    conv.compact(budget=10_000_000, keep=10_000_000)
    assert [("<draw>" in m["content"]) for m in conv.history if m["role"] == "assistant"] == [False, False, True]
    grown = brain._tokens([{"content": conv.system()}]) - brain.SYSTEM_BASE_TOKENS
    assert grown > 0, "the drawing examples made the system prompt bigger"
    conv.history += [{"role": "user", "content": "x" * int((brain.HISTORY_BUDGET_TOKENS - grown // 2) * 3.5)}, {"role": "user", "content": "last"}]
    conv.compact()
    assert brain._tokens(conv.history) <= brain.HISTORY_BUDGET_TOKENS - grown
