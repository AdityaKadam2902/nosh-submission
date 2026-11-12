"""Build data/recipes.db from the 3 raw JSON files (M0: originals + validity only).

  python -m scripts.build_db                 # full build
  python -m scripts.build_db --sample 5000   # fast demo build: 5000 records total, split evenly over ar/epi/fn
  python -m scripts.build_db --inspect       # print top-level JSON structure only

Top-level structure expected (ARCHITECTURE §2 [VERIFY]): dict {orig_key: {title, ingredients, instructions, picture_link}}.
A list is tolerated (orig_key = index, loud warning). Anything else aborts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from recipebot.db import ING_INSERT_SQL, INSERT_SQL, SCHEMA, SOURCES, connect, data_dir, db_path, find_source_file, recipe_row
from recipebot.normalize import CONFIG_DIR, clean_ingredients
from recipebot.search import build_fts
from recipebot.steps import count_steps


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def config_sha() -> str:
    h = hashlib.sha256()
    for p in sorted(Path(CONFIG_DIR).glob("*.yaml")):
        h.update(p.name.encode() + p.read_bytes())
    return h.hexdigest()


def derive(rec):
    """M1: (recipe_derived_tuple, ingredient_rows). is_valid = title AND >=1 clean ingredient AND >=1 step."""
    r = rec if isinstance(rec, dict) else {}
    ings = r.get("ingredients")
    rows = [(d["pos"], d["raw"], d["canon"], d["qty"], d["unit"], ",".join(d["forms"]) or None,
             json.dumps(d["alts"], ensure_ascii=False) if d["alts"] else None)
            for d in clean_ingredients(ings if isinstance(ings, list) else [])]
    n_steps, n_alt = count_steps(r.get("instructions"))
    title = r.get("title")
    if not isinstance(rec, dict):
        reasons = ["malformed_record"]
    else:
        reasons = [x for x, bad in (("no_title", not (isinstance(title, str) and title.strip())),
                                    ("no_ingredients", not rows), ("no_instructions", n_steps == 0)) if bad]
    return (0 if reasons else 1, ",".join(reasons) or None, len(rows), n_steps, n_alt), rows


def iter_records(obj, log=print):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k), v
    elif isinstance(obj, list):
        log("  WARNING: top-level is a LIST, not a dict; using the list index as orig_key.")
        for i, v in enumerate(obj):
            yield str(i), v
    else:
        raise SystemExit(f"Unsupported top-level JSON type: {type(obj).__name__}")


def describe_structure(obj, n_examples: int = 2) -> list[str]:
    lines = [f"top-level type: {type(obj).__name__}, size: {len(obj):,}"]
    items = list(iter_records(obj, log=lambda *_: None))
    if not items:
        return lines + ["(empty)"]
    value_types = Counter(type(v).__name__ for _, v in items)
    key_sets = Counter(tuple(sorted(v)) if isinstance(v, dict) else () for _, v in items)
    lines.append(f"value types: {dict(value_types)}")
    lines.append(f"key samples: {[k for k, _ in items[:3]]}")
    lines.append("field sets: " + "; ".join(f"{list(ks)} x{n:,}" for ks, n in key_sets.most_common(5)))
    for k, v in items[:n_examples]:
        if isinstance(v, dict):
            lines.append(f"example {k}: " + json.dumps({f: (str(x)[:60] if not isinstance(x, list) else [str(i)[:40] for i in x[:2]] + (["..."] if len(x) > 2 else [])) for f, x in v.items()}, ensure_ascii=False))
    return lines


def build(data_directory=None, db=None, sample: int | None = None, seed: int = 0, log=print) -> dict:
    data_directory = Path(data_directory or data_dir())
    db = Path(db or db_path())
    tmp = db.with_name(db.name + ".tmp")
    db.parent.mkdir(parents=True, exist_ok=True)
    tmp.unlink(missing_ok=True)

    conn = connect(tmp)
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA journal_mode=MEMORY")
    meta = {"sample": str(sample or ""), "seed": str(seed), "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    summary = {}

    for i, src in enumerate(SOURCES):
        path = find_source_file(data_directory, src)
        log(f"[{src}] reading {path.name}")
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
        for line in describe_structure(obj):
            log("  " + line)
        items = list(iter_records(obj, log))
        n_file = len(items)
        field_counts = Counter(f for _, v in items if isinstance(v, dict) for f in v)
        if sample:
            quota = min(sample // len(SOURCES) + (1 if i < sample % len(SOURCES) else 0), n_file)
            idx = sorted(random.Random(f"{seed}:{src}").sample(range(n_file), quota))
            items = [items[j] for j in idx]
        batch, ibatch, loaded = [], [], 0
        for key, rec in items:
            derived, rows = derive(rec)
            batch.append(recipe_row(src, key, rec, derived))
            rid = batch[-1][0]
            ibatch.extend((rid, *row) for row in rows)
            if len(batch) >= 5000:
                conn.executemany(INSERT_SQL, batch)
                conn.executemany(ING_INSERT_SQL, ibatch)
                loaded += len(batch)
                batch, ibatch = [], []
        if batch:
            conn.executemany(INSERT_SQL, batch)
            conn.executemany(ING_INSERT_SQL, ibatch)
            loaded += len(batch)
        meta[f"source_file:{src}"] = path.name
        meta[f"sha256:{src}"] = sha256_file(path)
        meta[f"source_records:{src}"] = str(n_file)
        meta[f"loaded:{src}"] = str(loaded)
        meta[f"fields:{src}"] = json.dumps(dict(field_counts), sort_keys=True)
        summary[src] = {"file_records": n_file, "loaded": loaded}
        log(f"  loaded {loaded:,} / {n_file:,}")
        del obj, items

    meta["config_sha"] = config_sha()
    conn.executemany("INSERT INTO meta VALUES (?,?)", list(meta.items()))
    conn.executescript("CREATE INDEX idx_ing_recipe ON ingredients(recipe_id); CREATE INDEX idx_ing_canon ON ingredients(canon);")
    conn.commit()
    log(f"FTS5 index: {build_fts(conn):,} rows")
    valid, total = conn.execute("SELECT SUM(is_valid), COUNT(*) FROM recipes").fetchone()
    conn.close()
    os.replace(tmp, db)
    summary["total"] = {"loaded": total, "valid": valid or 0, "invalid": total - (valid or 0)}
    log(f"Built {db}: {total:,} records, {valid or 0:,} valid, {total - (valid or 0):,} invalid")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--sample", type=int, default=None, help="total records, split evenly across sources (seeded)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--inspect", action="store_true", help="only print top-level JSON structure")
    a = ap.parse_args(argv)
    if a.inspect:
        for src in SOURCES:
            p = find_source_file(a.data_dir or data_dir(), src)
            print(f"[{src}] {p}")
            with open(p, encoding="utf-8") as f:
                for line in describe_structure(json.load(f)):
                    print("  " + line)
        return 0
    build(a.data_dir, a.db, a.sample, a.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
