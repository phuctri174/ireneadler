r"""How often each summon entrance really comes up.

    .venv\Scripts\python scripts\entrance_odds.py [--since "2026-10-04 17:00"]

For the weights in config/entrances.json as they are now, per entrance:
  weight   its raw share of the weights
  expect   its real long-run share with the repeat rule (a heavy entrance sits out
           the summon after itself, so its share is below its raw one) - the
           stationary distribution of the pick-to-pick chain
  sim      20,000 picks through the app's own Picker
  log      the drawn summons in core/logs (named ones - the hand sign, "Irene
           Adler" - are not draws and are left out), since --since
"""
from __future__ import annotations

import argparse
import collections
import glob
import random
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from irene import entrances  # noqa: E402


def expected(weights: dict[str, float], picking: dict) -> dict[str, float]:
    """The long-run share of each entrance under the repeat rule."""
    names = [n for n, w in weights.items() if w > 0]
    w = np.array([weights[n] for n in names])
    chain = np.zeros((len(names), len(names)))
    for i, name in enumerate(names):
        row = w.copy()
        if picking.get("no_repeat", True) and name not in picking.get("may_repeat", []):
            row[i] = 0
        chain[i] = row / row.sum()
    vals, vecs = np.linalg.eig(chain.T)
    v = np.real(vecs[:, np.argmin(np.abs(vals - 1))])
    return dict(zip(names, v / v.sum()))


def simulate(entries: list[dict], n: int = 20000, seed: int = 0) -> dict[str, float]:
    picker = entrances.Picker(entries, random.Random(seed), live=True)
    counts = collections.Counter(picker.pick()["name"] for _ in range(n))
    return {k: v / n for k, v in counts.items()}


def from_logs(since: str) -> collections.Counter:
    counts: collections.Counter = collections.Counter()
    for path in glob.glob(str(HERE.parent / "logs" / "core.log*")):
        for line in open(path, encoding="utf-8", errors="replace"):
            m = re.search(r"summon entrance: (\w+) \(drawn", line)
            if m and line[:19] >= since:
                counts[m.group(1)] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="0000", help="only log lines from this time on (YYYY-MM-DD HH:MM)")
    args = parser.parse_args()
    entries = entrances.load_registry()
    weights, picking = entrances.load_odds()
    exp = expected(weights, picking)
    sim = simulate(entries)
    logged = from_logs(args.since)
    total_w = sum(w for w in weights.values() if w > 0)
    n_log = sum(logged.values())
    print(f"repeat rule: no_repeat={picking.get('no_repeat', True)}, may_repeat={picking.get('may_repeat', [])}")
    print(f"{'entrance':18} {'weight':>7} {'raw':>6} {'expect':>7} {'sim':>6}   log ({n_log} drawn)")
    for name in sorted(exp, key=lambda n: -exp[n]):
        share = f"{logged[name]:3d} {logged[name] / n_log:5.0%}" if n_log else "-"
        print(f"{name:18} {weights[name]:7g} {weights[name] / total_w:6.0%} {exp[name]:7.1%} {sim.get(name, 0):6.1%}   {share}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
