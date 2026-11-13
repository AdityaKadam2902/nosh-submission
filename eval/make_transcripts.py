"""Record the 5 required demo transcripts (ARCHITECTURE §13) through the REAL orchestrator + LLM into eval/conversations/*.md.
  python -m eval.make_transcripts [--only 1 3]      (set DB_PATH, GEMINI_*; replies are cached in .cache/llm so reruns are free)
Quota: ~10 turns = 10-20 requests (free tier ~20/model/day): use RECIPEBOT_WRITER=off to halve it, or run with --only on separate days."""
import argparse
import sys
from pathlib import Path

from scripts.chat_script import main as chat

OUT = Path(__file__).parent / "conversations"
SCRIPTS = {
    1: ("01_penne_dairy_mushrooms.md", ["Find penne pasta", "I cannot have dairy", "also no mushrooms", "show the second one"]),
    2: ("02_garlic_onion_percent.md", ["How many recipes contain both garlic and onion, and what percentage of all recipes is that?"]),
    3: ("03_tomato_fewest_steps.md", ["Which 5 recipes with tomato have the fewest steps?"]),
    4: ("04_match_no_peanuts_exclude_eggs_nomatch.md", ["I have eggs, onions, tomatoes and rice. What can I cook in at most 6 steps, no peanuts?", "exclude eggs too",
                                                       "I have only peanut butter, and I'm allergic to peanuts. What can I cook?"]),
    5: ("05_banana_bread_substitution.md", ["Find banana bread", "Replace the eggs in the first one", "Replace the butter in the first one", "Replace the saffron in the first one"]),
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, nargs="+", default=None)
    a = ap.parse_args(argv)
    rc = 0
    for n, (name, turns) in SCRIPTS.items():
        if a.only and n not in a.only:
            continue
        rc |= chat(turns + ["--out", str(OUT / name)])
    return rc


if __name__ == "__main__":
    sys.exit(main())
