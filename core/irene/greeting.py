# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""How she greets him: like someone who has been paying attention.

"Good morning Mister Tri, how can I help you?" every time is lifeless. Her
greeting is built from what she really knows right now (Context, filled in by
the app from real readings - never made up):

  the clock      the band (morning/afternoon/evening), the weekday, an unusually
                 early start or a late night (against his own usual start,
                 presence.py)
  the weather    his city's, from the dashboard's Open-Meteo reading: raining
                 now, how many days running, a cold or warm one, rain later
  him            how long since they last spoke ("Back already?"), when he
                 started today ("you were at this at six this morning"), what
                 they were doing last time (the last research)
  his things     a timer still running

Every fact that applies is an observation with a weight and a few ways to say
it; one is drawn (the stronger ones more often), so the line is never the same
twice running and usually about something real. It may open with an
observation or a question, and only sometimes ends with an offer of help. One
or two sentences; "Mister Tri" always (with_name). With nothing notable at all,
the hour's plain greeting.

The entrance itself is pre-rendered (entrances.py); this is spoken live right
after it. What she was busy doing during the entrance is the conversation's
(brain.Conversation.entered).
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import datetime

from .presence import clock_words, since_words

NAME = "Mister Tri"

# by band: how she opens. "{name}" is filled in.
BANDS: dict[str, tuple[str, ...]] = {
    "morning": ("Good morning", "Morning", "Good morning to you"),
    "afternoon": ("Good afternoon", "Afternoon", "Good afternoon to you"),
    "evening": ("Good evening", "Evening", "Good evening to you"),
}
# the short ones, for in front of an observation
SHORT: dict[str, tuple[str, ...]] = {
    "morning": ("Morning", "Good morning"),
    "afternoon": ("Afternoon", "Hi"),
    "evening": ("Evening", "Good evening"),
}

# what follows the greeting - the offer of help, her way
TAILS = (
    "how can I help?",
    "how can I help you today?",
    "what can I do for you?",
    "what are we doing today?",
    "what's on the agenda?",
    "at your service.",
    "what would you like?",
    "ready when you are.",
)
# an offer after an observation, as its own sentence - only now and then
OFFERS = ("What can I do for you?", "What are we up to?", "What's the plan?", "Need anything?", "I'm all yours.")
OFFER_CHANCE = 0.4

# now and then she skips the greeting entirely
PLAYFUL = (
    "Did you miss me?",
    "You rang, sir?",
    "Ta-da! I'm here.",
    "Miss me already?",
    "Back! What did I miss?",
    "Here I am. What's the plan?",
    "You called, and I came. What's up?",
    "At last, some company! What do you need?",
)

PLAYFUL_CHANCE = 0.25
# how often the greeting after an entrance is one of that entrance's own - when
# nothing real is worth saying; with something notable, hers comes first
ENTRANCE_GREETING_CHANCE = 0.8
ENTRANCE_WITH_CONTEXT_CHANCE = 0.25
# how notable something must be (summed weight) before it beats the plain greeting
NOTABLE = 2.0

# heavy rain: "pouring"; the rest: "raining"
_POURING = re.compile(r"heavy|shower|thunder", re.I)
_RAINY = re.compile(r"rain|drizzle|shower|thunder", re.I)
_CLEAR = re.compile(r"^(clear|mostly clear)$", re.I)
WORDS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen".split()


def band(hour: int) -> str:
    """Which greeting the hour asks for."""
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    return "evening"


def with_name(line: str) -> str:
    """Every greeting says his name - enforced here, not left to a prompt. A "sir"
    becomes "Mister Tri"; otherwise the name goes in before the first sentence's
    end: "Did you miss me?" -> "Did you miss me, Mister Tri?"."""
    if NAME.lower() in line.lower():
        return line
    if re.search(r"\bsir\b", line, re.I):
        return re.sub(r"\bsir\b", NAME, line, count=1, flags=re.I)
    m = re.search(r"[.!?]", line)
    if not m:
        return f"{line.rstrip()}, {NAME}."
    return f"{line[: m.start()].rstrip(' ,')}, {NAME}{line[m.start():]}"


def _phrase(rng: random.Random, hour: int) -> str:
    """"Good morning, Mister Tri, how can I help?" - always with his name."""
    opener = rng.choice(BANDS[band(hour)])
    tail = rng.choice(TAILS)
    return f"{opener}, {NAME}, {tail}"


def sentences(line: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", line.strip()) if s])


def ends_with_offer(line: str) -> bool:
    """Does the line close on an offer of service ("how can I help?")?"""
    last = re.split(r"(?<=[.!?])\s+", line.strip())[-1].lower()
    return bool(re.search(r"help|what can i do|at your service|what would you like|ready when you are|need anything|all yours|agenda|what are we (?:doing|up to)|what'?s the plan", last))


# ---- what she knows ---------------------------------------------------------------------------


@dataclass
class Context:
    """What is real right now. Anything unknown stays None and is never mentioned."""

    now: datetime
    # the dashboard's weather reading (tools/dashboard.weather): temp, sky, days[0]
    # (high/low/rain chance), rain_streak (days running with rain, today included)
    weather: dict | None = None
    since_last_s: float | None = None
    first_today: datetime | None = None
    usual_hour: float | None = None
    topic: str | None = None
    topic_at: datetime | None = None
    # the first running timer: {"label", "left_s"}
    timer: dict | None = None
    city: str = "town"


@dataclass
class Observation:
    kind: str
    weight: float
    lines: tuple[str, ...]
    # the line opens with the hour's greeting ("Morning. It's pouring...")
    opener: bool = True
    facts: dict = field(default_factory=dict)


def _num(n: int) -> str:
    return WORDS[n] if 0 <= n < len(WORDS) else str(n)


def _ordinal(n: int) -> str:
    return {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}.get(n, str(n))


def observations(ctx: Context) -> list[Observation]:
    """Everything worth remarking on now, each with how notable it is."""
    out: list[Observation] = []
    now = ctx.now
    hour = now.hour + now.minute / 60
    gap = ctx.since_last_s

    # ---- him: how long since they spoke ----
    if gap is not None and gap < 15 * 60:
        out.append(Observation("back-quick", 5, (
            "Back already? That was quick.",
            "That was fast. Forget something?",
            "Oh, hello again. Miss me?",
            "Back so soon? I'd barely sat down.",
            "You again! I was just getting comfortable.",
        ), opener=False))
    elif gap is not None and gap < 3 * 3600:
        said = since_words(gap)
        out.append(Observation("back-later", 2, (
            f"Welcome back. That was {said}.",
            f"There you are - {said} since we last spoke.",
            f"Back again. {said[0].upper() + said[1:]} - all sorted?",
        ), opener=False, facts={"gap": said}))
    elif gap is not None and gap > 2 * 24 * 3600:
        days = round(gap / 86400)
        out.append(Observation("long-absence", 4, (
            f"It's been {_num(days)} days - I was starting to wonder.",
            f"Well, look who it is. {_num(days).capitalize()} days!",
            f"{_num(days).capitalize()} days without a word. Everything alright?",
            f"There you are! {_num(days).capitalize()} days - I kept your seat warm.",
            f"Back after {_num(days)} days. Did I miss anything good?",
        ), opener=False, facts={"days": days}))

    # ---- the clock: early, late, a long day ----
    early = 4 <= hour < 6 or (ctx.usual_hour is not None and hour < ctx.usual_hour - 2 and 4 <= hour < 11)
    first = ctx.first_today
    if early and (first is None or (now - first).total_seconds() < 600):
        out.append(Observation("early", 5, (
            "You're up early. Everything alright?",
            "Up before the sun? Everything alright?",
            "Early start today - big day?",
            "That's early, even for you. Couldn't sleep?",
            "Morning already? The birds aren't even up yet.",
            "Early bird today. What's got you up?",
            "You beat the sunrise. Big plans?",
        ), opener=False, facts={"hour": now.hour}))
    if hour >= 23 or hour < 4:
        clock = "midnight" if now.hour == 0 else clock_words(now) if now.hour < 4 else "eleven"
        past = f"It's past {clock}." if now.hour in (0, 23) else f"It's {clock} in the morning."
        out.append(Observation("late", 5, (
            f"Still up? {past}",
            "Burning the midnight oil again?",
            f"{past} Shouldn't you be asleep?",
            "Late one tonight. Want me to keep it short?",
            "Night owl mode, I see. What's keeping you up?",
            "Can't sleep either?",
            "Everyone sensible's in bed. What are we up to?",
        ), opener=False, facts={"hour": now.hour}))
    if first is not None and first.hour < 10 and (now - first).total_seconds() >= 9 * 3600 and band(now.hour) != "morning":
        at = clock_words(first)
        out.append(Observation("long-day", 5, (
            f"Long day? You were at this at {at} this morning.",
            f"Still going? You started at {at} this morning.",
            f"You've been at it since {at}. Time for a break?",
        ), facts={"first": at}))

    # ---- the weather, his city's (a real reading) ----
    w = ctx.weather or {}
    sky = str(w.get("sky") or "")
    today = (w.get("days") or [{}])[0] if w.get("days") else {}
    streak = int(w.get("rain_streak") or 0)
    raining = bool(_RAINY.search(sky))
    if raining and streak >= 2:
        out.append(Observation("rain-streak", 5, (
            f"Still raining. Day {_ordinal(streak)}, if anyone's counting.",
            f"Rain again - that's {_num(streak)} days running. Tea weather.",
            f"Day {_ordinal(streak)} of rain. I'd stay in, if I were you.",
        ), facts={"streak": streak, "sky": sky}))
    elif raining:
        verb = "pouring" if _POURING.search(sky) else "raining"
        out.append(Observation("rain-now", 4, (
            f"It's {verb} out there - good day to stay in.",
            f"Hear that? It's {verb} in {ctx.city}.",
            f"It's {verb}. Umbrella, if you're heading out.",
        ), facts={"sky": sky}))
    elif w and isinstance(today.get("rain"), (int, float)) and today["rain"] >= 60 and band(now.hour) != "evening":
        pct = int(today["rain"])
        sure = pct >= 90
        out.append(Observation("rain-later", 3, (
            ("Dry for now, but it's going to rain later - no doubt about it." if sure
             else f"Dry for now, but there's a {pct} percent chance of rain later."),
            ("Rain's coming later, so keep an umbrella handy." if sure
             else f"Rain's likely later - {pct} percent - so keep an umbrella handy."),
            *((f"Rain again later{', day ' + _ordinal(streak) if streak >= 2 else ''}. Umbrella weather.",) if sure else ()),
        ), facts={"rain": pct}))
    temp = w.get("temp")
    if isinstance(temp, (int, float)) and temp <= 14:
        out.append(Observation("cold", 3, (
            f"Chilly one - {round(temp)} degrees out there.",
            f"{round(temp)} degrees. Jumper weather, even for {ctx.city}.",
        ), facts={"temp": round(temp)}))
    elif isinstance(temp, (int, float)) and temp >= 27:
        out.append(Observation("warm", 2, (
            f"Warm one for {ctx.city} - {round(temp)} degrees.",
            f"{round(temp)} degrees out there. Practically summer.",
        ), facts={"temp": round(temp)}))
    elif w and _CLEAR.match(sky) and 7 <= now.hour < 18:
        out.append(Observation("clear", 1.5, (
            f"Blue skies over {ctx.city} - lovely.",
            "Sun's out for once.",
        ), facts={"sky": sky}))

    # ---- his things ----
    if ctx.timer and ctx.timer.get("left_s", 0) > 30:
        left = since_words(ctx.timer["left_s"])
        label = str(ctx.timer.get("label") or "").strip()
        named = f"the {label} timer" if label and label.lower() != "timer" else "your timer"
        out.append(Observation("timer", 4, (
            f"{named[0].upper() + named[1:]}'s still running - {left} to go.",
            f"Just so you know, {named} has {left} left.",
        ), facts={"left": left}))

    # ---- what they were doing last time (a new session only) ----
    if ctx.topic and (gap is None or gap > 3600):
        t = ctx.topic
        out.append(Observation("topic", 3, (
            f"Still on {t}, or something new today?",
            f"Last time it was {t}. Picking that back up?",
            f"Any more thoughts on {t}?",
        ), facts={"topic": t}))

    # ---- the day of the week ----
    day = now.strftime("%A")
    if day == "Monday" and band(now.hour) == "morning":
        out.append(Observation("weekday", 1.5, ("Monday again. Let's ease into it.", "New week. What's first?"), facts={"day": day}))
    elif day == "Friday":
        out.append(Observation("weekday", 1.5, ("Friday at last.", "Friday! Nearly there."), facts={"day": day}))
    elif day in ("Saturday", "Sunday") and band(now.hour) != "evening":
        out.append(Observation("weekday", 1.5, (f"A {day}, and here you are. Working or playing?", f"Happy {day}. Anything fun planned?"), facts={"day": day}))
    return out


def notable(ctx: Context) -> bool:
    return sum(o.weight for o in observations(ctx)) >= NOTABLE


# ---- the line ---------------------------------------------------------------------------------


class Greeter:
    """Her greeting; never the same line twice running."""

    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()
        self.last: str | None = None
        self.last_kind: str | None = None

    def next(self, hour: int, ctx: Context | None = None) -> str:
        if ctx is not None:
            line = self.considerate(ctx)
            if line is not None:
                return line
        line = self.last
        for _ in range(12):
            line = self.rng.choice(PLAYFUL) if self.rng.random() < PLAYFUL_CHANCE else _phrase(self.rng, hour)
            if line != self.last:
                break
        line = with_name(line)
        self.last, self.last_kind = line, "plain"
        return line

    def considerate(self, ctx: Context) -> str | None:
        """A greeting drawn from what is real right now, or None with nothing notable."""
        found = observations(ctx)
        if sum(o.weight for o in found) < NOTABLE:
            return None
        # the same kind of remark twice running only when nothing else applies
        pool = [o for o in found if o.kind != self.last_kind] or found
        for _ in range(16):
            obs = self.rng.choices(pool, weights=[o.weight for o in pool])[0]
            line = self._say(obs, ctx)
            if line != self.last:
                break
        self.last, self.last_kind = line, obs.kind
        return line

    def _say(self, obs: Observation, ctx: Context) -> str:
        body = self.rng.choice(obs.lines)
        b = band(ctx.now.hour)
        if obs.opener and (ctx.now.hour >= 4 and ctx.now.hour < 23):
            opener = self.rng.choice(SHORT[b])
            line = f"{opener}! {body}" if self.rng.random() < 0.2 else f"{opener}. {body}"
        else:
            line = body
        # the offer only sometimes, only after a statement, and never past two sentences
        if not line.rstrip().endswith("?") and sentences(line) < 2 and self.rng.random() < OFFER_CHANCE:
            line = f"{line} {self.rng.choice(OFFERS)}"
        if sentences(line) > 2:
            line = " ".join(re.split(r"(?<=[.!?])\s+", line.strip())[:2])
        return with_name(line)

    def for_entrance(self, entry: dict, hour: int, ctx: Context | None = None) -> str:
        """The greeting right after `entry`. With something real worth saying, that
        - most of the time; otherwise one of the entrance's own (the entrance and
        what she says are one moment), else the hour's. His name always."""
        own = [g for g in entry.get("greetings", ()) if with_name(g) != self.last]
        chance = ENTRANCE_WITH_CONTEXT_CHANCE if ctx is not None and notable(ctx) else ENTRANCE_GREETING_CHANCE
        if own and self.rng.random() < chance:
            line = with_name(self.rng.choice(own))
            self.last, self.last_kind = line, "entrance"
            return line
        return self.next(hour, ctx)
