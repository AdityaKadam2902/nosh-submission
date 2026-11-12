"""Code-built receipts (ARCHITECTURE §0.3). Numbers shown to users come from here, never from an LLM."""
from __future__ import annotations

from recipebot.normalize import query_info

STEP_RULE = ("estimated instruction steps: newline-separated blocks if >=2 blocks, else sentences "
             "(ADVERTISEMENT/bare numbering removed; recipebot/steps.py)")
DEDUP_NOTE = "near-duplicate recipes (same title + ingredients, mostly across sources) are NOT removed; see docs/DATA_AUDIT.md section 4"
DENOMINATOR_DEF = "valid recipes = title non-blank AND >=1 clean ingredient line AND >=1 instruction step"


def dataset_counts(conn) -> dict:
    total, valid = conn.execute("SELECT COUNT(*), COALESCE(SUM(is_valid),0) FROM recipes").fetchone()
    return {"total_records": total, "valid": valid, "invalid": total - valid}


def normalization_mode(terms) -> str:
    notes = []
    for t in terms:
        qi = query_info(t)
        if qi["distinct"]:
            notes.append(f"'{qi['canon']}' excludes items with: {', '.join(qi['distinct'][:6])}{'...' if len(qi['distinct']) > 6 else ''}")
    base = "form-aware token-sequence match on normalized names (aliases, singular forms); e.g. garlic powder is not counted as garlic"
    return base + ("; " + "; ".join(notes) if notes else "")


def describe_filters(f: dict) -> list[str]:
    out = []
    if f.get("contains_all"):
        out.append("contains ALL of: " + ", ".join(f["contains_all"]))
    if f.get("contains_any"):
        out.append("contains ANY of: " + ", ".join(f["contains_any"]))
    if f.get("exclude"):
        out.append("excludes: " + ", ".join(f["exclude"]))
    if f.get("title_contains"):
        out.append(f"title contains '{f['title_contains']}'")
    if f.get("source"):
        out.append(f"source = {f['source']}")
    return out or ["no filters (all valid recipes)"]


def make_receipt(tool: str, filters: list[str], counts: dict, **fields) -> dict:
    r = {"tool": tool, "filters": filters, "dataset": counts, "denominator_definition": DENOMINATOR_DEF,
         "duplicates": DEDUP_NOTE}
    r.update(fields)
    return r


def render_receipt(r: dict) -> str:
    d = r.get("dataset", {})
    lines = ["--- RECEIPT ---", f"tool: {r['tool']}", "filters: " + "; ".join(r["filters"])]
    if d:
        lines.append(f"dataset: {d['valid']:,} valid of {d['total_records']:,} records ({d['invalid']:,} invalid, excluded)")
    for key, label in (("n_analyzed", "analyzed"), ("denominator", "denominator"), ("formula", "formula"), ("retrieval", "retrieval"),
                       ("ordering", "ordering"), ("normalization", "normalization"), ("step_rule", "step rule"),
                       ("candidates", "candidates"), ("dropped", "dropped by filters"), ("tie_note", "ties")):
        if r.get(key) is not None:
            v = r[key]
            lines.append(f"{label}: {v:,}" if isinstance(v, int) and not isinstance(v, bool) else f"{label}: {v}")
    if r.get("denominator_definition"):
        lines.append(f"valid = {r['denominator_definition'].split('= ', 1)[-1]}")
    lines.append(f"duplicates: {r['duplicates']}")
    if r.get("recipe_ids"):
        lines.append("recipe ids: " + ", ".join(r["recipe_ids"]))
    for q in r.get("sql", []):
        lines.append("sql: " + " ".join(q.split()))
    return "\n".join(lines)
