"""Her drawing specs, laid out (Round 8): every form she may choose fits the board
and keeps out of her face; a loosely written spec is read the way she meant it; one
that can't be drawn is a SpecError - never any other exception."""
import json
import random
import re
from pathlib import Path

import pytest

from irene import drawing
from irene.compose import width
from irene.drawing import SpecError, compile, read

PERSONA = Path(__file__).resolve().parents[2] / "config" / "persona.md"


def examples() -> list[dict]:
    """The worked examples she learns from (config/persona.md)."""
    return [json.loads(m) for m in re.findall(r"^    <draw>(\{.*\})</draw>$", PERSONA.read_text(encoding="utf-8"), re.M)]


def in_bounds(shapes):
    for s in shapes:
        if s["type"] == "label":
            w = width(s["text"])
            x0 = s["x"] - (w - 1 if s.get("align") == "right" else w // 2 if s.get("align") == "center" else 0)
            assert -1 <= x0 and x0 + w <= drawing.W + 1, s
            assert 0 <= s["y"] and s["y"] + 5 <= drawing.H, s
            assert s["id"] == "title" or not (x0 + w > 100 and s["y"] < 16), f"in her face: {s}"
        for k in ("x", "x1", "x2"):
            if k in s:
                assert 0 <= s[k] < drawing.W, s
        for k in ("y", "y1", "y2"):
            if k in s:
                assert 0 <= s[k] < drawing.H, s
        if s["type"] != "label" and "y" in s and s["y"] < 16:
            assert s.get("x", 0) < 100, f"in her face: {s}"
    ids = [s["id"] for s in shapes]
    assert len(ids) == len(set(ids)), "ids unique: the HUD keeps each one's moment"


def test_the_persona_teaches_by_many_examples_of_different_forms():
    forms = {e.get("layout") or ("chess" if "chess" in e else e.get("chart")) for e in examples()}
    assert len(examples()) >= 15 and len(forms) >= 12, forms


def test_no_example_is_one_of_the_topics_it_is_tested_on():
    text = PERSONA.read_text(encoding="utf-8").lower()
    for topic in ("ruy lopez", "london system", "neural network", "animal cell", "human heart", "https", "vietnam", "photosynthesis",
                  "binary search tree", "git", "water cycle", "pixel", "world war", "engine", "kendo scoring", "nvidia", "gold price"):
        assert f"he: {topic}" not in text and f'"title": "{topic}' not in text, topic


@pytest.mark.parametrize("spec", examples(), ids=lambda e: e.get("title", "?"))
def test_every_example_lays_out_on_the_board(spec):
    r = read(spec)
    if r.layout == "chess":
        return
    drawn = compile(r)
    assert drawn.elements
    in_bounds(drawn.shapes())


LOOSE = [
    # a tree written flat: one tree
    ({"title": "BST", "layout": "tree", "items": [{"label": "50", "items": ["30", "70"]}, {"label": "30", "items": ["20", "40"]}, {"label": "20", "items": []}]}, "tree", None),
    # links to nodes she never listed: the nodes, as a graph
    ({"title": "Photo", "layout": "flow", "items": ["Water", "Glucose"], "links": [["Water", "Plant"], ["Plant", "Glucose"]]}, "graph", "added node 'Plant'"),
    ({"title": "X", "layout": "timeline", "items": ["Start", "Middle", "End"]}, "flow", "timeline without dates -> flow"),
    ({"title": "X", "layout": "timeline", "items": ["Start 1939", "End 1945"]}, "timeline", None),
    ({"title": "X", "layout": "sequence", "items": ["A", "B"]}, "flow", "sequence without messages -> flow"),
    ({"title": "X", "layout": "mind map", "items": ["A", "B", "C"]}, "radial", "layout 'mind map' -> radial"),
    ({"title": "X", "type": "steps", "steps": ["A", "B", "C"]}, "flow", None),
    ({"title": "X", "items": [{"at": "1969", "label": "Moon"}, {"at": "1989", "label": "Web"}]}, "timeline", None),
    ({"title": "X", "layout": "bar chart", "data": [{"label": "A", "value": "$1,200"}, {"label": "B", "value": "3.5k"}]}, "bar", None),
    ({"title": "X", "layout": "parts", "shape": "blob", "items": [{"label": "A", "on": "top"}]}, "parts", "shape 'blob' -> box"),
]


@pytest.mark.parametrize("spec,layout,fix", LOOSE)
def test_a_loosely_written_spec_is_read_the_way_she_meant_it(spec, layout, fix):
    r = read(spec)
    assert r.layout == layout
    if fix:
        assert fix in r.fixed
    in_bounds(compile(r).shapes())


def test_a_flat_tree_is_one_tree():
    r = read(LOOSE[0][0])
    assert len(r.items) == 1 and [c.label for c in r.items[0].items[0].items] == ["20", "40"]


@pytest.mark.parametrize("raw", ['{"title": "X", "layout": ', "[1, 2]", "no json here", '{"title": "X"}', '{"items": []}', '{"chart": "line", "points": [["a", 1]]}'])
def test_what_cannot_be_drawn_is_a_spec_error(raw):
    with pytest.raises(SpecError):
        spec = read(drawing.loads(raw))
        compile(spec)


def test_a_fenced_or_trailing_comma_spec_still_reads():
    assert drawing.loads('```json\n{"items": ["a", "b"],}\n```') == {"items": ["a", "b"]}


def test_numbers_are_read_as_written():
    assert drawing.number("$2,650.40") == 2650.4 and drawing.number("3.2k") == 3200 and drawing.number("45%") == 45
    assert drawing.number("1.2 billion") == 1.2e9 and drawing.number("n/a") is None


def test_live_numbers_match_the_pages_to_half_a_percent():
    spec = read({"chart": "line", "title": "NVDA", "points": [["Jan", 135], ["Sep", 181.2]]})
    assert drawing.numbers(spec, "NVIDIA stock this year", "opened the year at $134.29 and trades at $181.23") is None
    assert drawing.numbers(spec, "NVIDIA stock this year", "opened the year at $120.00") is not None


def test_an_arrow_goes_up_once_both_ends_are_up():
    board = drawing.SpecBoard(compile(read({"title": "X", "layout": "row", "items": ["Browser", "Server"], "links": [["Browser", "Server"]]})))
    board.snapshot()
    first = board.step("The browser asks.")
    assert not any(s["type"] == "arrow" for s in first["set"]["shapes"])
    both = board.step("The server answers.")
    assert any(s["type"] == "arrow" for s in both["set"]["shapes"])


def test_keywords_are_the_fallback_and_count_as_text_not_a_picture():
    drawn = drawing.keywords("how does x work", ["Evaporation lifts water.", "Condensation makes clouds."], "X")
    assert not drawn.visual() and {"EVAPORATION", "CONDENSATION"} <= {s["text"] for s in drawn.shapes() if s["type"] == "label"}


def test_random_specs_never_raise_anything_but_a_spec_error():
    rng = random.Random(8)
    words = ["Alpha", "Beta gamma", "A very long label indeed here", "", "x", "1941-06-22", "Nucleus", 42, None, 3.5]
    layouts = [*drawing.LAYOUTS, "chart", "nonsense", "", "bar", "line"]

    def item(depth=0):
        if depth > 2 or rng.random() < 0.4:
            return rng.choice(words)
        return {k: v for k, v in {
            "label": rng.choice(words), "items": [item(depth + 1) for _ in range(rng.randint(0, 5))] if rng.random() < 0.5 else None,
            "shape": rng.choice([*drawing.SHAPES, "blob", None]), "on": rng.choice(["top", "head", "edge", "nowhere", None]),
            "at": rng.choice(["1939", "June 1944", "soon", None]), "value": rng.choice([1, -3, "$5", None]), "row": rng.choice([0, 3, None]), "col": rng.choice([1, 9, None]),
        }.items() if v is not None}

    for _ in range(400):
        spec = {"title": rng.choice(words), "layout": rng.choice(layouts), "items": [item() for _ in range(rng.randint(0, 14))]}
        if rng.random() < 0.3:
            spec["links"] = [[rng.choice(words), rng.choice(words), rng.choice(words)] for _ in range(rng.randint(0, 6))]
        if rng.random() < 0.2:
            spec["points"] = [[rng.choice(words), rng.choice([1, 2.5, "x", -4])] for _ in range(rng.randint(0, 6))]
            spec["chart"] = rng.choice(["line", "bar"])
        try:
            drawn = compile(read(spec))
        except SpecError:
            continue
        in_bounds(drawn.shapes())


SERIES = """NVIDIA Corporation (NVDA), USD, weekly closes, Jan 1 to Sep 25:
Jan 1: 189.11
May 7: 225.83
Sep 25: 225.07
Latest price: 225.07 USD"""


def test_with_a_real_series_her_numbers_must_be_the_series():
    """Live, Round 8: invented NVIDIA prices (800, 1200, 1700) matched stray numbers
    on the pages - the series is what counts."""
    fake = read({"chart": "line", "title": "NVDA", "points": [["Mar", 800], ["Jul", 1200]]})
    pages = "Nvidia hit $800 in March and $1,200 later, analysts said. " + SERIES
    assert drawing.numbers(fake, "NVIDIA stock this year", pages) is None, "the pages alone let it through"
    assert drawing.numbers(fake, "NVIDIA stock this year", pages, SERIES) is not None
    real = read({"chart": "line", "title": "NVDA", "points": [["Jan", 189.11], ["Sep", 225.07]]})
    assert drawing.numbers(real, "NVIDIA stock this year", pages, SERIES) is None


def test_the_series_itself_is_charted_when_her_chart_cannot_be():
    spec = drawing.series_chart(SERIES, "How has NVIDIA stock done this year?")
    assert spec.layout == "line" and spec.unit == "$" and spec.points == [("Jan 1", 189.11), ("May 7", 225.83), ("Sep 25", 225.07)]
    in_bounds(compile(spec).shapes())
    assert drawing.series_chart("no rows here") is None


# ---- readable boards (2026-10-14: a lecture's boards had "EX- EC-", "PERFORMA-",
# "PROGRAMMI" and "INTRODUCTION TO") -------------------------------------------------------


def _labels_of(drawn):
    return [s.get("text", "") for s in drawn.shapes() if s.get("type") == "label"]


def test_a_title_keeps_its_meaning_when_cut():
    from irene.compose import fit_title

    assert fit_title("Introduction to Algorithm Analysis", 96) == "ALGORITHM ANALYSIS"
    assert fit_title("Course Structure and Activities", 96) == "COURSE STRUCTURE"
    assert fit_title("Water cycle", 96) == "WATER CYCLE"
    assert not fit_title("An overview of the history of the very long things of the world", 96).endswith(("OF", "THE", "TO", "AND"))


def test_six_steps_wrap_into_rows_with_whole_words():
    from irene import drawing

    labels = ["Execution Time", "Empirical Approach", "Implement Algorithm", "Measure Performance", "Theoretical Approach", "CPU Operations"]
    drawn = drawing.compile(drawing.read({"title": "Algorithms", "layout": "flow", "items": labels}))
    text = " ".join(_labels_of(drawn))
    assert "-" not in text.replace("CPU", "")  # no word broken across lines
    assert "PERFORMANCE" in text and "THEORETICAL" in text


def test_a_radial_keeps_two_word_labels_whole():
    from irene import drawing

    drawn = drawing.compile(drawing.read({"title": "Course", "layout": "radial",
                                          "items": ["Programming", "Python", "Variables", "C++", "Control Flow", "Software Engineering", "Functions"]}))
    text = " ".join(_labels_of(drawn))
    assert "PROGRAMMING" in text and "ENGINEERING" in text and "FLOW" in text


def test_a_graph_too_wide_for_its_words_goes_top_down():
    from irene import drawing

    spec = {"title": "Photosynthesis", "layout": "flow", "items": ["Sunlight", "CO2", "H2O", "Chloroplast", "Glucose", "O2"],
            "links": [["Sunlight", "Chloroplast"], ["CO2", "Chloroplast"], ["H2O", "Chloroplast"], ["Chloroplast", "Glucose"], ["Chloroplast", "O2"]]}
    drawn = drawing.compile(drawing.read(spec))
    assert "CHLOROPLAST" in _labels_of(drawn)
