"""Independent ground truth: a pure-Python pass over the ORIGINAL records (recipes.title/ingredients_json/instructions), re-parsing
ingredients with normalize.clean_ingredients/matcher (identity only). Does NOT use the ingredients table, SQL filters, stats.py, search.py,
match.py or substitute.py. Validity is recomputed (title non-empty, >=1 ingredient line, >=1 step), not read from is_valid."""
from __future__ import annotations

import json
import statistics
from collections import Counter

from recipebot.normalize import clean_ingredients, matcher
from recipebot.steps import count_steps


class Reference:
    def __init__(self, conn):
        self.recs = []
        for rid, src, title, ij, instr, flag in conn.execute("SELECT id, source, title, ingredients_json, instructions, is_valid FROM recipes ORDER BY id"):
            try:
                raw = json.loads(ij)
            except (TypeError, ValueError):
                raw = []
            ings = clean_ingredients(raw if isinstance(raw, list) else [])
            steps, alt = count_steps(instr if isinstance(instr, str) else "")
            if isinstance(title, str) and title.strip() and ings and steps >= 1:
                self.recs.append({"id": rid, "source": src, "title": title, "ings": ings, "n": len(ings), "steps": steps, "alt": alt, "db_valid": flag})
        self.by_id = {r["id"]: r for r in self.recs}
        self._m: dict = {}

    @property
    def valid_agrees(self) -> bool:  # recomputed validity == DB is_valid flag for every record
        return all(r["db_valid"] == 1 for r in self.recs)

    def has(self, rec, term) -> bool:
        m = self._m.setdefault(term, matcher(term))
        return any(m(d) for d in rec["ings"])

    def select(self, f: dict, pool=None) -> list[dict]:
        out = []
        for r in (self.recs if pool is None else pool):
            if f.get("source") and r["source"] != f["source"]:
                continue
            if f.get("title_contains") and f["title_contains"].lower() not in r["title"].lower():
                continue
            if not all(self.has(r, t) for t in f.get("contains_all") or []):
                continue
            if f.get("contains_any") and not any(self.has(r, t) for t in f["contains_any"]):
                continue
            if any(self.has(r, t) for t in f.get("exclude") or []):
                continue
            out.append(r)
        return out

    def stats(self, spec: dict) -> dict:
        """-> same shape as stats.run_stats()['answer_data'] (top/rank items as tuples)."""
        f, op, k = spec.get("filters") or {}, spec["op"], int(spec.get("k") or 10)
        chosen = self.select(f)
        if op == "count":
            return {"count": len(chosen), "denominator": len(self.recs)}
        if op == "percentage":
            if spec.get("of"):
                den = self.select(spec["of"])
                ids = {r["id"] for r in den}
                num = [r for r in chosen if r["id"] in ids]
                return {"count": len(num), "denominator": len(den), "percentage": 100 * len(num) / len(den) if den else None}
            return {"count": len(chosen), "denominator": len(self.recs), "percentage": 100 * len(chosen) / len(self.recs) if self.recs else None}
        if op == "top_ingredients":
            c = Counter()
            for r in chosen:
                c.update({d["canon"] for d in r["ings"]})
            return {"items": sorted(c.items(), key=lambda x: (-x[1], x[0]))[:k]}
        if op == "ingredient_count_summary":
            v = [r["n"] for r in chosen]
            return {"n": len(v), "mean": statistics.fmean(v) if v else None, "median": statistics.median(v) if v else None, "min": min(v, default=None), "max": max(v, default=None)}
        if op == "rank_steps":
            rev = (spec.get("order") or "asc") == "desc"
            return {"items": [(r["id"], r["steps"]) for r in sorted(chosen, key=lambda r: (-r["steps"] if rev else r["steps"], r["id"]))[:k]]}
        raise ValueError(op)

    def first(self, pick) -> tuple[str, dict] | None:
        """(id, selector) of the first valid recipe id (ascending) matching {title_contains, contains}; `pick` may be a list of selectors tried in order (fallbacks for small DBs)."""
        for p in (pick if isinstance(pick, list) else [pick]):
            for r in self.select({"title_contains": p.get("title_contains"), "contains_all": [p["contains"]] if p.get("contains") else []}):
                return r["id"], p
        return None
