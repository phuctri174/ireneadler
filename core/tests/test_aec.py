"""Echo cancellation: her voice out of the mic, his voice kept - on synthetic rooms."""
import numpy as np
import pytest
from scipy.signal import lfilter

from irene.aec import BLOCK, EchoCanceller, Reference

RATE = 16000


def speechy(seconds, seed, f0=160.0):
    """Speech-like: a buzzy voice under a syllable-rate envelope, band-shaped."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    t = np.arange(n) / RATE
    pitch = f0 * (1 + 0.1 * np.sin(2 * np.pi * 0.7 * t + seed))
    buzz = np.sign(np.sin(2 * np.pi * np.cumsum(pitch) / RATE)) * 0.5 + 0.3 * rng.standard_normal(n)
    shaped = lfilter([1, -0.95], [1], lfilter([0.2], [1, -0.8], buzz))
    envelope = np.clip(np.sin(2 * np.pi * 3.5 * t + rng.random() * 6), 0, 1) ** 0.5
    return (0.25 * shaped * envelope / np.abs(shaped).max()).astype(np.float32)


def room(her, delay_s=0.18, gain=0.35, seed=1):
    rng = np.random.default_rng(seed)
    tail = np.exp(-np.arange(4000) / 700.0) * rng.standard_normal(4000)
    rir = np.concatenate([np.zeros(int(delay_s * RATE)), [1.0], 0.35 * tail / np.abs(tail).max()])
    return (np.convolve(her, rir)[: len(her)] * gain).astype(np.float32)


def run(mic, ref):
    aec = EchoCanceller()
    out = np.zeros_like(mic)
    for k in range(len(mic) // BLOCK):
        s = slice(k * BLOCK, (k + 1) * BLOCK)
        out[s] = aec.process(mic[s], ref[s])
    return out, aec


def db(a, b):
    return 10 * np.log10((np.sum(a.astype(np.float64) ** 2) + 1e-12) / (np.sum(b.astype(np.float64) ** 2) + 1e-12))


def test_her_echo_is_taken_out_of_the_mic():
    her = speechy(8.0, seed=2)
    mic = room(her) + np.random.default_rng(9).normal(0, 0.001, len(her)).astype(np.float32)
    out, aec = run(mic, her)
    settled = slice(3 * RATE, 8 * RATE)
    # a buzzy stand-in with nothing else in the room; on his real room (live dump,
    # people talking nearby) the part of the mic that correlates with her dropped
    # from 0.34 to 0.03 at this step size once aligned
    assert db(mic[settled], out[settled]) > 4, "a clear cut of her echo once it has learned the room"
    assert aec.converged


def test_his_voice_survives_while_she_talks():
    her = speechy(9.0, seed=2)
    him = np.zeros_like(her)
    talk = slice(5 * RATE, 7 * RATE)
    him[talk] = speechy(2.0, seed=5, f0=120.0) * 1.5
    mic = room(her) + him
    out, _ = run(mic, her)
    left_of_her = out[talk] - him[talk]
    assert db(him[talk], left_of_her) > 3, "his voice stays clearly above what is left of hers"
    assert np.corrcoef(out[talk], him[talk])[0, 1] > np.corrcoef(mic[talk], him[talk])[0, 1], "cleaner than the raw mic"


def test_silence_from_her_leaves_the_mic_alone():
    mic = speechy(2.0, seed=7)
    out, _ = run(mic, np.zeros_like(mic))
    assert np.allclose(out, mic, atol=1e-6)


def test_the_reference_pairs_blocks_by_sample_count_at_16k():
    ref = Reference(24000)
    tone24 = np.sin(2 * np.pi * 440 * np.arange(24000) / 24000).astype(np.float32)
    for k in range(0, 24000, 1200):  # the Speaker's 50 ms blocks
        ref.push(tone24[k : k + 1200])
    assert ref.written == 16000
    block = ref.read(8000)
    expected = np.sin(2 * np.pi * 440 * (8000 + np.arange(BLOCK)) / 16000)
    assert np.max(np.abs(block - expected)) < 0.05
    assert not ref.read(20000).any(), "not written yet: silence, not garbage"


def test_the_echo_delay_is_measured_from_the_signals():
    from irene.aec import echo_lag

    her = speechy(3.0, seed=4)
    mic = room(her, delay_s=0.12)
    assert echo_lag(mic.astype(np.float64), her.astype(np.float64)) == pytest.approx(0.12, abs=0.004)
    # a reference that runs early (the live bug: the echo came 108 ms BEFORE it)
    early = np.concatenate([her[1728:], np.zeros(1728, np.float32)])
    assert echo_lag(mic.astype(np.float64), early.astype(np.float64)) == pytest.approx(0.12 + 0.108, abs=0.004)


def test_the_aligner_moves_the_echo_to_where_the_canceller_can_reach_it():
    from irene.aec import Aligner

    her = speechy(8.0, seed=4)
    early_by = int(0.108 * RATE)
    mic = room(her, delay_s=0.0)  # her echo, as she played it...
    ref = np.concatenate([np.zeros(early_by, np.float32), her[:-early_by]])  # ...but the reference is 108 ms behind it
    aligner = Aligner(margin_s=0.15)
    moved = False
    for k in range(len(mic) // BLOCK):
        moved = aligner.add(mic[k * BLOCK : (k + 1) * BLOCK], ref[k * BLOCK : (k + 1) * BLOCK]) or moved
    assert moved
    # the echo was 108 ms early; to land it 40 ms in, the reference comes 148 ms later
    assert aligner.margin_s == pytest.approx(0.15 - 0.148, abs=0.006)


def test_the_aligner_ignores_a_room_with_nothing_of_her_in_it():
    from irene.aec import Aligner

    aligner = Aligner(margin_s=0.0)
    noise = np.random.default_rng(1).normal(0, 0.02, 16 * RATE).astype(np.float32)
    her = speechy(16.0, seed=4)
    assert not any(aligner.add(noise[k * BLOCK : (k + 1) * BLOCK], her[k * BLOCK : (k + 1) * BLOCK]) for k in range(len(noise) // BLOCK))
    assert aligner.margin_s == 0.0


def test_a_room_full_of_noise_never_makes_the_mic_worse():
    # live, the canceller ran away on room noise in bins she barely plays in: here
    # her voice is band-limited (nothing above 4 kHz) and the room is loud and busy
    rng = np.random.default_rng(11)
    her = lfilter([0.1] * 10, [1], speechy(12.0, seed=3)).astype(np.float32)
    room_noise = (0.03 * rng.standard_normal(len(her))).astype(np.float32)
    mic = room(her) + room_noise
    out, aec = run(mic, her)
    for k in range(0, len(mic) - BLOCK, BLOCK):
        m, o = mic[k : k + BLOCK], out[k : k + BLOCK]
        assert np.all(np.isfinite(o))
        assert (o @ o) <= 4.0 * (m @ m) + 1e-6, f"block {k // BLOCK} came out louder than it went in"
    assert np.sqrt(np.mean(out ** 2)) < 2 * np.sqrt(np.mean(mic ** 2))
