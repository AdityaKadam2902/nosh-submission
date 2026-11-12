# HANDOFF: read this first (every new chat)

**Project:** RecipeBot, NOSH Robotics GenAI Intern take-home. Conversational chatbot over the Recipe Box dataset (3 JSON files, 125,164 records, 122,918 valid).
**Tasks / weights:** T1 search + factual Q&A + stats (30) | T2 ingredient matching (30) | T3 evidence-based substitution (40).
**Deadline:** submit within 3 days of 2026-11-10, i.e. assume **2026-11-13**; the owner confirms the exact hour. Submit with >= 4 h to spare.
**Owner:** Aditya, Windows + PowerShell, repo at `D:\Nosh Submission\recipebot`. Direct, token-efficient. Wants targeted patches, not rewrites.

## Principle (never violate)
*Evidence before generation.* The LLM never computes, filters, ranks or invents. Code does. The LLM only (a) turns user text into a typed Plan, (b) writes a short sentence around code-built results. Every answer carries a code-built RECEIPT (filters, denominator, normalization, step rule, ids, SQL). The verifier checks LLM prose (ids, numbers, banned words like "safe"/"guaranteed"). Constraints are 3-state (`contains`/`possible`/`free`); `possible` is NEVER in the main list; never claim "safe".

## Status
| Milestone | State |
|---|---|
| M0 ingest/audit, M1 normalize/steps/constraints, M2 search/stats/receipts/CLI | DONE, verified on the real data |
| M3 LLM layer (llm.py, state.py, planner, writer, verifier, orchestrator, free-text CLI) | DONE offline (mock LLM). Live Gemini chain NOT yet verified: free-tier daily quota is tiny (see below) |
| M4 matching (match.py, /match, planner intent) | BUILT, 224 offline tests pass; owner must extract `recipebot_m4.zip` and run on real data |
| M5 substitution (T3, 40%) | NOT STARTED, biggest remaining item |
| M6 eval harness | NOT STARTED |
| M7 Streamlit UI + README | NOT STARTED |
| M8 clean-clone test, video, submit | owner |

## Repo map
`recipebot/` modules: db, normalize, steps, constraints, search, stats, match, receipt, llm, state, planner, writer, verifier, orchestrator, cli. `scripts/`: download_data, build_db, build_fts, audit, top_canon, chat_script, llm_probe, gen_interfaces. `config/*.yaml`: aliases, forms (+distinct_pairs), allergens, units, staples. `tests/`: ~230 offline tests (+9 `real` tests that need the built DB). `docs/`: ARCHITECTURE.md, BUILD_PLAN.md, CONTEXT.md, DATA_AUDIT.md, **INTERFACES.md (real, generated signatures: read it)**. `eval/conversations/` for transcripts.
Regenerate interfaces any time: `python -m scripts.gen_interfaces`.

## Data facts (docs/DATA_AUDIT.md)
Dict-of-records JSON; ids namespaced `ar:|epi:|fn:<key>` (keys contain `/` and `.`). AR lines end with ` ADVERTISEMENT` (stripped in derived data, originals untouched). Instructions are newline blocks in 86.9% of recipes, else one paragraph (steps rule: blocks if >=2 else sentences). 1.3% near-duplicate recipes are NOT removed (stated in every receipt). `ingredients` table: one row per clean ingredient line (`salt and pepper` becomes 2 rows), columns recipe_id,pos,raw,canon,qty,unit,forms,alts. `recipes.n_steps/n_ingredients/is_valid` precomputed. FTS5 `recipes_fts` (valid recipes).

## Run / test (PowerShell, venv active, repo root)
```
python -m pytest -q -k "not real"      # ~5 s, offline, MUST stay green
python -m pytest -q                    # ~3 min, includes real-data cross-checks (needs data/recipes.db)
python -m scripts.build_db             # full build ~2 min; --sample N --db data\sample.db for a small DB
python -m recipebot.cli "/stats percentage --all garlic onion"
python -m recipebot.cli                # REPL; plain English needs GEMINI_API_KEY + GEMINI_MODEL in .env
```
No GNU make on the owner's machine: give plain `python -m ...` commands.

## LLM facts (important)
Gemini free tier via google-genai (API version forced to v1beta). `gemini-3.8-flash` is too slow (12-64 s, timeouts). `gemini-2.5-flash` is fast (2-4 s) but the free daily quota is ~20 requests/model/day. `gemini-2.5-flash-lite` is retired for new users (Google's error names `gemini-3.5-flash-lite`). `.env` knobs: GEMINI_API_KEY, GEMINI_MODEL, GEMINI_FALLBACK_MODEL, LLM_MIN_INTERVAL_S, LLM_TIMEOUT_S, RECIPEBOT_WRITER=off (1 LLM call per turn). **All unit tests must use a mock backend** (see tests/test_orchestrator.py `Script`); never burn real quota in tests. LLM results are cached on disk (`.cache/llm`).

## Conventions for deliverables
- New files in full; changes to existing files as minimal patches (or the whole file if tiny). **Return a zip of every new/changed file at repo-relative paths** (owner runs `Expand-Archive -Force`), plus an updated PROGRESS.md block, plus an ISSUES list for anything you found in files you do not own.
- Before returning: `python -m pytest -q -k "not real"` green; add tests for what you write; state the exact verify commands.
- Respect FILE OWNERSHIP in WORKSTREAMS.md. Do not edit files owned by another workstream; report instead.
- Python 3.11/3.12, no new frameworks (no LangChain). Windows-safe paths. UTF-8 stdout.
