import json

from irene import board
from irene.brain import StreamingReply
from irene.reply import parse_reply


def test_a_draw_is_parsed_and_never_spoken_or_displayed():
    raw = '<speak>Here it is, sir.</speak><draw>{"template": "chessboard", "opening": "Ruy Lopez"}</draw>'
    r = parse_reply(raw)
    assert r.speak == "Here it is, sir." and r.display == ""
    assert r.draw.spec == {"template": "chessboard", "opening": "Ruy Lopez"}


def test_invalid_drawings_are_refused_with_a_reason():
    assert parse_reply("<speak>Hi.</speak>").draw is None
    assert parse_reply('<draw>{"template": "chessboard", </draw>').draw.error.startswith("not JSON")
    assert "no template" in parse_reply('<draw>{"template": "mickey_mouse"}</draw>').draw.error
    assert "needs" in parse_reply('<draw>{"template": "sort", "values": [3, 1]}</draw>').draw.error
    assert "no drawable shapes" in parse_reply('<draw>{"shapes": [{"type": "spaceship"}]}</draw>').draw.error
    assert parse_reply('<draw>```json\n{"template": "bogu"}\n```</draw>').draw.spec == {"template": "bogu"}


def test_a_draw_inside_speak_is_still_not_spoken():
    s = StreamingReply()
    lines = s.feed('<speak>Look. <draw>{"template": "bogu"}</draw> Nice? </speak>') + s.finish()
    assert [l.text for l in lines] == ["Look.", "Nice?"]


def test_the_stream_hands_over_the_drawing_once_as_soon_as_it_closes():
    s = StreamingReply()
    s.feed('<speak>Watch. </speak><draw>{"template": "cl')
    assert s.drawing() is None
    s.feed('ock"}</draw>')
    assert s.drawing().spec == {"template": "clock"}
    assert s.drawing() is None


def test_every_registered_template_is_offered_and_its_example_passes_core_checks():
    text = board.board_section()
    reg = json.loads(board.REGISTRY_PATH.read_text(encoding="utf-8"))
    # every live widget for the model; core's internal ones (the research terms
    # board) never, nor the retired ones (Round 8: topic recipes, and what her own
    # specs now draw) - which still draw if she writes one
    for t in reg["templates"]:
        if t.get("internal") or t.get("retired"):
            assert f"- {t['name']}(" not in text
            if t.get("internal"):
                continue
        else:
            assert f"- {t['name']}(" in text
        assert board.check(t["example"]) is None, t["name"]
    assert {"shinai", "bogu", "kendo_targets", "chessboard"} <= {t["name"] for t in reg["templates"] if t.get("retired")}
    assert board.check(reg["shapes_example"]) is None


def test_unambiguous_template_mistakes_are_normalized():
    assert parse_reply('<draw>{"calendar": {"month": "2026-09"}}</draw>').draw.spec == {"template": "calendar", "month": "2026-09"}
    assert parse_reply('<draw>{"shapes": [{"type": "stack", "values": [1, 2]}]}</draw>').draw.spec == {"template": "stack", "values": [1, 2]}
    assert parse_reply('<draw>{"type": "bogu"}</draw>').draw.spec == {"template": "bogu"}
    # a real freehand drawing is left as it is
    free = {"shapes": [{"type": "circle", "x": 3, "y": 3, "r": 2}]}
    assert parse_reply(f"<draw>{json.dumps(free)}</draw>").draw.spec == free


def test_drawing_requests_name_their_widget_or_ask_her_to_compose_it():
    assert board.wanted("What's the capital of France?") is None
    assert board.wanted("Show me my calendar for this month") == "calendar"
    # a chart, a tree, an opening, a kendo target: hers to compose (Round 8)
    for request in ("Plot my chess rating over the last months", "Draw a binary search tree with 8, 3, 10",
                    "Show me the Ruy Lopez on the board.", "Draw the kendo scoring targets", "Draw a simple house"):
        assert board.wanted(request) == "shapes", request
        assert "compose it" in board.hint(request)
    assert not hasattr(board, "opening_in")
    assert "copyrighted" in board.hint("Draw Pikachu for me!")


def test_a_fenced_drawing_with_a_name_is_never_a_tool_call():
    """Routing evals, Round 8: a spec titled "Nvidia RTX 5090" was read as a tool."""
    from irene.brain import parse_tool_call

    raw = '<speak>Big card.</speak><draw>```json\n{"name": "Nvidia RTX 5090", "layout": "column", "items": ["a"]}\n```</draw>'
    assert parse_tool_call(raw) is None
    assert parse_tool_call('```json\n{"name": "research", "arguments": {"question": "q"}}\n```') == ("research", {"question": "q"})
