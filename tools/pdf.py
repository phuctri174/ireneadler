"""save_panel_pdf(name, location): what's on the panel, as a PDF on his Desktop or in
Downloads - text, images, screenshots and clickable links, in the panel's own look,
printed by Chrome (Irene's browser, print-to-PDF).

Only ever creates a new file: an existing name gets " (2)", " (3)"... - nothing is
overwritten, so it is the one file-changing tool allowed after reading outside
content (Tool.creates_only). The path goes through the policy whitelist like every
file tool: a root name and a file name, never a raw path.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from .browser import BROWSER
from .policy import policy
from .registry import ToolContext, ToolError, tool

MAX_NAME = 80

# the panel's look (hud/src/ui/Panel.css, chrome.css), for paper: A4, the same dark
# instrument card, cyan headings, violet quotes, mono readouts
CSS = """
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; background: #060e14; }
body { font-family: "Inter", "Segoe UI", system-ui, sans-serif; color: #cdefff; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.card { margin: 14mm; padding: 10mm 12mm 12mm; border: 1px solid rgba(34, 224, 255, 0.28); border-radius: 3px;
        background: linear-gradient(180deg, rgba(18, 42, 54, 0.6), rgba(4, 10, 15, 0.3)), #061016; }
.head { border-bottom: 1px solid rgba(34, 224, 255, 0.16); padding-bottom: 5mm; margin-bottom: 6mm; }
.readout { font-family: "Cascadia Mono", "JetBrains Mono", Consolas, monospace; font-size: 7.5pt; letter-spacing: 0.16em;
           color: rgba(216, 246, 255, 0.55); text-transform: uppercase; }
.title { margin-top: 3mm; font-family: "Cascadia Mono", Consolas, monospace; font-size: 20pt; font-weight: 700;
         letter-spacing: 0.12em; color: #9ffbff; }
.sub { margin-top: 2mm; }
.body { font-size: 11pt; line-height: 1.5; }
h2 { display: flex; align-items: center; gap: 3mm; margin: 7mm 0 2.5mm; font-family: "Cascadia Mono", Consolas, monospace;
     font-size: 9.5pt; letter-spacing: 0.2em; text-transform: uppercase; color: #22e0ff; break-after: avoid; }
h2::before { content: ""; width: 8mm; height: 2px; background: #22e0ff; }
h2:first-child { margin-top: 0; }
h3 { margin: 5mm 0 1.5mm; font-family: "Cascadia Mono", Consolas, monospace; font-size: 8.5pt; letter-spacing: 0.14em;
     text-transform: uppercase; color: rgba(216, 246, 255, 0.75); break-after: avoid; }
p { margin: 0 0 3mm; white-space: pre-wrap; }
blockquote { margin: 4mm 0; padding: 0.5mm 0 0.5mm 4mm; border-left: 2px solid #b892ff; color: #e6d9ff; font-style: italic; break-inside: avoid; }
blockquote p { margin: 0; }
cite { display: block; margin-top: 1.5mm; font-style: normal; }
figure { margin: 4mm 0; break-inside: avoid; }
figure .frame { padding: 2.5mm; border: 1px solid rgba(34, 224, 255, 0.16); background: rgba(2, 7, 11, 0.8); }
figure img { display: block; max-width: 100%; max-height: 110mm; height: auto; margin: 0 auto; object-fit: contain; }
figcaption { margin-top: 1.5mm; }
a { color: #22e0ff; text-decoration: underline; text-decoration-color: rgba(34, 224, 255, 0.4); }
.link { margin: 0 0 2.5mm; font-size: 10pt; }
.link .readout { margin-left: 2mm; }
.video { display: flex; gap: 4mm; align-items: center; margin: 0 0 3mm; padding: 2mm; border: 1px solid rgba(34, 224, 255, 0.16);
         background: rgba(2, 7, 11, 0.6); break-inside: avoid; text-decoration: none; color: inherit; }
.video img, .video .thumb { width: 38mm; aspect-ratio: 16 / 9; object-fit: cover; background: rgba(34, 224, 255, 0.08); }
ol { margin: 0; padding-left: 6mm; }
.foot { margin-top: 8mm; padding-top: 3mm; border-top: 1px solid rgba(34, 224, 255, 0.16); display: flex; justify-content: space-between; }
"""


def _e(text) -> str:
    return html.escape(str(text or ""))


def _href(url: str) -> str:
    return _e(url) if re.match(r"^https?://", str(url or "")) else "#"


def _src(src: str) -> str:
    # only embedded images (data:) - the PDF never fetches anything
    return _e(src) if str(src or "").startswith("data:image/") else ""


def block_html(b: dict) -> str:
    kind = b.get("kind")
    if kind == "heading":
        tag = "h3" if b.get("level") == 3 else "h2"
        return f"<{tag}>{_e(b.get('text'))}</{tag}>"
    if kind == "text":
        return f"<p>{_e(b.get('text'))}</p>"
    if kind == "quote":
        cite = f"<cite class='readout'>{_e(b['attribution'])}</cite>" if b.get("attribution") else ""
        return f"<blockquote><p>{_e(b.get('text'))}</p>{cite}</blockquote>"
    if kind in ("image", "screenshot") and _src(b.get("src")):
        img = f"<img src='{_src(b['src'])}' alt='{_e(b.get('alt') or b.get('caption'))}'>"
        if b.get("url"):
            img = f"<a href='{_href(b['url'])}'>{img}</a>"
        caption = f"<figcaption class='readout'>{_e(b['caption'])}</figcaption>" if b.get("caption") else ""
        return f"<figure><div class='frame'>{img}</div>{caption}</figure>"
    if kind == "link":
        note = f"<span class='readout'>{_e(b['note'])}</span>" if b.get("note") else ""
        return f"<div class='link'><a href='{_href(b.get('url'))}'>{_e(b.get('text'))}</a>{note}</div>"
    if kind == "video":
        thumb = f"<img src='{_src(b['thumbnail'])}' alt=''>" if _src(b.get("thumbnail")) else "<span class='thumb'></span>"
        return (f"<a class='video' href='{_href(b.get('url'))}'>{thumb}<span><span>{_e(b.get('title'))}</span><br>"
                f"<span class='readout'>{_e(b.get('channel'))} · {_e(b.get('duration'))}</span></span></a>")
    if kind == "sourceList":
        items = "".join(f"<li>{_e(s.get('title'))} <span class='readout'>{_e(s.get('publisher'))} · {_e(s.get('year'))}</span></li>" for s in b.get("sources", []))
        return f"<h3>{_e(b.get('label') or 'Sources')}</h3><ol>{items}</ol>"
    return ""


def render_html(content: dict, saved_at: str = "") -> str:
    blocks = "\n".join(block_html(b) for b in content.get("blocks", []))
    sub = f"<div class='sub readout'>{_e(content.get('subtitle'))}</div>" if content.get("subtitle") else ""
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{_e(content.get('title'))}</title><style>{CSS}</style></head>"
        f"<body><div class='card'><div class='head'><div class='readout'>Irene · result · saved {_e(saved_at)}</div>"
        f"<div class='title'>{_e(content.get('title'))}</div>{sub}</div><div class='body'>{blocks}</div>"
        f"<div class='foot readout'><span>Local · no net</span><span>Links open in your browser</span></div></div></body></html>"
    )


def file_name(name: str | None, content: dict) -> str:
    """A safe file name from his words or the panel's title: 'Eiffel Tower.pdf'."""
    base = re.sub(r"\.pdf$", "", str(name or "").strip(), flags=re.I) or str(content.get("title") or "Irene panel")
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", base)
    base = re.sub(r"\s+", " ", base).strip(" .")[:MAX_NAME].strip(" .") or "Irene panel"
    return f"{base}.pdf"


def free_path(root: str, name: str) -> Path:
    """The file to write: `name` in the root, numbered if that exists - never overwritten."""
    path = policy().resolve(root, name)
    stem, n = path.stem, 2
    while path.exists():
        path = policy().resolve(root, f"{stem} ({n}).pdf")
        n += 1
    return path


async def render_pdf(content: dict, saved_at: str) -> bytes:
    page = await (await BROWSER.page()).context.new_page()
    try:
        await page.set_content(render_html(content, saved_at), wait_until="load")
        return await page.pdf(format="A4", print_background=True, margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
    except Exception as error:  # playwright's errors: report, don't crash
        raise ToolError(f"Chrome couldn't print it ({type(error).__name__})") from error
    finally:
        await page.close()


@tool(
    "save_panel_pdf",
    "Save what's on the panel as a PDF - text, images, screenshots and clickable links - on "
    "his Desktop or in Downloads. For 'save this as a PDF', 'save the panel', 'keep this for later'.",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "file name; default the panel's title"},
            "location": {"type": "string", "enum": ["desktop", "downloads"]},
        },
        "required": [],
    },
    readonly=False,
    creates_only=True,
    cue="folder",
)
async def save_panel_pdf(ctx: ToolContext, name: str | None = None, location: str = "desktop") -> str:
    import time

    content = ctx.panel_content()
    if not content:
        # "save this" right after a research answer means that research, shown or
        # not (live: "the panel is empty" straight after the Queen's Gambit)
        from .panel import resolve

        try:
            content, _ = resolve("that", ctx.panel_answers())
        except ToolError:
            content = None
    if not content:
        raise ToolError("the panel is empty - there's nothing to save yet")
    path = free_path(location, file_name(name, content))
    data = await render_pdf(content, time.strftime("%Y-%m-%d %H:%M"))
    # "x": create only - fails rather than replace a file that appeared meanwhile
    with open(path, "xb") as f:
        f.write(data)
    # "open that PDF you saved" finds it (files.open_file)
    from .files import remember_saved

    remember_saved(location, path)
    return f"saved the panel as {path.name} in {location.capitalize()} ({len(data) // 1024} KB)"
