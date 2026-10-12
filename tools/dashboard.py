"""The second screen's sources, and opening one of its items for him.

News (RSS headlines), weather (Open-Meteo, his home from config/home.yaml), stock
quotes (Yahoo chart data, the same source as tools/series.py), system load
(tools/system.py) and his timers. Read-only reads of public data; nothing he
says or has leaves the machine. Headlines are outside text: shown and opened,
never acted on.

ITEMS is what the dashboard shows right now (core/irene/dashboard.py keeps it):
"open the second news item" is resolved against it, and a click is only honoured
for a link that is on it.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
import yaml

from .registry import ToolContext, ToolError, tool
from tools.localconfig import personal

log = logging.getLogger("irene.tools")

CONFIG = Path(__file__).resolve().parents[1] / "config" / "dashboard.yaml"
HOME = personal("home.yaml")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"}
TIMEOUT_S = 8.0
# weather: the days before today Open-Meteo also gives, and what counts as a wet day
PAST_DAYS = 3
RAIN_DAY_MM = 1.0
SECTIONS = ("news", "weather", "stocks")
# the window a "today's story" must fall in
NEWS_WINDOW_H = 24

# section -> the items on screen, in order: {"title", "url", ...}
ITEMS: dict[str, list[dict]] = {s: [] for s in SECTIONS}
# called with (section, number) when he opens an item by voice: the panel brings
# that card to its centre and holds it there (core/irene/dashboard.py)
FOCUS_HOOKS: list = []

WMO = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Fog", 51: "Drizzle", 53: "Drizzle",
       55: "Drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain", 80: "Showers", 81: "Showers", 82: "Heavy showers",
       95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm"}


def config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT_S, headers=UA, follow_redirects=True)


def _text(node, tag: str) -> str:
    found = node.find(tag)
    return html.unescape(re.sub(r"<[^>]+>", "", (found.text or "") if found is not None else "")).strip()


def parse_feed(xml: str, source: str) -> list[dict]:
    """RSS 2.0 or Atom -> [{"title", "url", "source", "at"}]."""
    root = ET.fromstring(xml)
    out = []
    for item in root.iter("item"):
        title, url = _text(item, "title"), _text(item, "link")
        if title and url.startswith("http"):
            out.append({"title": title, "url": url, "source": source, "at": _text(item, "pubDate")})
    atom = "{http://www.w3.org/2005/Atom}"
    for entry in root.iter(f"{atom}entry"):
        link = entry.find(f"{atom}link")
        url = link.get("href", "") if link is not None else ""
        title = _text(entry, f"{atom}title")
        if title and url.startswith("http"):
            out.append({"title": title, "url": url, "source": source, "at": _text(entry, f"{atom}updated")})
    return out


def _when(text: str, tz=timezone.utc) -> datetime | None:
    """A feed's date (RSS pubDate, Atom ISO, or Tuổi Trẻ's "10/6/2026 12:02:00 AM")
    as an aware datetime; one with no zone is in `tz` (the outlet's own)."""
    from email.utils import parsedate_to_datetime

    text = (text or "").strip()
    if not text:
        return None
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            when = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                when = datetime.strptime(text, "%m/%d/%Y %I:%M:%S %p")
            except ValueError:
                return None
    return when if when.tzinfo else when.replace(tzinfo=tz)


_STOP = set("""a an the and or but of in on at to for from by with as is are was were be been being has have had
it its this that these those after before over under into out up down off about than then there their his her
they them he she we you i our your who what when where why how will would can could may might says say said
new news live latest update video watch more after amid says""".split())


def _keywords(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9][a-z0-9'\-]+", title.lower())
    return {w.rstrip("s") if len(w) > 4 else w for w in words if w not in _STOP and len(w) > 2}


def top_stories(feeds: list[tuple[str, list[dict]]], want: int, now: datetime | None = None, keywords=None) -> list[dict]:
    """The day's biggest stories: every outlet's last 24 h, headlines about the same
    story grouped (shared key words), groups ranked by how many outlets carry it -
    the measure of 'big' - then by how fresh; one story per group, from the first
    outlet in the configured order that has it. `keywords`: how a headline's key
    words are found (English by default; Vietnamese pairs its syllables)."""
    keywords = keywords or _keywords
    now = now or datetime.now(timezone.utc)
    order = {name: k for k, (name, _) in enumerate(feeds)}
    items = []
    for name, entries in feeds:
        for e in entries:
            when = _when(e.get("at", ""))
            if when is None or (now - when).total_seconds() > NEWS_WINDOW_H * 3600:
                continue
            items.append({**e, "when": when, "words": keywords(e["title"])})
    items.sort(key=lambda e: e["when"], reverse=True)
    groups: list[dict] = []
    for e in items:
        best, overlap = None, 0.0
        for g in groups:
            shared = len(e["words"] & g["words"])
            score = shared / max(1, min(len(e["words"]), len(g["words"])))
            if shared >= 3 or (shared >= 2 and score >= 0.4):
                if score > overlap:
                    best, overlap = g, score
        if best is None:
            groups.append({"items": [e], "words": set(e["words"]), "sources": {e["source"]}, "newest": e["when"]})
        else:
            best["items"].append(e)
            best["words"] |= e["words"]
            best["sources"].add(e["source"])
    groups.sort(key=lambda g: (len(g["sources"]), g["newest"]), reverse=True)
    out = []
    for g in groups[:want]:
        lead = min(g["items"], key=lambda e: (order.get(e["source"], 99), -e["when"].timestamp()))
        others = sorted(g["sources"] - {lead["source"]}, key=lambda n: order.get(n, 99))
        out.append({"title": lead["title"], "url": lead["url"], "source": lead["source"],
                    "at": lead["when"].isoformat(), "also": others})
    return out


async def news() -> list[dict]:
    cfg = config().get("news") or {}
    feeds = cfg.get("feeds") or []
    want = int(cfg.get("items", 4))
    async with _client() as client:
        async def one(feed):
            try:
                r = await client.get(feed["url"])
                r.raise_for_status()
                return feed["name"], parse_feed(r.text, feed["name"])
            except Exception as error:  # noqa: BLE001 - one feed down: the others still count
                log.info("dashboard news %s: %s", feed.get("name"), error)
                return feed["name"], []

        fetched = await asyncio.gather(*(one(f) for f in feeds))
        out = top_stories(list(fetched), want)
        log.info("dashboard news: %d outlets, top stories %s", sum(1 for _, e in fetched if e),
                 "; ".join(f"{o['title'][:40]} ({1 + len(o['also'])} outlets)" for o in out))
        # each story's picture, from the article's own metadata
        thumbs = await asyncio.gather(*(thumbnail(item["url"], client) for item in out))
    for item, thumb in zip(out, thumbs):
        if thumb:
            item["image"] = thumb
    return out


# article url -> its thumbnail (data: URI), or "" when it has none: fetched once
_THUMBS: dict[str, str] = {}
_META_IMAGE = re.compile(
    r"""<meta[^>]+(?:property|name)=["'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["'][^>]*>""", re.I)
_CONTENT = re.compile(r"""content=["']([^"']+)["']""", re.I)
THUMB_W = 640


async def thumbnail(url: str, client: httpx.AsyncClient) -> str:
    """The article's own picture (og:image / twitter:image in its page head), small,
    as a data: URI - the HUD never loads a remote image."""
    if url in _THUMBS:
        return _THUMBS[url]
    found = ""
    try:
        r = await client.get(url)
        r.raise_for_status()
        head = r.text[:200_000]
        meta = _META_IMAGE.search(head)
        image = _CONTENT.search(meta.group(0)).group(1) if meta and _CONTENT.search(meta.group(0)) else ""
        if image:
            image = html.unescape(image)
            if image.startswith("//"):
                image = "https:" + image
            img = await client.get(httpx.URL(url).join(image))
            img.raise_for_status()
            found = await asyncio.to_thread(_shrink, img.content)
    except Exception as error:  # noqa: BLE001 - no picture: the story still shows
        log.info("dashboard thumbnail %s: %s", url[:80], error)
    _THUMBS[url] = found
    return found


def _shrink(data: bytes, width: int = THUMB_W) -> str:
    import base64
    import io

    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("RGB")
        if im.width > width:
            im = im.resize((width, round(im.height * width / im.width)))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=78)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


async def weather() -> dict | None:
    home = yaml.safe_load(HOME.read_text(encoding="utf-8")) or {}
    params = {
        "latitude": home.get("latitude"), "longitude": home.get("longitude"), "timezone": "auto", "forecast_days": 4,
        # the days before today too: how many days running it has rained (her greeting)
        "past_days": PAST_DAYS,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,precipitation",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code,precipitation_sum",
    }
    async with _client() as client:
        r = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
        r.raise_for_status()
        data = r.json()
    now, d = data.get("current") or {}, data.get("daily") or {}
    city = str(home.get("city", ""))
    times = d.get("time") or []
    days = [
        {
            "day": datetime.strptime(t, "%Y-%m-%d").strftime("%a"),
            "high": round(d["temperature_2m_max"][k]), "low": round(d["temperature_2m_min"][k]),
            "rain": d["precipitation_probability_max"][k], "sky": WMO.get(d["weather_code"][k], ""),
            "mm": (d.get("precipitation_sum") or [None] * len(times))[k],
        }
        for k, t in enumerate(times)
    ]
    past, days = days[: min(PAST_DAYS, len(days))], days[min(PAST_DAYS, len(days)) :]
    yesterday = {k: past[-1][k] for k in ("high", "low", "sky")} if past else None
    sky = WMO.get(now.get("weather_code"), "")
    return {
        "title": f"Weather in {city}", "city": city,
        "temp": round(now.get("temperature_2m", 0)), "feels": round(now.get("apparent_temperature", 0)),
        "humidity": now.get("relative_humidity_2m"), "wind": now.get("wind_speed_10m"), "sky": sky,
        "days": days, "yesterday": yesterday, "rain_streak": rain_streak(past, days[0] if days else None, sky, now.get("precipitation")),
        "url": f"https://www.google.com/search?q={quote('weather ' + city)}",
    }


def rain_streak(past: list[dict], today: dict | None, sky_now: str, mm_now: float | None) -> int:
    """Days running with rain, today included - 0 when it isn't raining today. A
    day counts with RAIN_DAY_MM or more measured (Open-Meteo's daily sum)."""
    wet_now = bool(re.search(r"rain|drizzle|shower|thunder", sky_now or "", re.I)) or (mm_now or 0) > 0
    wet_today = wet_now or (today is not None and (today.get("mm") or 0) >= RAIN_DAY_MM)
    if not wet_today:
        return 0
    n = 1
    for day in reversed(past):
        if (day.get("mm") or 0) < RAIN_DAY_MM:
            break
        n += 1
    return n


async def stocks() -> list[dict]:
    return await quotes((config().get("stocks") or {}).get("symbols") or [])


async def quotes(symbols: list[dict]) -> list[dict]:
    """Yahoo chart data for each {symbol, name}: price, the DAY's change in percent
    (Yahoo's own regularMarketChangePercent - the chart's first close is five days
    back), the last few days' closes."""
    async with _client() as client:
        async def one(s):
            try:
                r = await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{s['symbol']}", params={"range": "5d", "interval": "30m"})
                r.raise_for_status()
                result = r.json()["chart"]["result"][0]
                meta = result["meta"]
                closes = [c for c in (result["indicators"]["quote"][0].get("close") or []) if c is not None]
                price = float(meta.get("regularMarketPrice") or closes[-1])
                day = meta.get("regularMarketChangePercent")
                if day is None:
                    # no day change given: against the last close before today's
                    daily = [c for c in closes[:-1]] or closes
                    prev = float(meta.get("previousClose") or daily[-1])
                    day = 100 * (price / prev - 1) if prev else 0.0
                return {
                    "title": s.get("name") or s["symbol"], "symbol": s["symbol"], "price": price, "currency": meta.get("currency", ""),
                    "change": float(day), "spark": [round(c, 2) for c in closes[-40:]],
                    "url": f"https://finance.yahoo.com/quote/{quote(s['symbol'])}",
                }
            except Exception as error:  # noqa: BLE001
                log.info("dashboard stock %s: %s", s.get("symbol"), error)
                return None

        found = await asyncio.gather(*(one(s) for s in symbols))
    return [f for f in found if f]



def pick(section: str, number: int) -> dict:
    items = ITEMS.get(section) or []
    if not items:
        raise ToolError(f"there is nothing under {section} on the dashboard yet")
    index = number - 1 if number > 0 else len(items) + number
    if not 0 <= index < len(items):
        raise ToolError(f"the dashboard has {len(items)} {section} item(s), not {number}")
    return items[index]


def allowed(url: str) -> bool:
    return any(item.get("url") == url for items in ITEMS.values() for item in items)


@tool(
    "open_dashboard_item",
    "Open an item from the dashboard on his second screen in HIS Chrome: a news story, the weather, a stock. "
    "'open the second news item' = section news, number 2; 'the last headline' = number -1; 'open the weather' = weather, 1.",
    {
        "type": "object",
        "properties": {
            "section": {"type": "string", "enum": list(SECTIONS), "description": "which part of the dashboard"},
            "number": {"type": "integer", "description": "1 = first/top item, 2 = second, ... -1 = last"},
        },
        "required": ["section"],
    },
    readonly=False,
    cue="globe",
)
async def open_dashboard_item(_ctx: ToolContext, section: str, number: int = 1) -> str:
    from .browser import open_in_his_chrome

    if section not in SECTIONS:
        raise ToolError(f"the dashboard has no {section!r} section")
    item = pick(section, int(number))
    for hook in FOCUS_HOOKS:
        hook(section, int(number))
    open_in_his_chrome(item["url"])
    return f"opened {section} item {number} in his Chrome: {item.get('title', '')[:100]}"
