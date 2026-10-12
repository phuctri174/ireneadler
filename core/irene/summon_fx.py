"""The summon line as a produced piece of audio, not a plain TTS read.

Kokoro has no emotion control, so the drama is made in the mix:

  [bass swell + whoosh rising] -> PART 1 "Domain... Expansion." slow, pitched down,
  blended deeper voice, big reverb + echo -> held breath (~400 ms) ->
  PART 2a "Irene Adler" unhurried, micro-pause between the words ->
  PART 2b "is coming!" fast, bright, dry, sparkle chime on "coming".

Everything here is numpy: FFT filtering and convolution, synthesized SFX. No
sample files. Rendered once and cached - the line never changes.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SR = 24000
PART1 = "Domain... Expansion."
# part 2 in two takes: the name slow enough to hear, then the fast bright payoff
PART2A = "Irene Adler"
PART2B = "is coming!"
NAME_SPLIT_WORD = "Adler"
PART2_JOIN = 0.04  # seconds between "Adler" and "is coming"
CHIME_WORD = "coming"
PART2_PUNCH_DB = 1.0  # part 2 speech over part 1 speech, RMS


@dataclass(frozen=True)
class Intensity:
    name: str
    blend: tuple[tuple[str, float], ...]  # part 1 voice mix, weights sum to 1
    part1_tempo: float  # net tempo after the pitch shift
    pitch_semitones: float  # part 1, negative is down
    reverb_seconds: float  # RT60 of the synthetic room
    reverb_wet: float
    echo_taps: int
    swell_seconds: float  # bass/whoosh lead-in before the first word
    swell_gain: float
    whoosh_gain: float
    breath_seconds: float
    part2_speed: float  # 2b, "is coming!"
    bright_db: float  # high shelf on part 2
    chime_gain: float
    chime_notes: int
    part2a_speed: float = 1.0  # 2a, "Irene Adler" - clarity over pace
    name_gap: float = 0.08  # micro-pause between "Irene" and "Adler"


INTENSITIES = {
    "v1": Intensity(
        name="v1 - restrained",
        blend=(("af_bella", 0.8), ("af_kore", 0.2)),
        part1_tempo=0.85,
        pitch_semitones=-1.0,
        reverb_seconds=1.6,
        reverb_wet=0.32,
        echo_taps=0,
        swell_seconds=0.9,
        swell_gain=0.35,
        whoosh_gain=0.0,
        breath_seconds=0.40,
        part2_speed=1.15,
        bright_db=2.5,
        chime_gain=0.18,
        chime_notes=2,
    ),
    "v2": Intensity(
        name="v2 - theatrical",
        blend=(("af_bella", 0.7), ("am_onyx", 0.3)),
        part1_tempo=0.8,
        pitch_semitones=-2.0,
        reverb_seconds=2.4,
        reverb_wet=0.5,
        echo_taps=2,
        swell_seconds=1.3,
        swell_gain=0.55,
        whoosh_gain=0.12,
        breath_seconds=0.40,
        part2_speed=1.2,
        bright_db=4.0,
        chime_gain=0.26,
        chime_notes=3,
    ),
    "v3": Intensity(
        name="v3 - full anime",
        blend=(("af_bella", 0.6), ("am_onyx", 0.4)),
        part1_tempo=0.76,
        pitch_semitones=-3.0,
        reverb_seconds=3.4,
        reverb_wet=0.65,
        echo_taps=3,
        swell_seconds=1.8,
        swell_gain=0.75,
        whoosh_gain=0.22,
        breath_seconds=0.45,
        part2_speed=1.25,
        bright_db=5.5,
        chime_gain=0.34,
        chime_notes=4,
    ),
}


@dataclass
class Rendered:
    audio: np.ndarray  # final mix, float32 mono at SR
    voice: np.ndarray  # voice-only stem, same length - drives the mouth, not the SFX
    part2_at: float  # seconds from start to the first sample of part 2


# --- numpy DSP --------------------------------------------------------------


def _spectrum_filter(x: np.ndarray, gain_of_freq) -> np.ndarray:
    n = len(x)
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n, 1 / SR)
    return np.fft.irfft(spec * gain_of_freq(freqs), n).astype(np.float32)


def lowpass(x: np.ndarray, cutoff: float, order: int = 4) -> np.ndarray:
    return _spectrum_filter(x, lambda f: 1 / np.sqrt(1 + (f / cutoff) ** (2 * order)))


def highpass(x: np.ndarray, cutoff: float, order: int = 4) -> np.ndarray:
    return _spectrum_filter(x, lambda f: 1 / np.sqrt(1 + (cutoff / np.maximum(f, 1e-3)) ** (2 * order)))


def high_shelf(x: np.ndarray, corner: float, gain_db: float) -> np.ndarray:
    g = 10 ** (gain_db / 20)
    return _spectrum_filter(x, lambda f: 1 + (g - 1) / (1 + (corner / np.maximum(f, 1e-3)) ** 2))


def convolve(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    n = len(a) + len(b) - 1
    size = 1 << (n - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(a, size) * np.fft.rfft(b, size), size)[:n].astype(np.float32)


def resample(x: np.ndarray, ratio: float) -> np.ndarray:
    """Play back at `ratio` x speed: <1 is slower and lower. Upsampling only here, so
    linear interpolation doesn't alias."""
    positions = np.arange(0, len(x) - 1, ratio)
    return np.interp(positions, np.arange(len(x)), x).astype(np.float32)


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


def trim(x: np.ndarray, threshold: float = 0.01) -> tuple[np.ndarray, int]:
    """Cut leading/trailing near-silence; returns the audio and samples cut from the front."""
    loud = np.flatnonzero(np.abs(x) > threshold)
    if not len(loud):
        return x, 0
    start = max(0, loud[0] - int(0.01 * SR))
    end = min(len(x), loud[-1] + int(0.03 * SR))
    return x[start:end], start


def fade(n: int, kind: str) -> np.ndarray:
    ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, n))
    return (ramp if kind == "in" else ramp[::-1]).astype(np.float32)


# --- procedural SFX ---------------------------------------------------------


def room_impulse(rt60: float, rng: np.random.Generator) -> np.ndarray:
    """Exponentially decaying noise that darkens as it decays, with a few early reflections."""
    n = int(rt60 * SR)
    t = np.arange(n) / SR
    tail = rng.standard_normal(n).astype(np.float32) * np.exp(-6.9 * t / rt60)
    # high frequencies die faster in a real room: blend a bright and a dark copy over time
    dark = lowpass(tail, 1800)
    bright = lowpass(tail, 7000)
    mix = np.exp(-3 * t / rt60)
    ir = bright * mix + dark * (1 - mix)
    predelay = int(0.025 * SR)
    ir = np.concatenate([np.zeros(predelay, np.float32), ir])
    for delay, gain in ((0.011, 0.5), (0.019, 0.35), (0.031, 0.28), (0.043, 0.2)):
        ir[int(delay * SR)] += gain
    return ir / np.sqrt(np.sum(ir**2))


def multitap_echo(x: np.ndarray, taps: int, spacing: float = 0.23, feedback: float = 0.45) -> np.ndarray:
    if taps == 0:
        return np.zeros_like(x)
    step = int(spacing * SR)
    out = np.zeros(len(x) + step * taps, np.float32)
    voice = lowpass(x, 3500)
    for k in range(1, taps + 1):
        voice = lowpass(voice, 3500 - 600 * k)  # each repeat duller than the last
        out[step * k : step * k + len(x)] += voice * feedback**k
    return out


def bass_swell(seconds: float, tail: float) -> np.ndarray:
    """Sine sweep 32 -> 58 Hz rising into the first word, then decaying under it.
    2nd/3rd harmonics keep it audible on speakers that can't reproduce sub-bass."""
    n_rise, n_tail = int(seconds * SR), int(tail * SR)
    n = n_rise + n_tail
    t = np.arange(n) / SR
    freq = 32 + 26 * np.clip(t / seconds, 0, 1) ** 1.5
    phase = 2 * np.pi * np.cumsum(freq) / SR
    tone = np.sin(phase) + 0.35 * np.sin(2 * phase) + 0.12 * np.sin(3 * phase)
    env = np.concatenate([np.linspace(0, 1, n_rise) ** 2.2, np.exp(-np.linspace(0, 4, n_tail))])
    return (tone * env / 1.47).astype(np.float32)


def whoosh(seconds: float, rng: np.random.Generator) -> np.ndarray:
    """Noise whose centre frequency climbs 250 Hz -> 5 kHz: a riser that stops dead at the word."""
    n = int(seconds * SR)
    noise = rng.standard_normal(n).astype(np.float32)
    centres = np.geomspace(150, 8000, 10)
    progress = np.linspace(0, 1, n)
    centre = 250 * (5000 / 250) ** (progress**1.3)
    out = np.zeros(n, np.float32)
    for c in centres:
        band = _spectrum_filter(noise, lambda f, c=c: np.exp(-0.5 * (np.log(np.maximum(f, 1) / c) / 0.35) ** 2))
        weight = np.exp(-0.5 * (np.log(centre / c) / 0.6) ** 2)
        out += band * weight
    env = progress**2.5
    out *= env / (np.max(np.abs(out)) + 1e-9)
    return out.astype(np.float32)


def chime(notes: int, rng: np.random.Generator) -> np.ndarray:
    """Quick rising sparkle: bell tones (inharmonic partials) arpeggiated, plus shimmer."""
    pitches = [1318.5, 1661.2, 1975.5, 2637.0][:notes]
    spacing = 0.055
    length = spacing * notes + 1.1
    n = int(length * SR)
    out = np.zeros(n, np.float32)
    for i, f0 in enumerate(pitches):
        start = int(i * spacing * SR)
        t = np.arange(n - start) / SR
        bell = np.zeros_like(t)
        for ratio, amp, decay in ((1, 1, 2.6), (2.76, 0.45, 5), (5.4, 0.22, 9), (8.93, 0.1, 14)):
            if f0 * ratio < SR / 2 - 500:
                bell += amp * np.sin(2 * np.pi * f0 * ratio * t) * np.exp(-decay * t)
        attack = np.minimum(1, t / 0.002)
        out[start:] += (bell * attack * (0.8 + 0.2 * i / max(1, notes - 1))).astype(np.float32)
    shimmer = highpass(rng.standard_normal(n).astype(np.float32), 7000)
    shimmer *= np.exp(-np.arange(n) / SR * 7) * 0.25
    out += shimmer
    return out / (np.max(np.abs(out)) + 1e-9)


# --- render -----------------------------------------------------------------


def _synth(pipeline, text: str, voice, speed: float) -> tuple[np.ndarray, list]:
    audio, tokens, offset = [], [], 0.0
    for result in pipeline(text, voice=voice, speed=speed):
        chunk = np.asarray(result.audio, dtype=np.float32)
        for tok in result.tokens or []:
            if tok.start_ts is not None:
                tokens.append((tok.text, offset + tok.start_ts, offset + tok.end_ts))
        audio.append(chunk)
        offset += len(chunk) / SR
    return np.concatenate(audio), tokens


def split_at_word(audio: np.ndarray, tokens: list, word: str, gap: float) -> np.ndarray:
    """Insert `gap` seconds of silence where `word` starts, with short fades so the cut
    doesn't click. Unchanged if the word's timestamp is missing."""
    start = next((t[1] for t in tokens if t[0].strip(" .,!?") == word), None)
    if start is None:
        return audio
    at = int(start * SR)
    edge = int(0.004 * SR)
    left, right = audio[:at].copy(), audio[at:].copy()
    left[-edge:] *= fade(edge, "out")
    right[:edge] *= fade(edge, "in")
    return np.concatenate([left, np.zeros(int(gap * SR), np.float32), right])


def blend_voice(pipeline, blend):
    packs = [pipeline.load_single_voice(name) * weight for name, weight in blend]
    return sum(packs[1:], packs[0])


class TurboTakes:
    """Chatterbox-Turbo in place of the Kokoro pipeline for the same production. It
    has one cloned voice, no speed control and no word timings, so: part 1's pitch
    and tempo both come from the resample, and the name is said as two takes with
    the breath between them."""

    def __init__(self, turbo) -> None:
        self.turbo = turbo

    def synth(self, text: str) -> tuple[np.ndarray, list]:
        return self.turbo.synth_one(text), []


def render(pipeline, spec: Intensity, seed: int = 7) -> Rendered:
    rng = np.random.default_rng(seed)
    turbo = pipeline if isinstance(pipeline, TurboTakes) else None

    # PART 1: pitch down by resampling; render faster to land on the target tempo
    ratio = 2 ** (spec.pitch_semitones / 12)
    if turbo:
        raw1, _ = turbo.synth(PART1)
    else:
        raw1, _ = _synth(pipeline, PART1, blend_voice(pipeline, spec.blend), spec.part1_tempo / ratio)
    dry1, _ = trim(resample(raw1, ratio))
    dry1 = lowpass(dry1, 9000)
    wet1 = convolve(dry1, room_impulse(spec.reverb_seconds, rng))
    echo1 = multitap_echo(dry1, spec.echo_taps)

    # PART 2: fast, bright, dry
    # PART 2a: the name, unhurried, with a breath of space between the two words
    if turbo:
        first, second = PART2A.split(" ", 1)
        a, _ = trim(turbo.synth(f"{first},")[0])
        b, _ = trim(turbo.synth(f"{second}.")[0])
        dry2a = np.concatenate([a, np.zeros(int(spec.name_gap * SR), np.float32), b])
        raw2b, tokens2b = turbo.synth(PART2B)
    else:
        raw2a, tokens2a = _synth(pipeline, PART2A, "af_bella", spec.part2a_speed)
        dry2a, _ = trim(split_at_word(raw2a, tokens2a, NAME_SPLIT_WORD, spec.name_gap))
        # PART 2b: fast and bright
        raw2b, tokens2b = _synth(pipeline, PART2B, "af_bella", spec.part2_speed)
    dry2b, cut2b = trim(raw2b)
    join = np.zeros(int(PART2_JOIN * SR), np.float32)
    dry2 = high_shelf(np.concatenate([dry2a, join, dry2b]), 3500, spec.bright_db)
    word = next((t for t in tokens2b if t[0].lower().strip(" !") == CHIME_WORD), None)
    chime_in_2b = (word[1] if word else len(raw2b) / SR * 0.3) - cut2b / SR
    chime_at = (len(dry2a) + len(join)) / SR + chime_in_2b

    # timeline
    lead = spec.swell_seconds
    p1 = int(lead * SR)
    p1_end = p1 + len(dry1)
    breath = int(spec.breath_seconds * SR)
    p2 = p1_end + breath
    total = p2 + len(dry2) + int(1.4 * SR)

    voice = np.zeros(total, np.float32)
    fx = np.zeros(total, np.float32)
    voice[p1:p1_end] += dry1

    # reverb and echo tail: full under part 1, then drawn down across the held breath
    # so the beat before part 2 is actually quiet
    space = np.zeros(total, np.float32)
    wet_len = min(len(wet1), total - p1)
    space[p1 : p1 + wet_len] += wet1[:wet_len] * spec.reverb_wet * 2.2
    echo_len = min(len(echo1), total - p1)
    space[p1 : p1 + echo_len] += echo1[:echo_len]
    duck_len = int(breath * 0.8)
    duck = np.ones(total, np.float32)
    duck[p1_end : p1_end + duck_len] = fade(duck_len, "out")
    duck[p1_end + duck_len :] = 0
    space *= duck

    swell = bass_swell(lead, tail=len(dry1) / SR + 0.3) * spec.swell_gain
    swell_len = min(len(swell), total)
    fx[:swell_len] += swell[:swell_len] * duck[:swell_len]
    if spec.whoosh_gain > 0:
        w = whoosh(lead, rng) * spec.whoosh_gain
        fx[p1 - len(w) : p1] += w

    # part 2 is the payoff: dry and bright, it would sit well under part 1's dense bus,
    # so match it to part 1's spoken loudness and push it a little over
    bus1 = (voice + space + fx)[p1:p1_end]
    dry2 = dry2 * (_rms(bus1) * 10 ** (PART2_PUNCH_DB / 20) / (_rms(dry2) + 1e-9))
    voice[p2 : p2 + len(dry2)] += dry2
    c = chime(spec.chime_notes, rng) * spec.chime_gain
    at = p2 + int(max(0.0, chime_at) * SR)
    fx[at : at + len(c)] += c[: total - at]

    mix = voice + space + fx
    # gentle soft clip, then peak to -1 dBFS
    mix = np.tanh(mix * 1.2) / np.tanh(1.2)
    peak = np.max(np.abs(mix)) + 1e-9
    gain = 0.89 / peak
    return Rendered(audio=(mix * gain).astype(np.float32), voice=(voice * gain).astype(np.float32), part2_at=p2 / SR)
