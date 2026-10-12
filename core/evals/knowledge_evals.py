r"""Round 7: she researches on her own, and a known answer still draws and details.

  .venv\Scripts\python evals\knowledge_evals.py

Through the live Conversation.respond (the real model; research returns canned
pages so it is repeatable, and no web is touched):

  must_research   things she would only half-remember or that change - she
                  researches WITHOUT being asked, and never says "I don't know"
  known           things she knows - she may answer without research, but the
                  board still draws (a board message goes out) and the detail
                  goes to the panel (a <display>); never "I don't know"

Writes core/logs/knowledge-evals.json.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))

import irene  # noqa: E402,F401
from irene import brain, illustrate  # noqa: E402
from irene.brain import Conversation  # noqa: E402
from irene.llm import Ollama  # noqa: E402
from irene.reply import admits_ignorance  # noqa: E402
from tools import research as R  # noqa: E402
from tools.registry import ToolResult  # noqa: E402

MUST_RESEARCH = [
    ("What's the latest version of Python?", "Python 3.14 is the latest stable release of Python, released in October 2025, with free-threaded builds and template strings."),
    ("Who won the most recent Ballon d'Or?", "Ousmane Dembele won the 2025 Ballon d'Or, awarded in Paris, after his season with Paris Saint-Germain."),
    ("How much does an RTX 5090 cost right now?", "The GeForce RTX 5090 launched at 1999 dollars, but retail prices are currently around 2500 to 3000 dollars."),
    ("When does Avengers Doomsday come out?", "Avengers: Doomsday is scheduled for release on December 18, 2026, directed by the Russo brothers."),
    ("How many people live in Hanoi?", "Hanoi has a population of about 8.6 million people according to the latest census estimates."),
    ("What's the newest iPhone?", "The iPhone 17 lineup, including the iPhone 17 Pro and iPhone Air, was announced in September 2025."),
    ("Who is the current CEO of Intel?", "Lip-Bu Tan became the CEO of Intel in March 2025, succeeding Pat Gelsinger."),
    ("What are the rules for the 3rd dan kendo grading in Vietnam?", "The 3rd dan grading requires at least two years after 2nd dan, a practical examination, kendo kata one to seven and a written test."),
]
KNOWN = [
    "How does photosynthesis work?",
    "Explain the water cycle.",
    "What are the parts of a shinai?",
    "Explain the Italian Game in chess.",
]


def canned(question: str, page: str) -> R.Research:
    found = R.Research("20260928-150000", question, "2026-09-28 15:00")
    found.sources = [R.Source(1, "Source", "https://example.org/a", "example.org", page[:200], text=page, passages=[page])]
    found.searched = 5
    return found


class Host:
    def __init__(self):
        self.said: list[str] = []
        self.boards = 0

    async def thinking(self):
        pass

    async def confirm(self, prompt):
        return False

    async def tool_status(self, name, status):
        pass

    def reply_sink(self):
        host = self

        class Sink:
            # the app's board feed: every sentence heard at once
            def __init__(self):
                self.feed = illustrate.BoardFeed(lambda message: setattr(host, "boards", host.boards + 1))

            def line(self, line):
                host.said.append(line.text)
                self.feed.line()
                self.feed.heard(line.text, line.terms)

            def illustrate(self, plan):
                self.feed.start(plan)

            def adopt(self, board):
                self.feed.adopt(board)

            def close_board(self):
                self.feed.close()

            async def finish(self, reply):
                pass

        return Sink()

    async def announce(self, text):
        pass

    def forget(self):
        pass

    async def capture_shield(self, on):
        pass

    async def show_panel(self, content):
        pass

    def panel_answers(self):
        return []

    def panel_content(self):
        return None

    async def perform(self, names):
        return names


async def main() -> int:
    import tempfile

    R.STORE = Path(tempfile.mkdtemp())
    llm = Ollama()
    rows = []
    try:
        for question, page in MUST_RESEARCH + [(q, "") for q in KNOWN]:
            must = bool(page)
            found = canned(question, page or "No page needed.")

            async def run_tool(self, name, args, host, found=found):
                if name == "research":
                    R.save(found)
                    return ToolResult(R.for_model(found), tainted=True)
                return f"error: {name} is not part of this eval"

            brain.Conversation._run_tool = run_tool
            R.last = lambda found=found: found
            host = Host()
            turn = await Conversation(llm).respond(question, host)
            spoken = " ".join(host.said)
            researched = "research" in turn.tools_used
            ignorant = admits_ignorance(spoken)
            if must:
                ok = researched and not ignorant
                why = "" if ok else ("never researched" if not researched else "said it doesn't know")
            else:
                detail = bool(turn.reply.display.strip()) or researched
                ok = not ignorant and host.boards > 0 and detail
                why = "" if ok else ("said it doesn't know" if ignorant else "no board" if not host.boards else "no detail for the panel")
            rows.append({"question": question, "kind": "must_research" if must else "known", "ok": ok, "why": why, "researched": researched, "boards": host.boards, "said": spoken[:240]})
            print(f"{'OK  ' if ok else 'FAIL'} {'research' if must else 'known   '} {question:60} {why}\n     {spoken[:180]}", flush=True)
    finally:
        await llm.close()
    must_rows = [r for r in rows if r["kind"] == "must_research"]
    known_rows = [r for r in rows if r["kind"] == "known"]
    summary = {
        "researched_unasked": f"{sum(r['ok'] for r in must_rows)}/{len(must_rows)}",
        "known_drawn_and_detailed": f"{sum(r['ok'] for r in known_rows)}/{len(known_rows)}",
        "i_dont_know_without_search": sum(1 for r in rows if admits_ignorance(r["said"]) and not r["researched"]),
    }
    print(json.dumps(summary, indent=1))
    (ROOT / "core" / "logs" / "knowledge-evals.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
