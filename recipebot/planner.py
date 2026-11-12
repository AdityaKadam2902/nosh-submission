"""Planner (ARCHITECTURE §10): user text + state + last turns -> typed Plan (Gemini structured output, temperature 0).
The LLM only PROPOSES; code applies ops, resolves ordinals ("the second one") and runs tools."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from recipebot.llm import LLM
from recipebot.state import ConversationState, Op, state_summary

Intent = Literal["search", "stats", "match", "substitute", "recipe_detail", "followup_refine", "chat", "out_of_scope"]


class ToolArgs(BaseModel):
    query: str | None = None
    stats_op: Literal["count", "percentage", "top_ingredients", "ingredient_count_summary", "rank_steps"] | None = None
    contains_all: list[str] = Field(default_factory=list)
    contains_any: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    of_all: list[str] = Field(default_factory=list)
    title_contains: str | None = None
    source: Literal["ar", "epi", "fn"] | None = None
    k: int | None = None
    order: Literal["asc", "desc"] | None = None
    skip_staples: bool = False
    row: int | None = None
    recipe_id: str | None = None
    target: str | None = None


class Plan(BaseModel):
    intent: Intent
    tool_args: ToolArgs = Field(default_factory=ToolArgs)
    ops: list[Op] = Field(default_factory=list)
    new_topic: bool = False
    needs_clarification: str | None = None


PLANNER_SYSTEM = """You are the PLANNER of a recipe chatbot over the Recipe Box dataset (~120k recipes). Output ONLY JSON for the schema.
You never answer, compute, rank or invent recipes. You only choose an intent and conversation-state ops.

INTENTS
- search: find recipes for a dish/ingredients. Put the dish in ops (dish_query set) and tool_args.query.
- followup_refine: the user changes constraints of the CURRENT search (dietary needs, excluded/required ingredients, step limit). Use ops only; no new dish.
- stats: questions about counts, percentages, most common ingredients, average ingredients, fewest/most steps over the dataset. Set tool_args.stats_op (count|percentage|top_ingredients|ingredient_count_summary|rank_steps) and filters (contains_all, contains_any, exclude, title_contains, source, k, order). Stats ignore conversation state: use only what the user says.
- recipe_detail: the user wants to see one recipe ("show the second one", "tell me about that recipe", or an id). Leave tool_args.row/recipe_id empty unless the user gave an explicit number or id.
- match: the user lists ingredients they HAVE and wants recipes. Put them in ops (available set/add, one value each, keep quantities like "2 eggs"), plus any limits (max_steps, restrictions, exclude) and ranking wishes in ops (preferences add, e.g. "fewest extra ingredients", "fewest steps", "most matched").
- substitute: the user wants a replacement for / to leave out an ingredient in a recipe. Set tool_args.target (the ingredient to replace, one name) and, only if the user gave one, tool_args.recipe_id (an id) or tool_args.row (a number from the last results). Otherwise leave them empty: code uses the focus recipe. Dietary needs go in ops restrictions add, as always. You never suggest replacements yourself.
- chat: greetings/thanks. out_of_scope: anything unrelated to recipes in this dataset.

OPS = {field, op, value|values}. fields: dish_query, include, exclude, restrictions, max_steps, available, preferences, focus_recipe_id. op: set|add|remove|clear.
- Dietary needs ("I cannot have dairy", "I'm allergic to peanuts", "vegetarian", "gluten free") -> restrictions add. Allowed keys: dairy, egg, peanut, tree_nut, gluten, shellfish, soy, pork, beef, alcohol, vegetarian.
- Allergen/diet words (dairy, egg, peanut, tree nut, gluten, shellfish, soy, pork, beef, alcohol, vegetarian) after "no/can't have/allergic to" -> restrictions add ("no peanuts" -> restriction peanut).
- Other "no mushrooms", "without onions", "exclude eggs" -> exclude add. "must have garlic" -> include add.
- Restrictions and excludes persist until the user removes them ("I can eat dairy now" -> restrictions remove). Never clear them yourself.
- A brand-new dish topic -> intent search, new_topic=true, ops dish_query set. Restrictions and excludes are kept by code.
- "at most 6 steps" -> max_steps set "6".
- If the request is too vague to act on, set needs_clarification to ONE short question and intent chat.

EXAMPLES
"Find penne pasta" -> {"intent":"search","tool_args":{"query":"penne pasta"},"ops":[{"field":"dish_query","op":"set","value":"penne pasta"}],"new_topic":true}
"I cannot have dairy" -> {"intent":"followup_refine","ops":[{"field":"restrictions","op":"add","value":"dairy"}]}
"also no mushrooms" -> {"intent":"followup_refine","ops":[{"field":"exclude","op":"add","value":"mushroom"}]}
"show the second one" -> {"intent":"recipe_detail"}
"I have eggs, onions, tomatoes and rice, at most 6 steps, no peanuts, prefer fewest extra ingredients" -> {"intent":"match","ops":[{"field":"available","op":"set","values":["eggs","onions","tomatoes","rice"]},{"field":"max_steps","op":"set","value":"6"},{"field":"restrictions","op":"add","value":"peanut"},{"field":"preferences","op":"add","value":"fewest extra ingredients"}]}
"exclude eggs too" (after a match) -> {"intent":"followup_refine","ops":[{"field":"exclude","op":"add","value":"eggs"}]}
"what percent of recipes have garlic and onion" -> {"intent":"stats","tool_args":{"stats_op":"percentage","contains_all":["garlic","onion"]}}
"replace the eggs in the second one" -> {"intent":"substitute","tool_args":{"target":"egg"}}
"what can I use instead of cream in ar:1234, I can't have dairy" -> {"intent":"substitute","tool_args":{"target":"cream","recipe_id":"ar:1234"},"ops":[{"field":"restrictions","op":"add","value":"dairy"}]}
"5 recipes with tomato with the fewest steps" -> {"intent":"stats","tool_args":{"stats_op":"rank_steps","contains_all":["tomato"],"k":5,"order":"asc"}}
"""


def _history(history) -> str:
    lines = []
    for u, a in list(history)[-4:]:
        lines.append(f"user: {u[:200]}\nbot: {a[:200]}")
    return "\n".join(lines) or "(none)"


def plan_turn(llm: LLM, user_text: str, state: ConversationState, history=()) -> Plan:
    prompt = f"CURRENT STATE: {state_summary(state)}\nRECENT TURNS:\n{_history(history)}\nUSER MESSAGE: {user_text}"
    return llm.generate_json(prompt, Plan, system=PLANNER_SYSTEM)
