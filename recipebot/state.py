"""Conversation state + deterministic op application (ARCHITECTURE §10). The LLM only proposes ops; code applies them.
Rules: restrictions AND excludes persist until explicitly removed; new_topic resets dish_query/include/last_ids/focus but keeps
restrictions and excludes; ordinals ("the second one") are resolved here from last_ids, never by the LLM."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from recipebot.constraints import resolve
from recipebot.normalize import canon_name, parse_ingredient


class Ingredient(BaseModel):
    name: str
    qty: float | None = None
    unit: str | None = None


class ConversationState(BaseModel):
    dish_query: str | None = None
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    restrictions: list[str] = Field(default_factory=list)
    max_steps: int | None = None
    available: list[Ingredient] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    focus_recipe_id: str | None = None
    last_ids: list[str] = Field(default_factory=list)
    last_intent: str | None = None


class Op(BaseModel):
    field: Literal["dish_query", "include", "exclude", "restrictions", "max_steps", "available", "preferences", "focus_recipe_id"]
    op: Literal["set", "add", "remove", "clear"]
    value: str | None = None
    values: list[str] = Field(default_factory=list)


def _items(op: Op) -> list[str]:
    return [v.strip() for v in ([op.value] if op.value else []) + list(op.values) if v and v.strip()]


def _uniq(xs):
    return list(dict.fromkeys(xs))


def apply_ops(state: ConversationState, ops: list[Op], new_topic: bool = False) -> tuple[ConversationState, list[str]]:
    """Pure: returns (new_state, notes). Notes describe rejected/adjusted ops (shown to the user, never silent)."""
    s, notes = state.model_copy(deep=True), []
    if new_topic:
        had = bool(s.dish_query or s.include or s.last_ids or s.focus_recipe_id)
        s.dish_query, s.include, s.last_ids, s.focus_recipe_id, s.last_intent = None, [], [], None, None
        if had:  # no noise on the first turn of a conversation
            notes.append("new topic: cleared dish, include list and results; kept restrictions and excludes")
    for op in ops:
        f, kind, items = op.field, op.op, _items(op)
        if f in ("dish_query", "focus_recipe_id"):
            setattr(s, f, items[0] if kind in ("set", "add") and items else None)
        elif f == "max_steps":
            if kind == "clear" or kind == "remove":
                s.max_steps = None
            else:
                m = re.search(r"\d+", items[0]) if items else None
                if m:
                    s.max_steps = int(m.group())
                else:
                    notes.append(f"ignored max_steps value {items[:1]!r}")
        elif f == "restrictions":
            keys = []
            for it in items:
                try:
                    keys += resolve(it)
                except ValueError:
                    notes.append(f"unknown restriction ignored: {it!r}")
            if kind == "clear":
                s.restrictions = []
            elif kind == "set":
                s.restrictions = _uniq(keys)
            elif kind == "add":
                s.restrictions = _uniq(s.restrictions + keys)
            else:
                s.restrictions = [r for r in s.restrictions if r not in keys]
        elif f in ("include", "exclude"):
            other = "exclude" if f == "include" else "include"
            names = []
            for it in items:
                c = canon_name(it)
                if c:
                    names.append(c)
                else:
                    notes.append(f"ignored unrecognized ingredient {it!r}")
            cur = getattr(s, f)
            if kind == "clear":
                cur = []
            elif kind == "set":
                cur = _uniq(names)
            elif kind == "add":
                cur = _uniq(cur + names)
                clash = [n for n in names if n in getattr(s, other)]
                if clash:
                    setattr(s, other, [x for x in getattr(s, other) if x not in clash])
                    notes.append(f"moved {', '.join(clash)} from {other} to {f}")
            else:
                cur = [x for x in cur if x not in names]
            setattr(s, f, cur)
        elif f == "available":
            parsed = []
            for it in items:
                p = parse_ingredient(it)
                if p["canon"]:
                    parsed.append(Ingredient(name=p["canon"], qty=p["qty"], unit=p["unit"]))
                else:
                    notes.append(f"ignored unrecognized ingredient {it!r}")
            if kind == "clear":
                s.available = []
            elif kind == "set":
                s.available = parsed
            elif kind == "add":
                byname = {i.name: i for i in s.available}
                byname.update({i.name: i for i in parsed})
                s.available = list(byname.values())
            else:
                names = {i.name for i in parsed}
                s.available = [i for i in s.available if i.name not in names]
        elif f == "preferences":
            vals = [i.lower() for i in items]
            s.preferences = [] if kind == "clear" else _uniq(vals) if kind == "set" else _uniq(s.preferences + vals) if kind == "add" else [p for p in s.preferences if p not in vals]
    return s, notes


def set_results(state: ConversationState, ids: list[str], intent: str) -> ConversationState:
    s = state.model_copy(deep=True)
    s.last_ids, s.last_intent = list(ids), intent
    if len(ids) == 1:
        s.focus_recipe_id = ids[0]
    return s


_ORD = {w: i for i, w in enumerate(["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"], 1)}


def resolve_reference(text: str, state: ConversationState) -> str | None:
    """'the second one', '#3', 'option 2', '2nd', 'the last one', 'that recipe' -> recipe id (or None)."""
    t, ids = text.lower(), state.last_ids
    idx = None
    if m := re.search(r"(?:#|\bno\.?\s*|\bnumber\s*|\boption\s*|\bresult\s*|\brecipe\s*|\bshow\s*)(\d+)\b", t) or re.search(r"\b(\d+)(?:st|nd|rd|th)\b", t):
        idx = int(m.group(1))
    else:
        for w, i in _ORD.items():
            if re.search(rf"\b{w}\b", t):
                idx = i
                break
        if idx is None and re.search(r"\blast\b", t) and ids:
            idx = len(ids)
    if idx is not None:
        return ids[idx - 1] if 1 <= idx <= len(ids) else None
    if re.search(r"\b(that|this|the)\s+(one|recipe)\b|\bit\b", t):
        return state.focus_recipe_id or (ids[0] if len(ids) == 1 else None)
    return None


def state_summary(s: ConversationState) -> str:
    parts = [f"dish: {s.dish_query or '-'}", f"include: {s.include or '-'}", f"exclude: {s.exclude or '-'}",
             f"restrictions: {s.restrictions or '-'}", f"max_steps: {s.max_steps or '-'}",
             f"available: {[i.name for i in s.available] or '-'}", f"preferences: {s.preferences or '-'}",
             f"focus: {s.focus_recipe_id or '-'}", f"last_results: {len(s.last_ids)}"]
    return " | ".join(parts)
