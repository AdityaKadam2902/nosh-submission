# RecipeBot

A conversational recipe assistant over the **Recipe Box** dataset (125,164 records, **122,918 valid**). It does four things: search recipes under hard dietary constraints, answer dataset questions exactly (counts, percentages, rankings), suggest what you can cook from what you have, and propose ingredient substitutions backed by what other recipes in the dataset actually do.

> **Evidence before generation.** Code retrieves, filters, counts, ranks and edits. The LLM (Gemini) only turns your words into a typed plan and phrases a short sentence around code-built results. Every answer carries a code-built **receipt** (filters, denominator, normalization, step rule, recipe ids, SQL), and a **verifier** rejects LLM prose that cites an unknown id, invents a number, or says "safe". With no LLM, every feature still works through slash commands.

## Results (full dataset, `python -m eval.run_eval --tools-only`)
| check | result |
|---|---|
| Offline test suite (mock LLM only) | 282 passing |
| Golden cases run on the full DB (stats, search, matching, substitution) | 26 pass, 0 fail (4 multi-turn chat cases need the LLM and run with `--llm`) |
| Stats vs an **independent** recomputation from the original records | all 10 stats cases exact |
| Hard-constraint violations in returned rows (allergen / exclude / max steps) | **0** |
| Hallucinated recipe ids | **0** |

See `EVAL_REPORT.md` for every case. The golden file contains no hand-typed expected numbers; truth is recomputed at run time by `eval/reference.py`.

## Quickstart (Windows PowerShell, Python 3.11/3.12)
```
git clone <repo-url> recipebot; cd recipebot
python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt
copy .env.example .env          # set GEMINI_API_KEY and GEMINI_MODEL (optional: slash commands work without them)
python -m scripts.download_data; python -m scripts.build_db       # ~2 min -> data\recipes.db
streamlit run app.py            # or: python -m recipebot.cli
```
Fast demo DB: `python -m scripts.build_db --sample 20000 --db data\sample.db`, then `$env:DB_PATH="data\sample.db"`.
Verify: `python -m pytest -q -k "not real"` (offline, ~5 s) and `python -m eval.run_eval --tools-only` (writes `EVAL_REPORT.md`, no LLM calls).

## Try it
| You say | What you get |
|---|---|
| `Find penne pasta` then `I cannot have dairy` then `also no mushrooms` | Search that keeps its filters across turns; recipes that *might* contain dairy are listed separately, never in the main list |
| `How many recipes contain both garlic and onion, and what percentage is that?` | Exact count and percentage over the full corpus, with the SQL and denominator in the receipt |
| `/match --have eggs onions tomatoes rice --restrict peanut --steps 6` | Ranked by matched / missing / steps, each with a one-line "why ranked here" |
| `/match --have "peanut butter" --restrict peanut` | `NO_MATCH`, with a separate list of alternatives that each say which constraint they violate |
| `/sub <recipe id> --replace egg --draft` | Mined replacements with graded evidence, a code-made ingredient edit, validated revised steps, and predictions labelled "prediction (not verified)" |
| `/help` | All commands |

## How it works
```
 user text --> Planner (LLM -> typed Plan)  --> state ops applied by CODE
                                               |
        search / stats / match / substitute  (pure code over SQLite: FTS5, SQL, normalization)
                                               |
        result + RECEIPT (code) --> Writer (LLM phrases)  --> Verifier (ids, numbers, banned claims)
                                               |                      fail -> repair once -> code-rendered answer
                                            UI / CLI
```
Layout: `recipebot/` (engine: `search`, `stats`, `match`, `substitute`, `substitute_draft`, `constraints`, `normalize`, `steps`, `verifier`, `orchestrator`), `config/*.yaml` (aliases, forms, allergens, staples, units and every substitution threshold, editable without code changes), `eval/` (golden set, independent reference, baseline, report), `tests/`, `app.py` (Streamlit), `docs/ARCHITECTURE.md` (full design).

## Decisions
- **Retrieval:** SQLite FTS5 (BM25, title weighted 5x) over title + normalized ingredients; hard filters (include/exclude/restrictions/max steps) are applied in code after retrieval. Vector search is not built (BM25 only, stated in the receipt). Aggregates never use search: `stats.py` runs over the full filtered corpus.
- **Normalization:** `normalize.py` + `config/*.yaml`. Form-aware: scallion = green onion, garlic powder is not garlic, butter is not peanut butter, eggplant is not egg. One row per ingredient line ("salt and pepper" becomes 2). Originals are never modified; the literal `ADVERTISEMENT` noise (361k occurrences in AllRecipes lines) is stripped only in derived data and display.
- **Ranking:** search by BM25 then id; matching by a lexicographic key (most matched, fewest missing, fewest steps, id); stats ties by name/id. Steps are *estimated*: newline blocks if there are at least 2 (true for 86.9% of recipes), else sentences; both counts are shown.
- **Computation:** counts, percentages, medians, rankings and the substitution edit are code, reproducible from the receipt SQL, and independently recomputed in `tests/test_stats_crosscheck.py` and `eval/reference.py`.
- **Uncertainty:** constraints are 3-state (`contains` / `possible` / `free`); nothing is ever called "safe". Substitution evidence is graded `strong | moderate | weak | conflicting | indirect | insufficient` from cohort counts (thresholds in `config/roles.yaml`); `insufficient` refuses and shows the counts. LLM-drafted steps and trade-offs are checked by code (no new ingredients, no new numbers, no "studies show") and labelled as predictions.
- **Failure behaviour:** LLM down, quota out or bad JSON never breaks a turn: the planner failure message points to slash commands, prose failure falls back to the code table.
- **External search:** none. Everything shown comes from the dataset.
- **AI tools disclosure:** built with AI assistance. Claude (chat, several sessions) wrote most of the code, tests and docs under my direction; Gemini (google-genai, free tier) is the runtime LLM. I ran every test suite and checked the results on the full dataset (122,918 valid recipes); the independent cross-checks (`tests/test_stats_crosscheck.py`, `eval/reference.py`) recompute the numbers from the original records. *[owner: edit this to what you personally changed and verified]*

## Known limitations
- Free-tier Gemini quota is small (about 20 requests/model/day); replies are cached in `.cache/llm`; `RECIPEBOT_WRITER=off` halves calls per turn and `RECIPEBOT_DRAFT=off` disables substitution drafting.
- About 1.3% near-duplicate recipes are not removed (stated in every receipt). The dataset has no nutrition, cook-time or allergen-label data, so the bot says so instead of guessing.
- Step counts are estimates; quantities are compared only when units are in the same family; substitution evidence describes similar recipes, not a tested conversion; allergen cross-contamination is not verified. Not medical advice.
- Small cohorts yield more `indirect` / `insufficient` substitution grades by design.