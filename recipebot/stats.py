"""Task-1 analytics (ARCHITECTURE §7). run_stats(spec) -> {answer_data, receipt}.
spec = {op, filters, k, ...}. Aggregates run over the FULL filtered corpus (SQL + form-aware matcher), never over search results.
ops: count | percentage (of valid dataset, or of `of` filters) | top_ingredients(k, skip_staples) |
     ingredient_count_summary | rank_steps(k, order asc|desc; ties: n_steps then id ASC)
filters: contains_all[], contains_any[], exclude[], title_contains, source
"""
from __future__ import annotations

import json
import statistics

from recipebot.db import connect, db_path
from recipebot.normalize import load_yaml, matcher, query_info
from recipebot.receipt import STEP_RULE, dataset_counts, describe_filters, make_receipt, normalization_mode

OPS = ("count", "percentage", "top_ingredients", "ingredient_count_summary", "rank_steps")
BASE_SQL = "SELECT id FROM recipes WHERE is_valid=1"
TERM_SQL = ("SELECT i.recipe_id, i.canon, i.forms, i.alts FROM ingredients i JOIN recipes r ON r.id=i.recipe_id "
            "WHERE r.is_valid=1 AND i.canon LIKE ?")


def _term_ids(conn, term: str, sqls: list) -> set:
    qi = query_info(term)
    if not qi["canon"]:
        raise ValueError(f"cannot normalize ingredient term: {term!r}")
    m = matcher(term)
    sqls.append(TERM_SQL.replace("?", f"'%{qi['canon']}%'") + "  -- then form-aware match in Python")
    out = set()
    for rid, canon, forms, alts in conn.execute(TERM_SQL, (f"%{qi['canon']}%",)):
        if m({"canon": canon, "forms": forms or "", "alts": json.loads(alts) if alts else []}):
            out.add(rid)
    return out


def match_ids(conn, f: dict, sqls: list | None = None) -> set:
    sqls = sqls if sqls is not None else []
    sql, args = BASE_SQL, []
    if f.get("source"):
        sql += " AND source=?"
        args.append(f["source"])
    if f.get("title_contains"):
        sql += " AND lower(title) LIKE ?"
        args.append(f"%{f['title_contains'].lower()}%")
    sqls.append(sql.replace("?", "{}").format(*[repr(a) for a in args]) if args else sql)
    ids = {r[0] for r in conn.execute(sql, args)}
    for t in f.get("contains_all") or []:
        ids &= _term_ids(conn, t, sqls)
    if f.get("contains_any"):
        anyset = set()
        for t in f["contains_any"]:
            anyset |= _term_ids(conn, t, sqls)
        ids &= anyset
    for t in f.get("exclude") or []:
        ids -= _term_ids(conn, t, sqls)
    return ids


def _with_ids(conn, ids: set):
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _ids(id TEXT PRIMARY KEY)")
    conn.execute("DELETE FROM _ids")
    conn.executemany("INSERT INTO _ids VALUES (?)", ((i,) for i in sorted(ids)))


def run_stats(spec: dict, db=None, conn=None) -> dict:
    op = spec.get("op")
    if op not in OPS:
        raise ValueError(f"unknown op {op!r}; choose from {OPS}")
    f = spec.get("filters") or {}
    k = int(spec.get("k") or 10)
    own = conn is None
    conn = conn or connect(db or db_path(), readonly=True)
    try:
        counts = dataset_counts(conn)
        sqls: list = []
        ids = match_ids(conn, f, sqls)
        terms = list(f.get("contains_all") or []) + list(f.get("contains_any") or []) + list(f.get("exclude") or [])
        filt = describe_filters(f)
        common = dict(normalization=normalization_mode(terms), step_rule=STEP_RULE, sql=sqls)
        if op == "count":
            data = {"count": len(ids), "denominator": counts["valid"]}
            rc = make_receipt("stats.count", filt, counts, n_analyzed=counts["valid"], formula="count = number of valid recipes matching the filters", **common)
        elif op == "percentage":
            of = spec.get("of") or {}
            den_ids = match_ids(conn, of, sqls) if of else None
            num_ids = ids & den_ids if den_ids is not None else ids
            den = len(den_ids) if den_ids is not None else counts["valid"]
            pct = 100.0 * len(num_ids) / den if den else None
            data = {"count": len(num_ids), "denominator": den, "percentage": pct}
            rc = make_receipt("stats.percentage", filt, counts, n_analyzed=counts["valid"],
                              denominator=f"{den:,} " + ("(valid recipes matching: " + "; ".join(describe_filters(of)) + ")" if of else "(all valid recipes)"),
                              formula="percentage = 100 * matching / denominator", **common)
        elif op == "top_ingredients":
            _with_ids(conn, ids)
            skip = {" ".join(s.lower().split()) for s in (load_yaml("staples")["default"] if spec.get("skip_staples") else [])}
            q = ("SELECT canon, COUNT(DISTINCT recipe_id) n FROM ingredients WHERE recipe_id IN (SELECT id FROM _ids) "
                 "GROUP BY canon ORDER BY n DESC, canon ASC LIMIT ?")
            rows = [(c, n) for c, n in conn.execute(q, (k + len(skip),)) if c not in skip][:k]
            sqls.append(q.replace("?", str(k)))
            data = {"items": [{"canon": c, "recipes": n, "percent": 100.0 * n / len(ids) if ids else None} for c, n in rows], "n_recipes": len(ids)}
            rc = make_receipt("stats.top_ingredients", filt, counts, n_analyzed=len(ids),
                              formula="rank = number of analyzed recipes containing the normalized ingredient (once per recipe); ties by name"
                                      + ("; staples skipped: " + ", ".join(sorted(skip)) if skip else ""), **common)
        elif op == "ingredient_count_summary":
            _with_ids(conn, ids)
            q = "SELECT n_ingredients FROM recipes WHERE id IN (SELECT id FROM _ids)"
            vals = [r[0] for r in conn.execute(q)]
            sqls.append(q)
            data = {"n": len(vals), "mean": statistics.fmean(vals) if vals else None, "median": statistics.median(vals) if vals else None,
                    "min": min(vals) if vals else None, "max": max(vals) if vals else None}
            rc = make_receipt("stats.ingredient_count_summary", filt, counts, n_analyzed=len(vals),
                              formula="n_ingredients = clean ingredient lines per recipe (ADVERTISEMENT/headers dropped; 'salt and pepper' counts as 2)", **common)
        else:  # rank_steps
            order = (spec.get("order") or "asc").lower()
            if order not in ("asc", "desc"):
                raise ValueError("order must be asc or desc")
            _with_ids(conn, ids)
            q = (f"SELECT r.id, r.title, r.n_steps, r.n_steps_alt FROM recipes r JOIN _ids ON _ids.id=r.id "
                 f"ORDER BY r.n_steps {order.upper()}, r.id ASC LIMIT ?")
            rows = conn.execute(q, (k,)).fetchall()
            sqls.append(q.replace("?", str(k)))
            tie = None
            if rows:
                last = rows[-1][2]
                n_tied = conn.execute("SELECT COUNT(*) FROM recipes r JOIN _ids ON _ids.id=r.id WHERE r.n_steps=?", (last,)).fetchone()[0]
                tie = f"{n_tied:,} analyzed recipes have {last} estimated steps (the boundary value); ties broken by id ascending"
            data = {"items": [{"id": i, "title": (t or "").strip(), "n_steps": n, "n_steps_alt": a} for i, t, n, a in rows], "order": order}
            rc = make_receipt("stats.rank_steps", filt, counts, n_analyzed=len(ids), formula=f"sort by estimated steps {order}, then id ascending; top {k}",
                              tie_note=tie, recipe_ids=[r[0] for r in rows], **common)
        return {"answer_data": data, "receipt": rc}
    finally:
        if own:
            conn.close()
