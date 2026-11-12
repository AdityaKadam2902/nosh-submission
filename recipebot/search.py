"""Retrieval (ARCHITECTURE §6): FTS5 BM25 candidates -> code-side hard filters -> ordered rows + receipt.
Vector (FAISS/RRF) retrieval is optional and not built yet: search says so in the receipt (BM25 only).
For aggregates use stats.py, NOT search.
"""
from __future__ import annotations

import html
import json
import re
from collections import defaultdict

from recipebot.constraints import check, resolve
from recipebot.db import connect, db_path
from recipebot.normalize import matcher
from recipebot.receipt import STEP_RULE, describe_filters, make_receipt, dataset_counts, normalization_mode

STOP = {"a", "an", "the", "for", "with", "and", "or", "of", "some", "me", "find", "show", "recipe", "recipes", "to", "in", "on", "i", "want", "give", "please"}
FTS_SQL = ("SELECT r.id, bm25(recipes_fts, 5.0, 1.0) AS score FROM recipes_fts JOIN recipes r ON r.rowid = recipes_fts.rowid "
           "WHERE recipes_fts MATCH ? ORDER BY score, r.id LIMIT ?")


def build_fts(conn) -> int:
    """(Re)build recipes_fts over valid recipes: title + normalized ingredient names. rowid = recipes.rowid."""
    conn.execute("DROP TABLE IF EXISTS recipes_fts")
    conn.execute("CREATE VIRTUAL TABLE recipes_fts USING fts5(title, ingredients_text, tokenize='porter unicode61')")
    ing = defaultdict(list)
    for rid, canon in conn.execute("SELECT recipe_id, canon FROM ingredients ORDER BY recipe_id, pos"):
        ing[rid].append(canon)
    rows = ((rowid, html.unescape(title or "").strip(), " ".join(dict.fromkeys(ing.get(rid, []))))
            for rowid, rid, title in conn.execute("SELECT rowid, id, title FROM recipes WHERE is_valid=1"))
    conn.executemany("INSERT INTO recipes_fts(rowid, title, ingredients_text) VALUES (?,?,?)", rows)
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM recipes_fts").fetchone()[0]


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP]


def _fts_rank(conn, toks: list[str], limit: int, k_min: int):
    """AND query first; widen to OR when AND yields fewer than k_min hits. Returns [(id, score)], mode."""
    quoted = [f'"{t}"' for t in toks]
    rows = conn.execute(FTS_SQL, (" AND ".join(quoted), limit)).fetchall()
    mode = "AND"
    if len(rows) < k_min and len(toks) > 1:
        seen = {r[0] for r in rows}
        more = conn.execute(FTS_SQL, (" OR ".join(quoted), limit)).fetchall()
        rows += [r for r in more if r[0] not in seen][: limit - len(rows)]
        mode = "AND then OR"
    return rows, mode


def _load_ingredients(conn, ids: list[str]) -> dict:
    out = defaultdict(list)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = f"SELECT recipe_id, pos, raw, canon, forms, alts, qty, unit FROM ingredients WHERE recipe_id IN ({','.join('?' * len(chunk))}) ORDER BY recipe_id, pos"
        for rid, pos, raw, canon, forms, alts, qty, unit in conn.execute(q, chunk):
            out[rid].append({"pos": pos, "raw": raw, "canon": canon, "forms": forms or "",
                             "alts": json.loads(alts) if alts else [], "qty": qty, "unit": unit})
    return out


def search(query: str = "", include=None, exclude=None, restrictions=None, max_steps=None, k: int = 10,
           db=None, conn=None, candidates: int = 300) -> dict:
    include, exclude, restrictions = list(include or []), list(exclude or []), list(restrictions or [])
    own = conn is None
    conn = conn or connect(db or db_path(), readonly=True)
    try:
        toks = _tokens(query)
        if toks:
            ranked, qmode = _fts_rank(conn, toks, candidates, k_min=k)
            retrieval = f"FTS5 BM25 (title weight 5x), query mode {qmode}, top {candidates}; vector index not built -> BM25 only"
        elif include:
            ids = [r[0] for r in conn.execute("SELECT id FROM recipes WHERE is_valid=1 ORDER BY id")]
            ings_all = _load_ingredients(conn, ids)
            ms = [matcher(t) for t in include]
            ranked = [(i, 0.0) for i in ids if all(any(m(d) for d in ings_all[i]) for m in ms)][:candidates]
            retrieval = "no text query: candidates = recipes matching include terms (ordered by id)"
        else:
            raise ValueError("empty query: give a dish query and/or include terms")
        ids = [r[0] for r in ranked]
        score = dict(ranked)
        ings = _load_ingredients(conn, ids)
        meta = {r[0]: r for r in conn.execute(
            f"SELECT id, title, source, n_steps, n_ingredients FROM recipes WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else {}
        inc_m, exc_m = [matcher(t) for t in include], [matcher(t) for t in exclude]
        dropped = {"include": 0, "exclude": 0, "max_steps": 0, "restriction_contains": 0}
        main, uncertain = [], []
        for rid in ids:
            _, title, source, n_steps, n_ing = meta[rid]
            L = ings[rid]
            if not all(any(m(d) for d in L) for m in inc_m):
                dropped["include"] += 1
                continue
            if any(any(m(d) for d in L) for m in exc_m):
                dropped["exclude"] += 1
                continue
            if max_steps is not None and n_steps > max_steps:
                dropped["max_steps"] += 1
                continue
            res = {r: check(L, r) for r in restrictions}
            states = [v["state"] for v in res.values()]
            if "contains" in states:
                dropped["restriction_contains"] += 1
                continue
            row = {"id": rid, "title": html.unescape(title or "").strip(), "source": source, "n_steps": n_steps, "n_ingredients": n_ing,
                   "score": score[rid], "restrictions": res}
            (uncertain if "possible" in states else main).append(row)
        key = lambda r: (r["score"], r["id"])
        main.sort(key=key)
        uncertain.sort(key=key)
        filt = describe_filters({"contains_all": include, "exclude": exclude}) if (include or exclude) else []
        if query.strip():
            filt.insert(0, f"text query: '{query.strip()}'")
        if restrictions:
            filt.append("restrictions (3-state, 'possible' goes to Uncertain): " + ", ".join(restrictions))
        if max_steps is not None:
            filt.append(f"max estimated steps <= {max_steps}")
        filt = filt or ["no filters (all valid recipes)"]
        shown = main[:k]
        receipt = make_receipt(
            "search", filt, dataset_counts(conn), retrieval=retrieval, candidates=len(ids),
            dropped=", ".join(f"{n}={v}" for n, v in dropped.items() if v) or "none",
            ordering="BM25 score ascending (best first), ties by id", normalization=normalization_mode(include + exclude),
            step_rule=STEP_RULE, recipe_ids=[r["id"] for r in shown], sql=[FTS_SQL])
        return {"rows": shown, "uncertain": uncertain[:k], "total_candidates": len(ids), "post_filter_count": len(main),
                "n_uncertain": len(uncertain), "dropped": dropped, "receipt": receipt}
    finally:
        if own:
            conn.close()


def get_recipe(recipe_id: str, db=None, conn=None) -> dict | None:
    """Original (untouched) record fields + derived columns, for /show and the evidence panel."""
    from recipebot.db import get_original
    own = conn is None
    conn = conn or connect(db or db_path(), readonly=True)
    try:
        orig = get_original(conn, recipe_id)
        if orig is None:
            return None
        row = conn.execute("SELECT source, is_valid, invalid_reason, n_ingredients, n_steps, n_steps_alt FROM recipes WHERE id=?", (recipe_id,)).fetchone()
        return {"id": recipe_id, **orig, "source": row[0], "is_valid": row[1], "invalid_reason": row[2],
                "n_ingredients": row[3], "n_steps": row[4], "n_steps_alt": row[5], "parsed": _load_ingredients(conn, [recipe_id])[recipe_id]}
    finally:
        if own:
            conn.close()
