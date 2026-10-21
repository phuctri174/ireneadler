# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""daily_briefing(): "what's new today" - the few things actually worth his ear.

Five sources, all real, all read-only fetches of public data (nothing he says
leaves the machine):

  weather   Open-Meteo for his city (tools/dashboard.weather): today's sky,
            high/low, rain chance, how many days running it has rained
  gold      SJC's own price service (sjc.com.vn): the SJC gold bar ("Vàng SJC
            1L, 10L, 1KG", Hồ Chí Minh), buy/sell in VND per lượng, and its
            change against the previous day's last price. This is what he means
            by gold - never XAU/USD spot.
  markets   Yahoo chart data: the panel's tickers (config/dashboard.yaml) plus
            USD/VND - the day's change (regularMarketChangePercent)
  world     the panel's international ranking: every outlet's last 24 h, the
            same story grouped across outlets, ranked by how many carry it
  vietnam   the same ranking over Vietnamese outlets (VnExpress, Tuổi Trẻ,
            Thanh Niên, VietnamNet, Dân Trí), the headlines put into English
            by her own local model (TRANSLATE, set by core)

Each candidate gets a notability score (how far it moved, how many outlets lead
with it, how unusual the weather is); anything that hasn't moved is dropped,
and the top MAX_ITEMS are spoken - one sentence each, the most notable first -
while the whole briefing goes to the panel. A source that fails is said to have
failed; a number is never guessed. Readings are cached CACHE_S, so asking twice
doesn't fetch twice.

"Tell me more about the second one" = daily_briefing(expand=2): that item's
full detail (for a story, the article's own summary), and its card on the panel.

LAST is the briefing just given: core/irene/fast.py speaks it, brain.py draws
its board (core/irene/drawing.sections).
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timedelta, timezone

from . import dashboard as data
from .registry import ToolContext, ToolError, ToolResult, tool

log = logging.getLogger("irene.tools.briefing")

VN = timezone(timedelta(hours=7))
CACHE_S = 15 * 60
MAX_ITEMS = 3
# a story or a price on the panel: this many of each
PANEL_STORIES = 4
# below these, a move is a flat day - not reported (percent)
FLAT = {"stock": 0.5, "index": 0.3, "crypto": 1.0, "fx": 0.1}
# how big a move is "big" for each kind (percent): a move this size scores 3
TYPICAL = {"stock": 1.5, "index": 1.0, "crypto": 3.0, "fx": 0.3}
GOLD_TYPICAL_PCT = 0.3
SJC_SERVICE = "https://sjc.com.vn/GoldPrice/Services/PriceService.ashx"
SJC_PAGE = "https://sjc.com.vn/"
# the SJC gold bar, as SJC names it, and the branch quoted
SJC_BAR = "Vàng SJC 1L, 10L, 1KG"
SJC_BRANCH = "Hồ Chí Minh"
SJC_DAYS = 14
EXTRA_SYMBOLS = [{"symbol": "VND=X", "name": "USD/VND"}]
VN_FEEDS = [
    {"name": "VnExpress", "url": "https://vnexpress.net/rss/tin-moi-nhat.rss"},
    {"name": "Tuổi Trẻ", "url": "https://tuoitre.vn/rss/tin-moi-nhat.rss"},
    {"name": "Thanh Niên", "url": "https://thanhnien.vn/rss/home.rss"},
    {"name": "VietnamNet", "url": "https://vietnamnet.vn/rss/thoi-su.rss"},
    {"name": "Dân Trí", "url": "https://dantri.com.vn/rss/home.rss"},
]

# set by core: async (list of Vietnamese headlines) -> the same in English, or None
TRANSLATE = None
# the briefing just given (what "the second one" means)
LAST: "Briefing | None" = None
_CACHE: dict[str, tuple[float, object]] = {}
# Vietnamese headline -> its English (a headline is translated once), and how many
# headlines her model has translated in all
_TRANSLATED: dict[str, str] = {}
TRANSLATIONS_RUN = [0]


# ---- the pieces ---------------------------------------------------------------------------------


@dataclass
class Item:
    kind: str  # weather | gold | market | world | vietnam
    header: str  # the board's section header: GOLD, NVDA, his city, the story's subject
    score: float
    say: str  # the one sentence she says
    # the board section (drawing.Section fields): chart / sky / story
    board: dict = field(default_factory=dict)
    detail: str = ""
    url: str = ""


@dataclass
class Briefing:
    at: str
    items: list[Item]  # the spoken ones, most notable first
    failed: list[str]  # sources that didn't answer
    flat: list[str]  # sources that answered with nothing worth saying
    content: dict  # the panel's full briefing
    speech: list[str]  # every sentence, in order
    data: dict = field(default_factory=dict)


async def _cached(name: str, fetch, fresh_s: float = CACHE_S):
    hit = _CACHE.get(name)
    if hit and time.monotonic() - hit[0] < fresh_s:
        return hit[1]
    value = await fetch()
    _CACHE[name] = (time.monotonic(), value)
    return value


async def prefetch(margin_s: float = 120.0) -> int:
    """Core, while she is idle: every reading that would expire within `margin_s`
    fetched again, so "what's new" never waits on the network or a translation.
    Returns how many headlines her model translated (it then re-reads the
    conversation: a translation pushes it out of Ollama's prompt cache)."""
    before = TRANSLATIONS_RUN[0]
    for name in SOURCES:
        try:
            await _cached(name, SOURCES[name], CACHE_S - margin_s)
        except Exception as error:  # noqa: BLE001 - tried again when he asks
            log.info("briefing prefetch %s: %s", name, error)
    await read_ahead()
    return TRANSLATIONS_RUN[0] - before


def clear_cache() -> None:
    _CACHE.clear()


# ---- gold: SJC ------------------------------------------------------------------------------------


def _sjc_when(raw: str) -> datetime | None:
    m = re.search(r"Date\((-?\d+)\)", raw or "")
    if not m or int(m.group(1)) <= 0:
        return None
    return datetime.fromtimestamp(int(m.group(1)) / 1000, VN)


def parse_sjc(rows: list[dict], now: datetime | None = None) -> dict:
    """SJC's history rows -> the bar's latest buy/sell, the change against the
    previous day's last price, daily closes. Raises ValueError with no bar rows."""
    now = (now or datetime.now(VN)).astimezone(VN)
    bar = []
    for r in rows:
        when = _sjc_when(str(r.get("GroupDate", "")))
        if when is None or not str(r.get("TypeName", "")).startswith("Vàng SJC 1L"):
            continue
        if r.get("BranchName") and r["BranchName"] != SJC_BRANCH:
            continue
        buy, sell = float(r.get("BuyValue") or 0), float(r.get("SellValue") or 0)
        if buy > 0 and sell > 0:
            bar.append((when, buy, sell))
    if not bar:
        raise ValueError("no SJC bar price in the reply")
    bar.sort(key=lambda b: b[0])
    when, buy, sell = bar[-1]
    before = [b for b in bar if b[0].date() < when.date()]
    prev = before[-1] if before else None
    # the day's closes, oldest first (the board's chart)
    closes: dict = {}
    for b in bar:
        closes[b[0].date()] = b
    series = [(d.strftime("%b %d"), b[2]) for d, b in sorted(closes.items())][-8:]
    today = when.date() == now.date()
    change_sell = (sell - prev[2]) if (prev and today) else 0.0
    change_buy = (buy - prev[1]) if (prev and today) else 0.0
    window = [b[2] for b in bar if (when - b[0]).days <= SJC_DAYS]
    low = sell <= min(window) and len(closes) >= 7 and change_sell < 0
    high = sell >= max(window) and len(closes) >= 7 and change_sell > 0
    return {
        "buy": buy, "sell": sell, "change_buy": change_buy, "change_sell": change_sell,
        "pct": 100 * change_sell / prev[2] if (prev and today) else 0.0,
        "at": when.strftime("%H:%M %d/%m/%Y"), "today": today, "updated": when,
        "previous": prev[2] if prev else None, "series": series,
        "two_week_low": low, "two_week_high": high,
        "source": "sjc.com.vn", "url": SJC_PAGE, "name": SJC_BAR,
    }


def _curl_post(url: str, form: dict) -> str:
    """POST through Windows' own curl.exe: SJC sits behind Cloudflare, which turns
    away Python's TLS handshake (403 "Just a moment...") but not curl's."""
    import shutil
    import subprocess
    from urllib.parse import urlencode

    exe = Path(r"C:\Windows\System32\curl.exe")
    curl = str(exe) if exe.exists() else shutil.which("curl")
    if not curl:
        raise RuntimeError("no curl to reach SJC with")
    done = subprocess.run(
        [curl, "-s", "-m", str(int(data.TIMEOUT_S + 4)), "-A", data.UA["User-Agent"], "-X", "POST", url, "-d", urlencode(form)],
        capture_output=True, timeout=data.TIMEOUT_S + 8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if done.returncode != 0:
        raise RuntimeError(f"curl exit {done.returncode}")
    return done.stdout.decode("utf-8", "replace")


async def gold(now: datetime | None = None) -> dict:
    """The SJC gold bar, from SJC itself - else today's price from giavang.org
    (which publishes SJC's buy/sell), with no day change claimed."""
    import json

    now = (now or datetime.now(VN)).astimezone(VN)
    form = {
        "method": "GetGoldPriceHistory", "goldPriceId": "1",
        "fromDate": (now - timedelta(days=SJC_DAYS)).strftime("%d/%m/%Y"), "toDate": now.strftime("%d/%m/%Y"),
    }
    try:
        body = json.loads(await asyncio.to_thread(_curl_post, SJC_SERVICE, form))
        if not body.get("success"):
            raise ValueError("SJC said no")
        found = parse_sjc(body.get("data") or [], now)
    except Exception as error:  # noqa: BLE001 - the second source, price only
        log.warning("briefing gold: SJC itself failed (%s: %s) - trying giavang.org", type(error).__name__, error)
        found = await gold_fallback()
    log.info("briefing gold: %s sell %.0f buy %.0f, change %+.0f (%s)", found["source"], found["sell"], found["buy"], found["change_sell"], found["at"])
    return found


GOLD_FALLBACK = "https://giavang.org/trong-nuoc/sjc/"
_FALLBACK_ROW = re.compile(r"(Mua vào|Bán ra)\s*\|\s*([\d.]+)\s*\|\s*x1000đ/lượng", re.I)


def parse_fallback(page: str) -> dict:
    """giavang.org's SJC bar ("Giá vàng Miếng"): buy and sell, x1000 VND a lượng."""
    i = page.find("Giá vàng Miếng")
    if i < 0:
        raise ValueError("no SJC bar row on giavang.org")
    text = re.sub(r"(\s*\|\s*)+", " | ", re.sub(r"<[^>]+>", " | ", page[i : i + 3000]))
    rows = {m.group(1).lower(): float(m.group(2).replace(".", "")) * 1000 for m in _FALLBACK_ROW.finditer(text)}
    if "mua vào" not in rows or "bán ra" not in rows:
        raise ValueError("SJC buy/sell not found on giavang.org")
    when = re.search(r"Cập nhật lúc ([\d:]+ [\d/]+)", page)
    return {
        "buy": rows["mua vào"], "sell": rows["bán ra"], "change_buy": 0.0, "change_sell": 0.0, "pct": 0.0,
        "at": when.group(1) if when else "", "today": False, "updated": None, "previous": None, "series": [],
        "two_week_low": False, "two_week_high": False, "source": "giavang.org", "url": GOLD_FALLBACK, "name": SJC_BAR,
        "no_change": True,
    }


async def gold_fallback() -> dict:
    async with data._client() as client:
        r = await client.get(GOLD_FALLBACK)
        r.raise_for_status()
        return parse_fallback(r.text)


# ---- markets -------------------------------------------------------------------------------------


def _kind(symbol: str) -> str:
    if symbol.startswith("^"):
        return "index"
    if symbol.endswith("-USD"):
        return "crypto"
    if symbol.endswith("=X"):
        return "fx"
    return "stock"


async def markets() -> list[dict]:
    symbols = list((data.config().get("stocks") or {}).get("symbols") or []) + EXTRA_SYMBOLS
    found = await data.quotes(symbols)
    for q in found:
        q["kind"] = _kind(q["symbol"])
    return found


# ---- news ----------------------------------------------------------------------------------------

_VI_STOP = set("""và của là có được cho trong với người một các những này khi đã sẽ không về tại từ ra vào lên theo sau trước đến
bị nhiều hơn vì để đang còn như thì mà nên cũng rất đó nay ngày hôm năm tháng mới gì sao thế nào ai đâu bao hay hoặc
tin video ảnh clip vụ việc""".split())


def vi_keywords(title: str) -> set[str]:
    """A Vietnamese headline's key phrases: its syllables in pairs (most words are
    two syllables), leaving out the little ones - so two outlets' headlines about
    the same story share them."""
    syl = [w for w in re.findall(r"\w+", title.lower()) if not w.isdigit() or len(w) >= 3]
    words = set()
    for a, b in zip(syl, syl[1:]):
        if a in _VI_STOP or b in _VI_STOP:
            continue
        words.add(f"{a} {b}")
    words |= {w for w in syl if w.isdigit()}
    return words


async def vietnam_news() -> list[dict]:
    """The day's biggest Vietnamese stories, ranked across outlets, in English."""
    async with data._client() as client:
        async def one(feed):
            try:
                r = await client.get(feed["url"])
                r.raise_for_status()
                entries = data.parse_feed(r.text, feed["name"])
                for e in entries:
                    when = data._when(e.get("at", ""), VN)
                    e["at"] = when.isoformat() if when else ""
                return feed["name"], entries
            except Exception as error:  # noqa: BLE001 - one outlet down: the others still count
                log.info("briefing vietnam %s: %s", feed["name"], error)
                return feed["name"], []

        fetched = await asyncio.gather(*(one(f) for f in VN_FEEDS))
        if not any(entries for _, entries in fetched):
            raise RuntimeError("no Vietnamese outlet answered")
        # a couple spare: two groups about one story merge once in English (below)
        out = data.top_stories(list(fetched), PANEL_STORIES + 2, keywords=vi_keywords)
        thumbs = await asyncio.gather(*(data.thumbnail(item["url"], client) for item in out))
    for item, thumb in zip(out, thumbs):
        if thumb:
            item["image"] = thumb
        item["original"] = item["title"]
    english = None
    if TRANSLATE is not None and out:
        # only headlines not seen before go to the model (a headline stays up for hours)
        todo = [o["title"] for o in out if o["title"] not in _TRANSLATED]
        try:
            if todo:
                done = await TRANSLATE(todo)
                TRANSLATIONS_RUN[0] += len(todo)
                if done and len(done) == len(todo):
                    _TRANSLATED.update(zip(todo, done))
            english = [_TRANSLATED[o["title"]] for o in out] if all(o["title"] in _TRANSLATED for o in out) else None
        except Exception as error:  # noqa: BLE001 - shown untranslated, and said so
            log.warning("briefing: translating the Vietnamese headlines failed: %s", error)
    if english and len(english) == len(out):
        for item, en in zip(out, english):
            item["title"] = str(en).strip() or item["title"]
            item["english"] = True
        # the same match written two ways ("Vietnam - Malaysia", "Malaysia vs Vietnam
        # preview"): one story, its outlets together
        kept: list[dict] = []
        for item in out:
            twin = next((k for k in kept if len(data._keywords(k["title"]) & data._keywords(item["title"])) >= 2), None)
            if twin is None:
                kept.append(item)
            else:
                twin["also"] = sorted(set(twin["also"]) | {item["source"], *item["also"]} - {twin["source"]})
        out = sorted(kept, key=lambda o: -len(o["also"]))
    out = out[:PANEL_STORIES]
    log.info("briefing vietnam: %d outlets, top %s", sum(1 for _, e in fetched if e),
             "; ".join(f"{o['title'][:40]} ({1 + len(o['also'])})" for o in out))
    return out


async def world_news() -> list[dict]:
    found = await data.news()
    if not found:
        raise RuntimeError("no headlines from any feed")
    return found


# ---- what's notable ------------------------------------------------------------------------------

_STORM = re.compile(r"\b(storm|typhoon|flood|floods|flooding|landslide|rain|cyclone|hurricane|tornado)\b", re.I)
_DANGER = re.compile(r"\b(war|attack|attacks|killed|kill|dead|deaths?|crash|fire|blast|explosion|shooting|strike|strikes|missile|earthquake|quake)\b", re.I)
_DEAL = re.compile(r"\b(deal|agree|agreement|agrees|signs?|signed|wins?|won|elected|approves?|approved|passes|passed|peace|ceasefire|truce)\b", re.I)
_HEALTH = re.compile(r"\b(health|hospital|virus|outbreak|vaccine|disease|covid|flu|patients?)\b", re.I)
_STOP_EN = set("""a an the and or but of in on at to for from by with as is are was were be been has have had it its this that
after before over under into out up down off about than then there their his her they them he she we you i our your who
what when where why how will would can could may might says say said new news live latest update video watch more amid
says year years day days first last two three one people""".split())


def story_icon(title: str) -> str:
    """A generic board icon for a headline (hud/src/board/icons.ts)."""
    if _STORM.search(title):
        return "storm"
    if _DANGER.search(title):
        return "warning"
    if _HEALTH.search(title):
        return "heart"
    if _DEAL.search(title):
        return "check"
    return "star"


_LEAD_IN = re.compile(r"^\s*(?:watch|live|video|in pictures|explainer|analysis|opinion|breaking|update)\s*[:|-]\s*", re.I)


def clean_title(title: str) -> str:
    """A headline as she says it: no "Watch:" / "Live:" in front, no full stop."""
    return _LEAD_IN.sub("", " ".join(title.split())).rstrip(". ")


def story_words(title: str, n: int = 3) -> list[str]:
    """Two or three key words of a headline: its names first ("Spain"), then its
    content words in order - not a past-tense verb ("resulted")."""
    tokens = re.findall(r"[A-Za-z][\w'’.-]*", clean_title(title))
    names: list[str] = []
    run: list[str] = []
    for tok in [*tokens, "."]:
        word = re.sub(r"['’]s$", "", tok).strip(".'’")
        if word[:1].isupper() and word.lower() not in _STOP_EN and len(word) > 1:
            run.append(word)
            continue
        if run:
            names.append(" ".join(run[:2]))
            run = []
    words = [w for w in (re.sub(r"['’]s$", "", t).strip(".'’") for t in tokens)
             if len(w) >= 5 and w.lower() not in _STOP_EN and not re.search(r"(?:ed|ly)$", w) and not w[:1].isupper()]
    out: list[str] = []
    for w in [*names, *words]:
        if len(out) >= n:
            break
        if not any(w.lower() in o.lower() or o.lower() in w.lower() for o in out):
            out.append(w)
    return out


def subject(title: str) -> str:
    """The story's subject, short, for the section header."""
    words = story_words(title, 1)
    return words[0] if words else "NEWS"


def _vnd(v: float) -> str:
    """143,500,000 -> "143.5 million"; 200,000 -> "200,000"."""
    a = abs(v)
    if a >= 1e6:
        s = f"{a / 1e6:.1f}".rstrip("0").rstrip(".")
        return f"{s} million"
    return f"{a:,.0f}"


def _vnd_short(v: float) -> str:
    """For the board: 143.5M, 200K."""
    a = abs(v)
    return (f"{a / 1e6:.1f}".rstrip("0").rstrip(".") + "M") if a >= 1e6 else f"{a / 1e3:.0f}K"


def _pct(v: float) -> str:
    return f"{abs(v):.1f}".rstrip("0").rstrip(".") + " percent"


def _money(price: float, currency: str) -> str:
    if currency == "USD":
        return f"{price:,.2f} dollars" if price < 1000 else f"{price:,.0f} dollars"
    if currency == "VND":
        return f"{price:,.0f} dong"
    return f"{price:,.0f}"


def gold_item(g: dict) -> Item | None:
    change = g["change_sell"]
    if not g["today"] or change == 0:
        return None
    up = change > 0
    extra = " - the lowest in two weeks" if g["two_week_low"] else " - the highest in two weeks" if g["two_week_high"] else ""
    say = (f"Gold's up {_vnd(change)} a lượng - SJC is selling at {_vnd(g['sell'])}{extra}." if up
           else f"Gold's down {_vnd(change)} a lượng, to {_vnd(g['sell'])} at SJC{extra}.")
    score = 1.0 + 3 * abs(g["pct"]) / GOLD_TYPICAL_PCT + (1.5 if extra else 0)
    return Item("gold", "GOLD", score, say, {
        "kind": "chart", "points": g["series"], "up": up, "change": ("+" if up else "-") + _vnd_short(change), "value": _vnd_short(g["sell"]),
    }, gold_detail(g), g["url"])


def gold_detail(g: dict) -> str:
    move = (f"{'up' if g['change_sell'] > 0 else 'down'} {_vnd(g['change_sell'])} on the day" if g["change_sell"]
            else "the day's change not known (SJC's own service didn't answer; price from giavang.org)" if g.get("no_change")
            else f"unchanged today (last update {g['at']})")
    if not g["series"]:
        return f"SJC gold bar ({g['name']}), from {g['source']} at {g['at']}: buy {_vnd(g['buy'])}, sell {_vnd(g['sell'])} dong per lượng, {move}."
    week = ", ".join(f"{d} {_vnd(v)}" for d, v in g["series"][-5:])
    return (f"SJC gold bar ({g['name']}, {SJC_BRANCH}), from sjc.com.vn at {g['at']}: SJC buys at {_vnd(g['buy'])} and sells at "
            f"{_vnd(g['sell'])} dong per lượng, {move}. Recent closing sell prices: {week}.")


_NAMES = {"^GSPC": "the S&P 500", "BTC-USD": "Bitcoin", "VND=X": "the dollar"}


def market_item(q: dict) -> Item | None:
    kind, change = q["kind"], q["change"]
    if abs(change) < FLAT[kind]:
        return None
    up = change > 0
    name = _NAMES.get(q["symbol"], q["title"])
    big = abs(change) >= 2 * TYPICAL[kind]
    if kind == "fx":
        say = f"The dollar's {'up' if up else 'down'} {_pct(change)} against the dong, at {q['price']:,.0f}."
    elif kind == "crypto":
        say = f"{name}'s {'up' if up else 'down'} {_pct(change)}, at about {_money(q['price'], q['currency'])}."
    elif up:
        say = f"{name} {'jumped' if big else 'gained'} {_pct(change)}" + (f", to {_money(q['price'], q['currency'])}." if kind == "stock" else ".")
    else:
        say = (f"{name} had a rough night - down {_pct(change)}." if big and kind == "stock"
               else f"{name} slipped {_pct(change)}" + (f", to {_money(q['price'], q['currency'])}." if kind == "stock" else "."))
    say = say[0].upper() + say[1:]
    header = {"^GSPC": "S&P 500", "BTC-USD": "BTC", "VND=X": "USD/VND"}.get(q["symbol"], q["symbol"])
    score = 3 * abs(change) / TYPICAL[kind]
    points = [(str(k), v) for k, v in enumerate(q.get("spark") or [])]
    detail = (f"{q['title']} ({q['symbol']}) at {_money(q['price'], q['currency'])}, {'up' if up else 'down'} {_pct(change)} on the day "
              f"(Yahoo Finance chart data). Last 5 days' range: {min(q.get('spark') or [q['price']]):,.2f} to {max(q.get('spark') or [q['price']]):,.2f}.")
    return Item("market", header, score, say, {
        "kind": "chart", "points": points, "up": up, "change": f"{'+' if up else '-'}{abs(change):.1f}%", "value": _short_price(q["price"]),
    }, detail, q.get("url", ""))


def _short_price(v: float) -> str:
    return f"{v / 1e3:.1f}K" if v >= 10_000 else f"{v:,.0f}" if v >= 1000 else f"{v:.2f}".rstrip("0").rstrip(".")


_RAINY = re.compile(r"rain|drizzle|shower|thunder", re.I)


def weather_item(w: dict) -> Item | None:
    days = w.get("days") or []
    if not days:
        return None
    today = days[0]
    sky, chance = today.get("sky", ""), today.get("rain") or 0
    city = w.get("city", "")
    streak = int(w.get("rain_streak") or 0)
    yesterday = w.get("yesterday") or {}
    score, why = 0.0, ""
    if chance >= 70 or _RAINY.search(w.get("sky", "")):
        score = 3.0 + (1.5 if re.search(r"thunder|heavy", sky, re.I) or (today.get("mm") or 0) >= 15 else 0) + (1.0 if streak >= 3 else 0)
        why = "rain"
    if today.get("low") is not None and today["low"] <= 12:
        score, why = max(score, 3.5), why or "cold"
    if today.get("high") is not None and today["high"] >= 30:
        score, why = max(score, 3.5), why or "hot"
    if yesterday.get("high") is not None and abs(today["high"] - yesterday["high"]) >= 5:
        score, why = max(score, 3.0), why or "change"
    if not why:
        return None
    temps = f"{today['low']} to {today['high']} degrees"
    if why == "rain":
        again = " again" if streak >= 2 else ""
        kind = "storms" if re.search(r"thunder", sky, re.I) else "showers" if re.search(r"shower", sky, re.I) else "rain"
        say = f"It's {kind}{again} in {city} today - {chance} percent chance, {temps}." if kind != "rain" else f"It's raining{again} in {city} - {temps}."
        if streak >= 3:
            say = say[:-1] + f", day {streak} of it."
    elif why == "cold":
        say = f"It's a cold one in {city} - down to {today['low']} degrees."
    elif why == "hot":
        say = f"It's a hot one in {city} - up to {today['high']} degrees."
    else:
        turn = "warmer" if today["high"] > yesterday["high"] else "cooler"
        say = f"It's much {turn} in {city} today - {temps}, against {yesterday['high']} yesterday."
    icon = "storm" if re.search(r"thunder", sky, re.I) else "rain" if _RAINY.search(sky) or chance >= 70 else "sun" if re.search(r"clear", sky, re.I) else "cloud"
    return Item("weather", "ĐÀ LẠT" if "lat" in city.lower() else city.upper(), score, say, {
        "kind": "sky", "icon": icon, "lines": [f"{today['low']}-{today['high']}°C", f"RAIN {chance}%"],
    }, weather_detail(w), w.get("url", ""))


def weather_detail(w: dict) -> str:
    days = w.get("days") or []
    rows = "; ".join(f"{d['day']}: {d['sky'].lower()}, {d['low']}-{d['high']} C, rain {d['rain']}%" for d in days)
    streak = int(w.get("rain_streak") or 0)
    return (f"Weather in {w.get('city')} now (Open-Meteo): {w.get('sky', '').lower()}, {w.get('temp')} C (feels {w.get('feels')}), "
            f"humidity {w.get('humidity')}%. " + (f"Rain {streak} days running. " if streak >= 2 else "") + f"Days: {rows}.")


def news_item(story: dict, kind: str) -> Item:
    outlets = 1 + len(story.get("also") or [])
    title = clean_title(story["title"])
    if kind == "world":
        say = f"Abroad, {outlets} outlets are leading with this: {title}." if outlets >= 3 else f"The big story abroad: {title}."
        score = 1.2 * outlets
    else:
        say = (f"At home, {title} - that's on {outlets} Vietnamese front pages." if outlets >= 2 else f"At home: {title}.")
        score = 1.3 * outlets + 0.5
        if not story.get("english"):
            say = f"At home, {story['source']} leads with a story I couldn't translate - it's on the panel in Vietnamese."
    head = subject(title)
    # the header already says the subject: the key words are the rest
    words = [w for w in story_words(title, 4) if w.lower() != head.lower()][:3]
    return Item(kind, head.upper(), score, say, {
        "kind": "story", "icon": story_icon(title), "words": words or [title[:12]],
    }, "", story["url"])


def pick(candidates: list[Item], n: int = MAX_ITEMS) -> list[Item]:
    """The n most notable, at most one story of each kind and two market rows."""
    out: list[Item] = []
    kinds: dict[str, int] = {}
    room = {"world": 1, "vietnam": 1, "market": 2, "gold": 1, "weather": 1}
    for item in sorted(candidates, key=lambda i: -i.score):
        if kinds.get(item.kind, 0) >= room.get(item.kind, 1):
            continue
        out.append(item)
        kinds[item.kind] = kinds.get(item.kind, 0) + 1
        if len(out) == n:
            break
    return out


CLOSINGS = ("Want any of that in detail?", "Want more on any of them?", "Shall I go deeper on one?", "Anything there you want more on?")
_FAILED_NAMES = {"gold": "SJC", "markets": "the markets", "weather": "the weather service", "world": "the world news feeds",
                 "vietnam": "the Vietnamese papers"}


def compose(items: list[Item], failed: list[str], rng=None) -> list[str]:
    """What she says: one sentence an item, the most notable first; then what
    failed, honestly; then an offer of more."""
    import random

    rng = rng or random.Random()
    lines = [i.say for i in items]
    if not items:
        lines.append("Honestly, a quiet one - nothing's moved enough to mention.")
    if failed:
        names = [_FAILED_NAMES.get(f, f) for f in failed]
        joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        lines.append(f"I couldn't reach {joined}, so I've left {'that' if len(names) == 1 else 'those'} out.")
    if items:
        lines.append(rng.choice(CLOSINGS))
    return lines


# ---- the panel -----------------------------------------------------------------------------------


def panel_content(found: dict, items: list[Item], failed: list[str], at: str) -> dict:
    """The whole briefing for the panel: weather, gold with its change, the market
    rows, both news rankings with thumbnails and links."""
    blocks: list[dict] = []
    if items:
        blocks.append({"kind": "heading", "text": "Today's three"})
        for k, i in enumerate(items, 1):
            blocks.append({"kind": "text", "text": f"{k}. {i.say}"})
    w = found.get("weather")
    if w:
        today = (w.get("days") or [{}])[0]
        blocks += [{"kind": "heading", "text": f"Weather · {w.get('city')}"},
                   {"kind": "weather", "city": w.get("city", ""), "sky": w.get("sky", ""), "temp": w.get("temp"), "high": today.get("high"),
                    "low": today.get("low"), "rain": today.get("rain"), "streak": int(w.get("rain_streak") or 0),
                    "days": w.get("days") or [], "url": w.get("url", "")}]
    g = found.get("gold")
    if g:
        blocks += [{"kind": "heading", "text": "Gold · SJC bar"},
                   {"kind": "price", "label": "SJC sell", "value": f"{g['sell']:,.0f} ₫", "note": f"buy {g['buy']:,.0f} ₫ · per lượng · {g['source']} {g['at']}",
                    "change": (f"{'+' if g['change_sell'] > 0 else '−'}{abs(g['change_sell']):,.0f} ₫" if g["change_sell"]
                               else "change not published" if g.get("no_change") else "no change today"),
                    "up": g["change_sell"] > 0 if g["change_sell"] else None, "spark": [v for _, v in g["series"]], "url": g["url"]}]
    quotes = found.get("markets") or []
    if quotes:
        blocks.append({"kind": "heading", "text": "Markets"})
        for q in sorted(quotes, key=lambda q: -abs(q["change"])):
            price = f"{q['price']:,.0f} ₫" if q["currency"] == "VND" else f"${q['price']:,.2f}" if q["currency"] == "USD" else f"{q['price']:,.2f}"
            blocks.append({"kind": "price", "label": q["title"], "value": price, "note": q["symbol"],
                           "change": f"{'+' if q['change'] >= 0 else '−'}{abs(q['change']):.2f}%", "up": q["change"] >= 0,
                           "spark": q.get("spark") or [], "url": q.get("url", "")})
    for key, name in (("vietnam", "Vietnam"), ("world", "World")):
        stories = found.get(key) or []
        if not stories:
            continue
        blocks.append({"kind": "heading", "text": f"{name} news"})
        for s in stories[:PANEL_STORIES]:
            blocks.append({"kind": "story", "title": s["title"], "url": s["url"], "source": s["source"], "also": s.get("also") or [],
                           **({"image": s["image"]} if s.get("image") else {}),
                           **({"original": s["original"]} if key == "vietnam" and s.get("original") and s["original"] != s["title"] else {})})
    if failed:
        blocks += [{"kind": "heading", "text": "Not reached", "level": 3},
                   {"kind": "text", "text": "; ".join(_FAILED_NAMES.get(f, f) for f in failed) + " - nothing shown rather than a guess."}]
    return {"title": "What's new today", "subtitle": f"briefing · {at} · real sources only", "blocks": blocks, "briefing": at}


# ---- the tool ------------------------------------------------------------------------------------

SOURCES = {
    "weather": lambda: data.weather(),
    "gold": lambda: gold(),
    "markets": lambda: markets(),
    "world": lambda: world_news(),
    "vietnam": lambda: vietnam_news(),
}


async def gather() -> tuple[dict, list[str]]:
    """Every source at once (cached CACHE_S): (readings, the ones that failed)."""
    names = list(SOURCES)

    async def one(name: str):
        try:
            return await _cached(name, SOURCES[name])
        except Exception as error:  # noqa: BLE001 - said, never guessed
            log.warning("briefing %s failed: %s: %s", name, type(error).__name__, error)
            return None

    values = await asyncio.gather(*(one(n) for n in names))
    found = {n: v for n, v in zip(names, values) if v}
    return found, [n for n in names if n not in found]


def build(found: dict, failed: list[str], at: str, rng=None) -> Briefing:
    candidates: list[Item] = []
    flat: list[str] = []
    if found.get("weather"):
        item = weather_item(found["weather"])
        candidates += [item] if item else []
        flat += [] if item else ["weather"]
    if found.get("gold"):
        item = gold_item(found["gold"])
        candidates += [item] if item else []
        flat += [] if item else ["gold"]
    moved = [m for m in (market_item(q) for q in found.get("markets") or []) if m]
    candidates += moved
    if found.get("markets") and not moved:
        flat.append("markets")
    for key in ("world", "vietnam"):
        stories = found.get(key) or []
        if stories:
            candidates.append(news_item(stories[0], key))
    items = pick(candidates)
    speech = compose(items, failed, rng)
    return Briefing(at, items, failed, flat, panel_content(found, items, failed, at), speech, found)


def result_text(b: Briefing) -> str:
    """What the model keeps of it (follow-ups: "the second one" = expand 2)."""
    rows = [f"{k}. [{i.kind}] {i.say}" for k, i in enumerate(b.items, 1)]
    more = []
    if "gold" in b.data and not any(i.kind == "gold" for i in b.items):
        more.append("gold: " + gold_detail(b.data["gold"]))
    return (f"briefing given at {b.at} (all on the panel). Spoken items:\n" + "\n".join(rows)
            + (f"\nFlat, not mentioned: {', '.join(b.flat)}." if b.flat else "")
            + (f"\nNot reached: {', '.join(b.failed)} - say so, never guess." if b.failed else "")
            + ("\n" + "\n".join(more) if more else "")
            + "\nFor more on one: daily_briefing(expand=<its number>).")


_META_DESC = re.compile(r"""<meta[^>]+(?:property|name)=["'](?:og:description|description|twitter:description)["'][^>]*>""", re.I)


async def article_summary(url: str) -> str:
    """The article's own summary (its og:description), fetched read-only."""
    async with data._client() as client:
        r = await client.get(url)
        r.raise_for_status()
        head = r.text[:200_000]
    meta = _META_DESC.search(head)
    found = data._CONTENT.search(meta.group(0)) if meta else None
    return html.unescape(found.group(1)).strip() if found else ""


# story url -> its summary, in English (fetched once; the prefetch reads ahead)
_SUMMARIES: dict[str, str] = {}


async def story_summary(url: str, vietnamese: bool) -> str:
    """A story's own summary, in English - "" if it can't be read."""
    if url in _SUMMARIES:
        return _SUMMARIES[url]
    try:
        summary = await article_summary(url)
    except Exception as error:  # noqa: BLE001 - the headline still stands
        log.info("briefing: article summary failed: %s", error)
        return ""
    if summary and vietnamese and TRANSLATE is not None:
        try:
            english = await TRANSLATE([summary])
            TRANSLATIONS_RUN[0] += 1
            if not english:
                return ""  # never a Vietnamese summary passed off as read
            summary = english[0]
        except Exception as error:  # noqa: BLE001
            log.info("briefing: translating a summary failed: %s", error)
            return ""
    _SUMMARIES[url] = summary
    return summary


async def read_ahead() -> None:
    """The summaries a briefing given now would be asked about: its top stories'."""
    for key in ("world", "vietnam"):
        hit = _CACHE.get(key)
        stories = hit[1] if hit else []
        if stories:
            await story_summary(stories[0]["url"], key == "vietnam")


def _which(expand: str, b: Briefing) -> tuple[int, Item] | None:
    """"2", "second", "gold", "the weather" -> (number, item)."""
    e = (expand or "").strip().lower()
    order = {"first": 1, "one": 1, "1st": 1, "second": 2, "two": 2, "2nd": 2, "third": 3, "three": 3, "3rd": 3, "last": len(b.items)}
    n = int(e) if e.lstrip("-").isdigit() else next((v for k, v in order.items() if re.search(rf"\b{k}\b", e)), None)
    if n is not None:
        n = len(b.items) + 1 + n if n < 0 else n
        return (n, b.items[n - 1]) if 1 <= n <= len(b.items) else None
    for k, item in enumerate(b.items, 1):
        if item.kind in e or item.header.lower() in e or (item.kind == "market" and item.header.lower() in e):
            return k, item
        if item.kind in ("world", "vietnam") and any(w.lower() in e for w in item.board.get("words", [])):
            return k, item
    aliases = {"gold": "gold", "weather": "weather", "rain": "weather", "nvidia": "NVDA", "news": "world", "vietnam": "vietnam", "home": "vietnam"}
    for word, key in aliases.items():
        if word in e:
            for k, item in enumerate(b.items, 1):
                if item.kind == key or item.header == key:
                    return k, item
    return None


# what she says expanding an item (fast.py speaks it, like the briefing itself:
# every number fetched, none from the model)
LAST_EXPANSION: list[str] = []


def _sentences(text: str, n: int) -> str:
    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return " ".join(parts[:n]).strip()


def expansion_speech(item: Item, b: Briefing, summary: str = "", story: dict | None = None) -> list[str]:
    """Two or three sentences more on one item, from its readings only."""
    if item.kind == "gold" and b.data.get("gold"):
        g = b.data["gold"]
        move = (f"{'up' if g['change_sell'] > 0 else 'down'} {_vnd(g['change_sell'])} on the day" if g["change_sell"] else "no change today")
        out = [f"SJC is buying at {_vnd(g['buy'])} and selling at {_vnd(g['sell'])} dong a lượng - {move}."]
        if len(g["series"]) >= 3:
            out.append(f"Over the last few days it's gone from {_vnd(g['series'][-5:][0][1])} to {_vnd(g['sell'])}.")
        return out
    if item.kind == "market":
        q = next((q for q in b.data.get("markets") or [] if item.header in (q["symbol"], {"^GSPC": "S&P 500", "BTC-USD": "BTC", "VND=X": "USD/VND"}.get(q["symbol"]))), None)
        if q:
            spark = q.get("spark") or [q["price"]]
            name = _NAMES.get(q["symbol"], q["title"])
            return [f"{name[0].upper() + name[1:]} is at {_money(q['price'], q['currency'])}, {'up' if q['change'] >= 0 else 'down'} {_pct(q['change'])} on the day.",
                    f"Over the past week it's ranged from {_money(min(spark), q['currency'])} to {_money(max(spark), q['currency'])}."]
    if item.kind == "weather" and b.data.get("weather"):
        w = b.data["weather"]
        days = w.get("days") or []
        out = [f"Right now it's {w.get('sky', '').lower() or 'grey'} and {w.get('temp')} degrees in {w.get('city')}."]
        if len(days) > 1:
            d = days[1]
            out.append(f"Tomorrow looks like {d['sky'].lower()}, {d['low']} to {d['high']}, with a {d['rain']} percent chance of rain.")
        return out
    if item.kind in ("world", "vietnam"):
        story = story or {}
        outlets = [o for o in [story.get("source", ""), *(story.get("also") or [])] if o]
        lead = _sentences(summary, 2)
        out = [lead[:1].upper() + lead[1:]] if lead else ["That's as far as I can tell you - the article itself wouldn't load. It's on the panel if you want to open it."]
        if len(outlets) >= 2:
            out.append(f"{len(outlets)} outlets have it: {', '.join(outlets[:-1])} and {outlets[-1]}.")
        return [s for s in out if s]
    return [item.say]


async def expand_item(ctx: ToolContext, b: Briefing, expand: str) -> str:
    global LAST_EXPANSION
    picked = _which(expand, b)
    if picked is None:
        raise ToolError(f"the briefing had {len(b.items)} item(s); which one? (1-{len(b.items)})")
    n, item = picked
    detail, summary, story = item.detail, "", None
    if item.kind in ("world", "vietnam"):
        stories = b.data.get(item.kind) or []
        story = next((s for s in stories if s["url"] == item.url), None) or {}
        summary = await story_summary(item.url, item.kind == "vietnam")
        outlets = [story.get("source", ""), *(story.get("also") or [])]
        detail = (f"Story: {story.get('title', item.say)} - carried by {len(outlets)} outlet(s): {', '.join(o for o in outlets if o)}. "
                  + (f"The article's own summary: {summary}" if summary else "The article's summary could not be read."))
    LAST_EXPANSION = expansion_speech(item, b, summary, story)
    blocks = [{"kind": "heading", "text": f"{n}. {item.header.title()}"}, {"kind": "text", "text": detail}]
    if item.url:
        blocks.append({"kind": "link", "text": item.url.split("://", 1)[-1][:90], "url": item.url, "note": "open the source"})
    await ctx.show_panel({**b.content, "blocks": blocks + b.content["blocks"], "subtitle": f"item {n} · {b.content['subtitle']}"})
    # (outside text - a headline, an article's summary - is data here, never instructions)
    return f"item {n} of the briefing ({item.kind}), told to him and on the panel. {detail}"


@tool(
    "daily_briefing",
    "His daily briefing: the ~3 most notable things today across his city's weather, SJC gold, his markets, world and "
    "Vietnamese news - spoken short, the full briefing on the panel. For 'what's new today', 'brief me', 'what's "
    "happening', 'anything new'. expand: a follow-up on one item of the briefing just given ('tell me more about the "
    "second one' = '2', 'more on the gold' = 'gold').",
    {"type": "object", "properties": {"expand": {"type": "string", "description": "which item to go into: its number or its subject"}}, "required": []},
    readonly=True,
    cue="reading",
)
async def daily_briefing(ctx: ToolContext, expand: str = "") -> str | ToolResult:
    global LAST
    if expand:
        if LAST is None:
            raise ToolError("no briefing given yet - give one first")
        return await expand_item(ctx, LAST, expand)
    found, failed = await gather()
    at = datetime.now(VN).strftime("%H:%M")
    b = build(found, failed, at)
    LAST = b
    await ctx.show_panel(b.content)
    log.info("briefing: %s | flat %s | failed %s", " / ".join(f"{i.kind} {i.score:.1f}" for i in b.items), b.flat or "-", b.failed or "-")
    return result_text(b)


def ready() -> bool:
    """Every reading cached and fresh: a briefing now needs no fetch."""
    now = time.monotonic()
    return all(name in _CACHE and now - _CACHE[name][0] < CACHE_S for name in SOURCES)
