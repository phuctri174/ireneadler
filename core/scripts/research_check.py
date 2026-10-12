r"""Research success rate: ten real questions through tools/research.py, live web.

  .venv\Scripts\python scripts\research_check.py

Per question: results searched, pages read vs skipped (and why), screenshots and
main images captured, videos found, seconds. Totals at the end; the whole report
is written to core/logs/research-check.json. Uses Irene's own Chrome and her
local SearXNG - no OS input.
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.research import run_research  # noqa: E402

QUESTIONS = [
    "How tall is the Eiffel Tower?",
    "What causes the northern lights?",
    "Best budget mechanical keyboard 2026",
    "How does a heat pump work?",
    "Who painted The Starry Night and when?",
    "RTX 5060 Ti 16GB specs",
    "How long should you boil an egg for a soft yolk?",
    "What is the James Webb Space Telescope looking at now?",
    "Pho recipe beef broth",
    "Why is the sky blue?",
]


async def main() -> None:
    rows, why = [], Counter()
    for q in QUESTIONS:
        try:
            r = await run_research(q)
        except Exception as error:  # a failed question is a result too
            rows.append({"question": q, "error": str(error)})
            print(f"FAIL {q}: {error}")
            continue
        for s in r.skipped:
            why[s["why"].split(" (")[0]] += 1
        row = {
            "question": q, "searched": r.searched, "read": len(r.sources), "skipped": len(r.skipped),
            "screenshots": sum(1 for s in r.sources if s.screenshot), "images": sum(1 for s in r.sources if s.image),
            "videos": len(r.videos), "seconds": r.seconds, "skips": r.skipped,
        }
        rows.append(row)
        print(f"{q[:48]:48} searched {r.searched}  read {len(r.sources)}  skipped {len(r.skipped)}  "
              f"shots {row['screenshots']}  images {row['images']}  videos {row['videos']}  {r.seconds}s")
    ok = [r for r in rows if "error" not in r]
    fetched = sum(r["read"] for r in ok)
    tried = sum(r["read"] + r["skipped"] for r in ok)
    summary = {
        "questions_answered_from_sources": f"{sum(1 for r in ok if r['read'] >= 3)}/{len(rows)} with 3+ sources",
        "pages_fetched": f"{fetched}/{tried} ({fetched / max(1, tried):.0%})",
        "skipped_because": dict(why),
        "screenshots": f"{sum(r['screenshots'] for r in ok)}/{fetched}",
        "main_images": f"{sum(r['images'] for r in ok)}/{fetched}",
        "median_seconds": sorted(r["seconds"] for r in ok)[len(ok) // 2] if ok else None,
    }
    print(json.dumps(summary, indent=1))
    out = ROOT / "core" / "logs" / "research-check.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
