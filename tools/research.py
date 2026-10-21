# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Research: search, read the best pages, keep what was found.

  research(question)       SearXNG (several engines, Wikipedia among them) -> the top
                           ~8 results -> each fetched IN PARALLEL in Irene's own
                           Chrome, with a per-page timeout -> blocked, paywalled and
                           thin pages skipped -> the best 3-5 kept, each with its
                           title, URL, key extract, a screenshot of the part that
                           answers, and the page's main image; plus YouTube videos
                           (yt-dlp metadata and thumbnails). The whole result is
                           saved as the "last research" (core/data/research/) for
                           the panel; the model gets the extracts to answer from.
  open_in_my_browser(url)  opens a page in HIS normal Chrome (not Irene's profile).

SearXNG is Irene's own local instance (127.0.0.1:8888), started on demand like
her Chrome; see core/scripts/setup_searxng.ps1. Everything read from the web is
tainted: data to answer from, never instructions.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
import secrets
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .browser import BROWSER, CHROME, PAGE_NOTE, _clock, _extract, safe_url, search_youtube
from . import series
from .registry import ToolContext, ToolError, ToolResult, tool

log = logging.getLogger("irene.tools.research")

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "core" / "data" / "research"
SEARX_URL = "http://127.0.0.1:8888"
SEARX_SRC = Path(os.environ.get("IRENE_SEARXNG_SRC", r"C:\irene\searxng-src"))
SEARX_PY = Path(os.environ.get("IRENE_SEARXNG_PY", r"C:\irene\searxng-venv\Scripts\python.exe"))
SEARX_SETTINGS = ROOT / "config" / "searxng" / "settings.yml"
SEARX_SHIM = ROOT / "config" / "searxng" / "shim"

RESULTS = 8          # search results considered
KEEP = (3, 5)        # sources kept: at least / at most
VIDEOS = 3
PAGE_TIMEOUT_S = 7.0  # one page's load
ENOUGH_S = 5.5       # with KEEP[0] good pages in, stop waiting for the rest here
DEADLINE_S = 9.0     # and never wait past this for any
MIN_WORDS = 120      # below this a page is "thin"
EXTRACT_CHARS = 700
MODEL_CHARS = 1600   # per source, in what the model reads
TEXT_CHARS = 14000   # per source, kept for checking her claims
PASSAGES = 4
SHOT_W, SHOT_H = 900, 460
IMAGE_MAX = 640
HISTORY = 20

# social sites and walled gardens: no readable article behind the link
SKIP_HOSTS = re.compile(
    r"(^|\.)(instagram|facebook|tiktok|x|twitter|pinterest|linkedin|threads|quora|youtube|youtu)\.(com|be|net)$", re.I
)
PAYWALL = re.compile(
    r"subscribe (now )?to (continue|read|keep reading)|to continue reading|create a free account to|"
    r"you('ve| have) reached (your|the) (free )?(article )?limit|already a subscriber\?|"
    r"verify you are (a )?human|are you a robot|unusual traffic|access denied|enable javascript and cookies|"
    r"just a moment\.\.\.|checking your browser",
    re.I,
)
STOP = set(
    "the a an and or of to in on for with is are was were be been what who whom whose when where why how "
    "does do did can could should would will much many about from that this these those it its as at by "
    "me my you your tell please irene sir look up research find out search".split()
)


@dataclass
class Source:
    index: int
    title: str
    url: str
    site: str
    extract: str
    screenshot: str | None = None  # data: URI (jpeg)
    image: str | None = None       # data: URI (jpeg), the page's main image
    words: int = 0
    # the page's readable text (capped): what every claim of her answer is checked
    # against (core/irene/grounding.py)
    text: str = ""
    # the passages the model reads, best first
    passages: list[str] = field(default_factory=list)


@dataclass
class Video:
    title: str
    channel: str
    duration: str
    url: str
    thumbnail: str | None = None   # data: URI


@dataclass
class Research:
    id: str
    question: str
    at: str
    sources: list[Source] = field(default_factory=list)
    videos: list[Video] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # {url, why}
    searched: int = 0
    engines: list[str] = field(default_factory=list)
    seconds: float = 0.0
    # what she answered from it, for the panel
    answer: str = ""
    # each claim of that answer with its source and the fetched text supporting it
    claims: list[dict] = field(default_factory=list)


# --- the search server --------------------------------------------------------------


class Searx:
    """Irene's SearXNG, started on first use and left running."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def up(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                return (await client.get(f"{SEARX_URL}/healthz")).status_code == 200
        except httpx.HTTPError:
            return False

    async def ensure(self) -> None:
        async with self._lock:
            if await self.up():
                return
            if not SEARX_PY.exists() or not (SEARX_SRC / "searx").exists():
                raise ToolError("my search engine isn't installed (core/scripts/setup_searxng.ps1)")
            env = {
                **os.environ,
                "SEARXNG_SETTINGS_PATH": str(SEARX_SETTINGS),
                "SEARXNG_SECRET": secrets.token_hex(24),
                "PYTHONPATH": f"{SEARX_SRC}{os.pathsep}{SEARX_SHIM}",
            }
            log.info("starting SearXNG")
            subprocess.Popen(
                [str(SEARX_PY), "-m", "searx.webapp"],
                cwd=str(SEARX_SRC),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
            for _ in range(120):
                if await self.up():
                    return
                await asyncio.sleep(0.25)
            raise ToolError("my search engine didn't start")


SEARX = Searx()


async def _query(client: httpx.AsyncClient, query: str) -> list[dict]:
    params = {"q": query, "format": "json", "language": "en", "safesearch": 0}
    try:
        return (await client.get(f"{SEARX_URL}/search", params=params)).json().get("results", [])
    except (httpx.HTTPError, ValueError):
        return []


async def web_search(query: str, count: int = RESULTS) -> tuple[list[dict], list[str]]:
    """Top results (title, url, content), social sites dropped, and the engines that
    answered. A second search for the reference pages ("... wikipedia") runs
    alongside and is interleaved, so a definition is always in the running."""
    await SEARX.ensure()
    async with httpx.AsyncClient(timeout=10.0) as client:
        main, reference = await asyncio.gather(_query(client, query), _query(client, f"{query} wikipedia"))
    if not main and not reference:
        raise ToolError("the search failed")
    mixed = [r for pair in zip(main, reference) for r in pair] + main[len(reference):] + reference[len(main):]
    # the main search leads: its top two first
    mixed = main[:2] + [r for r in mixed if r not in main[:2]]
    seen, results, engines = set(), [], set()
    for r in mixed:
        url = r.get("url") or ""
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        key = url.split("#")[0].rstrip("/")
        if not url.startswith("http") or key in seen or SKIP_HOSTS.search(host):
            continue
        seen.add(key)
        engines.update(r.get("engines") or [])
        results.append({"title": r.get("title") or host, "url": url, "content": r.get("content") or "", "site": host})
        if len(results) >= count:
            break
    return results, sorted(engines)


# --- reading a page -----------------------------------------------------------------


def fold(text: str) -> str:
    """Lower case, accents off ("Gyaku-dō" -> "gyaku-do"): how words are compared."""
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def _terms(question: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{2,}", fold(question)) if w not in STOP and (len(w) > 2 or w.isdigit() or w == "do")}


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n|\n", text) if len(p.strip().split()) >= 12]


def best_passages(text: str, question: str, count: int = PASSAGES, chars: int = MODEL_CHARS) -> list[str]:
    """The paragraphs of `text` that best answer `question`, best first, within `chars`."""
    terms = _terms(question)
    paras = _paragraphs(text)

    def score(item):
        k, p = item
        low = fold(p)
        words = set(re.findall(r"[a-z0-9]{2,}", low))
        hits = len(terms & words)
        # a paragraph that defines the subject ("X is a...", "this means...") answers most,
        # even when it doesn't repeat the subject's name ("As the name suggests, this means...")
        defines = hits >= 1 and re.search(r"\b(is an?|means|refers to|is the|stands for|known as|is called|as the name suggests)\b| [-–] ", low)
        return hits * 3 + (5 if defines else 0) + min(len(p), 600) / 300 - k * 0.05

    ranked = [p for _, p in sorted(enumerate(paras), key=score, reverse=True)]
    out, used = [], 0
    for p in ranked[:count]:
        p = p[:700]
        if used + len(p) > chars and out:
            break
        out.append(p)
        used += len(p)
    return out


def best_passage(text: str, question: str) -> str:
    """The paragraph (or two) of `text` that best answers `question`."""
    terms = _terms(question)
    paras = _paragraphs(text)
    if not paras:
        return text[:EXTRACT_CHARS]

    def score(item):
        k, p = item
        words = set(re.findall(r"[a-z0-9]{2,}", fold(p)))
        # relevance first; earlier paragraphs win ties (a lede usually answers)
        return len(terms & words) * 3 + min(len(p), 600) / 300 - k * 0.05

    k, top = max(enumerate(paras), key=score)
    passage = top
    if len(passage) < EXTRACT_CHARS // 2 and k + 1 < len(paras):
        passage += "\n\n" + paras[k + 1]
    return passage[:EXTRACT_CHARS].rsplit(" ", 1)[0] + ("..." if len(passage) > EXTRACT_CHARS else "")


def _jpeg(raw: bytes, max_side: int = IMAGE_MAX, quality: int = 70) -> str | None:
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:  # not an image PIL can read (svg, broken)
        return None
    if img.width < 120 or img.height < 80:
        return None  # an icon or a tracking pixel, not a picture
    if img.mode in ("P", "LA", "PA"):
        img = img.convert("RGBA")  # palette transparency, before dropping alpha
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


async def fetch_image(url: str, referer: str | None = None) -> str | None:
    try:
        url = safe_url(url)
        headers = {"User-Agent": "Mozilla/5.0", **({"Referer": referer} if referer else {})}
        async with httpx.AsyncClient(timeout=4.0, follow_redirects=True, headers=headers) as client:
            r = await client.get(url)
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/") or len(r.content) > 4_000_000:
            return None
        return await asyncio.to_thread(_jpeg, r.content)
    except (ToolError, httpx.HTTPError):
        return None


# finds the element holding the passage, scrolls it to the middle, returns its box
_LOCATE = """(needle) => {
  const norm = s => s.replace(/\\s+/g, ' ').trim().toLowerCase();
  const want = norm(needle).slice(0, 60);
  let best = null;
  for (const el of document.querySelectorAll('p, li, td, dd, blockquote, h1, h2, h3, div')) {
    const t = norm(el.innerText || '');
    if (t.length >= want.length && t.includes(want) && (!best || t.length < norm(best.innerText).length)) best = el;
  }
  if (!best) return null;
  best.scrollIntoView({block: 'center'});
  const r = best.getBoundingClientRect();
  return {y: r.top, h: r.height, vw: window.innerWidth, vh: window.innerHeight};
}"""

_MAIN_IMAGE = """() => {
  const meta = document.querySelector('meta[property="og:image"], meta[name="og:image"], meta[name="twitter:image"]');
  if (meta && meta.content) return new URL(meta.content, location.href).href;
  let best = null, area = 0;
  for (const img of document.images) {
    const a = img.naturalWidth * img.naturalHeight;
    if (a > area && img.naturalWidth >= 200) { best = img.currentSrc || img.src; area = a; }
  }
  return best;
}"""


async def _shoot(page, passage: str) -> str | None:
    """A screenshot of the part of the page the passage came from."""
    try:
        box = await page.evaluate(_LOCATE, passage.split("\n")[0][:200])
        await asyncio.sleep(0.15)  # let a lazy image or sticky header settle
        if box:
            vw, vh = box["vw"], box["vh"]
            h = min(max(box["h"] + 80, 240), vh)
            y = max(0, min(box["y"] - 40, vh - h))
            raw = await page.screenshot(type="png", clip={"x": 0, "y": y, "width": min(vw, 1400), "height": h}, timeout=4000)
        else:
            raw = await page.screenshot(type="png", timeout=4000)
    except Exception as error:  # playwright errors: no screenshot, the source still counts
        log.info("screenshot failed: %s", error)
        return None
    return await asyncio.to_thread(_jpeg, raw, SHOT_W, 65)


async def read_source(context, result: dict, question: str) -> tuple[Source | None, str | None]:
    """One search result -> a Source, or (None, why it was skipped)."""
    page = await context.new_page()
    try:
        try:
            response = await page.goto(result["url"], wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_S * 1000)
        except Exception as error:
            return None, f"didn't load ({type(error).__name__})"
        if response is not None and response.status >= 400:
            return None, f"blocked (HTTP {response.status})"
        await asyncio.sleep(0.6)  # late text (hydration) and consent banners
        html = await page.content()
        text = await asyncio.to_thread(_extract, html) or ""
        words = len(text.split())
        if PAYWALL.search(text[:3000]) or (words < MIN_WORDS * 2 and PAYWALL.search(html[:200000])):
            return None, "paywall or bot check"
        if words < MIN_WORDS:
            return None, f"thin ({words} words)"
        passage = best_passage(text, question)
        title = (await page.title()).strip() or result["title"]
        shot, image_url = await asyncio.gather(_shoot(page, passage), page.evaluate(_MAIN_IMAGE))
        image = await fetch_image(image_url, result["url"]) if image_url else None
        return Source(0, title[:160], page.url, result["site"], passage, shot, image, words,
                      text[:TEXT_CHARS], best_passages(text, question)), None
    finally:
        await page.close()


async def _videos(question: str) -> list[Video]:
    try:
        found = await search_youtube(question, VIDEOS)
    except ToolError:
        return []
    thumbs = await asyncio.gather(*(fetch_image(f"https://i.ytimg.com/vi/{v['url'].rsplit('=', 1)[-1]}/hqdefault.jpg") for v in found))
    return [Video(v["title"], v["channel"], _clock(v["duration"]), v["url"], t) for v, t in zip(found, thumbs)]


async def _read_all(context, results: list[dict], question: str) -> list:
    """Every result read at once. Once enough good pages are in (KEEP[0] after
    ENOUGH_S, or KEEP[1] at any time) the stragglers are dropped; nothing waits
    past DEADLINE_S. Per result: (Source|None, why), an exception, or None (dropped)."""
    tasks = [asyncio.create_task(read_source(context, r, question)) for r in results]
    started = time.perf_counter()
    pending = set(tasks)
    while pending:
        elapsed = time.perf_counter() - started
        good = sum(1 for t in tasks if t.done() and not t.cancelled() and t.exception() is None and t.result()[0] is not None)
        if good >= KEEP[1] or (good >= KEEP[0] and elapsed >= ENOUGH_S) or elapsed >= DEADLINE_S:
            break
        wait = (ENOUGH_S if good >= KEEP[0] and elapsed < ENOUGH_S else DEADLINE_S) - elapsed
        _, pending = await asyncio.wait(pending, timeout=max(0.05, wait), return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()  # its finally closes the tab
    await asyncio.gather(*pending, return_exceptions=True)
    return [None if t.cancelled() else (t.exception() or t.result()) for t in tasks]


def _relevance(source: Source, question: str) -> float:
    terms = _terms(question)
    words = set(re.findall(r"[a-z0-9]{2,}", fold(" ".join(source.passages) or source.extract)))
    return len(terms & words) / max(1, len(terms))


async def run_research(question: str) -> Research:
    started = time.perf_counter()
    rid = time.strftime("%Y%m%d-%H%M%S")
    research = Research(rid, question, time.strftime("%Y-%m-%d %H:%M"))
    videos_task = asyncio.create_task(_videos(question))
    # the real numbers, for a question about something that changes (series.py)
    series_task = asyncio.create_task(series.fetch(question))
    results, research.engines = await web_search(question)
    research.searched = len(results)
    if results:
        context = (await BROWSER.page()).context
        outcomes = await _read_all(context, results, question)
        good: list[tuple[int, Source]] = []
        for rank, (result, outcome) in enumerate(zip(results, outcomes)):
            if outcome is None:
                research.skipped.append({"url": result["url"], "why": "cut at the deadline"})
            elif isinstance(outcome, BaseException):
                research.skipped.append({"url": result["url"], "why": type(outcome).__name__})
            elif outcome[0] is None:
                research.skipped.append({"url": result["url"], "why": outcome[1]})
            else:
                good.append((rank, outcome[0]))
        # the same page under two URLs counts once
        seen_text: set[str] = set()
        unique = []
        for rank, source in good:
            fingerprint = re.sub(r"\W+", "", source.text[:400].lower())
            if fingerprint in seen_text:
                research.skipped.append({"url": source.url, "why": "duplicate page"})
                continue
            seen_text.add(fingerprint)
            unique.append((rank, source))
        good = unique
        # search rank matters, but a page that actually talks about the question wins
        good.sort(key=lambda rs: -_relevance(rs[1], question) + rs[0] * 0.08)
        keep = [s for _, s in good[: KEEP[1]] if _relevance(s, question) > 0 or len(good) <= KEEP[0]]
        if len(keep) < KEEP[0]:
            keep = [s for _, s in good[: KEEP[0]]]
        research.sources = keep
    data = await series_task
    if data is not None:
        # first: the numbers he asked about, as the data gives them
        research.sources.insert(0, Source(0, data.title, data.url, data.site, data.text[:EXTRACT_CHARS], words=len(data.text.split()), text=data.text, passages=[data.text]))
    for k, source in enumerate(research.sources, 1):
        source.index = k
    research.videos = await videos_task
    research.seconds = round(time.perf_counter() - started, 1)
    save(research)
    log.info(
        "research %r: %d searched, %d read, %d skipped, %d videos, %.1fs",
        question, research.searched, len(research.sources), len(research.skipped), len(research.videos), research.seconds,
    )
    return research


# --- keeping it ---------------------------------------------------------------------


# research is kept for a day: past that it is gone from her memory and the panel
EXPIRE_S = 24 * 3600
# called after research is cleared or expires: (ids removed, why) - the running
# assistant drops it from the conversation, the session notes and the panel
FORGET_HOOKS: list = []


def made_at(path: Path) -> float:
    """When a research was made (its id is the local time, YYYYmmdd-HHMMSS)."""
    try:
        return time.mktime(time.strptime(path.stem, "%Y%m%d-%H%M%S"))
    except ValueError:
        return path.stat().st_mtime


def live_paths(now: float | None = None) -> list[Path]:
    """The research files still in date, oldest first: nothing past EXPIRE_S is
    ever read again, even before the sweep removes it."""
    if not STORE.exists():
        return []
    now = time.time() if now is None else now
    return [p for p in sorted(STORE.glob("2*.json")) if now - made_at(p) < EXPIRE_S]


def _drop(paths: list[Path], why: str) -> list[str]:
    """Her own research cache (core/data/research - never his files) removed, and
    everything that remembers it told."""
    ids = []
    for path in paths:
        path.unlink(missing_ok=True)
        ids.append(path.stem)
    if ids:
        log.info("research %s: %d removed (%s)", why, len(ids), ", ".join(ids))
        for hook in FORGET_HOOKS:
            hook(ids, why)
    return ids


def expire(now: float | None = None) -> list[str]:
    """Remove research older than EXPIRE_S; returns the ids removed."""
    if not STORE.exists():
        return []
    now = time.time() if now is None else now
    return _drop([p for p in sorted(STORE.glob("2*.json")) if now - made_at(p) >= EXPIRE_S], "expired after 24 h")


def clear_all() -> list[str]:
    """Every saved research removed - his "clear your research"."""
    return _drop(sorted(STORE.glob("2*.json")) if STORE.exists() else [], "cleared")


def save(research: Research) -> None:
    STORE.mkdir(parents=True, exist_ok=True)
    (STORE / f"{research.id}.json").write_text(json.dumps(asdict(research)), encoding="utf-8")
    old = sorted(STORE.glob("2*.json"))[:-HISTORY]
    for path in old:  # Irene's own cache, not his files
        path.unlink(missing_ok=True)


def _load(path: Path) -> Research:
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["sources"] = [Source(**s) for s in raw.get("sources", [])]
    raw["videos"] = [Video(**v) for v in raw.get("videos", [])]
    return Research(**raw)


def history() -> list[Research]:
    """Saved research still in date, newest first."""
    return [_load(p) for p in reversed(live_paths())]


def last() -> Research | None:
    items = live_paths()
    return _load(items[-1]) if items else None


def attach_answer(text: str, claims: list[dict] | None = None) -> None:
    """Keep her answer - and what supports each of its claims - with its research."""
    found = last()
    if found is not None and text.strip():
        found.answer = text.strip()
        found.claims = claims or []
        save(found)


def for_model(research: Research) -> str:
    """What the model reads: the extracts, numbered, and how to answer."""
    lines = [f"Research for {research.question!r}: read {len(research.sources)} of {research.searched} results"
             + (f" ({len(research.skipped)} skipped: blocked, paywalled or thin)" if research.skipped else "") + "."]
    for s in research.sources:
        body = "\n".join(s.passages) if s.passages else s.extract
        lines.append(f"[{s.index}] {s.title} ({s.site})\n{body[:MODEL_CHARS]}")
    if research.videos:
        lines.append("Videos: " + "; ".join(f"{v.title} - {v.channel} ({v.duration})" for v in research.videos))
    if not research.sources:
        lines.append("No page could be read. Say so honestly; don't answer from memory as if you had checked.")
    data = next((s for s in research.sources if s.site in ("finance.yahoo.com", "open-meteo.com")), None)
    if data is not None:
        lines.append(
            f"Source [{data.index}] is the real series: say the latest figure and how it moved, and draw those "
            'numbers, exactly as given: <draw>{"chart": "line", "title": ..., "unit": ..., "points": [[label, number], ...]}</draw>.'
        )
    lines.append(
        "Answer by TALKING: a real spoken summary of four to six conversational sentences "
        "(70-120 words) inside <speak> - the direct answer to his question first, then the "
        "key points, as you would explain it to a friend. Never offer the panel or say you can "
        "only tell part of it: you SAY the summary, and the panel is offered after it. "
        "and end every factual sentence with the source it comes from, like [1] or [2]. Say ONLY "
        "what these sources say - nothing from memory; each sentence is checked against the "
        "page text and one the sources don't support is cut. If the sources disagree or say "
        "little, say that out loud. No <display>: the details and sources go on the panel. "
        "After </speak>, draw what you explained: one <draw>{...}</draw> (Your drawing board) - any "
        "numbers in it only as these sources give them."
    )
    lines.append(PAGE_NOTE)
    return "\n\n".join(lines)


# --- tools --------------------------------------------------------------------------


@tool(
    "research",
    "Look something up on the web: searches several engines, reads the best 3-5 pages "
    "in Irene's browser, and finds YouTube videos. For 'look up', 'research', 'find "
    "sources', news and recent events, prices and specs, and any factual question you're not sure of.",
    {"type": "object", "properties": {"question": {"type": "string", "description": "what to find out, as a search"}}, "required": ["question"]},
    cue="magnifier",
)
async def research(_ctx: ToolContext, question: str) -> ToolResult:
    question = question.strip()[:300]
    if not question:
        raise ToolError("research needs a question")
    found = await run_research(question)
    return ToolResult(for_model(found), tainted=True)


@tool(
    "clear_research",
    "Clear everything Irene has researched: removes her saved research from her memory "
    "and the panel's history. Only when he asks to clear, wipe or forget her research "
    "(\"clear your research\"). Never for a new search.",
    readonly=False,
    cue="folder",
)
async def clear_research(ctx: ToolContext) -> str:
    ids = clear_all()
    return f"research cleared: {len(ids)} saved research removed from memory and the panel" if ids else "there was no saved research to clear"


def open_normal_chrome(url: str) -> str:
    """Open a page in his everyday Chrome (his profile) - a link he chose."""
    # his profile, logged in (config/chrome.yaml) - one launcher for everything he sees
    from .browser import open_in_his_chrome

    return open_in_his_chrome(url)


@tool(
    "open_in_my_browser",
    "Open a page in HIS normal Chrome (his own profile and tabs), e.g. a source from the "
    "research. open_url is for Irene's own browser.",
    {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
    readonly=False,
    cue="globe",
)
async def open_in_my_browser(_ctx: ToolContext, url: str) -> str:
    # "the second source": a number resolves against the last research
    m = re.fullmatch(r"\s*(?:source\s*)?\[?(\d)\]?\s*", url, re.I)
    if m:
        found = last()
        match = next((s for s in (found.sources if found else []) if s.index == int(m.group(1))), None)
        if match is None:
            raise ToolError(f"there's no source {m.group(1)} in the last research")
        url = match.url
    return f"opened {open_normal_chrome(url)} in his Chrome"
