"""Where he lives (config/home.yaml): in front of every message, like the clock,
and added to any location-dependent search that names no place of its own.

Asked "what's the weather today?", she once reported New York - the search engine's
default when a query names nowhere (config/home.yaml; a fresh clone has the example's).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from tools.localconfig import personal

CONFIG = personal("home.yaml")

# questions whose answer depends on where he is
_LOCAL = re.compile(
    r"\b(weather|forecast|temperature|how (hot|cold|warm)|rain(ing|y)?|snow(ing)?|sunny|humid(ity)?|wind(y)?|storm|typhoon|air quality|aqi|uv index"
    r"|sunrise|sunset|near me|nearby|around here|close to me|local(ly)?|in (my|this) (city|town|area)|open now|traffic|time zone|electricity cut)\b",
    re.I,
)
# "... in Tokyo", "... at Hanoi", "... for London": he named a place himself
_PLACE = re.compile(r"\b(?:in|at|for|near|around|to|from)\s+(?:the\s+)?([A-Z][\w'-]+(?:\s+[A-Z][\w'-]+)*)")
_NOT_PLACES = {"I", "Irene", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "January", "February",
               "March", "April", "May", "June", "July", "August", "September", "October", "November", "December", "Celsius", "Fahrenheit"}


@dataclass(frozen=True)
class Home:
    city: str
    region: str
    country: str
    timezone: str

    @property
    def place(self) -> str:
        return f"{self.city}, {self.country}"

    def section(self) -> str:
        """His location, for the per-message context."""
        # a fact, stated once - not an instruction to search: telling the model every
        # turn to research anything local made it research everything (routing
        # 199/203 -> 197/211, an injected screenshot obeyed). Weather and the like
        # go straight to research (fast.py) and get his city there (localise).
        return (
            f"He lives in {self.city} ({self.region}), {self.country}, time zone {self.timezone}. "
            f"'Here', 'near me' or 'outside' means {self.city} unless he names another place."
        )

    def localise(self, question: str) -> str:
        """`question` with his city added, if it depends on where he is and names no
        place of its own."""
        if not _LOCAL.search(question or ""):
            return question
        if not self.city:
            return question
        folded = question.lower()
        # "Da Nang" / "Danang": spaces aside, the same place
        if self.city.lower().replace(" ", "") in folded.replace(" ", "") or (self.country and self.country.lower() in folded):
            return question
        named = [m.group(1) for m in _PLACE.finditer(question) if m.group(1).split()[0] not in _NOT_PLACES]
        if named:
            return question
        return f"{question.rstrip(' ?.!')} in {self.place}"


def load(path: Path = CONFIG) -> Home:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    data = data or {}
    return Home(
        str(data.get("city", "")),
        str(data.get("region", "")),
        str(data.get("country", "")),
        str(data.get("timezone", "")),
    )


HOME = load()
