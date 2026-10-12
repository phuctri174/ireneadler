import random
from collections import Counter

import numpy as np

from irene import entrances, sfx


def test_registry_is_complete_and_its_effects_exist():
    entries = entrances.load_registry()
    names = [e["name"] for e in entries]
    for want in ("domain_expansion", "chess", "kendo", "energy_wave", "cards", "victorian"):
        assert want in names
    # cut for not reaching the domain expansion's bar (2026-10-05)
    for gone in ("web_swing", "run_in", "pop_in", "robo_pet", "gaming"):
        assert gone not in names
    for e in entries:
        assert e["line"].strip()
        assert e["doing"].strip()
        if e["name"] != entrances.DOMAIN:
            assert 5500 <= e["ms"] <= 6500, f"{e['name']}: as long as the domain expansion (5.8 s)"
            assert 0 <= e["voice_at"] < e["ms"] / 1000
    domain = next(e for e in entries if e["name"] == entrances.DOMAIN)
    assert domain["line"] == "DOMAIN EXPANSION: IRENE ADLER IS COMING!!!"


def test_never_the_same_entrance_twice_running_and_the_signature_weighted_highest():
    entries = entrances.load_registry()
    picker = entrances.Picker(entries, random.Random(3))
    picks = [picker.pick()["name"] for _ in range(5000)]
    assert all(a != b for a, b in zip(picks, picks[1:]))
    counts = Counter(picks)
    assert set(counts) == {e["name"] for e in entries if e.get("weight", 1) > 0}  # every one comes up
    assert "victorian" not in counts, "the Victorian lady comes only when he says 'Irene Adler'"
    # domain expansion, the signature, the most often of all - for real, with the
    # repeat rule taking its share; then kendo and chess; then the rest
    assert counts[entrances.DOMAIN] > 1.3 * max(counts["kendo"], counts["chess"]), counts
    assert min(counts["kendo"], counts["chess"]) > 2 * max(counts["energy_wave"], counts["cards"]), counts


def test_the_real_distribution_matches_the_configured_odds():
    """20,000 picks through the app's Picker land on the long-run shares the weights
    and the repeat rule imply (scripts/entrance_odds.py) - and a weight edited in the
    config applies to the next pick, no restart."""
    import json
    import shutil
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from entrance_odds import expected, simulate

    entries = entrances.load_registry()
    weights, picking = entrances.load_odds()
    exp, sim = expected(weights, picking), simulate(entries)
    for name, share in exp.items():
        assert abs(sim.get(name, 0) - share) < 0.012, (name, share, sim.get(name))
    assert max(exp, key=exp.get) == entrances.DOMAIN


def test_weights_are_read_live_and_every_draw_says_why(tmp_path):
    import json

    raw = json.loads(entrances.REGISTRY.read_text(encoding="utf-8"))
    path = tmp_path / "entrances.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    entries = entrances.load_registry(path)
    picker = entrances.Picker(entries, random.Random(1), live=True, path=path)
    picker.pick()
    assert "weight" in picker.why and "p=" in picker.why
    # only kendo left in the draw: every pick is kendo (the repeat rule gives way
    # when nothing else is left)
    for e in raw["entrances"]:
        e["weight"] = 1.0 if e["name"] == "kendo" else 0
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert {picker.pick()["name"] for _ in range(20)} == {"kendo"}
    # may_repeat: domain expansion alone may come twice running
    for e in raw["entrances"]:
        e["weight"] = {"domain_expansion": 50.0, "kendo": 1.0}.get(e["name"], 0)
    raw["picking"] = {"no_repeat": True, "may_repeat": ["domain_expansion"]}
    path.write_text(json.dumps(raw), encoding="utf-8")
    picks = [picker.pick()["name"] for _ in range(60)]
    assert any(a == b == "domain_expansion" for a, b in zip(picks, picks[1:]))


def test_every_effect_renders_short_finite_and_normalised():
    rng = np.random.default_rng(1)
    for name in sfx.EFFECTS:
        x = sfx.render(name, rng, 0.5)
        assert x.dtype == np.float32 and 0 < len(x) < 3 * 24000, name
        assert np.all(np.isfinite(x)), name
        assert 0.99 <= float(np.max(np.abs(x))) <= 1.0001, name


def test_she_can_say_what_she_was_just_doing():
    entries = entrances.load_registry()
    assert "kendo" in entrances.doing(entries, "kendo")
    assert entrances.doing(entries, "cards").startswith("rehearsing a card trick")
    assert entrances.doing(entries, None) is None
    assert entrances.doing(entries, "no_such_entrance") is None


def test_a_changed_entry_gets_a_new_cache_key():
    entry = next(e for e in entrances.load_registry() if e["name"] == "chess")
    assert entrances.key_of(entry) != entrances.key_of({**entry, "line": "Check."})
    assert entrances.key_of(entry, "turbo") != entrances.key_of(entry, "kokoro")


def fake_voice(text, speed=1.0):
    """A voice stand-in: a 0.8 s tone per line."""
    return 0.3 * np.sin(np.arange(int(0.8 * 24000 / speed)) / 24000 * 2 * np.pi * 220).astype(np.float32)


def test_a_rendered_clip_fits_its_animation_and_keeps_the_voice_on_time():
    for entry in entrances.load_registry():
        if entry["name"] == entrances.DOMAIN:
            continue
        mix, stem = entrances.render(fake_voice, entry)
        seconds = len(mix) / 24000
        assert seconds <= entrances.MAX_SECONDS, f"{entry['name']}: {seconds:.2f}s"
        loud = np.flatnonzero(np.abs(stem) > 0.05)
        assert abs(loud[0] / 24000 - entry["voice_at"]) < 0.05, entry["name"]
        assert float(np.max(np.abs(mix))) <= 0.99


def test_a_cue_sound_mixes_softly_under_the_start_of_a_sentence():
    from irene.react import resolve
    from irene.tts import SFX_LEAD_S, mix_under

    assert resolve("giggle").sfx == "giggle" and resolve("surprised").sfx == "gasp" and resolve("wave").sfx is None
    voice = np.zeros(24000, np.float32)
    out = mix_under(voice, sfx.render("gasp", np.random.default_rng(0)))
    lead = int(SFX_LEAD_S * 24000)
    assert np.all(out[:lead] == 0) and 0 < np.max(np.abs(out)) <= 0.15
    assert len(mix_under(np.zeros(100, np.float32), np.ones(500, np.float32))) >= 500 + lead
