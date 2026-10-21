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
    assert react.act_out("Irene, flinch!") == "flinch"
    assert react.act_out("Cover your head!") == "flinch"
    assert react.act_out("Can you brace yourself?") == "flinch"
    assert react.act_out("Irene, peer over the edge!") == "peerDown"
    assert react.act_out("Can you look down?") == "peerDown"
    assert react.act_out("Peek over the edge for my hands.") == "peerDown"
    assert react.act_out("Irene, measure it!") == "measure"
    assert react.act_out("Show me this big with your hands.") == "measure"
    assert react.act_out("Size it up for me.") == "measure"
    assert react.act_out("Irene, raise the flag!") == "refFlag"
    assert react.act_out("Call the point, shinpan.") == "refFlag"
    assert react.act_out("Irene, lights, camera, action!") == "clapper"
    assert react.act_out("Roll the camera!") == "clapper"
    assert react.act_out("Can you show me the clapperboard?") == "clapper"
    assert react.act_out("Irene, do the talk to the hand!") == "notNow"
    assert react.act_out("Show me a stop sign with your hand.") == "notNow"
    assert react.act_out("Irene, can you shout hajime like a shinpan?") == "hajimeCall"
    assert react.act_out("Do the hajime call!") == "hajimeCall"
    assert react.act_out("Can you time me?") == "stopwatch"
    assert react.act_out("Show me your stopwatch!") == "stopwatch"
    assert react.act_out("Can you bite your nails?") == "nailBite"
    assert react.act_out("Show me how you look nervous") == "nailBite"
    assert react.act_out("Can you dial it down a notch?") == "dialDown"
    assert react.act_out("Can you hum along?") == "humAlong"
    assert react.act_out("Could you hum it for me?") == "humAlong"
    assert react.act_out("Can you go easy on me?") == "dialDown"


def test_mentions_and_other_requests_are_not_act_outs():
    assert react.act_out("I'd flinch too if someone swung a shinai at me.") is None
    assert react.act_out("Cover the news for me.") is None
    assert react.act_out("Don't look down on me.") is None
    assert react.act_out("I peered at the logs all night.") is None
    assert react.act_out("Can you measure my reaction time?") is None
    assert react.act_out("Can you tell me how big the sun is?") is None
    assert react.act_out("Raise the volume a bit.") is None
    assert react.act_out("Call mom later.") is None
    assert react.act_out("Can you show me the action items?") is None
    assert react.act_out("Roll back the update.") is None
    assert react.act_out("Hold that thought, can you check the time?") is None
    assert react.act_out("What does hajime mean?") is None
    assert react.act_out("What time is it?") is None
    assert react.act_out("Are you nervous about the exam?") is None
    assert react.act_out("Can you turn down the volume?") is None
    assert react.act_out("What song am I humming?") is None
    assert react.act_out("Did you go easy on me last game?") is None
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
