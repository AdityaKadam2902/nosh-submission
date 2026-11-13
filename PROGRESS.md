## Done
- M0 ✔ ingest + audit (125,164 records, 122,918 valid). M1 ✔ normalize/steps/constraints/config. M2 ✔ FTS5 search, stats (5 ops), receipts, /search /stats /show, cross-check vs raw JSON (real data).
- M3 ✔ (offline) llm.py (cache, backoff, fallback model, pacing), state.py + apply_ops, planner, writer, verifier, orchestrator, free-text CLI. Live Gemini chain unverified (quota).
- M4 ✔ built (match.py, /match, planner intent, "exclude eggs too" re-run); 224 offline tests pass; awaiting owner's real-data run.
## Decisions
- steps: blocks if >=2 else sentences (audit 86.9% blocks). Form-aware matching (distinct_pairs); green onion is not onion; soft forms (ground/canned/fresh...) recorded in `forms`, not in canon. "salt and pepper" -> 2 ingredient rows.
- possible -> Uncertain list, never main; peanut oil = possible for peanut. Search BM25-only (no vectors). Candidate cap 300, or 1000 with filters.
- LLM: Gemini via google-genai v1beta; writer optional (RECIPEBOT_WRITER=off); all unit tests use a mock backend.
## Known issues
- Gemini free-tier quota (~20 req/model/day): live runs and eval need caching or billing. gemini-3.8-flash too slow; gemini-2.5-flash-lite retired for new users.
- Full pytest ~3 min (real-data cross-checks); quick loop: -k "not real".
- Planner schema with defaults accepted by Gemini (verified once); writer prose rarely verified live.
## Next
- Parallel: A=M5 substitution, B=M6 eval, C=M7 UI+README (see WORKSTREAMS.md). Owner: apply recipebot_m4.zip, build data\sample.db, merge, M8.

## M5 Tier 1 (chat A)
### Done
- M5 Tier 1 ✔ (offline, mini-DB fixture; NOT yet run on sample.db / full DB): `config/roles.yaml` (26 ingredients: roles, can_fill, omit_ok; ALL thresholds), `recipebot/substitute.py` (`substitute(recipe_id, target, constraints=None, conn=None, *, use=None, config=None)`), `/sub`, planner intent `substitute`, orchestrator `_run_substitute` (substitute removed from NOT_YET). 21 new tests, 245 offline pass (after the 1-line test_orchestrator patch, see ISSUES).
### Decisions
- Cohort = valid recipes whose title shares >=60% of the dish tokens (same-dish, Jaccard>=0.20) or the dish class word bread/cake/pasta... (same-class, Jaccard>=0.35); ingredient sets compared without target/staples/salt/water/pepper. C_with/C_without = contains the target or not.
- Candidates come ONLY from roles.yaml `can_fill` (role gate); the dataset decides support: share_without, share_with, lift = share_without/max(share_with,0.05). Kept if used in >=2 recipes without the target and lift>=1.5 (items common everywhere, e.g. milk/baking soda, drop out and are named "common ingredients, not replacements" when nothing else remains).
- Grades (thresholds in roles.yaml, formula printed in every receipt): insufficient (<3 without) | conflicting (top two within 20% relative) | indirect (<8 without, <4 same-dish without, or <3 with so lift is unreliable) | strong (leader, share>=0.25, lift>=2, support>=3, runner-up <=0.7x leader) | moderate (share>=0.15, lift>=1.5, support>=2) | weak.
- Omission = cohort recipes without the target that use NO can_fill item; graded at most `moderate`; chosen only when no replacement qualifies.
- Constraints: candidate line checked with constraints.check -> `contains` BLOCKED, `possible` UNCERTAIN (never proposed); edited list re-checked and conflicts in OTHER lines reported as `residual` (replacing the target alone is not claimed to satisfy a restriction). User may pick only a MINED candidate (`--use`); anything else is refused.
- Edit applied by code on the original line index; amount = cohort median only if >=3 recipes give one in the same unit, labelled "not a tested conversion"; lines holding several ingredients ("salt and pepper") are never auto-edited.
### Known issues
- sample.db is ~16% of the data: cohorts ~6x smaller, expect more `indirect`/`insufficient` there; tune roles.yaml on the full DB.
- Tier 2 (LLM revised steps + validator, "prediction" labels) not built; `predictions` is [] and the CLI says so.
### Next
- Owner: run the verify commands on sample.db and the full DB; tune thresholds in roles.yaml. Then Tier 2 or eval T3 cases (chat B).

## M6 eval harness (chat B)
### Done
- M6 ✔ (offline; run on a generated 900-recipe DB and on the T3 fixture DB, NOT yet on sample.db/full DB): `eval/golden.yaml` (30 cases: 10 stats, 6 search, 5 match, 5 substitution, 4 multi-turn), `eval/reference.py` (independent recomputation from original records), `eval/run_eval.py` (`--tools-only` default = 0 LLM calls, `--llm`, `--baseline`) -> `EVAL_REPORT.md` + `eval/results.json`, `eval/baseline_oneshot.py` (cached, `--n` caps new calls), `eval/make_transcripts.py` (5 required transcripts), `tests/test_eval.py` (9 tests incl. mutation tests). 272 offline tests pass.
### Decisions
- No typed expected numbers: stats truth = reference.py; search/match/T3 = row-level audit (constraints.check on re-parsed originals, include/exclude/steps, ids exist). T3 grade is reported, not asserted; invariants: evidence ids lack the target and use the candidate, no proposed candidate violates a restriction, no edit when grade is insufficient/conflicting, abstentions return no edit, predictions labelled.
- T3 recipes are picked at run time by selector lists with fallbacks (skip, not fail, if the DB has none). Exit code 1 on any fail / violation / hallucinated id.
- Baseline is never fabricated: no cache -> report says "not recorded".
### Known issues
- Needs the owner to run: `python -m eval.baseline_oneshot --n 6` once (quota) for the verbatim wrong one-shot answer; `python -m eval.make_transcripts` for the 5 transcripts; `--llm` for C01-C04.
- Reference parses all records once (full DB: expect ~1-3 min; not measured).
### Next
- Owner: run on full DB, paste report failures/ISSUES to the owning chat; commit generated EVAL_REPORT.md + transcripts.

## M7 UI + README (chat C)
### Done
- M7 ✔ (offline-tested; Streamlit itself NOT installed in the build sandbox, so `streamlit run app.py` and the AppTest smoke test are unrun): `app.py` (chat via `Orchestrator.turn`, slash commands via `cli.handle`, receipt expander, evidence expander per cited id with ORIGINAL text (display strips ADVERTISEMENT), sidebar state + reset + example buttons, graceful no-LLM mode, one Orchestrator per browser session, read-only SQLite conn with check_same_thread=False), `README.md` (quickstart + decisions + AI disclosure + limitations), `.streamlit/config.toml`, `tests/test_app.py` (10 tests + 1 AppTest smoke that auto-skips without streamlit). 282 offline pass, 1 skipped.
### Decisions
- Logic lives in plain functions (`respond`, `evidence`, `split_receipt`, `state_rows`, `make_orchestrator`) so it is tested without Streamlit; UI in `main()`.
### Known issues
- Owner must run `streamlit run app.py` once on the real DB (M8) and confirm README commands on a clean clone; AI-disclosure sentence in README needs owner confirmation.
- Uses `st.rerun`, `use_container_width` (Streamlit >= 1.35 per requirements.txt).
