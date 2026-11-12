"""Eyeball normalization: top-N canon names + random raw->canon pairs.  python scripts/top_canon.py [--top 50] [--sample 30] [--seed 0]"""
import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from recipebot.db import connect, db_path  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--sample", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    c = connect(a.db or db_path(), readonly=True)
    n_valid = c.execute("SELECT COUNT(*) FROM recipes WHERE is_valid=1").fetchone()[0]
    print(f"== top {a.top} canon names by # valid recipes (of {n_valid:,}) ==")
    for i, (canon, n) in enumerate(c.execute(
            "SELECT canon, COUNT(DISTINCT recipe_id) n FROM ingredients WHERE recipe_id IN (SELECT id FROM recipes WHERE is_valid=1) "
            "GROUP BY canon ORDER BY n DESC, canon LIMIT ?", (a.top,)), 1):
        print(f"{i:3}. {canon:32} {n:8,}  {100 * n / max(n_valid, 1):5.1f}%")
    tot, dist = c.execute("SELECT COUNT(*), COUNT(DISTINCT canon) FROM ingredients").fetchone()
    print(f"\ningredient rows: {tot:,}; distinct canon: {dist:,}")
    print(f"\n== {a.sample} random raw -> canon (seed {a.seed}) ==")
    lo, hi = c.execute("SELECT MIN(rowid), MAX(rowid) FROM ingredients").fetchone()
    rng, shown = random.Random(a.seed), 0
    while shown < a.sample:
        r = c.execute("SELECT raw, canon, qty, unit, forms, alts FROM ingredients WHERE rowid >= ? ORDER BY rowid LIMIT 1", (rng.randint(lo, hi),)).fetchone()
        if r:
            raw, canon, qty, unit, forms, alts = r
            print(f"{raw[:60]!r:64} -> {canon!r} qty={qty} unit={unit} forms={forms} alts={alts}")
            shown += 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
