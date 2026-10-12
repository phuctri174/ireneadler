from irene.reply import MAX_SPOKEN_WORDS, cap_words, parse_reply


def test_splits_speak_and_display():
    r = parse_reply("<speak>Four files, sir.</speak>\n<display>\na.pdf  9 MB\nb.pdf  2 MB\n</display>")
    assert r.speak == "Four files, sir."
    assert "a.pdf" in r.display and "a.pdf" not in r.speak


def test_display_never_spoken():
    r = parse_reply("<display>C:\\secret\\path.txt</display>")
    assert r.speak == ""
    assert r.display == "C:\\secret\\path.txt"


def test_untagged_text_is_display_not_speech():
    r = parse_reply("Sure, here you go.")
    assert r.speak == ""
    assert r.display == "Sure, here you go."


def test_multiple_speak_blocks_join():
    r = parse_reply("<speak>One.</speak><display>x</display><speak>Two.</speak>")
    assert r.speak == "One. Two."


def test_speech_capped_at_sentence():
    long = " ".join(["This is a sentence of eight words here."] * 10)
    capped = cap_words(long)
    assert len(capped.split()) <= MAX_SPOKEN_WORDS
    assert capped.endswith(".")


def test_speech_capped_without_sentence_end():
    capped = cap_words(" ".join(["word"] * (MAX_SPOKEN_WORDS + 40)))
    assert len(capped.split()) == MAX_SPOKEN_WORDS
    assert capped.endswith("…")


def test_react_parsed_and_stripped():
    r = parse_reply("<react>thumbsUp</react><speak>Done, sir.</speak>")
    assert r.react and r.react.name == "thumbsUp" and r.react.kind == "gesture"
    assert r.speak == "Done, sir." and "react" not in r.display


def test_react_names_are_forgiving():
    assert parse_reply("<react>Thumbs Up</react><speak>x</speak>").react.name == "thumbsUp"
    assert parse_reply("<react>heart-hands</react><speak>x</speak>").react.name == "heartHands"


def test_react_kinds():
    assert parse_reply("<react>concerned</react><speak>x</speak>").react.kind == "expression"
    assert parse_reply("<react>kendo</react><speak>x</speak>").react.kind == "scene"


def test_unknown_or_missing_react_is_no_reaction():
    assert parse_reply("<react>backflip</react><speak>Hi.</speak>").react is None
    assert parse_reply("<react></react><speak>Hi.</speak>").react is None
    assert parse_reply("<speak>Hi.</speak>").react is None
    assert parse_reply("<react>backflip</react><speak>Hi.</speak>").speak == "Hi."


def test_react_never_spoken():
    r = parse_reply("<speak>Well <react>giggle</react> thank you.</speak>")
    assert "giggle" not in r.speak and r.react.name == "giggle"


def test_stage_directions_are_dropped():
    r = parse_reply("<speak>Men! Ha!</speak>\n<display>\n(Irene performs a kendo strike.)\n[image of a board]\nreal line\n</display>")
    assert r.display == "real line"
    assert parse_reply("<display>(Irene waves)</display>").display == ""


def test_asterisks_never_reach_speech():
    assert parse_reply("<speak>It depends what you want to *do*.</speak>").speak == "It depends what you want to do."


def test_third_person_self_narration_is_dropped():
    assert parse_reply("<display>\nIrene waves.\nIrene shakes her head playfully.\n</display>").display == ""
    assert parse_reply("<display>Irene's disk is 80% full</display>").display == "Irene's disk is 80% full"


def test_a_speak_inside_a_speak_is_dropped_so_history_does_not_teach_it():
    from irene.reply import parse_reply, unnest

    raw = "<speak><cue>thinking</cue>Hmm, good one. <speak>The Sicilian, sir.</speak><display>x</display>"
    assert unnest(raw) == "<speak><cue>thinking</cue>Hmm, good one. The Sicilian, sir.</speak><display>x</display>"
    assert "<speak>" not in parse_reply(raw).speak
    assert unnest("<speak>A.</speak> <speak>B.</speak>") == "<speak>A.</speak> <speak>B.</speak>"
