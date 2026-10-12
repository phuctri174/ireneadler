r"""Research answers, live: ten questions with known answers through the whole turn -
router, research (SearXNG + her Chrome), the model, grounding - scored on what she
actually SAYS.

  .venv\Scripts\python evals\research_answers.py

Per question: correct (the spoken answer matches the known answer, and never the
known wrong one), a real spoken SUMMARY - four to six sentences before the panel
offer, 60-150 words in all - never a deflection to the panel in place of the
answer, the panel offered only after it, claims kept vs cut by grounding.
The last five are topics, not facts ("Research the Queen's Gambit"): the case
that, live, got "I can only say part of it - want me to show the panel?". Writes
core/logs/research-answers.json. Needs Ollama, her SearXNG and Chrome; no OS input.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

import irene  # noqa: E402,F401
from irene.brain import Conversation  # noqa: E402
from irene.llm import Ollama  # noqa: E402

# (question, the spoken answer must match, and must never match)
CASES = [
    ("What is gyaku-do in kendo?", r"\bleft\b|hidari", r"backward step|step back|evade|evasion|dodge"),
    ("How tall is the Eiffel Tower?", r"\b3[03]0\b|1,?083", None),
    ("Who painted The Starry Night?", r"van gogh", None),
    ("In what year did the Berlin Wall fall?", r"1989", None),
    ("What is the boiling point of water in Fahrenheit at sea level?", r"212", None),
    ("How many bones are in the adult human body?", r"\b206\b", None),
    ("Who wrote One Hundred Years of Solitude?", r"m[aá]rquez", None),
    ("What does a men strike target in kendo?", r"\bhead\b", None),
    ("What is the speed of light in kilometres per second?", r"299,?\s?79\d|300,?000|three hundred thousand", None),
    ("What is the capital of Australia?", r"canberra", r"^(?!.*canberra).*sydney"),
    # topics: a summary of the key points
    ("Research the Queen's Gambit opening.", r"\bd4\b|\bc4\b|pawn", None),
    ("Research how kendo dan grades work.", r"\bdan\b|\bkyu\b", None),
    ("Research why the sky is blue.", r"scatter", None),
    ("Research how photosynthesis works.", r"light|sun", None),
    ("Research what caused the French Revolution.", r"debt|tax|bread|estate|monarch|king", None),
]
BAND = (60, 150)
SENTENCES = (4, 6)
# the panel offered in place of an answer
DEFLECT = re.compile(r"only (say|tell|give|cover|share) (you )?(a |part|some)|can'?t (say|tell you|fit) (it )?all|all (on|in) the panel|panel has the rest|too (much|long) to say", re.I)


class Host:
    """Runs tools for real; collects what she says."""

    def __init__(self):
        self.said: list[str] = []

    async def thinking(self):
        pass

    async def confirm(self, prompt):
        return False

    async def tool_status(self, name, status):
        pass

    def reply_sink(self):
        host = self

        class Sink:
            def line(self, line):
                host.said.append(line.text)

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

    async def perform(self, names):
        return names


async def main() -> None:
    llm = Ollama()
    rows = []
    for question, right, wrong in CASES:
        conv = Conversation(llm)  # each question fresh: no carry-over
        host = Host()
        started = time.perf_counter()
        turn = await conv.respond(question + " Look it up.", host)
        spoken = " ".join(host.said)
        words = len(spoken.split())
        ok = bool(re.search(right, spoken, re.I)) and not (wrong and re.search(wrong, spoken, re.I | re.S))
        offer = host.said[-1] if host.said and "panel" in host.said[-1].lower() else ""
        summary_text = " ".join(host.said[:-1] if offer else host.said)
        sentences = len([x for x in re.split(r"(?<=[.!?])\s+", summary_text) if len(x.split()) >= 4])
        deflected = bool(DEFLECT.search(spoken)) or any("panel" in t.lower() for t in host.said[:-1])
        row = {
            "question": question, "correct": ok, "words": words, "in_band": BAND[0] <= words <= BAND[1],
            "sentences": sentences, "summary": SENTENCES[0] <= sentences <= SENTENCES[1], "deflected": deflected,
            "researched": "research" in turn.tools_used, "claims_kept": len(turn.claims),
            "offered_panel": bool(offer),
            "seconds": round(time.perf_counter() - started, 1), "said": spoken, "cut": turn.cut,
        }
        rows.append(row)
        print(f"{'OK  ' if ok else 'FAIL'} {words:3d}w {sentences}s {'band' if row['in_band'] else 'OUT '} {'DEFLECTED ' if deflected else ''}claims {row['claims_kept']} cut {len(turn.cut)}  {question}\n     {spoken[:300]}")
        for c in turn.cut:
            print(f"     CUT: {c[:140]}")
    n = len(rows)
    summary = {
        "correct": f"{sum(r['correct'] for r in rows)}/{n}",
        "spoken_in_60_150_words": f"{sum(r['in_band'] for r in rows)}/{n}",
        "summary_4_to_6_sentences": f"{sum(r['summary'] for r in rows)}/{n}",
        "deflected": f"{sum(r['deflected'] for r in rows)}/{n}",
        "median_words": sorted(r["words"] for r in rows)[n // 2],
        "researched": f"{sum(r['researched'] for r in rows)}/{n}",
        "offered_panel": f"{sum(r['offered_panel'] for r in rows)}/{n}",
        "median_seconds": sorted(r["seconds"] for r in rows)[n // 2],
    }
    print(json.dumps(summary, indent=1))
    out = ROOT / "core" / "logs" / "research-answers.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    await llm.close()


if __name__ == "__main__":
    asyncio.run(main())
