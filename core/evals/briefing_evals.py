r"""Evals for her considerate greetings and the daily briefing - no model needed.

  greetings   per scenario (a rainy morning, back after five minutes, a late
              night, a long day, a timer running, ...): her greetings vary, never
              repeat back to back, always say "Mister Tri", stay at two sentences,
              mention the scenario's real context, and don't all end in an offer
  gold        the gold is SJC's bar in VND per lượng from a Vietnamese source
              (sjc.com.vn, else giavang.org) - never XAU/USD spot; live, and on a
              fixed reply of SJC's own service
  expansion   "the second one", "gold", "last" resolve to the right item

Run (from core/): .venv\Scripts\python evals\briefing_evals.py [--offline]
"""
from __future__ import annotations

import argparse
import asyncio
import random
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from irene.greeting import NAME, Context, Greeter, ends_with_offer, sentences  # noqa: E402
from tools import briefing as B  # noqa: E402

RAIN = {"temp": 15, "sky": "Heavy rain", "days": [{"day": "Tue", "high": 22, "low": 14, "rain": 100, "sky": "Heavy rain"}], "rain_streak": 3}
DRY = {"temp": 21, "sky": "Partly cloudy", "days": [{"day": "Tue", "high": 25, "low": 15, "rain": 10, "sky": "Partly cloudy"}], "rain_streak": 0}

# (name, context, a pattern every greeting must match: its real context)
SCENARIOS = [
    ("rainy-morning", Context(datetime(2026, 10, 6, 8, 10), weather=RAIN, since_last_s=14 * 3600), r"rain|pouring|umbrella|day three|three days"),
    ("back-quickly", Context(datetime(2026, 10, 6, 15, 0), weather=DRY, since_last_s=240), r"back|again|fast|quick|soon|forget"),
    ("late-night", Context(datetime(2026, 10, 7, 0, 40), weather=DRY, since_last_s=5 * 3600), r"still up|midnight|asleep|late|night|sleep|bed"),
    ("long-day", Context(datetime(2026, 10, 6, 19, 30), weather=DRY, since_last_s=2 * 3600, first_today=datetime(2026, 10, 6, 6, 0)), r"six|since|long day|still going|two hours|welcome back|there you are|back again"),
    ("early", Context(datetime(2026, 10, 6, 5, 10), weather=DRY, since_last_s=9 * 3600, usual_hour=8.5), r"early|sun|sleep|bird|got you up"),
    ("timer", Context(datetime(2026, 10, 6, 14, 0), weather=DRY, since_last_s=1800, timer={"label": "tea", "left_s": 480}), r"timer|left|to go|welcome back|there you are|back again"),
    ("away-days", Context(datetime(2026, 10, 6, 10, 0), weather=DRY, since_last_s=4 * 86400), r"days|wonder|look who"),
]


def greeting_evals(lines: list[str]) -> tuple[int, int]:
    ok_n = total = 0
    offers: list[bool] = []
    for name, ctx, must in SCENARIOS:
        g = Greeter(random.Random(sum(map(ord, name))))
        said = []
        for _ in range(30):
            said.append(g.for_entrance({"name": "x", "greetings": ["Ta-da! Did you miss me?"]}, ctx.now.hour, ctx))
        problems = []
        if any(NAME not in s for s in said):
            problems.append("no name")
        if any(a == b for a, b in zip(said, said[1:])):
            problems.append("repeated back to back")
        if len(set(said)) < 6:
            problems.append(f"only {len(set(said))} different")
        if any(sentences(s) > 2 for s in said):
            problems.append("over two sentences: " + next(s for s in said if sentences(s) > 2))
        # her own entrance line stands in now and then; the rest are about now
        about = [s for s in said if "miss me" not in s.lower()]
        missing = [s for s in about if not re.search(must, s, re.I)]
        if len(missing) > len(about) * 0.4:
            problems.append(f"{len(missing)}/{len(about)} ignore the context, e.g. {missing[0]!r}")
        offers += [ends_with_offer(s) for s in about]
        total += 1
        ok_n += not problems
        lines.append(f"{'PASS' if not problems else 'FAIL'} greeting {name:14} {said[0]!r} | {said[1]!r}" + (f"  {'; '.join(problems)}" if problems else ""))
    rate = sum(offers) / max(1, len(offers))
    total += 1
    ok_n += rate < 0.4
    lines.append(f"{'PASS' if rate < 0.4 else 'FAIL'} greeting offers      {rate:.0%} end in an offer of help (under 40%)")
    return ok_n, total


def _ms(when: datetime) -> str:
    return f"/Date({int(when.timestamp() * 1000)})/"


def gold_fixture_evals(lines: list[str]) -> tuple[int, int]:
    """SJC's own reply format -> the right bar, its day change, VND per lượng."""
    vn = B.VN
    now = datetime(2026, 10, 6, 9, 0, tzinfo=vn)
    rows = [
        {"TypeName": "Vàng SJC 1L, 10L, 1KG", "BranchName": "Hồ Chí Minh", "BuyValue": 140500000, "SellValue": 143500000, "GroupDate": _ms(now - timedelta(days=1, hours=1))},
        {"TypeName": "Vàng nhẫn SJC 99,99% 1 chỉ, 2 chỉ, 5 chỉ", "BranchName": "Hồ Chí Minh", "BuyValue": 139000000, "SellValue": 142000000, "GroupDate": _ms(now - timedelta(minutes=30))},
        {"TypeName": "Vàng SJC 1L, 10L, 1KG", "BranchName": "Hồ Chí Minh", "BuyValue": 140700000, "SellValue": 143700000, "GroupDate": _ms(now - timedelta(minutes=20))},
    ]
    g = B.parse_sjc(rows, now)
    item = B.gold_item(g)
    checks = [
        ("the bar, not the ring", g["sell"] == 143700000),
        ("day change against yesterday's last", g["change_sell"] == 200000),
        ("spoken per lượng at SJC", item is not None and "lượng" in item.say and "SJC" in item.say and "200,000" in item.say),
        ("flat day not spoken", B.gold_item(B.parse_sjc(rows[:1], now)) is None),
    ]
    for name, ok in checks:
        lines.append(f"{'PASS' if ok else 'FAIL'} gold     {name}")
    return sum(ok for _, ok in checks), len(checks)


async def gold_live_evals(lines: list[str]) -> tuple[int, int]:
    try:
        g = await B.gold()
    except Exception as error:  # noqa: BLE001
        lines.append(f"FAIL gold     live: both Vietnamese sources failed ({error})")
        return 0, 1
    checks = [
        (f"from a Vietnamese SJC source ({g['source']})", g["source"] in ("sjc.com.vn", "giavang.org")),
        (f"VND per lượng, not XAU/USD (sell {g['sell']:,.0f})", 50e6 < g["sell"] < 1e9 and 50e6 < g["buy"] <= g["sell"]),
        (f"the SJC bar ({g['name']})", g["name"].startswith("Vàng SJC 1L")),
    ]
    for name, ok in checks:
        lines.append(f"{'PASS' if ok else 'FAIL'} gold     live {name}")
    return sum(ok for _, ok in checks), len(checks)


def expansion_evals(lines: list[str]) -> tuple[int, int]:
    items = [
        B.Item("gold", "GOLD", 5, "Gold's up.", {"kind": "chart", "up": True}),
        B.Item("market", "NVDA", 4, "NVIDIA had a rough night.", {"kind": "chart", "up": False}),
        B.Item("world", "SPAIN", 3, "Abroad...", {"kind": "story", "words": ["housing", "crisis"]}),
    ]
    b = B.Briefing("07:00", items, [], [], {}, [])
    want = {"2": 2, "second": 2, "gold": 1, "the gold": 1, "nvidia": 2, "last": 3, "3": 3, "housing": 3, "1": 1}
    ok_n = 0
    for said, n in want.items():
        got = B._which(said, b)
        ok = got is not None and got[0] == n
        ok_n += ok
        lines.append(f"{'PASS' if ok else 'FAIL'} expand   {said!r:12} -> item {got[0] if got else None} (want {n})")
    bad = B._which("7", b) is None
    lines.append(f"{'PASS' if bad else 'FAIL'} expand   '7' -> none (three items)")
    return ok_n + bad, len(want) + 1


async def main_quiet(quiet: bool = False, offline: bool = False) -> bool:
    """For run_evals.py: every check, printed (failures only when quiet)."""
    lines, ok, total = await _run(offline)
    for line in lines:
        if not quiet or line.startswith("FAIL"):
            print(line)
    print(f"briefing evals: {ok}/{total}")
    return ok == total


async def _run(offline: bool) -> tuple[list[str], int, int]:
    lines: list[str] = []
    ok, total = 0, 0
    for got in (greeting_evals(lines), gold_fixture_evals(lines), expansion_evals(lines)):
        ok, total = ok + got[0], total + got[1]
    if not offline:
        got = await gold_live_evals(lines)
        ok, total = ok + got[0], total + got[1]
    return lines, ok, total


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="skip the live SJC fetch")
    args = parser.parse_args()
    return 0 if await main_quiet(offline=args.offline) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
