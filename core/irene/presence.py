# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""When he talks to her, and what about - kept on disk, so her greeting knows.

A greeting that has been paying attention needs a memory across restarts: how
long since they last spoke, when he started today, when he usually starts, and
what they were doing last time. One small JSON file in core/data (local, never
sent anywhere), written as he speaks:

    {"days": {"2026-10-06": {"first": 1791230000.0, "last": 1791260000.0}},
     "topic": {"text": "the Sicilian Defence", "at": 1791250000.0}}

Only his own turns count (a dev replay or another socket's command does not);
the last DAYS_KEPT days are kept.
"""
from __future__ import annotations

import json
import logging
import re
import statistics
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

log = logging.getLogger("irene.presence")

PATH = Path(__file__).resolve().parents[1] / "data" / "presence.json"
DAYS_KEPT = 30
# a topic older than this is not "what we were doing last time" any more
TOPIC_FRESH_S = 4 * 24 * 3600
# his usual start: the median first hour over at least this many days
USUAL_MIN_DAYS = 4

# how he asks, not what about: "can you tell me about the Sicilian?" -> "the Sicilian"
_LEAD = re.compile(
    r"^(?:(?:please|can you|could you|hey irene|irene|research|look up|look into|find out about|find out|tell me about|tell me|explain|describe|"
    r"show me|teach me|what(?:'s| is| are| was| were)?|who(?:'s| is| was)?|how(?: does| do| did| is| are)?|why(?: is| are| does| do)?|"
    r"when(?: is| was| did)?|where(?: is| are)?|key|main)[,\s]+)+",
    re.I,
)


def topic_of(question: str) -> str | None:
    """A few words for what a question was about, his own casing kept - or None
    when it is too long to say back naturally."""
    t = re.sub(r"[?.!]+$", "", " ".join((question or "").split()))
    t = re.sub(r"\s+[-–—:]\s+.*$", "", t)
    t = _LEAD.sub("", t).strip(" ,")
    t = re.sub(r"\s+(?:works?|happens?)$", "", t, flags=re.I)
    if not t or len(t.split()) > 6 or len(t) > 48:
        return None
    return t


@dataclass
class Seen:
    """What the log says, as of now (before this exchange is recorded)."""

    since_last_s: float | None = None
    first_today: datetime | None = None
    usual_hour: float | None = None
    topic: str | None = None
    topic_at: datetime | None = None


class Presence:
    def __init__(self, path: Path = PATH):
        self.path = path
        self.data: dict = {"days": {}, "topic": None}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as error:
            log.warning("presence log unreadable (%s) - starting a new one", error)

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as error:
            log.warning("presence log not saved: %s", error)

    def heard(self, now: float | None = None) -> None:
        """He said something to her."""
        now = now or time.time()
        day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        days = self.data.setdefault("days", {})
        entry = days.setdefault(day, {"first": now, "last": now})
        entry["last"] = now
        for old in sorted(days)[:-DAYS_KEPT]:
            del days[old]
        self._save()

    def topic(self, question: str, now: float | None = None) -> None:
        """What they were doing: a research question, a briefing."""
        said = topic_of(question)
        if said:
            self.data["topic"] = {"text": said, "at": now or time.time()}
            self._save()

    def seen(self, now: float | None = None) -> Seen:
        now = now or time.time()
        today = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        days = self.data.get("days") or {}
        last = max((d["last"] for d in days.values() if d.get("last", 0) <= now), default=None)
        first = days.get(today, {}).get("first")
        earlier = [datetime.fromtimestamp(d["first"]) for k, d in days.items() if k != today and d.get("first")]
        usual = statistics.median(t.hour + t.minute / 60 for t in earlier) if len(earlier) >= USUAL_MIN_DAYS else None
        topic = self.data.get("topic") or None
        fresh = topic and now - float(topic.get("at", 0)) < TOPIC_FRESH_S
        return Seen(
            since_last_s=(now - last) if last is not None else None,
            first_today=datetime.fromtimestamp(first) if first else None,
            usual_hour=usual,
            topic=topic["text"] if fresh else None,
            topic_at=datetime.fromtimestamp(topic["at"]) if fresh else None,
        )


def days_ago(when: datetime, now: datetime) -> int:
    return (now.date() - when.date()).days if when else 0


def clock_words(when: datetime) -> str:
    """6:00 -> "six", 7:30 -> "half past seven", 6:15 -> "quarter past six",
    8:40 -> "eight forty" - how she would say it."""
    names = "twelve one two three four five six seven eight nine ten eleven".split()
    h = names[when.hour % 12]
    m = round(when.minute / 5) * 5
    if m == 60:
        return names[(when.hour + 1) % 12]
    if m == 0:
        return h
    if m == 30:
        return f"half past {h}"
    if m == 15:
        return f"quarter past {h}"
    if m == 45:
        return f"quarter to {names[(when.hour + 1) % 12]}"
    tens = {5: "oh five", 10: "ten", 20: "twenty", 25: "twenty-five", 35: "thirty-five", 40: "forty", 50: "fifty", 55: "fifty-five"}
    return f"{h} {tens[m]}"


def since_words(seconds: float) -> str:
    """How long, said: "twenty minutes", "an hour", "three hours", "two days"."""
    words = "zero one two three four five six seven eight nine ten eleven twelve".split()
    minutes = seconds / 60
    if minutes < 55:
        n = max(5, round(minutes / 5) * 5)
        return {5: "five minutes", 10: "ten minutes", 15: "a quarter of an hour", 20: "twenty minutes", 25: "twenty-five minutes",
                30: "half an hour", 35: "thirty-five minutes", 40: "forty minutes", 45: "forty-five minutes", 50: "fifty minutes"}.get(n, "an hour")
    hours = round(minutes / 60)
    if hours < 24:
        return "an hour" if hours <= 1 else f"{words[hours] if hours < len(words) else hours} hours"
    days = round(hours / 24)
    return "a day" if days <= 1 else f"{words[days] if days < len(words) else days} days"

