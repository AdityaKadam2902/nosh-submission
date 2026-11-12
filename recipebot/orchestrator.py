"""Turn loop (ARCHITECTURE §11): user_text -> planner -> apply_ops -> tool (code) -> result + receipt (code) -> writer -> verifier -> render.
Fallbacks: LLM down -> LLM_DOWN_MESSAGE; verifier fails twice -> code template only; unimplemented intents say so."""
from __future__ import annotations

from dataclasses import dataclass, field
import os

from recipebot.constraints import check
from recipebot.db import connect, db_path
from recipebot.match import match
from recipebot.llm import LLM, LLM_DOWN_MESSAGE, LLMBadOutput, LLMUnavailable
from recipebot.planner import Plan, plan_turn
from recipebot.receipt import render_receipt
from recipebot.search import get_recipe, search
from recipebot.state import ConversationState, apply_ops, resolve_reference, set_results
from recipebot.stats import run_stats
from recipebot.verifier import verify
from recipebot.writer import write

OUT_OF_SCOPE = "I can help with recipe search, dataset statistics, ingredient matching and substitutions over the Recipe Box dataset."
NOT_YET: dict = {}  # intents without a tool yet (substitute is live since M5)
BAD_PLAN = "I couldn't interpret that. Please rephrase, or use /search, /stats, /show."


@dataclass
class TurnResult:
    text: str
    intent: str | None = None
    ids: list[str] = field(default_factory=list)
    fallback: bool = False  # True when LLM prose was dropped for the code template
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    llm_down: bool = False
    error: str | None = None


class Orchestrator:
    def __init__(self, llm: LLM, conn=None, state: ConversationState | None = None, use_writer: bool | None = None):
        self.llm, self.conn = llm, conn or connect(db_path(), readonly=True)
        # RECIPEBOT_WRITER=off -> no LLM prose (1 LLM call/turn instead of 2; table + receipt are always code-built)
        self.use_writer = (os.environ.get("RECIPEBOT_WRITER", "on").lower() != "off") if use_writer is None else use_writer
        self.state = state or ConversationState()
        self.history: list[tuple[str, str]] = []

    def reset(self) -> None:
        self.state, self.history = ConversationState(), []

    # ---- tools ----
    def _run_search(self, plan: Plan):
        s, ta = self.state, plan.tool_args
        query = s.dish_query or ta.query or ""
        if not query and not s.include:
            return None
        cap = 1000 if (s.restrictions or s.exclude or s.max_steps) else 300  # filters can drop most candidates
        res = search(query, s.include, s.exclude, s.restrictions, s.max_steps, min(ta.k or 10, 20), conn=self.conn, candidates=cap)
        self.state = set_results(self.state, [r["id"] for r in res["rows"]], "search")
        payload = {"intent": "search", "applied": {"dish": query, "include": s.include, "exclude": s.exclude, "restrictions": s.restrictions, "max_steps": s.max_steps},
                   "shown": [{"id": r["id"], "title": r["title"], "n_steps": r["n_steps"]} for r in res["rows"]],
                   "passed_all_filters": res["post_filter_count"], "retrieved_candidates": res["total_candidates"], "uncertain_count": res["n_uncertain"],
                   "dropped_by_filters": res["dropped"]}
        return payload, _table_search(res), res["receipt"], [r["id"] for r in res["rows"]]

    def _run_match(self, plan: Plan):
        s = self.state
        if not s.available:
            return None
        res = match(s.available, s.exclude, s.restrictions, s.max_steps, s.preferences, k=min(plan.tool_args.k or 10, 20), conn=self.conn)
        ids = [r["id"] for r in res["rows"]]
        self.state = set_results(self.state, ids, "match")
        slim = lambda r: {"id": r["id"], "title": r["title"], "n_steps": r["n_steps"], "matched": r["matched"], "missing": r["missing"], "why": r.get("why", ""),
                          "quantity": {c: v["status"] for c, v in r["quantity"].items()}}
        payload = {"intent": "match", "applied": {"have": [a["name"] for a in res["available"]], "exclude": s.exclude, "restrictions": s.restrictions,
                                                   "max_steps": s.max_steps, "ranking": res["order"], "staples_assumed": res["staples"]},
                   "shown": [slim(r) for r in res["rows"]], "eligible_count": res["n_eligible"], "uncertain_count": res["n_uncertain"], "no_match": res["no_match"],
                   "violating_alternatives": [{"id": r["id"], "violates": r["violates"]} for r in res["violating_alternatives"]], "dropped_by_filters": res["dropped"]}
        from recipebot.cli import _fmt_match
        return payload, _fmt_match(res), res["receipt"], ids

    def _run_stats(self, plan: Plan):
        ta = plan.tool_args
        if not ta.stats_op:
            return None
        spec = {"op": ta.stats_op, "k": ta.k or 10, "order": ta.order or "asc", "skip_staples": ta.skip_staples,
                "filters": {"contains_all": ta.contains_all, "contains_any": ta.contains_any, "exclude": ta.exclude,
                            "title_contains": ta.title_contains, "source": ta.source}, "of": {"contains_all": ta.of_all} if ta.of_all else None}
        res = run_stats(spec, conn=self.conn)
        ids = [x["id"] for x in res["answer_data"].get("items", []) if "id" in x]
        if ids:
            self.state = set_results(self.state, ids, "stats")
        return {"intent": "stats", "op": ta.stats_op, "result": res["answer_data"]}, _table_stats(spec["op"], res["answer_data"]), res["receipt"], ids

    def _run_detail(self, user_text: str, plan: Plan):
        ta, rid = plan.tool_args, resolve_reference(user_text, self.state)
        if rid is None and ta.recipe_id and (ta.recipe_id in self.state.last_ids or get_recipe(ta.recipe_id, conn=self.conn)):
            rid = ta.recipe_id
        if rid is None and ta.row and 1 <= ta.row <= len(self.state.last_ids):
            rid = self.state.last_ids[ta.row - 1]
        if rid is None:
            return "clarify", "Which recipe? Give a row number from the last results (e.g. 'show the second one') or a recipe id."
        r = get_recipe(rid, conn=self.conn)
        if r is None:
            return "clarify", f"I don't have a recipe with id {rid}."
        ing = [p["raw"] for p in r["parsed"]]
        states = {k: check(r["parsed"], k) for k in self.state.restrictions}
        self.state.focus_recipe_id = rid
        payload = {"intent": "recipe_detail", "id": rid, "title": (r["title"] or "").strip(), "n_ingredients": r["n_ingredients"], "n_steps": r["n_steps"],
                   "restriction_check": {k: {"state": v["state"], "evidence_lines": [e[2] for e in v["evidence"]]} for k, v in states.items()}}
        from recipebot.cli import _fmt_show
        return payload, _fmt_show(r), {"tool": "recipe_detail", "filters": [f"id = {rid}"], "dataset": {}, "denominator_definition": "", "duplicates": "n/a",
                                       "recipe_ids": [rid]}, [rid]

    def _run_substitute(self, user_text: str, plan: Plan):
        from recipebot.substitute import substitute
        ta, s = plan.tool_args, self.state
        rid = resolve_reference(user_text, s)
        if rid is None and ta.recipe_id and (ta.recipe_id in s.last_ids or get_recipe(ta.recipe_id, conn=self.conn)):
            rid = ta.recipe_id
        if rid is None and ta.row and 1 <= ta.row <= len(s.last_ids):
            rid = s.last_ids[ta.row - 1]
        rid = rid or s.focus_recipe_id
        if rid is None:
            return "clarify", "Which recipe? Give a row number from the last results (e.g. 'replace the eggs in the second one') or a recipe id."
        if not ta.target:
            return "clarify", "Which ingredient should I replace?"
        res = substitute(rid, ta.target, {"restrictions": s.restrictions, "exclude": s.exclude}, conn=self.conn)
        self.state.focus_recipe_id = rid
        co = res["cohort"]
        cand = lambda c: {"name": c["name"], "used_in_without": c["n_without"], "pct_without": c["pct_without"], "used_in_with": c["n_with"], "lift": c["lift"],
                          "grade": c["grade"], "ids": c["support_ids"]}
        payload = {"intent": "substitute", "status": res["status"], "recipe": res["recipe"], "target": res["target"], "roles": res["roles"], "grade": res["grade"],
                   "grade_reason": res["grade_reason"], "cohort": {k: co[k] for k in ("size", "with", "without", "same_dish")} if co else None,
                   "candidates": [cand(c) for c in res["candidates"][:5]], "blocked": [{"name": c["name"], "used_in_without": c["n_without"]} for c in res["blocked"]],
                   "uncertain": [{"name": c["name"]} for c in res["uncertain"]], "selected": res["selected"], "edited_ingredients": res["edited_ingredients"],
                   "refusal": res["refusal"], "restrictions_applied": res["restrictions"], "note": "evidence from similar recipes; not a tested conversion"}
        from recipebot.cli import _fmt_substitute
        ids = list(dict.fromkeys([rid] + [i for c in res["candidates"] + res["blocked"] + res["uncertain"] for i in c["support_ids"]]))
        return payload, _fmt_substitute(res), res["receipt"], ids

    # ---- turn ----
    def turn(self, user_text: str) -> TurnResult:
        try:
            plan = plan_turn(self.llm, user_text, self.state, self.history)
        except LLMBadOutput:
            return TurnResult(BAD_PLAN)
        except LLMUnavailable:
            return TurnResult(LLM_DOWN_MESSAGE, llm_down=True, error=self.llm.last_error)
        self.state, notes = apply_ops(self.state, plan.ops, plan.new_topic)
        intent = plan.intent
        if plan.needs_clarification:
            return self._finish(user_text, TurnResult(plan.needs_clarification, intent, notes=notes))
        if intent in ("chat", "out_of_scope"):
            return self._finish(user_text, TurnResult(OUT_OF_SCOPE, intent, notes=notes))
        if intent in NOT_YET:
            return self._finish(user_text, TurnResult(NOT_YET[intent], intent, notes=notes))
        try:
            if intent == "match" or (intent == "followup_refine" and self.state.last_intent == "match"):
                out = self._run_match(plan)
                if out is None:
                    return self._finish(user_text, TurnResult("Which ingredients do you have? (e.g. 'I have eggs, onions and rice')", intent, notes=notes))
            elif intent in ("search", "followup_refine"):
                out = self._run_search(plan)
                if out is None:
                    return self._finish(user_text, TurnResult("What dish or ingredients should I search for?", intent, notes=notes))
            elif intent == "substitute":
                out = self._run_substitute(user_text, plan)
                if out[0] == "clarify":
                    return self._finish(user_text, TurnResult(out[1], intent, notes=notes))
            elif intent == "stats":
                out = self._run_stats(plan)
                if out is None:
                    return self._finish(user_text, TurnResult("Which statistic? (count, percentage, top ingredients, ingredients per recipe, fewest/most steps)", intent, notes=notes))
            else:  # recipe_detail
                out = self._run_detail(user_text, plan)
                if out[0] == "clarify":
                    return self._finish(user_text, TurnResult(out[1], intent, notes=notes))
        except (ValueError, FileNotFoundError) as e:
            return TurnResult(f"error: {e}", intent, notes=notes)
        payload, table, receipt, ids = out
        prose, problems, fallback = self._prose(user_text, payload, receipt)
        parts = ([("Note: " + "; ".join(notes))] if notes else []) + ([prose] if prose else []) + [table, render_receipt(receipt) if receipt.get("dataset") else ""]
        return self._finish(user_text, TurnResult("\n\n".join(p for p in parts if p), intent, ids, fallback, problems, notes))

    def _prose(self, user_text: str, payload: dict, receipt: dict):
        """LLM prose -> verify -> one repair -> else '' (the code table + receipt still render). Returns (prose, problems, fallback)."""
        problems: list[str] = []
        if not self.use_writer:
            return "", [], False
        try:
            draft = write(self.llm, user_text, payload)
            for attempt in range(2):
                v = verify(draft, payload, receipt)
                if v.ok:
                    return draft, [], False
                problems = v.problems
                if attempt == 0:
                    draft = write(self.llm, user_text, payload, problems)
        except LLMUnavailable:
            return "", ["writer unavailable"], True
        return "", problems, True

    def _finish(self, user_text: str, r: TurnResult) -> TurnResult:
        self.history.append((user_text, r.text))
        return r


def _table_search(res: dict) -> str:
    from recipebot.cli import _fmt_search
    return _fmt_search(res)


def _table_stats(op: str, data: dict) -> str:
    from recipebot.cli import _fmt_stats
    return _fmt_stats({"op": op}, {"answer_data": data})
