"""Diagnose Gemini flakiness: N one-shot calls, NO retries, NO cache; prints latency and the exact error code per call.
  python -m scripts.llm_probe [-n 8] [--structured] [--model other-model-id]"""
import argparse
import os
import sys
import time

from recipebot.llm import LLM, LLMUnavailable
from recipebot.planner import PLANNER_SYSTEM, Plan


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=8)
    ap.add_argument("--structured", action="store_true", help="use the real planner schema instead of plain text")
    ap.add_argument("--model", default=None)
    a = ap.parse_args(argv)
    llm = LLM(model=a.model or os.environ.get("GEMINI_MODEL"), cache_dir=None, max_retries=0, fallback_model="")
    print(f"model={llm.model} timeout={llm.timeout_s}s structured={a.structured}")
    ok = 0
    for i in range(a.n):
        t = time.time()
        try:
            if a.structured:
                llm.generate_json(f"CURRENT STATE: none\nRECENT TURNS:\n(none)\nUSER MESSAGE: Find penne pasta #{i}", Plan, system=PLANNER_SYSTEM)
            else:
                llm.generate_text(f"Reply with the single word OK. #{i}")
            ok += 1
            print(f"{i + 1:2}. ok   {time.time() - t:5.1f}s")
        except LLMUnavailable as e:
            print(f"{i + 1:2}. FAIL {time.time() - t:5.1f}s  {e}")
    print(f"{ok}/{a.n} succeeded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
