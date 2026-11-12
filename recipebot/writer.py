"""Writer: LLM prose AROUND a code-built result. The prose is only a short summary; recipe tables, numbers and the receipt are
rendered by code. Everything the writer says is checked by verifier.verify."""
from __future__ import annotations

import json

from recipebot.llm import LLM

WRITER_SYSTEM = """You are the WRITER of a recipe chatbot. Use ONLY the JSON below. Do not add recipes, numbers, ingredients or facts.
Write 1-3 plain sentences summarizing the result for the user: what was searched/computed, which filters were applied, how many matched
(use the exact numbers from the JSON), and mention if some recipes are in the 'uncertain' group because an ingredient only MAY contain a
restricted item. Refer to recipes by their id only if needed. Do NOT list the recipes (a table is shown separately). Never say a recipe
is 'safe', 'allergen-free' or 'guaranteed'; say 'no listed ingredient matched' instead. No markdown headers."""


def write(llm: LLM, user_text: str, payload: dict, problems: list[str] | None = None) -> str:
    prompt = f"USER ASKED: {user_text}\nRESULT JSON:\n{json.dumps(payload, ensure_ascii=False, default=str)}"
    if problems:
        prompt += "\nYour previous draft failed verification: " + "; ".join(problems[:5]) + ". Rewrite it using only values present in the JSON."
    return llm.generate_text(prompt, system=WRITER_SYSTEM)
