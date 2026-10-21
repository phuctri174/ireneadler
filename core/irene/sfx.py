# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Short procedural sound effects: the summon entrances' foley and the little sounds
under her reactions. Pure numpy, no sample files - each effect is a function of a
seeded generator (and, for the stretchy ones, a duration), returning float32 at
the TTS sample rate, peak-normalised; the caller sets the level.

    render(name, rng, dur=None) -> np.ndarray
"""
from __future__ import annotations

from typing import Callable

import numpy as np

from .summon_fx import SR, chime, highpass, lowpass, whoosh as riser

TAU = 2 * np.pi


def _t(seconds: float) -> np.ndarray:
    return np.arange(int(seconds * SR)) / SR


def _norm(x: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    return (x / peak).astype(np.float32) if peak > 1e-9 else x.astype(np.float32)


def _band(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return lowpass(highpass(x, lo, 2), hi, 2)


def _place(out: np.ndarray, x: np.ndarray, start: int) -> None:
    """Mix `x` into `out` at `start`, clipped to fit."""
    end = min(len(out), start + len(x))
    if end > start:
        out[start:end] += x[: end - start]


def _sweep(f0: float, f1: float, seconds: float, shape: float = 1.0) -> np.ndarray:
    """Phase of a tone gliding f0 -> f1 over `seconds` (geometric, curved by `shape`)."""
    t = _t(seconds)
    progress = (t / max(seconds, 1e-6)) ** shape
    freq = f0 * (f1 / f0) ** progress
    return TAU * np.cumsum(freq) / SR


def click(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """A wooden piece set down on a board: a hard knock with a short hollow ring."""
    t = _t(0.16)
    knock = rng.standard_normal(len(t)) * np.exp(-t * 90)
    body = np.sin(TAU * 820 * t) * np.exp(-t * 38) + 0.5 * np.sin(TAU * 1370 * t) * np.exp(-t * 55)
    return _norm(_band(knock, 400, 5000) * 0.8 + body)


def swish(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """A shinai or a card cutting the air: band noise sweeping down, fast."""
    seconds = dur or 0.22
    t = _t(seconds)
    noise = rng.standard_normal(len(t))
    lo = _band(noise, 300, 1500)
    hi = _band(noise, 1800, 7000)
    p = t / seconds
    env = np.sin(np.pi * np.clip(p, 0, 1)) ** 1.5
    return _norm((hi * (1 - p) + lo * p) * env)


def thwack(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """Bamboo on a men: a dry crack over a short low thump."""
    t = _t(0.25)
    crack = _band(rng.standard_normal(len(t)), 1200, 8000) * np.exp(-t * 70)
    thump = np.sin(_sweep(180, 70, 0.25)) * np.exp(-t * 22)
    return _norm(crack * 1.2 + thump * 0.8)


def thwip(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """A line shooting out: a quick rising zip with a bright tail."""
    seconds = 0.2
    t = _t(seconds)
    zip_ = np.sin(_sweep(500, 3500, seconds, 0.6)) * np.exp(-t * 9)
    hiss = _band(rng.standard_normal(len(t)), 3000, 9000) * np.exp(-t * 18) * 0.5
    return _norm(zip_ + hiss)


def whoosh(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """Swinging past: air rising and falling away."""
    seconds = dur or 0.8
    up = riser(seconds * 0.6, rng)
    t = _t(seconds * 0.4)
    down = _band(rng.standard_normal(len(t)), 400, 3000) * np.exp(-t * 7)
    return _norm(np.concatenate([up, down * np.max(np.abs(up))]))


def thud(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """Landing: a soft low bump and a scuff."""
    t = _t(0.3)
    bump = np.sin(_sweep(110, 45, 0.3)) * np.exp(-t * 14)
    scuff = _band(rng.standard_normal(len(t)), 500, 3000) * np.exp(-t * 30) * 0.4
    return _norm(bump + scuff)


def charge(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """Energy gathering: a buzzing tone climbing in pitch and wobbling faster, with crackle."""
    seconds = dur or 1.0
    t = _t(seconds)
    p = t / seconds
    phase = _sweep(90, 420, seconds, 1.4)
    wobble = 1 + 0.35 * np.sin(TAU * np.cumsum(4 + 20 * p) / SR)
    tone = (np.sin(phase) + 0.4 * np.sin(2 * phase) + 0.2 * np.sin(3 * phase)) * wobble
    crackle = (rng.random(len(t)) < 0.004 + 0.02 * p) * rng.standard_normal(len(t))
    crackle = _band(crackle, 2000, 9000)
    return _norm((tone * 0.7 + crackle * 0.6) * p**1.3)


def beam(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """The blast: a low boom under a roaring, slowly darkening rush."""
    seconds = dur or 0.7
    t = _t(seconds)
    rush = lowpass(rng.standard_normal(len(t)), 3500, 2) * np.exp(-t * 2.5)
    boom = np.sin(_sweep(90, 35, seconds)) * np.exp(-t * 5)
    attack = np.minimum(1, t / 0.01)
    return _norm((rush * 0.8 + boom) * attack)


def paper(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """A sheet of paper dealt onto a desk: the air under it rushing out (a soft
    falling hiss), the flat slap as it lands, a dry rustle as it settles."""
    out = np.zeros(int(0.42 * SR), np.float32)
    ta = _t(0.16)
    air = _band(rng.standard_normal(len(ta)), 900, 6000) * np.sin(np.pi * ta / 0.16) ** 2
    air = lowpass(air * np.linspace(1.0, 0.4, len(ta)), 3500, 2)
    _place(out, 0.35 * air.astype(np.float32), 0)
    ts = _t(0.09)
    slap = _band(rng.standard_normal(len(ts)), 1200, 7000) * np.exp(-ts * 70)
    body = np.sin(TAU * 180 * ts) * np.exp(-ts * 60)
    _place(out, (slap + 0.35 * body).astype(np.float32), int(0.15 * SR))
    tr = _t(0.18)
    rustle = _band(rng.standard_normal(len(tr)), 2500, 9000) * np.exp(-tr * 22) * (0.6 + 0.4 * np.sign(np.sin(TAU * 38 * tr)))
    _place(out, 0.18 * rustle.astype(np.float32), int(0.2 * SR))
    return _norm(out)


def dust(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """Dusting off her hands: two soft pats."""
    out = np.zeros(int(0.45 * SR), np.float32)
    for k, at in enumerate((0.0, 0.2)):
        t = _t(0.12)
        pat = _band(rng.standard_normal(len(t)), 600, 4000) * np.exp(-t * 45) * (1 - 0.3 * k)
        start = int(at * SR)
        _place(out, pat, start)
    return _norm(out)


def footsteps(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """Running: quick soft steps, closing in (getting louder)."""
    seconds = dur or 1.0
    out = np.zeros(int(seconds * SR) + int(0.1 * SR), np.float32)
    at, gap, k = 0.0, 0.13, 0
    while at < seconds:
        t = _t(0.08)
        step = np.sin(_sweep(140, 60, 0.08)) * np.exp(-t * 50) + _band(rng.standard_normal(len(t)), 800, 4000) * np.exp(-t * 80) * 0.5
        start = int(at * SR)
        _place(out, step * (0.35 + 0.65 * at / seconds), start)
        at += gap * (0.93 + 0.14 * rng.random())
        k += 1
    return _norm(out)


def skid(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """Sliding to a stop: a squeak gliding down over scraping noise."""
    seconds = dur or 0.45
    t = _t(seconds)
    p = t / seconds
    squeak = np.sin(_sweep(1900, 700, seconds)) * (1 - p) ** 1.2
    scrape = _band(rng.standard_normal(len(t)), 1500, 6000) * (1 - p) * 0.6
    return _norm(squeak * 0.5 + scrape)


def riffle(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """A shuffle: a burst of tiny card flicks."""
    seconds = dur or 0.8
    out = np.zeros(int(seconds * SR) + int(0.05 * SR), np.float32)
    n = int(seconds * 55)
    for k in range(n):
        at = seconds * (k / n) ** 0.9
        t = _t(0.012)
        flick = _band(rng.standard_normal(len(t)), 2500, 9000) * np.exp(-t * 400)
        start = int(at * SR)
        _place(out, flick * (0.6 + 0.4 * rng.random()), start)
    return _norm(out)


def ding(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """The reveal: two bright bell notes."""
    return _norm(chime(2, rng)[: int(0.9 * SR)])


def sparkle(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """A quick shimmer of high bells."""
    return _norm(chime(4, rng)[: int(0.8 * SR)])


def rattle(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """Something inside a box, wanting out: quick knocks."""
    seconds = dur or 0.5
    out = np.zeros(int(seconds * SR) + int(0.1 * SR), np.float32)
    for at in np.arange(0, seconds, 0.075):
        k = click(rng) * (0.5 + 0.5 * rng.random())
        start = int(at * SR)
        _place(out, lowpass(k, 2500), start)
    return _norm(out)


def pop(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """Bursting out: a round pop gliding up, cork-like."""
    t = _t(0.18)
    body = np.sin(_sweep(220, 900, 0.18, 0.5)) * np.exp(-t * 22)
    puff = _band(rng.standard_normal(len(t)), 300, 3000) * np.exp(-t * 60) * 0.6
    return _norm(body + puff)


def glitch(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """Pixels settling: bit-crushed stutters of square tones and noise."""
    seconds = dur or 0.4
    out = np.zeros(int(seconds * SR), np.float32)
    at = 0.0
    while at < seconds:
        length = 0.02 + 0.05 * rng.random()
        t = _t(length)
        freq = rng.choice([220, 330, 440, 660, 880, 1320])
        chunk = np.sign(np.sin(TAU * freq * t)) if rng.random() < 0.6 else rng.standard_normal(len(t))
        chunk = np.round(chunk * 4) / 4  # crushed
        start = int(at * SR)
        end = min(len(out), start + len(chunk))
        out[start:end] += chunk[: end - start] * (1 - at / seconds * 0.6)
        at += length + 0.01 * rng.random()
    return _norm(lowpass(out, 6000))


def beep(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """A small robot: two square-ish blips."""
    out = np.zeros(int(0.22 * SR), np.float32)
    for at, f in ((0.0, 1200), (0.1, 1600)):
        t = _t(0.07)
        blip = np.tanh(3 * np.sin(TAU * f * t)) * np.minimum(1, (0.07 - t) / 0.01)
        start = int(at * SR)
        _place(out, blip, start)
    return _norm(lowpass(out, 5000))


def boing(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """A bouncing ball: a springy tone bending up with a wobble."""
    seconds = 0.3
    t = _t(seconds)
    phase = _sweep(160, 520, seconds, 0.4) + 0.6 * np.sin(TAU * 18 * t)
    return _norm(np.sin(phase) * np.exp(-t * 9))


def chirp(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """A happy robot pet: a quick rising-falling trill."""
    seconds = 0.28
    t = _t(seconds)
    p = t / seconds
    freq = 1100 + 900 * np.sin(np.pi * p) + 150 * np.sin(TAU * 30 * t)
    tone = np.tanh(2 * np.sin(TAU * np.cumsum(freq) / SR))
    return _norm(lowpass(tone * np.sin(np.pi * p), 6000))


# ---- entrance voices and props ---------------------------------------------------


def _vowel(seconds: float, f0: float, f1: float, formants: tuple[tuple[float, float], ...], rng: np.random.Generator) -> np.ndarray:
    """A shouted vowel: a buzzy glottal tone gliding f0 -> f1, shaped by formants.
    Not speech - just enough of a voice to read as a person making the sound."""
    t = _t(seconds)
    phase = _sweep(f0, f1, seconds)
    # a sawtooth-ish glottal source: harmonics falling off slowly, so it carries
    source = sum(np.sin(k * phase) / k for k in range(1, 14))
    source += _band(rng.standard_normal(len(t)), 200, 4000) * 0.12  # breath
    return sum(_band(source, lo, hi) * gain for (lo, hi), gain in zip(formants, (1.0, 0.6, 0.3)))


def kiai(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """The kendo shout that goes with the cut: a hard "MEN!" - a bright open vowel,
    thrown out and cut off short."""
    seconds = dur or 0.42
    t = _t(seconds)
    p = t / seconds
    voice = _vowel(seconds, 330, 250, ((500, 900), (1300, 1900), (2400, 3200)), rng)
    # a shout: instant attack, held, then clipped off
    env = np.minimum(1, p / 0.02) * np.minimum(1, (1 - p) / 0.18) * (1 - 0.3 * p)
    return _norm(np.tanh(voice * 2.2) * env)


def clock_tap(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """A chess clock's button: a firm plastic tap, then the lever's small ping."""
    out = np.zeros(int(0.3 * SR), np.float32)
    t = _t(0.1)
    tap = _band(rng.standard_normal(len(t)), 700, 5000) * np.exp(-t * 60)
    tap += np.sin(TAU * 300 * t) * np.exp(-t * 45) * 0.5
    _place(out, tap, 0)
    ping = _t(0.2)
    _place(out, np.sin(TAU * 2100 * ping) * np.exp(-ping * 26) * 0.35, int(0.035 * SR))
    return _norm(out)


def bark(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """The pet, pleased to see him: one bright "ruff" - a vowel that opens and shuts."""
    seconds = 0.2
    t = _t(seconds)
    p = t / seconds
    voice = _vowel(seconds, 420, 300, ((400, 800), (1100, 1700), (2200, 3000)), rng)
    env = np.minimum(1, p / 0.015) * np.exp(-p * 5.5) * (1 - 0.5 * p)
    return _norm(np.tanh(voice * 1.8) * env)


def meow(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """Or a cat, if that's the mood: a thin cry bending up then down."""
    seconds = dur or 0.5
    t = _t(seconds)
    p = t / seconds
    # up over the first third, down for the rest - the shape of a meow
    freq = np.where(p < 0.33, 500 + 320 * (p / 0.33), 820 - 400 * ((p - 0.33) / 0.67))
    phase = TAU * np.cumsum(freq) / SR
    source = sum(np.sin(k * phase) / k for k in range(1, 9))
    voice = _band(source, 600, 1400) + _band(source, 1800, 2800) * 0.4
    return _norm(voice * np.sin(np.pi * p) ** 0.7)


def mash(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """A controller taking a beating: little plastic clicks, fast and uneven."""
    seconds = dur or 0.9
    out = np.zeros(int(seconds * SR), np.float32)
    at = 0.0
    while at < seconds - 0.04:
        t = _t(0.05)
        tick = _band(rng.standard_normal(len(t)), 1500, 7000) * np.exp(-t * 110)
        tick += np.sin(TAU * (900 + 400 * rng.random()) * t) * np.exp(-t * 90) * 0.4
        _place(out, tick * (0.6 + 0.4 * rng.random()), int(at * SR))
        at += 0.055 + 0.05 * rng.random()
    return _norm(out)


def game_over(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """She loses: the four-note chiptune sag, square waves falling."""
    out = np.zeros(int(0.85 * SR), np.float32)
    for k, (at, f) in enumerate(((0.0, 523.0), (0.16, 440.0), (0.32, 349.0), (0.48, 262.0))):
        t = _t(0.34)
        square = np.sign(np.sin(TAU * f * t)) * 0.5
        _place(out, square * np.exp(-t * 6) * (1 - 0.12 * k), int(at * SR))
    return _norm(lowpass(out, 4500, 2))


def fire(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """The little flame on her head: a soft crackling hiss with pops in it."""
    seconds = dur or 0.8
    t = _t(seconds)
    p = t / seconds
    hiss = _band(rng.standard_normal(len(t)), 700, 6000)
    # wandering intensity, so it flickers rather than sits there
    flicker = 0.6 + 0.4 * np.sin(TAU * np.cumsum(7 + 5 * rng.random(len(t))) / SR)
    pops = (rng.random(len(t)) < 0.0025) * rng.standard_normal(len(t))
    pops = _band(pops, 300, 2500) * 2.5
    env = np.minimum(1, p / 0.08) * np.minimum(1, (1 - p) / 0.25)
    return _norm((hiss * flicker * 0.7 + pops) * env)


# ---- reactions (under her voice) ------------------------------------------------


def giggle(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """Not a laugh track: three tiny rising bubbles, the sound of a giggle."""
    out = np.zeros(int(0.42 * SR), np.float32)
    for k in range(3):
        t = _t(0.09)
        bubble = np.sin(_sweep(700 + 120 * k, 1300 + 150 * k, 0.09, 0.5)) * np.sin(np.pi * t / 0.09)
        start = int(k * 0.11 * SR)
        _place(out, bubble * (1 - 0.15 * k), start)
    return _norm(out)


def gasp(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """Surprise: a quick breathy intake - filtered noise swelling up and cut short."""
    seconds = 0.22
    t = _t(seconds)
    p = t / seconds
    air = _band(rng.standard_normal(len(t)), 900, 5000)
    return _norm(air * p**1.5 * np.minimum(1, (1 - p) / 0.1))


def sigh(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """Sympathy: a slow soft exhale, darkening as it falls."""
    seconds = 0.7
    t = _t(seconds)
    p = t / seconds
    air = rng.standard_normal(len(t))
    bright = _band(air, 400, 3000)
    dark = _band(air, 200, 1200)
    env = np.sin(np.pi * np.minimum(1, p * 1.6)) * (1 - p) ** 0.6
    return _norm((bright * (1 - p) + dark * p) * env)


def huff(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """Indignation: a short hard snort out through the nose - two dark puffs, the
    second bigger, like a bull about to charge."""
    out = np.zeros(int(0.5 * SR))
    for start, seconds, gain in ((0.0, 0.12, 0.6), (0.16, 0.24, 1.0)):
        t = _t(seconds)
        p = t / seconds
        air = _band(rng.standard_normal(len(t)), 150, 1400)
        _place(out, air * np.minimum(1, p / 0.08) * (1 - p) ** 1.4 * gain, int(start * SR))
    return _norm(out)


def flags(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """Shinpan flags going up for an ippon: each a cloth flag snapped up through the
    air - a rising whoosh with the cloth's flutter in it - one after another."""
    out = np.zeros(int(0.75 * SR))
    for k, start in enumerate((0.0, 0.14, 0.28)):
        seconds = 0.3
        t = _t(seconds)
        p = t / seconds
        air = _band(rng.standard_normal(len(t)), 500 + 300 * p.mean(), 4200)
        flutter = 0.6 + 0.4 * np.sign(np.sin(2 * np.pi * (38 + 6 * k) * t))
        env = np.sin(np.pi * np.minimum(1, p * 1.3)) * (1 - p) ** 0.5
        _place(out, air * flutter * env * (0.9 - 0.15 * k), int(start * SR))
    return _norm(out)


def whimper(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """Sulking: a small two-note complaint, falling, nose half in it. The sound of
    "huhu" - put out rather than actually hurt."""
    seconds = dur or 0.55
    out = np.zeros(int(seconds * SR), np.float32)
    for k, (at, f0, f1) in enumerate(((0.0, 430.0, 360.0), (0.26, 380.0, 290.0))):
        span = 0.24
        t = _t(span)
        phase = _sweep(f0, f1, span)
        # a nasal vowel: the low harmonics only, so it sounds closed-mouthed
        voice = sum(np.sin(n * phase) / n for n in range(1, 7))
        voice = _band(voice, 250, 1100) + _band(voice, 1400, 2200) * 0.25
        _place(out, voice * np.sin(np.pi * t / span) ** 0.8 * (1 - 0.25 * k), int(at * SR))
    return _norm(out)


def wail(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """Sobbing, loud and pathetic: a long "waaah" that climbs, cracks and sags with
    a sob shaking through it, a ragged catch of breath, then "ah-aaah" falling away."""
    seconds = dur or 1.75
    out = np.zeros(int(seconds * SR), np.float32)
    open_a = ((650, 1150), (1100, 1600), (2300, 3100))

    def cry(span: float, f0: float, peak: float, f1: float, sob_hz: float) -> np.ndarray:
        t = _t(span)
        p = t / span
        # up to the peak in the first third, then sagging down: the crack of a wail
        contour = np.where(p < 0.3, f0 * (peak / f0) ** (p / 0.3), peak * (f1 / peak) ** ((p - 0.3) / 0.7))
        # the sob: pitch and loudness shaking together
        shake = np.sin(TAU * sob_hz * t)
        freq = contour * (1 + 0.035 * shake)
        phase = TAU * np.cumsum(freq) / SR
        source = sum(np.sin(k * phase) / k**0.9 for k in range(1, 16))
        source += _band(rng.standard_normal(len(t)), 300, 5000) * 0.25  # wet, breathy
        voice = sum(_band(source, lo, hi) * g for (lo, hi), g in zip(open_a, (1.0, 0.7, 0.35)))
        env = np.minimum(1, p / 0.06) * np.minimum(1, (1 - p) / 0.2) * (0.75 + 0.25 * shake)
        return np.tanh(voice * 1.8) * env

    _place(out, cry(0.85, 420, 640, 380, 7.0), 0)
    # the catch: a sharp ragged inhale
    t = _t(0.16)
    air = _band(rng.standard_normal(len(t)), 1200, 6000) * (t / 0.16) ** 1.2 * np.minimum(1, (0.16 - t) / 0.03)
    _place(out, 0.5 * air, int(0.9 * SR))
    _place(out, 0.8 * cry(0.2, 470, 540, 430, 9.0), int(1.08 * SR))
    _place(out, 0.75 * cry(0.45, 500, 560, 330, 6.0), int(1.3 * SR))
    return _norm(out)


def tada(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """A job done: a short bright rising two-note flourish."""
    out = np.zeros(int(0.5 * SR), np.float32)
    for at, f in ((0.0, 784.0), (0.09, 1175.0)):
        t = _t(0.4 - at)
        note = (np.sin(TAU * f * t) + 0.3 * np.sin(TAU * 2 * f * t)) * np.exp(-t * 7)
        start = int(at * SR)
        _place(out, note, start)
    return _norm(out)


def boop(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """A soft 'hm?' for curiosity: one round tone bending up a little."""
    t = _t(0.16)
    return _norm(np.sin(_sweep(520, 700, 0.16)) * np.sin(np.pi * t / 0.16))


def carriage_bell(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """A carriage pulling up: a small brass hand-bell rung three times - bright,
    slightly inharmonic partials with a long shimmer - over two soft hoof clops."""
    out = np.zeros(int(1.6 * SR), np.float32)
    t = _t(1.1)
    for k, at in enumerate((0.0, 0.22, 0.44)):
        f = 1320.0 * (1 + 0.004 * rng.standard_normal())
        partials = sum(a * np.sin(TAU * f * r * t + rng.random() * TAU) for a, r in ((1.0, 1.0), (0.55, 2.76), (0.3, 5.4), (0.2, 8.93)))
        ring = partials * np.exp(-t * (4.5 + k)) * (1.0 - 0.15 * k)
        _place(out, ring.astype(np.float32), int(at * SR))
    for at in (0.9, 1.15):
        clop = lowpass(click(rng), 900) * 0.5
        _place(out, clop, int(at * SR))
    return _norm(out)


# her boot-up's soundtrack, on the HUD's timeline (hud/src/ui/boot.tsx ACT): every
# event below is at the same moment as its picture. Acts: a dark cold start, six
# subsystems coming online, the diagnostic sweep, an implosion and a held beat of
# silence, the name, the panel bursting in, her arrival.
BOOT_S = 12.0
BOOT_FLICKER_S = (0.3, 0.42, 0.5)          # the first point of light, stuttering
BOOT_LINE_S = 0.65                        # the CRT line opening
BOOT_SYSTEMS_S = tuple(1.1 + 0.4 * k for k in range(6))   # each subsystem lands
BOOT_SWEEP_S = (3.7, 4.6)                 # the diagnostic sweeps
BOOT_ORDER_S = 5.3                        # the swarm locks into order
BOOT_COLLAPSE_S = 5.6                     # everything implodes...
BOOT_SILENCE_S = 6.0                      # ... a flash, then held darkness
BOOT_HEART_S = 6.5                        # one pulse in the dark
BOOT_LETTERS_S = tuple(6.9 + 0.3 * k for k in range(5))  # I R E N E, each typing its word
BOOT_FOLD_S = 9.3                         # the words fold back into IRENE
BOOT_LETTER_NOTES = (523.25, 659.25, 783.99, 880.0, 1046.5)  # C5 E5 G5 A5 C6 - rising
BOOT_ADLER_S = 9.75                       # ... ADLER: the biggest hit so far
# THE PANEL's own startup (hud Dashboard.css), its acts on her clock
PANEL_COLD_S = 0.0                        # a line swells, the picture opens (to 1.2)
PANEL_DRAFT_S = (1.3, 1.45, 1.6, 1.85, 2.3, 2.45)   # card frames drafted
PANEL_RULER_S = (1.7, 1.9, 2.2, 2.45)               # rulers, dimension lines
PANEL_NOTES_S = (2.7, 2.95, 3.15)                   # margin notes write in
PANEL_CASCADE_S = (3.5, 3.6, 3.7, 3.75, 3.95, 4.55) # self-test: parts come alive
PANEL_GAUGES_S = (3.85, 4.05, 4.15, 4.25, 4.35)     # gauges swing to full scale
PANEL_SIGNAL_S = 6.0                      # the ticker out of noise, the boot log
PANEL_FILLS_S = (7.4, 7.5, 7.75, 8.0, 8.25, 8.55, 8.85, 9.15, 9.35)  # cards fill
PANEL_THUMBS_S = (8.75, 8.9, 9.05, 9.2)             # thumbnails come into focus
PANEL_CLAMPS_S = (10.0, 10.07, 10.14, 10.21, 10.3)  # brackets seat in the corners
PANEL_BEAM_S = 10.15                      # her beam crosses the panel
BOOT_FLARE_S = 11.6                       # her arrival: the last flash


def boot(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """Her boot-up, act by act: a low hum and crackles in the dark, a click-thump and
    a rising tick as each subsystem lands, whooshing sweeps and a chatter of data, a
    reversed rush as everything implodes - then nothing, one heartbeat - a rising
    note per letter of IRENE with an impact and a chatter of keys as its word types
    out, a falling sweep as the words fold, a huge chord and impact for ADLER,
    the panel's CRT (a thunk, a rising whine, static resolving), and a final impact with a shimmer as she arrives."""
    length = dur or BOOT_S
    t = _t(length)
    out = np.zeros(len(t), np.float32)

    # the hum: swelling from the cold start, gone at the silence, back for the name
    swell = np.clip((t - 0.2) / 1.2, 0, 1) * np.clip((BOOT_SILENCE_S - t) / 0.08, 0, 1)
    back = np.clip((t - BOOT_LETTERS_S[0]) / 0.3, 0, 1) * np.clip((BOOT_FLARE_S + 0.3 - t) / 0.4, 0, 1)
    hum = sum(a * np.sin(TAU * f * t + p) for f, a, p in ((46, 1.0, 0.0), (92, 0.45, 1.1), (138, 0.18, 2.3)))
    out += 0.2 * (swell + 0.7 * back) * hum * (1 + 0.08 * np.sin(TAU * 0.7 * t))

    # cold start: crackles at the flickers, a rising whine as the line opens
    for at in BOOT_FLICKER_S:
        crackle = _band(rng.standard_normal(int(0.07 * SR)), 1500, 7000) * np.exp(-np.arange(int(0.07 * SR)) / (0.015 * SR))
        _place(out, 0.45 * crackle, int(at * SR))
    whine = np.sin(_sweep(80, 1600, 0.6, 2.0)) * np.exp(-_t(0.6) / 0.35)
    _place(out, 0.12 * whine.astype(np.float32), int(BOOT_LINE_S * SR))

    # each subsystem lands: a click with a metal ring, a low thump, a rising tick
    for k, at in enumerate(BOOT_SYSTEMS_S):
        ring = np.sin(TAU * (2200 + 180 * k) * _t(0.06)) * np.exp(-_t(0.06) / 0.014)
        _place(out, 0.5 * click(rng), int(at * SR))
        _place(out, 0.16 * ring.astype(np.float32), int(at * SR))
        _place(out, (0.25 + 0.05 * k) * lowpass(thud(rng), 300), int(at * SR))

    # the sweeps: a rushing riser each, and a chatter of data under them
    for at in BOOT_SWEEP_S:
        _place(out, riser(0.85, rng) * 0.32, int(at * SR))
    for k in range(40):
        at = BOOT_SWEEP_S[0] + 0.045 * k
        blip = np.sin(TAU * rng.uniform(1800, 4200) * _t(0.012)) * np.exp(-_t(0.012) / 0.004)
        _place(out, 0.06 * blip.astype(np.float32), int(at * SR))
    # the swarm locking into order: a bright chord stab
    ct = _t(0.5)
    lock = sum(np.sin(TAU * f * ct) for f in (392.0, 587.33, 783.99)) * np.exp(-ct / 0.12)
    _place(out, 0.14 * lock.astype(np.float32), int(BOOT_ORDER_S * SR))

    # the implosion: a reversed rush into the flash, then silence
    rush = riser(BOOT_SILENCE_S - BOOT_COLLAPSE_S, rng)
    _place(out, 0.4 * rush, int(BOOT_COLLAPSE_S * SR))
    _place(out, 0.9 * thud(rng), int(BOOT_SILENCE_S * SR))
    # one heartbeat in the dark
    for dt, g in ((0.0, 0.55), (0.18, 0.35)):
        _place(out, g * lowpass(thud(rng), 160), int((BOOT_HEART_S + dt) * SR))

    # THE NAME: a note per letter (a bell-ish tone, its octave, an impact under it)
    for at, f in zip(BOOT_LETTERS_S, BOOT_LETTER_NOTES):
        nt = _t(0.7)
        note = (np.sin(TAU * f * nt) + 0.35 * np.sin(TAU * 2 * f * nt) + 0.12 * np.sin(TAU * 3 * f * nt)) * np.exp(-nt / 0.2)
        note *= np.clip(nt / 0.004, 0, 1)
        _place(out, 0.4 * note.astype(np.float32), int(at * SR))
        _place(out, 0.5 * lowpass(thud(rng), 400), int(at * SR))
        # its word typing out: a chatter of keys
        for k in range(7):
            blip = np.sin(TAU * rng.uniform(2200, 3600) * _t(0.014)) * np.exp(-_t(0.014) / 0.005)
            _place(out, 0.08 * blip.astype(np.float32), int((at + 0.18 + k * 0.04) * SR))
    # the words fold back: a falling sweep
    fold = np.sin(_sweep(1400, 300, 0.4, 0.8)) * np.exp(-_t(0.4) / 0.22)
    _place(out, 0.22 * fold.astype(np.float32), int(BOOT_FOLD_S * SR))
    # ADLER: a full chord and the biggest impact yet
    ct = _t(1.6)
    chord = sum(np.sin(TAU * f * ct) for f in (261.63, 523.25, 659.25, 783.99, 1046.5)) * np.exp(-ct / 0.6) * np.clip(ct / 0.01, 0, 1)
    _place(out, 0.2 * chord.astype(np.float32), int(BOOT_ADLER_S * SR))
    _place(out, 1.6 * thud(rng), int(BOOT_ADLER_S * SR))

    # THE PANEL'S STARTUP, under hers (quieter, higher, mechanical - so the two
    # never blur: hers is cinema, the panel is a machine running its diagnostic)
    # COLD START - a heavy relay thunk, a flyback whine rising slowly as the line
    # swells, static that clears as the picture opens
    _place(out, 0.8 * lowpass(thud(rng), 200), int(PANEL_COLD_S * SR))
    _place(out, 0.35 * click(rng), int(PANEL_COLD_S * SR))
    wt = _t(1.2)
    whine = np.sin(_sweep(220, 7400, 1.2, 1.4)) * np.clip(wt / 0.3, 0, 1) * np.exp(-np.clip(wt - 0.8, 0, None) / 0.2)
    _place(out, 0.08 * whine.astype(np.float32), int(PANEL_COLD_S * SR))
    st = _t(0.9)
    static = _band(rng.standard_normal(len(st)), 900, 9000) * np.clip(st / 0.2, 0, 1) * np.exp(-st / 0.3)
    _place(out, 0.18 * static.astype(np.float32), int(0.65 * SR))
    # BLUEPRINT - a plotter's pen: a soft scratch as each frame is drafted, ticks
    # running down the rulers, a writing scratch for each margin note
    for at in PANEL_DRAFT_S:
        pt = _t(0.5)
        pen = _band(rng.standard_normal(len(pt)), 2500, 6000) * np.clip(pt / 0.05, 0, 1) * np.exp(-pt / 0.25)
        _place(out, 0.05 * pen.astype(np.float32), int(at * SR))
    for at in PANEL_RULER_S:
        for k in range(8):
            tick = np.sin(TAU * 2600 * _t(0.006)) * np.exp(-_t(0.006) / 0.002)
            _place(out, 0.06 * tick.astype(np.float32), int((at + k * 0.09) * SR))
    for at in PANEL_NOTES_S:
        for k in range(10):
            _place(out, 0.05 * click(rng), int((at + k * 0.06) * SR))
    # SELF-TEST - a relay as each part comes alive, the clock's digits rattling,
    # every gauge's needle swinging up to full scale and back, the crosshair's servo
    for at in PANEL_CASCADE_S:
        _place(out, 0.28 * click(rng), int(at * SR))
    for k in range(20):
        tick = np.sin(TAU * 3200 * _t(0.008)) * np.exp(-_t(0.008) / 0.003)
        _place(out, 0.06 * tick.astype(np.float32), int((3.5 + k * 0.04) * SR))
    for at in PANEL_GAUGES_S:
        up = np.sin(_sweep(320, 1250, 0.5, 0.8))
        down = np.sin(_sweep(1250, 560, 0.7, 1.2))
        needle = np.concatenate([up, down]) * np.exp(-_t(1.2) / 0.55)
        _place(out, 0.055 * needle.astype(np.float32), int(at * SR))
    sv = _t(2.6)
    servo = np.sin(TAU * (180 + 60 * np.sin(TAU * 0.6 * sv)) * sv) * np.clip(sv / 0.25, 0, 1) * np.clip((2.6 - sv) / 0.3, 0, 1)
    _place(out, 0.03 * servo.astype(np.float32), int(3.5 * SR))
    # SIGNAL ACQUISITION - noise that narrows into a tone and locks, the boot log's
    # quick typing with a soft blip for each OK
    nt = _t(1.5)
    noise = rng.standard_normal(len(nt))
    sig = _band(noise, 400, 5000) * np.clip(1.0 - nt / 1.3, 0, 1) + np.sin(TAU * 1320 * nt) * np.clip((nt - 1.0) / 0.3, 0, 1) * np.exp(-np.clip(nt - 1.3, 0, None) / 0.12)
    _place(out, 0.08 * sig.astype(np.float32), int(PANEL_SIGNAL_S * SR))
    for k in range(13):
        at = PANEL_SIGNAL_S + 0.05 + k * 0.085
        for c in range(3):
            _place(out, 0.04 * click(rng), int((at + c * 0.03) * SR))
        bt = _t(0.06)
        blip = np.sin(TAU * 1760 * bt) * np.exp(-bt / 0.02)
        _place(out, 0.05 * blip.astype(np.float32), int((at + 0.15) * SR))
    # MATERIALISE - a soft low thump as each card fills, a chime as the sky opens,
    # a rising focus-whoosh as each thumbnail sharpens, ticks as market rows land
    for at in PANEL_FILLS_S:
        _place(out, 0.22 * lowpass(thud(rng), 300), int(at * SR))
    ct = _t(1.0)
    chime = (np.sin(TAU * 1568 * ct) + 0.5 * np.sin(TAU * 2349 * ct)) * np.exp(-ct / 0.35)
    _place(out, 0.05 * chime.astype(np.float32), int(7.7 * SR))
    for at in PANEL_THUMBS_S:
        ft = _t(0.5)
        focus = np.sin(_sweep(600, 2400, 0.5, 1.5)) * np.clip(ft / 0.1, 0, 1) * np.exp(-ft / 0.2)
        _place(out, 0.04 * focus.astype(np.float32), int(at * SR))
    for k in range(4):
        _place(out, 0.12 * click(rng), int((9.0 + k * 0.11) * SR))
    # LOCK - her beam crossing the panel, metal clamps as the brackets seat, a chord
    # as the badge arrives, the final sweep's long breath
    _place(out, 0.3 * whoosh(rng), int(PANEL_BEAM_S * SR))
    for at in PANEL_CLAMPS_S:
        ring = np.sin(TAU * 1900 * _t(0.12)) * np.exp(-_t(0.12) / 0.03)
        _place(out, 0.4 * click(rng), int(at * SR))
        _place(out, 0.1 * ring.astype(np.float32), int(at * SR))
        _place(out, 0.3 * lowpass(thud(rng), 260), int(at * SR))
    lt = _t(0.9)
    lock = sum(np.sin(TAU * f * lt) for f in (659.25, 987.77, 1318.5)) * np.exp(-lt / 0.4) * np.clip(lt / 0.02, 0, 1)
    _place(out, 0.06 * lock.astype(np.float32), int(10.3 * SR))
    _place(out, 0.15 * lowpass(whoosh(rng), 3000), int(10.55 * SR))

    # her arrival: a deep impact and a bright shimmer - the loudest moment
    _place(out, riser(0.7, rng) * 0.3, int((BOOT_FLARE_S - 0.7) * SR))
    _place(out, thud(rng) * 1.9, int(BOOT_FLARE_S * SR))
    _place(out, sparkle(rng) * 0.5, int((BOOT_FLARE_S + 0.02) * SR))
    return _norm(out)


def bubble_snap(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """A manga speech bubble slamming in: a hard paper-crack transient, a bright
    snapped pop, and a tiny high ring as it settles."""
    t = _t(0.22)
    crack = _band(rng.standard_normal(len(t)), 2500, 10000) * np.exp(-t * 140)
    pop_ = np.sin(_sweep(1600, 520, 0.22, 0.35)) * np.exp(-t * 34)
    ring = np.sin(TAU * 3150 * t) * np.exp(-t * 26) * 0.18
    knock = np.sin(_sweep(240, 110, 0.22)) * np.exp(-t * 45) * 0.6
    return _norm(crack * 1.4 + pop_ * 0.7 + ring + knock)


# when the HUD's domain moments happen, after the visor's summon/start (led/summon.ts:
# part2 is sent DOMAIN_PART2_S in; the eye reaches full burn HOOK_IN + 0.75 LIFT later)
DOMAIN_PART2_S = 0.42
DOMAIN_REVEAL_S = DOMAIN_PART2_S + 0.22 + 0.45 * 0.75


def domain_win(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """The domain expansion, re-fired on a line (skit "domain"): the summon's own
    riser and bass swell under the visor sliding in, then - on the ice-blue eye - a
    deep impact (a sub drop, a body hit, a cold crystalline shimmer and a reversed
    suck into it). (bubble_snap goes on top when a line has a speech bubble.)"""
    # (every effect is under 3 s: the impact's tail is over by ~2.6 s)
    out = np.zeros(int(2.9 * SR), np.float32)
    reveal = int(DOMAIN_REVEAL_S * SR)
    # the visor: the summon's whoosh, rising and stopping dead at the reveal
    rise = riser(DOMAIN_REVEAL_S, rng)
    _place(out, rise * 0.55, 0)
    # the summon's bass swell, peaking on the eye
    from .summon_fx import bass_swell

    _place(out, bass_swell(DOMAIN_REVEAL_S, 1.6) * 0.9, 0)
    # a reversed shimmer sucked INTO the reveal: cold air pulled in before the hit
    suck = chime(4, rng)[: int(0.5 * SR)][::-1] * np.linspace(0, 1, int(0.5 * SR)) ** 2
    _place(out, suck * 0.35, max(0, reveal - len(suck)))
    # the impact: a sub drop with a hard body under it
    t = _t(1.6)
    sub = np.sin(_sweep(95, 32, 1.6, 0.4)) * np.exp(-t * 2.2)
    body = _band(rng.standard_normal(len(t)), 60, 900) * np.exp(-t * 18)
    crack = _band(rng.standard_normal(len(t)), 1500, 9000) * np.exp(-t * 55) * 0.5
    _place(out, (sub * 1.0 + body * 0.7 + crack).astype(np.float32), reveal)
    # the eye's cold shimmer, ringing out under it
    shimmer = chime(4, rng)
    _place(out, highpass(shimmer, 900) * 0.4, reveal + int(0.05 * SR))
    return _norm(out)


def bonk(rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    """A cartoon whack on the head (study mode's hits): a hollow wooden knock that
    drops in pitch, and a few tiny bells ringing round after it - the stars."""
    out = np.zeros(int(0.7 * SR), np.float32)
    t = _t(0.22)
    knock = np.sin(_sweep(900, 260, 0.22, 0.35)) * np.exp(-t * 19)
    knock += _band(rng.standard_normal(len(t)), 400, 2500) * np.exp(-t * 90) * 0.6
    _place(out, np.tanh(knock * 1.6), 0)
    for k, f in enumerate((2600, 3100, 2800)):
        b = _t(0.18)
        _place(out, np.sin(TAU * f * b) * np.exp(-b * 24) * 0.22, int((0.12 + 0.09 * k) * SR))
    return _norm(out)


EFFECTS: dict[str, Callable[..., np.ndarray]] = {
    fn.__name__: fn
    for fn in (
        click, swish, thwack, thwip, whoosh, thud, charge, beam, paper, dust, footsteps, skid, riffle, ding, sparkle,
        rattle, pop, glitch, beep, boing, chirp, giggle, gasp, sigh, tada, boop, wail,
        kiai, clock_tap, bark, meow, mash, game_over, fire, whimper, carriage_bell, boot, huff, flags,
        bubble_snap, domain_win, bonk,
    )
}


def shout(voice: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Her spoken word turned into a kiai - "Hajime!" read flat becomes a sharp shout:
    the silence trimmed, the low end thinned, driven hard (the strain of a shout), the
    last syllable lifted and held, cut off short, with the kiai's open vowel under it."""
    x = np.asarray(voice, np.float32)
    loud = np.nonzero(np.abs(x) > 0.02 * (np.max(np.abs(x)) if len(x) else 1))[0]
    if len(loud) == 0:
        return kiai(rng)
    x = x[max(0, loud[0] - int(0.01 * SR)): loud[-1] + int(0.02 * SR)]
    x = highpass(x, 180, 2)
    x = x / (np.max(np.abs(x)) + 1e-9)
    p = np.linspace(0, 1, len(x))
    # the end carries the shout: rising into the last syllable, then a hard stop
    lift = 0.75 + 0.45 * np.clip((p - 0.45) / 0.4, 0, 1)
    stop = np.minimum(1, (1 - p) / 0.06)
    x = np.tanh(x * lift * 3.2) * stop
    out = np.zeros(len(x) + int(0.05 * SR), np.float32)
    _place(out, x, 0)
    under = kiai(rng, 0.3) * 0.35
    _place(out, under, max(0, len(x) - len(under)))
    return _norm(out)


def render(name: str, rng: np.random.Generator, dur: float | None = None) -> np.ndarray:
    if name not in EFFECTS:
        raise KeyError(f"no sound effect {name!r}; have {', '.join(sorted(EFFECTS))}")
    return EFFECTS[name](rng, dur)
