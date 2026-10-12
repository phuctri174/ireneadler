from irene import react


def test_gestures_come_from_the_hud():
    assert "thumbsUp" in react.GESTURES and "wave" in react.GESTURES and "embarrassed" in react.GESTURES
    assert len(react.GESTURES) == len(set(react.GESTURES)) >= 14


def test_names_do_not_collide_across_kinds():
    assert len(react.ALL) == len(set(react.ALL))


def test_act_out_requests_name_the_action():
    assert react.act_out("Can you do some kendo strikes?") == "kendo"
    assert react.act_out("Show me a kendo strike!") == "kendo"
    assert react.act_out("Play me a chess move, I want to see you think.") == "chess"
    assert react.act_out("Wave at me!") == "wave"
    assert react.act_out("Give me a thumbs up.") == "thumbsUp"
    assert react.act_out("Put your sunglasses on and look cool.") == "cool"


def test_mentions_and_other_requests_are_not_act_outs():
    assert react.act_out("I've got kendo practice tonight.") is None
    assert react.act_out("Can you strike that from the list?") is None
    assert react.act_out("Can you play some music?") is None
    assert react.act_out("What's the date?") is None


def test_every_tool_prop_is_a_registered_prop():
    from tools import REGISTRY

    for tool in REGISTRY.values():
        if tool.cue is not None:
            assert react.prop(tool.cue) is not None, f"{tool.name}: unknown prop {tool.cue}"
    assert REGISTRY["capture_screen"].cue == "magnifier"
    assert REGISTRY["get_time"].cue == "clock"
    assert REGISTRY["media_next"].cue == "headphones"
    assert REGISTRY["read_and_summarize"].cue == "reading"


def test_props_are_never_offered_to_the_model():
    catalogue = react.catalogue()
    for name in react.PROPS:
        assert react.resolve(name) is None
        assert f"- {name} " not in catalogue
    for name in react.ALL:
        assert f"- {name} - " in catalogue


def test_a_new_registry_entry_needs_no_code():
    # every kind the model can write resolves straight from the registry
    assert react.resolve("surprised").kind == "expression"
    assert react.resolve("shrug").kind == "gesture"
    assert react.resolve("kendo").kind == "scene"
    assert react.resolve("excited").speed > 1 > react.resolve("sad").speed
    assert react.resolve("wave").speed == 1.0
