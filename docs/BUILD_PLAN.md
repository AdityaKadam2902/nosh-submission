# BUILD PLAN (3 days, 9 milestones, one fresh chat per milestone)

## Token-saving protocol (important)
1. **One milestone = one new chat.** Don't continue old chats. Long chats cost more per message.
2. Start each chat with: `CONTEXT.md` + `ARCHITECTURE.md` + **only the milestone text below** + `PROGRESS.md` + only the files that milestone touches. Never paste the whole repo or raw data.
3. Ask for **new files in full, existing files as small patches**. Run the verify command yourself, then paste only the error/trace (last 30 lines).
4. At the end of each chat, ask for an updated `PROGRESS.md` block, then commit to git. Paste only that block next time.
5. Optional: if you use Claude Code or another repo-aware tool, it reads files itself and saves a lot of pasting. The docs work either way.
6. Don't polish prose or UI before M8. Correctness first.

## Cut line
**MUST (submit-worthy):** M0–M6 (data, normalize, T1, planner/loop, T2, T3, eval).
**SHOULD:** M7 (UI + README + video). **Cut entirely:** cooking-process extraction, React frontend, agents, model training.
If time runs short: ship CLI + README + eval; the UI is a Streamlit file of ~80 lines, so it's quick.

## Timeline
| Day | Milestones | Hours |
|---|---|---|
| 1 | M0, M1, M2 | ~7 |
| 2 | M3, M4, M5 (start) | ~8 |
| 3 | M5 (finish), M6, M7, M8 | ~8 |
Slack: M8 doubles as buffer. Submit with at least 4 hours to spare for a clean-clone test.

---
## M0: Scaffold, ingest, audit (~2h)
Build: repo layout, `requirements.txt`, `.env.example`, `Makefile`, `scripts/download_data.py`, `db.py`, `scripts/build_db.py` (namespaced IDs, originals untouched, `is_valid`, `--sample N`), `scripts/audit.py`.
Audit prints: records per file, invalid counts by reason, `ADVERTISEMENT` occurrences, duplicates (same normalized title + same ingredient list), instruction format (blocks vs single paragraph %), empty fields, ingredient-line oddities (top 30 weird lines).
Accept: `make data build` works; `audit.py` output saved to `docs/DATA_AUDIT.md`; IDs round-trip (`ar:<key>` → original JSON record identical).
Verify: `pytest tests/test_ingest.py`. **Then paste the audit output into the next chat to settle `steps.py` and the normalization rules [VERIFY items].**

## M1: Normalization, steps, constraints (+ config) (~3h)
Build: `normalize.py`, `steps.py`, `constraints.py`, the `config/*.yaml` files (aliases, forms/distinct_pairs, allergens incl. may_contain + exceptions, units, staples), fill `ingredients` table in `build_db.py`, `n_steps/n_steps_alt/n_ingredients`.
Accept: ≥40 unit tests (scallion=green onion; garlic powder≠garlic; peanut oil flagged for peanut as `possible`/definite per config; coconut milk not dairy; butternut squash not butter; eggplant not egg; "1/2 cup (120 g) chopped onion, divided" → onion). Print the top-50 canon names and eyeball them.
Verify: `pytest tests/ -q`.

## M2: Search + stats (Task 1 core, no LLM) (~2h)
Build: FTS5 index, `search.py` (BM25 first; FAISS optional via `build_embeddings.py`), `stats.py` with all ops + receipts, `receipt.py`, CLI slash commands `/search /stats /show`.
Accept: spec examples work from the CLI: garlic AND onion count + %, tomato → 5 fewest steps (IDs shown), common ingredients, mean/median ingredient count. `tests/test_stats_crosscheck.py` passes (independent pure-Python recomputation on ≥10 stats).
Verify: `pytest tests/test_stats_crosscheck.py`.

## M3: LLM layer, state, planner, verifier, orchestrator (~3h)
Build: `llm.py` (Gemini, cache, backoff), `state.py` + `apply_ops`, `planner.py` (Pydantic `Plan`), `writer.py`, `verifier.py`, `orchestrator.py`, free-text chat in CLI.
Accept: multi-turn works: "Find penne pasta" → "I cannot have dairy" (refines same search, restrictions persist) → "also no mushrooms" → "show the second one" (resolved from `last_ids`). Verifier blocks an injected fake ID (unit test with a mocked LLM). LLM-down fallback message works.
Verify: `pytest tests/test_state.py tests/test_verifier.py` + manual transcript.

## M4: Task 2 matching (~2.5h)
Build: `match.py` per ARCHITECTURE §8, `/match` command, planner intent `match`, preference parsing, quantity handling, NO_MATCH + violating alternatives.
Accept: the spec example (eggs, onions, tomatoes, rice; ≤6 steps; no peanuts; prefer fewest extra) returns ranked IDs with matched/missing/steps/"why". "Exclude eggs too" updates and re-runs. An impossible constraint → explicit no-match + separately labeled violating alternatives. Quantity case prints "not verified" when units are incomparable.
Verify: `pytest tests/test_match.py`.

## M5: Task 3 substitution engine (~5h, split across days 2–3; the biggest task)
Build: `config/roles.yaml` (roles + can_fill + thresholds for ~25 common ingredients: egg, butter, milk, cream, flour, sugar, oil, yogurt, cheese, etc.), `substitute.py` steps 1–5 (deterministic; test BEFORE adding the LLM), then step 6–8 (draft, validate, output), `/sub` command, planner intent `substitute`.
Order: (a) deterministic cohort/candidate/evidence-grade output with counts and IDs, (b) LLM draft with ingredient edits applied by code, (c) validator + refusal paths.
Accept: banana bread minus eggs → graded evidence with counts + IDs + updated list + revised steps + labeled predictions; cream→dairy-free in a pasta recipe; one `conflicting`/`indirect` case reported honestly; one `insufficient` case refuses; a request that would violate a stated allergy is blocked by the validator.
Verify: `pytest tests/test_substitute.py` (deterministic parts with a fixed mini-DB fixture).

## M6: Evaluation harness (~2.5h)
Build: `eval/golden.yaml` (~30 cases per ARCHITECTURE §13), `baseline_oneshot.py`, `run_eval.py`, `EVAL_REPORT.md` (auto-generated), 5 saved transcripts in `eval/conversations/`.
Accept: `make eval` regenerates the report; it contains system-vs-baseline table, ≥1 verbatim wrong one-shot answer with the system's correct handling, a failures section with causes. Hard-constraint violation = 0, hallucinated IDs = 0 (if not, fix or report honestly).

## M7: UI + README (~2h)
Build: `app.py` (Streamlit chat + evidence expanders + state sidebar), `README.md` (≤1 page quickstart + decisions: retrieval, normalization, ranking, computation, uncertainty, external search + AI-tools disclosure + known limitations), `docs/` kept.
Accept: fresh clone on a clean venv → 5 commands → working chat. Evidence panel shows original recipe text for each cited ID.

## M8: Hardening, rehearsal, submit (~2h, doubles as buffer)
Clean-clone test (fresh folder, fresh venv, README commands only). Remove secrets (`.env` ignored). Make the repo public. Record a 3–5 min walkthrough (architecture in 60s, then the 5 conversations, then eval report + one failure). Prepare answers to the interview questions below.

---
## Interview prep: be able to explain/modify live
1. Why hybrid retrieval (BM25 + vectors + filters), and what RRF does. 2. How stable IDs are formed. 3. How stats cover the full filtered set (SQL, not search). 4. Form-aware ingredient matching and where aliases live. 5. 3-state constraints and why "possible" is excluded. 6. How evidence grades are computed (thresholds in config). 7. How the verifier stops hallucinated IDs/numbers. 8. What happens when Gemini is down. 9. How to change a ranking rule or add an alias live. 10. Which parts the AI tools wrote, and what you changed or verified.

## PROGRESS.md template
```
## Done
- M0 ✔ (date) …
## Decisions
- step rule: …  | denominator: … | thresholds: …
## Known issues
- …
## Next
- M1: …
```

## Start-of-chat prompt template
"Context attached (CONTEXT.md, ARCHITECTURE.md, PROGRESS.md). Do **M<n>** only, exactly as specified. New files in full, existing files as minimal patches. Include tests and the verify command. End with an updated PROGRESS.md block."
