r"""A skit prop (config/skits/props/<name>.json) as a PDF on his Desktop - printed
exactly as her save_panel_pdf tool prints the panel (tools/pdf.py: her header, the
dark instrument card, cyan headings), so it looks like something she produced.

  .venv\Scripts\python scripts\skit_pdf.py first_dance

Never overwrites: an existing name gets " (2)". Local only - Chrome prints a page
built in memory; nothing is fetched.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from irene import skit  # noqa: E402
from tools import pdf  # noqa: E402


async def main(name: str) -> None:
    content = skit.prop(name)
    path = pdf.free_path("desktop", pdf.file_name(None, content))
    # her header says when it was saved: the prop's own research time
    saved = content.get("subtitle", "").split("·")[-1].strip()
    try:
        data = await pdf.render_pdf(content, saved)
    finally:
        # let go of her browser (it keeps running, as it does for her research)
        playwright = getattr(pdf.BROWSER, "_playwright", None)
        if playwright is not None:
            await playwright.stop()
    with open(path, "xb") as f:
        f.write(data)
    print(f"{path} ({len(data) // 1024} KB)")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "first_dance"))
