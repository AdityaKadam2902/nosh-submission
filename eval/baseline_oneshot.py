"""Naive one-shot baseline: ask Gemini the scalar stats questions with NO tools/data, store the raw answers, compare to the independent truth.
Quota-aware: every reply is cached in eval/baseline_cache.json (reruns are free); `--n` caps NEW calls per run; stops at the first LLM failure.
  python -m eval.baseline_oneshot --n 6        (uses .env GEMINI_*)
run_eval --baseline then reads the cache; nothing is ever fabricated: no cache -> the report says 'baseline not recorded'."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

CACHE = Path(__file__).with_name("baseline_cache.json")
GOLDEN = Path(__file__).with_name("golden.yaml")
SYSTEM = "You answer questions about the 'Recipe Box' recipe dataset (about 125k recipes from AllRecipes, Epicurious and Food Network). Answer directly with a number and one short sentence."
NUM = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")


def load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def first_number(text: str):
    m = NUM.search(text or "")
    return float(m.group().replace(",", "")) if m else None


def judge(case_baseline: str, truth: dict, answer: str) -> tuple[bool, float | None]:
    """exact for counts; |err| <= 0.05 absolute for percentages/means (rounding the model may do)."""
    got, want = first_number(answer), truth.get(case_baseline)
    if got is None or want is None:
        return False, got
    tol = 0 if case_baseline == "count" else 0.05
    return abs(got - want) <= tol, got


def questions() -> list[dict]:
    return [c for c in yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))["cases"] if c.get("baseline")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6, help="max NEW LLM calls this run")
    a = ap.parse_args(argv)
    from recipebot.llm import LLM, LLMUnavailable
    llm, cache, new = LLM(cache_dir=None), load_cache(), 0
    for c in questions():
        if c["id"] in cache or new >= a.n:
            continue
        try:
            cache[c["id"]] = {"question": c["question"], "model": llm.model, "answer": llm.generate_text(c["question"], system=SYSTEM, cache=False)}
        except LLMUnavailable as e:
            print(f"LLM unavailable, stopping: {e}")
            break
        new += 1
        CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
        print(c["id"], "->", cache[c["id"]]["answer"][:100].replace("\n", " "))
    print(f"{len(cache)} cached baseline answers ({new} new) in {CACHE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
