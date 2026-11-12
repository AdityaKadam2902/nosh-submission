"""Run a scripted multi-turn conversation through the real orchestrator and save the transcript (used for eval/conversations/).
  python -m scripts.chat_script --out eval/conversations/01_penne.md "Find penne pasta" "I cannot have dairy" "also no mushrooms" "show the second one"
"""
import argparse
import sys
from pathlib import Path

from recipebot.db import connect, db_path
from recipebot.llm import LLM
from recipebot.orchestrator import Orchestrator
from recipebot.state import state_summary


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("turns", nargs="+")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    llm = LLM()
    orch = Orchestrator(llm, connect(db_path(), readonly=True))
    md = []
    for t in a.turns:
        r = orch.turn(t)
        block = f"### User\n{t}\n\n### Bot\n{r.text}\n\n_state: {state_summary(orch.state)}_" + (f"\n\n_verifier fallback: {r.problems}_" if r.fallback else "") + (f"\n\n_LLM error: {r.error}_" if r.error else "") + (f"\n\n_last LLM error: {llm.last_error}_" if (r.fallback or r.llm_down) and llm.last_error else "")
        print(block + "\n" + "-" * 60)
        md.append(block)
    print(f"LLM calls: {llm.calls}, cache hits: {llm.cache_hits}, retries: {llm.retries}, fallbacks: {llm.fallbacks_used}")
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text("\n\n---\n\n".join(md), encoding="utf-8")
        print(f"saved {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
