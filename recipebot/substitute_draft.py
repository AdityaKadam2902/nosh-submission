"""Task 3 Tier 2 (ARCHITECTURE §9 step 6-7): the LLM drafts REVISED STEPS from the code-produced edit list; code validates the draft.

Rules (all thresholds/word lists: config/roles.yaml `draft`):
- the LLM never chooses the replacement, the quantities or the evidence: it only rewords the ORIGINAL steps around the edited ingredient list;
- the draft is validated (only ingredients from the edited list / allow_foods, the removed ingredient not still used, no number that is not in the original
  steps or the edited list, no banned claim such as "safe" or "tastes the same", sane length); one repair re-ask, then the draft is REJECTED and only the
  dataset evidence is shown. Unvalidated LLM text is never returned;
- the label "prediction" is set by code, never by the LLM.
"""
from __future__ import annotations

import html
import re

from pydantic import BaseModel, Field

from recipebot import steps as steps_mod
from recipebot.llm import LLM, LLMUnavailable
from recipebot.normalize import canon_name, clean_ingredients, load_yaml, tokens
from recipebot.substitute import load_roles

LABEL = "prediction"
DISCLAIMER = "PREDICTION: an LLM-drafted revision of the original steps, checked by code against the edited ingredient list. Not dataset evidence, not a tested recipe."

DRAFT_SYSTEM = """You are the REVISER of a recipe chatbot. A substitution was already decided and applied by code. Rewrite the recipe steps so they match the EDITED INGREDIENTS.
Rules: keep every original step verbatim unless it must change because of the substitution; use ONLY ingredients from EDITED INGREDIENTS (plus water and salt);
never mention the REMOVED ingredient except to say it is omitted/replaced; do not add any quantity, temperature, time or number that is not in ORIGINAL STEPS
or EDITED INGREDIENTS; do not claim the result is safe, identical, perfect or guaranteed; do not name other substitutions. `notes` may hold at most two short,
hedged cautions (use 'may') about the role the removed ingredient played. `changed_steps` lists the 1-based numbers of the steps you changed or added.
Return JSON only."""


class Draft(BaseModel):
    steps: list[str] = Field(default_factory=list)
    changed_steps: list[int] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- helpers
def original_steps(instructions) -> list[str]:
    text = "\n".join(instructions) if isinstance(instructions, list) else (instructions or "")
    text = html.unescape(text)
    b = steps_mod.blocks(text)
    return b if len(b) >= 2 else (steps_mod.split_sentences(text) or b)


_VOCAB: dict = {}


def known_foods(conn, min_count: int) -> set[str]:
    """Normalized ingredient names that occur >= min_count times in the dataset (cached per database file)."""
    db = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), "")
    key = (db, min_count)
    if key not in _VOCAB:
        _VOCAB[key] = {r[0] for r in conn.execute("SELECT canon FROM ingredients WHERE canon<>'' GROUP BY canon HAVING COUNT(*) >= ?", (min_count,))}
    return _VOCAB[key]


def _spans(text: str, vocab: set[str], maxn: int = 3) -> set[str]:
    """Longest-first n-gram matches of known food names in a text (so 'baking soda' is not also reported as 'soda')."""
    toks = tokens(html.unescape(text))
    used, found = [False] * len(toks), set()
    for n in range(maxn, 0, -1):
        for i in range(len(toks) - n + 1):
            if any(used[i:i + n]):
                continue
            g = " ".join(toks[i:i + n])
            if g in vocab:
                found.add(g)
                for j in range(i, i + n):
                    used[j] = True
    return found


def _has_phrase(text: str, phrase: str) -> bool:
    return re.search(r"(?<![a-z])" + re.escape(phrase).replace(r"\ ", r"[\s-]+") + r"(?![a-z])", text.lower()) is not None


def _numbers(text: str) -> set[str]:
    return {str(float(x)).rstrip("0").rstrip(".") for x in re.findall(r"\d+(?:\.\d+)?", text)}


# ---------------------------------------------------------------- validator
def validate(draft: Draft, edited_lines: list[str], removed: list[str], orig: list[str], title: str, vocab: set[str], cfg: dict) -> list[str]:
    """-> list of problems (empty = draft accepted). Pure code."""
    d = cfg["draft"]
    problems: list[str] = []
    st = draft.steps
    if not st:
        return ["no steps returned"]
    if len(st) > len(orig) + d["max_extra_steps"]:
        problems.append(f"{len(st)} steps (original {len(orig)}, at most {d['max_extra_steps']} more allowed)")
    if len(draft.notes) > d["max_notes"]:
        problems.append(f"{len(draft.notes)} notes (at most {d['max_notes']})")
    for n in draft.notes:
        if len(n.split()) > d["note_max_words"]:
            problems.append(f"a note is longer than {d['note_max_words']} words")
    rows = clean_ingredients(edited_lines)
    allowed = {r["canon"] for r in rows if r["canon"]} | {canon_name(a) for r in rows for a in (r.get("alts") or [])}
    allowed |= {canon_name(x) or x for x in d["allow_foods"]} | {canon_name(x) or x for x in load_yaml("staples").get("default", [])}
    ttoks = set(tokens(title))
    removed_c = [canon_name(x) for x in removed if canon_name(x)]
    src_numbers = _numbers(" ".join(orig + edited_lines))
    orig_norm = {re.sub(r"\W+", " ", o.lower()).strip() for o in orig}
    ctx = d["removal_context_words"]
    for i, text in enumerate([*st, *draft.notes], 1):
        is_note = i > len(st)
        label = f"note {i - len(st)}" if is_note else f"step {i}"
        if len(text) > d["max_step_chars"]:
            problems.append(f"{label} is longer than {d['max_step_chars']} characters")
        for p in d["banned_phrases"]:
            if _has_phrase(text, p):
                problems.append(f"{label} makes a claim that is not allowed ('{p}')")
        for n in sorted(_numbers(text) - src_numbers):
            problems.append(f"{label} contains the number {n}, which is not in the original steps or the edited ingredients")
        for r in removed_c:
            if _has_phrase(" ".join(tokens(text)), r) and not any(_has_phrase(text, w) for w in ctx):
                problems.append(f"{label} still uses the removed ingredient '{r}'")
        unchanged = not is_note and re.sub(r"\W+", " ", text.lower()).strip() in orig_norm
        if not unchanged:  # original sentences may mention what they always mentioned; new or reworded text may only use the edited list
            for f in sorted(_spans(text, vocab) - allowed):
                if set(f.split()) <= ttoks or f in removed_c or any(f in r or r in f for r in removed_c):
                    continue
                problems.append(f"{label} mentions '{f}', which is not in the edited ingredient list")
    return list(dict.fromkeys(problems))


# ---------------------------------------------------------------- draft + validate + one repair
def _prompt(res: dict, orig: list[str], problems: list[str] | None) -> str:
    edits = "; ".join(f"line {e['pos']}: {e['op']} '{e['old']}'" + (f" -> '{e['new']}'" if e.get("new") else "") for e in res["edits"])
    p = (f"RECIPE: {res['recipe']['title']}\nREMOVED INGREDIENT: {res['target']}\nEDIT APPLIED BY CODE: {edits}\nEDITED INGREDIENTS:\n"
         + "\n".join(f"- {x}" for x in res["edited_ingredients"]) + "\nORIGINAL STEPS:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(orig, 1)))
    if problems:
        p += "\nYour previous draft failed validation: " + "; ".join(problems[:6]) + ". Fix exactly these problems."
    return p


def draft_steps(llm: LLM, res: dict, rec: dict, conn, config: dict | None = None) -> dict:
    cfg = load_roles(config)
    d = cfg["draft"]
    base = {"label": LABEL, "status": "skipped", "steps": [], "changed_steps": [], "notes": [], "problems": [], "attempts": 0, "disclaimer": DISCLAIMER}
    if res.get("status") != "ok" or not res.get("edited_ingredients"):
        return {**base, "problems": ["no applied edit to revise the steps for"]}
    orig = original_steps(rec.get("instructions"))
    if not orig:
        return {**base, "problems": ["the recipe has no steps to revise"]}
    vocab = known_foods(conn, d["vocab_min_count"])
    removed = [res["target"]]
    problems: list[str] = []
    for attempt in range(1, d["repair_attempts"] + 2):
        try:
            dr = llm.generate_json(_prompt(res, orig, problems or None), Draft, system=DRAFT_SYSTEM)
        except LLMUnavailable as e:
            return {**base, "status": "llm_unavailable", "attempts": attempt, "problems": [str(e)[:200]]}
        problems = validate(dr, res["edited_ingredients"], removed, orig, res["recipe"]["title"] or "", vocab, cfg)
        if not problems:
            ch = sorted({c for c in dr.changed_steps if 1 <= c <= len(dr.steps)})
            return {**base, "status": "ok", "steps": [s.strip() for s in dr.steps], "changed_steps": ch, "notes": [n.strip() for n in dr.notes], "attempts": attempt}
    return {**base, "status": "rejected", "attempts": d["repair_attempts"] + 1, "problems": problems}


def attach_prediction(res: dict, llm: LLM, conn, config: dict | None = None) -> dict:
    """Fill res['predictions'] (list of validated, labelled drafts) and res['prediction_status']. Never raises for LLM trouble."""
    from recipebot.search import get_recipe
    if res.get("status") != "ok":
        res["prediction_status"] = "skipped"
        return res
    rec = get_recipe(res["recipe"]["id"], conn=conn) or {}
    pred = draft_steps(llm, res, rec, conn, config)
    res["prediction_status"] = pred["status"]
    res["prediction_problems"] = pred["problems"]
    res["predictions"] = [pred] if pred["status"] == "ok" else []
    return res
