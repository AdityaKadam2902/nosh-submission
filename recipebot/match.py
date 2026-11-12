"""Task 2: match recipes to what the user HAS (ARCHITECTURE §8). Deterministic; no LLM.
candidates (share >=1 non-staple canon) -> hard filters (exclude / restrictions 3-state / max_steps) -> matched/missing -> lexicographic rank.
match(...) -> {rows, uncertain, no_match, message, violating_alternatives, dropped, receipt}"""
from __future__ import annotations

import html
import re
from collections import defaultdict

from recipebot.constraints import Checker
from recipebot.db import connect, db_path
from recipebot.normalize import canon_name, canon_unit, load_yaml, matcher, parse_ingredient, query_info, unit_info
from recipebot.receipt import STEP_RULE, dataset_counts, make_receipt, normalization_mode
from recipebot.search import _load_ingredients

DEFAULT_PREFS = ["most_matched", "fewest_missing", "fewest_steps"]
_PREF_PATTERNS = [
    (re.compile(r"fewest[\s_]+(?:extra|missing)|least[\s_]+(?:extra|missing)|minimal[\s_]+(?:extra|missing)|few(?:er)?[\s_]+extra|no[\s_]+extra|fewest[\s_]+additional"), "fewest_missing"),
    (re.compile(r"most[\s_]+matched|most[\s_]+of[\s_]+my|use[\s_]+(?:the[\s_]+)?most|max(?:imum)?[\s_]+overlap|most[\s_]+overlap|match(?:es)?[\s_]+most"), "most_matched"),
    (re.compile(r"fewest[\s_]+steps|fewer[\s_]+steps|least[\s_]+steps|quick|fast|easy|simple|short"), "fewest_steps"),
]
STAPLE_SQL = "SELECT i.recipe_id, i.canon, i.forms, i.alts FROM ingredients i JOIN recipes r ON r.id=i.recipe_id WHERE r.is_valid=1 AND i.canon LIKE ?"


def parse_preferences(prefs) -> list[str]:
    """Free-text preferences -> ordered subset of DEFAULT_PREFS (unknown text ignored)."""
    out = []
    for p in prefs or []:
        t = str(p).lower().strip()
        for pat, name in _PREF_PATTERNS:
            if pat.search(t) or t.replace(" ", "_") == name:
                if name not in out:
                    out.append(name)
                break
    return out


def rank_order(prefs) -> list[str]:
    parsed = parse_preferences(prefs)
    return parsed + [p for p in DEFAULT_PREFS if p not in parsed]


def _key(order, r):
    parts = {"most_matched": -len(r["matched"]), "fewest_missing": len(r["missing"]), "fewest_steps": r["n_steps"]}
    return tuple(parts[o] for o in order) + (r["id"],)


def normalize_available(available) -> list[dict]:
    """strings ('2 eggs'), dicts or objects with name/qty/unit -> [{name (canon), qty, unit (canonical)}], deduped by name."""
    out, seen = [], set()
    for a in available or []:
        if isinstance(a, str):
            p = parse_ingredient(a)
            name, qty, unit = p["canon"], p["qty"], p["unit"]
        else:
            get = a.get if isinstance(a, dict) else (lambda k, d=None: getattr(a, k, d))
            name, qty, unit = canon_name(str(get("name", ""))), get("qty"), canon_unit(get("unit"))
        if name and name not in seen:
            seen.add(name)
            out.append({"name": name, "qty": qty, "unit": unit})
    return out


def _quantity(have: dict, need_row: dict) -> dict:
    """sufficient|insufficient|unverified (same unit family only; mass vs volume never compared)."""
    nq, nu = need_row.get("qty"), need_row.get("unit")
    hq, hu = have.get("qty"), have.get("unit")
    base = {"need": _fmt_q(nq, nu), "have": _fmt_q(hq, hu)}
    if hq is None or nq is None:
        return {"status": "unverified", **base}
    if nu is None and hu is None:  # plain counts
        return {"status": "sufficient" if hq >= nq else "insufficient", **base}
    iu, hi = unit_info(nu), unit_info(hu)
    if iu and hi and iu["family"] == hi["family"] and iu["family"] in ("mass", "volume"):
        return {"status": "sufficient" if hq * hi["to_base"] >= nq * iu["to_base"] - 1e-9 else "insufficient", **base}
    if nu == hu and nu is not None and iu and iu["family"] == "piece":
        return {"status": "sufficient" if hq >= nq else "insufficient", **base}
    return {"status": "unverified", **base}


def _fmt_q(q, u) -> str:
    return "?" if q is None else f"{q:g}" + (f" {u}" if u else "")


def _why(order, rows, i) -> str:
    """One line built from the key comparison with the next-ranked neighbour (previous one for the last row)."""
    if len(rows) == 1:
        return "only eligible recipe"
    a, b, last = (rows[i], rows[i + 1], False) if i + 1 < len(rows) else (rows[i - 1], rows[i], True)
    labels = {"most_matched": ("matches more of your ingredients", lambda r: len(r["matched"])),
              "fewest_missing": ("needs fewer extra ingredients", lambda r: len(r["missing"])),
              "fewest_steps": ("has fewer estimated steps", lambda r: r["n_steps"])}
    for o in order:
        va, vb = labels[o][1](a), labels[o][1](b)
        if va != vb:
            text = f"{labels[o][0]} ({va} vs {vb})"
            return f"ranked below #{i} because the previous recipe {text}" if last else f"ranked above #{i + 2} because it {text}"
    return "tied with its neighbour on every criterion; ordered by id"


def match(available, exclude=None, restrictions=None, max_steps=None, preferences=None, staples=None, k: int = 10, db=None, conn=None,
          min_matched: int | None = None) -> dict:
    """min_matched: a recipe must use at least this many of YOUR ingredients (default min(2, len(available)); 1 = spec's 'share >= 1')."""
    avail = normalize_available(available)
    if not avail:
        raise ValueError("no recognizable available ingredients")
    exclude, restrictions = list(exclude or []), list(restrictions or [])
    st_names = load_yaml("staples")["default"] if staples is None else list(staples)
    staple_set = {canon_name(x) for x in st_names if canon_name(x)}
    order = rank_order(preferences)
    mm = min(2, len(avail)) if min_matched is None else max(1, int(min_matched))
    own = conn is None
    conn = conn or connect(db or db_path(), readonly=True)
    try:
        matchers = [matcher(a["name"], use_alts=True) for a in avail]
        # 1. candidates: recipes with an ingredient row matching any available item
        cand: set[str] = set()
        for a, m in zip(avail, matchers):
            like = f"%{query_info(a['name'])['canon']}%"
            for rid, canon, forms, alts in conn.execute(STAPLE_SQL, (like,)):
                if m({"canon": canon, "forms": forms or "", "alts": _alts(alts)}):
                    cand.add(rid)
        ids = sorted(cand)
        meta = {}
        for i in range(0, len(ids), 500):
            ch = ids[i:i + 500]
            for r in conn.execute(f"SELECT id, title, source, n_steps FROM recipes WHERE id IN ({','.join('?' * len(ch))})", ch):
                meta[r[0]] = r
        exc_m = [matcher(t) for t in exclude]
        checkers = {r: Checker(r) for r in restrictions}
        mcache: dict = {}
        evaluated = []
        dropped = defaultdict(int)
        below_min = 0
        for i in range(0, len(ids), 500):
            rows_by = _load_ingredients(conn, ids[i:i + 500])
            for rid in ids[i:i + 500]:
                L = rows_by[rid]
                required: dict[str, dict] = {}
                for d in L:
                    if d["canon"] and d["canon"] not in staple_set and d["canon"] not in required:
                        required[d["canon"]] = d
                matched, missing, matched_by = [], [], {}
                for canon, d in required.items():
                    ck = (canon, d["forms"], tuple(d["alts"]))
                    if ck not in mcache:
                        mcache[ck] = [j for j, m in enumerate(matchers) if m(d)]
                    if mcache[ck]:
                        matched.append(canon)
                        matched_by[canon] = mcache[ck][0]
                    else:
                        missing.append(canon)
                if len(matched) < mm:
                    below_min += 1
                    continue
                _, title, source, n_steps = meta[rid]
                viol, possible, res = [], [], {}
                for t, m in zip(exclude, exc_m):
                    if any(m(d) for d in L):
                        viol.append(f"exclude: {t}")
                        dropped["exclude"] += 1
                for rname, chk in checkers.items():
                    res[rname] = chk(L)
                    if res[rname]["state"] == "contains":
                        viol.append(f"violates: {rname}")
                        dropped[f"restriction:{rname}"] += 1
                    elif res[rname]["state"] == "possible":
                        possible.append(rname)
                if max_steps is not None and n_steps > max_steps:
                    viol.append(f"max_steps: {n_steps} > {max_steps}")
                    dropped["max_steps"] += 1
                quantity = {}
                for canon in matched:
                    a = avail[matched_by[canon]]
                    if a["qty"] is not None:
                        quantity[canon] = _quantity(a, required[canon])
                evaluated.append({"id": rid, "title": html.unescape(title or "").strip(), "source": source, "n_steps": n_steps,
                                  "n_required": len(required), "matched": matched, "missing": missing, "extra_required": len(missing),
                                  "coverage": len(matched) / len(required), "quantity": quantity, "restrictions": res,
                                  "violates": viol, "possible": possible})
        eligible = sorted((r for r in evaluated if not r["violates"] and not r["possible"]), key=lambda r: _key(order, r))
        uncertain = sorted((r for r in evaluated if not r["violates"] and r["possible"]), key=lambda r: _key(order, r))
        violators = sorted((r for r in evaluated if r["violates"]), key=lambda r: _key(order, r))
        shown = eligible[:k]
        for i, r in enumerate(shown):
            r["why"] = _why(order, shown, i)
        for r in uncertain[:k] + violators[:k]:
            r["why"] = ""
        no_match = not eligible
        msg = None
        if no_match:
            msg = ("NO_MATCH: no recipe satisfies all constraints (" + ", ".join(
                (["restrictions: " + "/".join(restrictions)] if restrictions else []) + ([f"exclude: {', '.join(exclude)}"] if exclude else [])
                + ([f"max steps {max_steps}"] if max_steps is not None else [])) + ") with your ingredients.") if (restrictions or exclude or max_steps is not None) \
                else "NO_MATCH: no recipe shares an ingredient with your list."
        filters = ["have: " + ", ".join(f"{a['name']}" + (f" ({_fmt_q(a['qty'], a['unit'])})" if a["qty"] is not None else "") for a in avail)]
        if exclude: filters.append("excludes: " + ", ".join(exclude))
        if restrictions: filters.append("restrictions (3-state; 'possible' -> uncertain list): " + ", ".join(restrictions))
        if max_steps is not None: filters.append(f"max estimated steps <= {max_steps}")
        filters.append(f"must use at least {mm} of your ingredients (min_matched; {below_min:,} candidates used fewer and were skipped; CLI: --min-matched 1 to allow)")
        receipt = make_receipt(
            "match", filters, dataset_counts(conn), candidates=len(evaluated),
            dropped=", ".join(f"{n}={v}" for n, v in sorted(dropped.items())) or "none",
            ordering="lexicographic: " + ", ".join(order) + ", id (most_matched = more matched required ingredients first; fewest_missing = fewer missing first; fewest_steps)",
            normalization=normalization_mode([a["name"] for a in avail]) + f"; staples assumed available (not counted as missing): {', '.join(sorted(staple_set)) or 'none'}",
            step_rule=STEP_RULE, recipe_ids=[r["id"] for r in shown],
            formula="required = distinct normalized ingredients of the recipe minus staples; matched = required items covered by your list (or an 'or' alternative); missing = required - matched; coverage = matched/required. "
                    "Quantities are compared only when both sides give qty in the same unit family; otherwise 'name-level match; quantity sufficiency not verified'.",
            sql=[STAPLE_SQL.replace("?", "'%<ingredient>%'") + "  -- then form-aware match in Python, one pass per available item"])
        return {"rows": shown, "uncertain": uncertain[:k], "n_eligible": len(eligible), "n_uncertain": len(uncertain), "no_match": no_match,
                "message": msg, "violating_alternatives": violators[:k] if no_match else [], "dropped": dict(dropped), "order": order,
                "staples": sorted(staple_set), "available": avail, "receipt": receipt}
    finally:
        if own:
            conn.close()


def _alts(alts):
    import json
    return json.loads(alts) if alts else []
