"""The real numbers behind a question about something that changes (Round 8, part 4).

Price and weather pages mostly draw their numbers with JavaScript, so research read
prose about gold and NVIDIA and never the numbers: she had nothing real to chart.
When a research question is about a market (a stock, gold, oil, bitcoin, an
index, a currency) or the weather, research also fetches the series itself and
adds it as one more numbered source:

  markets   Yahoo Finance's public chart data (no key): the asset found by name
            (search), closes over the period asked ("this month", "this year")
  weather   Open-Meteo (no key): the next days' highs and lows, for the place he
            names or his own city (config/home.yaml)

It is read like any page - data, never instructions - and the chart she draws from
it is checked against it number by number (irene/drawing.numbers). Nothing is
invented: no series found, no source added.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml
from tools.localconfig import personal

log = logging.getLogger("irene.tools.series")

HOME = personal("home.yaml")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"}
TIMEOUT_S = 6.0
MAX_POINTS = 12

MARKET = re.compile(
    r"\b(price|prices|stock|stocks|shares?|share price|market cap|trading|traded|nasdaq|dow jones|s&p|index|crypto|bitcoin|btc|ethereum|eth|"
    r"gold|silver|platinum|copper|oil|brent|natural gas|exchange rate|forex|dollar|euro|yen|pound|dong|vnd)\b",
    re.I,
)
WEATHER = re.compile(r"\b(weather|temperature|forecast|rain|raining|hot|cold|degrees)\b", re.I)
# a commodity is its futures contract, never a company that happens to share its name
COMMODITY = re.compile(r"\b(gold|silver|platinum|copper|oil|brent|natural gas|wheat|corn|coffee)\b", re.I)
_NOT_THE_ASSET = re.compile(
    r"\b(what(?:'s| is| are| was)?|how(?:'s| has| have| did| is| are)?|has|have|did|does|do|done|doing|the|a|an|of|in|on|for|this|last|past|next|"
    r"week|month|year|today|now|currently|current|latest|so far|ytd|price|prices|stock|stocks|share|shares|value|chart|trend|performance|"
    r"performed|trading|traded|market|cap|me|show|tell|about|research|look up|please|irene|sir|per|ounce|oz|usd|going|gone|up|down|rate)\b",
    re.I,
)
# his words for a period -> (Yahoo range, interval)
_PERIODS = (
    (re.compile(r"\btoday\b|\bright now\b|\bthis morning\b", re.I), "1d", "30m"),
    (re.compile(r"\bthis week\b|\blast (?:few|5|five) days\b|\bpast week\b", re.I), "5d", "1d"),
    (re.compile(r"\bthis year\b|\bso far this year\b|\bytd\b|\byear to date\b", re.I), "ytd", "1wk"),
    (re.compile(r"\b(?:past|last) (?:year|12 months)\b|\bover the year\b", re.I), "1y", "1wk"),
    (re.compile(r"\b(?:past|last) (?:5|five) years\b|\bdecade\b", re.I), "5y", "1mo"),
    (re.compile(r"\b(?:past|last) (?:3|three|6|six) months\b", re.I), "6mo", "1wk"),
)


@dataclass
class Series:
    title: str
    site: str
    url: str
    text: str


def wanted(question: str) -> str | None:
    """"market", "weather" or None."""
    if WEATHER.search(question) and not MARKET.search(question):
        return "weather"
    if MARKET.search(question):
        return "market"
    return None


def _period(question: str) -> tuple[str, str]:
    for pattern, rng, interval in _PERIODS:
        if pattern.search(question):
            return rng, interval
    return "1mo", "1d"


_WHEN = re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b|\b(?:19|20)\d{2}\b|\b\d+\b", re.I)


def asset_name(question: str) -> str:
    """"What's the gold price this month?" -> "gold" (live: a stray "s" from "What's"
    found the GLD fund instead). A commodity is searched by its own name alone."""
    commodity = COMMODITY.search(question)
    if commodity:
        return commodity.group(1).lower()
    name = _NOT_THE_ASSET.sub(" ", _WHEN.sub(" ", re.sub(r"[?.!,]|['’]s\b|['’]", " ", question)))
    return " ".join(w for w in name.split() if len(w) > 1)


def _thin(points: list[tuple[int, float]], n: int = MAX_POINTS) -> list[tuple[int, float]]:
    if len(points) <= n:
        return points
    keep = sorted({round(k * (len(points) - 1) / (n - 1)) for k in range(n)})
    return [points[k] for k in keep]


def _label(ts: int, interval: str, tz_offset: int) -> str:
    t = datetime.fromtimestamp(ts + tz_offset, tz=timezone.utc)
    if interval.endswith("m"):
        return t.strftime("%H:%M")
    if interval == "1mo":
        return t.strftime("%b %Y")
    return t.strftime("%b %d").replace(" 0", " ")


def _number(v: float) -> str:
    return f"{v:,.2f}" if abs(v) < 1e5 else f"{v:,.0f}"


async def market(question: str, client: httpx.AsyncClient) -> Series | None:
    name = asset_name(question)
    if not name:
        return None
    r = await client.get("https://query1.finance.yahoo.com/v1/finance/search", params={"q": name, "quotesCount": 6, "newsCount": 0})
    r.raise_for_status()
    quotes = [q for q in r.json().get("quotes", []) if q.get("symbol")]
    if COMMODITY.search(name):
        quotes.sort(key=lambda q: q.get("quoteType") != "FUTURE")
    else:
        quotes = [q for q in quotes if q.get("quoteType") in ("EQUITY", "CRYPTOCURRENCY", "INDEX", "CURRENCY", "ETF", "MUTUALFUND")] or quotes
    if not quotes:
        return None
    symbol = quotes[0]["symbol"]
    label = quotes[0].get("longname") or quotes[0].get("shortname") or symbol
    rng, interval = _period(question)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    r = await client.get(url, params={"range": rng, "interval": interval})
    r.raise_for_status()
    result = (r.json().get("chart", {}).get("result") or [None])[0]
    if not result:
        return None
    meta = result.get("meta", {})
    closes = (result.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    points = [(ts, float(c)) for ts, c in zip(result.get("timestamp") or [], closes) if c is not None]
    if len(points) < 2:
        return None
    offset = int(meta.get("gmtoffset") or 0)
    if re.search(r"\bthis month\b", question, re.I):
        # this month, not the thirty days before today
        now = datetime.now(timezone.utc)
        start = datetime(now.year, now.month, 1, tzinfo=timezone.utc).timestamp() - offset
        points = [p for p in points if p[0] >= start] if sum(p[0] >= start for p in points) >= 2 else points
    shown = _thin(points)
    currency = meta.get("currency") or ""
    every = {"30m": "every 30 minutes", "1d": "daily closes", "1wk": "weekly closes", "1mo": "monthly closes"}[interval]
    lines = [f"{label} ({symbol}), {currency}, {every}, {_label(points[0][0], '1d', offset)} to {_label(points[-1][0], '1d', offset)}:"]
    lines += [f"{_label(ts, interval, offset)}: {_number(v)}" for ts, v in shown]
    last = meta.get("regularMarketPrice")
    if isinstance(last, (int, float)):
        lines.append(f"Latest price: {_number(float(last))} {currency}")
    lo, hi = min(v for _, v in points), max(v for _, v in points)
    lines.append(f"Low over the period: {_number(lo)}; high: {_number(hi)}; change: {100 * (points[-1][1] / points[0][1] - 1):+.1f}%.")
    return Series(f"{label} - price data ({symbol})", "finance.yahoo.com", f"https://finance.yahoo.com/quote/{symbol}", "\n".join(lines))


async def weather(question: str, client: httpx.AsyncClient) -> Series | None:
    home = yaml.safe_load(HOME.read_text(encoding="utf-8")) or {}
    city = str(home.get("city", ""))
    place = re.search(r"\b(?:in|for|at)\s+([A-Z][\w'-]+(?:\s+[A-Z][\w'-]+)*)", question)
    lat, lon, name = home.get("latitude"), home.get("longitude"), city
    if place and place.group(1).lower().replace(" ", "") != city.lower().replace(" ", ""):
        g = await client.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": place.group(1), "count": 1})
        g.raise_for_status()
        found = (g.json().get("results") or [None])[0]
        if found:
            lat, lon, name = found["latitude"], found["longitude"], found["name"]
    r = await client.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": lat, "longitude": lon, "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max", "timezone": "auto", "forecast_days": 7})
    r.raise_for_status()
    d = r.json().get("daily") or {}
    days = d.get("time") or []
    if not days:
        return None
    lines = [f"Weather forecast for {name} (Open-Meteo), next {len(days)} days, highs and lows in °C, chance of rain:"]
    for k, day in enumerate(days):
        label = datetime.strptime(day, "%Y-%m-%d").strftime("%a %b %d").replace(" 0", " ")
        lines.append(f"{label}: high {d['temperature_2m_max'][k]}, low {d['temperature_2m_min'][k]}, rain {d['precipitation_probability_max'][k]}%")
    return Series(f"Weather forecast - {name}", "open-meteo.com", "https://open-meteo.com", "\n".join(lines))


async def fetch(question: str) -> Series | None:
    """The real series for `question`, or None (not that kind of question, or not found)."""
    kind = wanted(question)
    if kind is None:
        return None
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, headers=UA, follow_redirects=True) as client:
            found = await (market(question, client) if kind == "market" else weather(question, client))
    except Exception as error:  # noqa: BLE001 - no data is fine: she says she couldn't get it
        log.info("series for %r: none (%s: %s)", question, type(error).__name__, error)
        return None
    log.info("series for %r: %s in %.1fs", question, found.title if found else "none", time.perf_counter() - started)
    return found
