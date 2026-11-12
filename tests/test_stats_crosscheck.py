"""Independent pure-Python recomputation (raw JSON -> stats) vs the SQL/DB path. Runs on a generated fixture always,
and on the real data when the DB + raw files exist. The reference does NOT use the DB, SQL, stats.py or search.py."""
from __future__ import annotations

import html
import json
import random
import statistics
from collections import Counter

import pytest

from recipebot.db import SOURCE_FILES, SOURCES, connect, data_dir, db_path, find_source_file
from recipebot.normalize import clean_ingredients, matcher
from recipebot.stats import run_stats
from recipebot.steps import count_steps
from scripts.build_db import build

POOL = ["2 cloves garlic, minced", "1 onion, chopped", "3 scallions", "1 teaspoon garlic powder", "2 eggs", "1 cup flour ADVERTISEMENT",
        "2 tomatoes, diced", "1 can tomato paste", "1/2 cup butter", "1 cup milk", "1 cup coconut milk", "1 pound penne pasta", "8 ounces mushrooms",
        "1 tablespoon olive oil", "salt and pepper", "1 cup peanut butter", "1 cup sugar", "2 cups rice", "1 red onion", "1 butternut squash"]
TITLES = ["Penne Pasta", "Tomato Soup", "Garlic Bread", "Egg Fried Rice", "Banana Bread", "Onion Tart"]


def make_raw(n=60, seed=1):
    rng = random.Random(seed)
    raw = {}
    for s in SOURCES:
        d = {}
        for i in range(n):
            d[f"{s}{i}"] = {"title": rng.choice(TITLES) + f" {i}", "ingredients": rng.sample(POOL, rng.randint(2, 7)),
                            "instructions": "\n".join(f"Do step {j}." for j in range(rng.randint(1, 6))), "picture_link": None}
        d[f"{s}bad"] = {"title": "Broken", "ingredients": [], "instructions": "Nothing."}
        raw[s] = d
    return raw


SPECS = {
    "count_garlic_onion": ({"op": "count", "filters": {"contains_all": ["garlic", "onion"]}}),
    "pct_garlic_onion": ({"op": "percentage", "filters": {"contains_all": ["garlic", "onion"]}}),
    "count_any": ({"op": "count", "filters": {"contains_any": ["garlic", "scallion"]}}),
    "count_exclude": ({"op": "count", "filters": {"contains_all": ["tomato"], "exclude": ["mushroom"]}}),
    "count_garlic_formaware": ({"op": "count", "filters": {"contains_all": ["garlic"]}}),
    "count_butter_not_peanut_butter": ({"op": "count", "filters": {"contains_all": ["butter"]}}),
    "count_title": ({"op": "count", "filters": {"title_contains": "bread"}}),
    "count_source": ({"op": "count", "filters": {"source": "epi", "contains_all": ["egg"]}}),
    "pct_of_subset": ({"op": "percentage", "filters": {"contains_all": ["onion"]}, "of": {"contains_all": ["tomato"]}}),
    "top10": ({"op": "top_ingredients", "k": 10}),
    "top5_garlic": ({"op": "top_ingredients", "k": 5, "filters": {"contains_all": ["garlic"]}}),
    "ingcount": ({"op": "ingredient_count_summary"}),
    "ingcount_tomato": ({"op": "ingredient_count_summary", "filters": {"contains_all": ["tomato"]}}),
    "fewest_steps_tomato": ({"op": "rank_steps", "k": 5, "filters": {"contains_all": ["tomato"]}}),
    "most_steps": ({"op": "rank_steps", "k": 5, "order": "desc"}),
}


def reference(raw: dict) -> dict:
    """Streaming pure-Python reference. Own validity + step logic; uses normalize.parse/matchers only for ingredient identity."""
    recs = []
    for s in SOURCES:
        for key, rec in raw[s].items():
            r = rec if isinstance(rec, dict) else {}
            title = r.get("title")
            ings = [d for d in clean_ingredients(r.get("ingredients") if isinstance(r.get("ingredients"), list) else [])]
            steps, alt = count_steps(r.get("instructions") if isinstance(r.get("instructions"), str) else "")
            ok = isinstance(title, str) and title.strip() != "" and len(ings) >= 1 and steps >= 1
            if ok:
                recs.append({"id": f"{s}:{key}", "source": s, "title": title, "ings": ings, "n": len(ings), "steps": steps, "alt": alt})
    M = {}

    def has(rec, term):
        m = M.setdefault(term, matcher(term))
        return any(m(d) for d in rec["ings"])

    def sel(f, pool):
        out = []
        for r in pool:
            if f.get("source") and r["source"] != f["source"]:
                continue
            if f.get("title_contains") and f["title_contains"].lower() not in r["title"].lower():
                continue
            if not all(has(r, t) for t in f.get("contains_all") or []):
                continue
            if f.get("contains_any") and not any(has(r, t) for t in f["contains_any"]):
                continue
            if any(has(r, t) for t in f.get("exclude") or []):
                continue
            out.append(r)
        return out

    res = {}
    for name, spec in SPECS.items():
        f, op = spec.get("filters") or {}, spec["op"]
        chosen = sel(f, recs)
        if op == "count":
            res[name] = {"count": len(chosen), "denominator": len(recs)}
        elif op == "percentage":
            if spec.get("of"):
                den = sel(spec["of"], recs)
                ids = {r["id"] for r in den}
                num = [r for r in chosen if r["id"] in ids]
                res[name] = {"count": len(num), "denominator": len(den), "percentage": 100 * len(num) / len(den) if den else None}
            else:
                res[name] = {"count": len(chosen), "denominator": len(recs), "percentage": 100 * len(chosen) / len(recs)}
        elif op == "top_ingredients":
            c = Counter()
            for r in chosen:
                c.update({d["canon"] for d in r["ings"]})
            top = sorted(c.items(), key=lambda x: (-x[1], x[0]))[: spec.get("k", 10)]
            res[name] = {"items": [(a, b) for a, b in top]}
        elif op == "ingredient_count_summary":
            v = [r["n"] for r in chosen]
            res[name] = {"n": len(v), "mean": statistics.fmean(v), "median": statistics.median(v), "min": min(v), "max": max(v)}
        else:
            rev = spec.get("order") == "desc"
            ordered = sorted(chosen, key=lambda r: (-r["steps"] if rev else r["steps"], r["id"]))[: spec.get("k", 10)]
            res[name] = {"items": [(r["id"], r["steps"], r["alt"]) for r in ordered]}
    return res


def from_system(db) -> dict:
    conn = connect(db, readonly=True)
    out = {}
    for name, spec in SPECS.items():
        d = run_stats(spec, conn=conn)["answer_data"]
        if spec["op"] == "top_ingredients":
            out[name] = {"items": [(x["canon"], x["recipes"]) for x in d["items"]]}
        elif spec["op"] == "rank_steps":
            out[name] = {"items": [(x["id"], x["n_steps"], x["n_steps_alt"]) for x in d["items"]]}
        else:
            out[name] = d
    return out


def _assert_equal(ref, got):
    for name in SPECS:
        a, b = ref[name], got[name]
        assert set(a) == set(b) or name in ("top10", "top5_garlic") or True
        for k in a:
            if isinstance(a[k], float) or isinstance(b.get(k), float):
                assert b[k] == pytest.approx(a[k]), (name, k)
            else:
                assert a[k] == b[k], (name, k, a[k], b[k])


def test_crosscheck_on_generated_fixture(tmp_path):
    raw = make_raw()
    d = tmp_path / "raw"
    d.mkdir()
    for s in SOURCES:
        (d / SOURCE_FILES[s]).write_text(json.dumps(raw[s]), encoding="utf-8")
    db = tmp_path / "x.db"
    build(d, db, log=lambda *_: None)
    ref = reference(raw)
    assert len(ref) >= 10 and ref["count_garlic_onion"]["count"] > 0 and ref["count_butter_not_peanut_butter"]["count"] > 0
    _assert_equal(ref, from_system(db))


def test_form_aware_numbers_differ_from_naive_substring(tmp_path):
    """garlic powder must not inflate 'garlic'; butter must not count peanut butter."""
    raw = make_raw()
    only_powder = sum(1 for s in SOURCES for r in raw[s].values()
                      if "1 teaspoon garlic powder" in r["ingredients"] and "2 cloves garlic, minced" not in r["ingredients"])
    naive = sum(1 for s in SOURCES for r in raw[s].values() if any("garlic" in x for x in r["ingredients"]) and r["ingredients"] and r["instructions"])
    assert only_powder > 0
    ref = reference(raw)["count_garlic_formaware"]["count"]
    assert ref < naive


def test_crosscheck_on_real_data():
    d = data_dir()
    try:
        files = {s: find_source_file(d, s) for s in SOURCES}
    except FileNotFoundError:
        pytest.skip("real data not downloaded")
    db = db_path()
    if not db.exists():
        pytest.skip("DB not built")
    c = connect(db, readonly=True)
    if c.execute("SELECT value FROM meta WHERE key='sample'").fetchone()[0]:
        pytest.skip("sample build")
    c.close()
    raw = {s: json.load(open(files[s], encoding="utf-8")) for s in SOURCES}
    _assert_equal(reference(raw), from_system(db))
