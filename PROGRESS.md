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
