# RecipeBot: ARCHITECTURE (single source of truth, v1)

Items marked **[VERIFY]** must be confirmed against real data or docs during M0/M1 (don't assume).

## 0. Design principles
1. **Evidence before generation.** Retrieve and compute first, then let the LLM phrase.
2. **LLM does language only:** (a) text → typed `Plan`, (b) prose around tool results, (c) T3 drafting of revised recipe text from evidence. It never counts, filters, ranks, or supplies recipe facts.
3. **Every answer has a RECEIPT built by code** (filters, denominator, rule names, recipe IDs, reproducible query). Numbers shown to the user are rendered by code, never typed by the LLM.
4. **Verifier on all LLM output:** every recipe ID cited must be in the tool result; every number in prose must appear in the receipt; T3 final ingredient list must pass constraints. On failure → repair once, else fall back to the code-rendered answer.
5. **Hard constraints are never relaxed silently.** No-match → say so; offer alternatives in a separate, labeled "violates X" section.
6. **Refuse > fabricate.** Missing attributes (nutrition, cook time) → say what is missing.
7. **Works without the LLM** (slash commands call tools directly). Also used by tests and eval.
8. **Simple enough to explain and modify live** (ranking weights, aliases, evidence thresholds all live in small config files).

## 1. Repo layout
```
recipebot/
  README.md  PROGRESS.md  requirements.txt  .env.example  Makefile
  config/ aliases.yaml  forms.yaml  allergens.yaml  roles.yaml  units.yaml  staples.yaml
  scripts/ download_data.py  build_db.py  build_embeddings.py  audit.py
  recipebot/
    db.py          # sqlite helpers, schema
    normalize.py   # ingredient line -> structured
    steps.py       # step counting
    constraints.py # 3-state allergen/exclusion engine
    search.py      # hybrid retrieval (FTS5 + FAISS + filters)
    stats.py       # analytical tools
    match.py       # Task 2
    substitute.py  # Task 3 evidence engine
    state.py       # ConversationState + apply_ops
    planner.py     # Gemini -> Plan (structured output)
    writer.py      # Gemini prose from results
    verifier.py    # grounding checks
    receipt.py     # receipt rendering
    llm.py         # Gemini client, retry/backoff, disk cache
    orchestrator.py# turn loop
    cli.py         # chat CLI + slash commands
  app.py           # Streamlit UI
  eval/ golden.yaml  run_eval.py  baseline_oneshot.py  EVAL_REPORT.md  conversations/
  tests/
```
Raw dataset and built DB/index are **git-ignored**. `download_data.py` fetches them. The dataset page is https://eightportions.com/datasets/Recipes/ ; find the actual archive link there **[VERIFY]**. Don't commit the raw data (no clear redistribution license).

## 2. Data model (SQLite)
```
recipes(id TEXT PK,            -- "ar:<origkey>" | "epi:<origkey>" | "fn:<origkey>"
        source TEXT, orig_key TEXT,
        title TEXT,            -- ORIGINAL, untouched
        ingredients_json TEXT, -- ORIGINAL list, untouched (incl. noise)
        instructions TEXT,     -- ORIGINAL, untouched
        picture_link TEXT,
        is_valid INT,          -- title non-empty AND >=1 clean ingredient AND >=1 step
        invalid_reason TEXT,
        n_ingredients INT,     -- count of CLEAN ingredient lines
        n_steps INT,           -- by steps.py primary rule
        n_steps_alt INT)       -- by alternate rule (for sensitivity report)
ingredients(recipe_id TEXT, pos INT, raw TEXT, canon TEXT, qty REAL NULL, unit TEXT NULL,
            forms TEXT)        -- canon = normalized name; qty/unit parsed if reliable
recipes_fts  -- FTS5(title, ingredients_text) rowid -> recipes.rowid
-- optional: embeddings.faiss + ids.json  (built by build_embeddings.py)
```
Original key kept in `orig_key`. The dataset files are dicts keyed by id **[VERIFY top-level structure]**. Keep raw noise (`ADVERTISEMENT`, HTML entities) in the originals, and clean only in derived columns.
**Duplicates across sources:** count all valid records. Report near-duplicate (same normalized title + same canon ingredient set) count separately in the audit. State this in stats receipts.
**Denominator rule:** "dataset" = all valid recipes (`is_valid=1`), and the receipt also shows total records and invalid count.

## 3. Normalization (`normalize.py`)
`parse_ingredient(raw) -> {canon, qty, unit, forms[], alts[], raw}`
Pipeline: html-unescape → lowercase → drop parentheticals → strip leading quantity (numbers, fractions, unicode fractions, ranges) + unit (`units.yaml`) → cut at first comma (prep text) → drop prep words (chopped, minced, diced, sliced, fresh, large, small…) → handle "or" alternatives (keep first as canon, store rest in `alts`; matching may consult alts only if flagged) → singularize (rule-based: tomatoes→tomato, leaves→leaf, with an exceptions list) → alias map (`aliases.yaml`: scallion/green onion, cilantro/coriander leaves, aubergine/eggplant …) → keep **form words** (`forms.yaml`: powder, paste, sauce, juice, oil, extract, dried, smoked, flakes, ground, canned…) as part of canon.
**Matching `contains(recipe, "garlic")`:** token-sequence containment of the query tokens in `canon`, EXCEPT compounds in `forms.yaml` `distinct_pairs` (garlic→[powder, salt, paste?]; tomato→[paste, sauce, juice]; onion→[powder, salt]; peanut→[oil, butter]…) which are different items unless `strict=False` is explicitly asked. Receipt states the mode ("form-aware": garlic powder not counted as garlic).
Quantity: parse only when unambiguous (number + known unit). Else `qty=NULL`.

## 4. Steps (`steps.py`)
`count_steps(instructions) -> (primary, alt)`; strip `ADVERTISEMENT`, empty lines, and bare numbering.
- Primary: if text has ≥2 non-empty newline-separated blocks → count blocks; else sentence-split (regex, abbreviation-safe) and count sentences. **[VERIFY after audit which format dominates; document the final rule.]**
- Alt: sentence count always. Reported in eval as sensitivity. Label as "estimated instruction steps".

## 5. Constraints (`constraints.py`, `allergens.yaml`)
Per restriction key (dairy, egg, peanut, tree_nut, gluten, shellfish, soy, pork, beef, alcohol, vegetarian…):
`definite` terms, `may_contain` terms (margarine, chocolate, "natural flavors", some broths…), `exceptions` (coconut milk, almond milk, peanut… ; butternut squash≠butter; cocoa butter, eggplant≠egg, nutmeg≠nut).
`check(recipe_ingredients, restriction) -> {"state": "contains"|"possible"|"free", "evidence": [(pos, raw, reason)]}`
Policy: `contains` → excluded. `possible` → excluded from main list, listed under "Uncertain". `free` → included **with ingredient-level evidence** (list "no dairy-listed ingredient found; label and cross-contamination not verified"). Never state "safe".

## 6. Retrieval (`search.py`)
`search(query, include=[], exclude=[], restrictions=[], max_steps=None, k=10) -> {rows, total_candidates, receipt}`
1. FTS5 BM25 over title + ingredient text → top 300 candidates. 2. If FAISS exists, embed the query (MiniLM, `sentence-transformers/all-MiniLM-L6-v2`), take top 300, and merge with Reciprocal Rank Fusion (k=60). If the index is missing → BM25 only (log it). 3. Apply hard filters (include/exclude/restrictions/max_steps) in code over the candidate set. 4. Sort by fused score, tie-break by id. Return k. Report `total_candidates` and `post_filter_count`.
Important: for **aggregates (T1 stats) do NOT use search.** Use `stats.py` over the full filtered corpus.

## 7. Stats (`stats.py`), Task 1 analytics
Single entry `run_stats(spec) -> {answer_data, receipt}` where `spec = {op, filters, k}`
ops: `count`, `percentage` (of valid dataset or of a named subset), `top_ingredients(k)` (by # recipes containing; canon-level), `ingredient_count_summary` (mean, median, min, max of n_ingredients), `rank_steps(k, order)`; tie-break `n_steps ASC, id ASC`.
filters: `contains_all[]`, `contains_any[]`, `exclude[]`, `title_contains`, `source`.
Receipt always includes: filters (human-readable), N analyzed, denominator + its definition, normalization mode, step rule, formula, the SQL, recipe IDs for ranked lists.
**Cross-check:** `tests/test_stats_crosscheck.py` recomputes 10 stats independently with pandas/pure Python over the raw JSON and asserts equality (this backs the "reproducible" claim).

## 8. Task 2 matching (`match.py`)
Input: `available=[{name, qty?, unit?}]`, `exclude[]`, `restrictions[]`, `max_steps`, `preferences` (ordered subset of: most_matched, fewest_missing, fewest_steps), `staples` (default from `staples.yaml`: water, salt, black pepper; shown in the receipt and toggleable).
Steps: normalize available (same pipeline + aliases) → candidate recipes = any recipe sharing ≥1 canon with the available set (inverted index query on `ingredients.canon`) → **hard filter** (exclude/restrictions/max_steps, 3-state) → per recipe: `matched`, `missing` (= required canon − available − staples), `extra_required = len(missing)`, `steps` → rank by lexicographic key built from preferences (default: most_matched desc, fewest_missing asc, fewest_steps asc, id asc) → top k. Also compute display `coverage = matched / n_required`.
Each result shows: matched, missing, steps, constraint evidence, and a one-line "why ranked here" built by code from the key comparison against its neighbor.
Quantities: if user gave qty+unit AND recipe line has qty+unit in the same family (mass/volume/count) → compare after unit conversion (`units.yaml`) → `sufficient|insufficient|unverified`. Otherwise: "name-level match; quantity sufficiency not verified."
No eligible → `NO_MATCH` message + separate `violating_alternatives` list, each tagged with the violated constraint (`violates: peanut` etc.). Follow-ups ("exclude eggs too") modify state and re-run.

## 9. Task 3 substitution (`substitute.py`), the 40% task
Input: `recipe_id` (or a recipe from the active result), `target` ingredient, `restrictions[]`, `dataset_only: bool`.
**Pipeline (all deterministic until step 6):**
1. **Locate** target lines in the recipe (via `contains`). None → say so.
2. **Role lookup** from `roles.yaml` (e.g. egg: binder, moisture, leavening, richness; cream/milk: fat, liquid, richness, thickener; butter: fat, flavor, tenderness; flour: structure, thickener…). Roles come from this table, not the LLM. Unknown target → `insufficient`.
3. **Cohort:** similar recipes = BM25 on title + shared canon (Jaccard ≥ τ on canon sets, excluding target and other volatile ingredients), same dish-class keywords. Split into `C_with` (contains target) and `C_without` (does not).
4. **Candidates:** for each canon ingredient `x` in `C_without` not present in the source recipe, compute `share_without(x)` = fraction of `C_without` containing x, and `share_with(x)`; `lift = share_without / max(share_with, ε)`. Keep x if (a) role-compatible per `roles.yaml` `can_fill` list, (b) passes the restrictions, (c) if `dataset_only`, it is in the dataset vocabulary (it always is by construction), (d) lift ≥ λ and support ≥ s.
5. **Evidence grade (rule-based, thresholds in `roles.yaml`/config):**
   - `strong`: `|C_without| ≥ 8`, top candidate share_without ≥ 0.25, lift ≥ 2, and clear margin over the runner-up.
   - `conflicting`: ≥2 candidates within 20% of each other, or the candidate appears in `C_with` at similar rates (it is just a common ingredient, not a replacement).
   - `indirect`: cohort is small (3 ≤ n < 8) or similarity is low; the evidence is from related dishes.
   - `insufficient`: otherwise → **refuse a specific recommendation**; optionally external search (secondary, labeled, with links).
   Always list supporting recipe IDs (top 5 by similarity) and the counts.
6. **Draft (LLM, constrained):** input = source recipe, chosen candidate(s), role, evidence, 2–3 exemplar recipes' texts. Output JSON: `{ingredient_edits:[{op: remove|replace|add, line_index, new_line}], instruction_edits:[...], predicted_effects:[...], caveats:[...]}`. **Code** applies ingredient edits to produce the final list.
7. **Validate:** final canon set must not contain forbidden/restricted items (3-state); any new ingredient must be a dataset-vocab canon (when `dataset_only`); cited IDs exist; effects labeled "prediction (not verified)". Fail → one repair attempt → else return evidence-only answer with no revised recipe.
8. **Output:** original ID, removed ingredient, role(s), candidate(s), evidence grade + numbers + recipe IDs, updated ingredient list, revised instructions, predicted trade-offs (labeled predictions), explicit uncertainty, "not medical advice; label/cross-contamination not verified".
External search: off by default. If used, a separate "External (secondary)" section with URLs. Never merged into local evidence counts.

## 10. Conversation state (`state.py`) and planner
```python
class ConversationState(BaseModel):
    dish_query: str|None; include: list[str]; exclude: list[str]
    restrictions: list[str]; max_steps: int|None
    available: list[Ingredient]; preferences: list[str]
    focus_recipe_id: str|None; last_ids: list[str]; last_intent: str|None
```
Planner returns `Plan{intent, tool_args, ops, needs_clarification?}`, intent ∈ {search, stats, match, substitute, recipe_detail, followup_refine, chat, out_of_scope}. `ops` = list of `{field, op: set|add|remove|clear, value}`. **Code applies ops** (`apply_ops`). Rules: restrictions and excludes persist until explicitly removed; a new dish topic (`new_topic=true`) resets dish_query/include/last_ids but **keeps restrictions**; "the first one"/"that recipe" resolved from `last_ids` by code. The planner is given the current state + last 4 turns + a tool catalog, and uses Gemini structured output (JSON schema). Temperature 0.
Gemini via `google-genai`: `client.models.generate_content(model=os.environ["GEMINI_MODEL"], contents=..., config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=Plan, temperature=0))`. **[VERIFY current free-tier model name in AI Studio; keep it in .env.]**
`llm.py`: disk cache keyed by sha256(model+prompt+schema), exponential backoff on 429/5xx, hard timeout, a request counter. If the LLM is down → CLI says "LLM unavailable, use /search /stats /match /sub".

## 11. Orchestrator turn loop
`user_text → planner(state) → apply_ops → run tool (code) → result + receipt (code) → writer(result) → verifier → render (prose + receipt + evidence panel)`.
Writer prompt: "Use ONLY the JSON below. Do not add recipes, numbers or ingredients. Refer to recipes by ID." Verifier: regex IDs ⊆ result IDs; numbers in prose ⊆ numbers in receipt/result; no banned claims ("safe", "guaranteed"); on fail repair once, else fall back to the code template.

## 12. UI
CLI (`python -m recipebot.cli`) with `/search /stats /match /sub /show <id> /state /reset /help`. Streamlit chat (`streamlit run app.py`): message list + collapsible "Evidence & receipt" under each answer (recipe IDs expand to the original title/ingredients/instructions) + sidebar showing the active state (restrictions, excludes). No other tabs.

## 13. Evaluation (`eval/`)
- `golden.yaml`: ~30 cases: ~10 stats (ground truth from an independent pure-Python computation), ~6 search/constraint (assert no `contains` for the restriction), 5 matching (incl. peanut + ≤6 steps, "exclude eggs too", no-match), 5 substitution (strong, indirect, conflicting, insufficient, restriction-violation attempt), 4 multi-turn.
- `baseline_oneshot.py`: sends the same stats questions to Gemini without tools; stores raw answers; compares to ground truth. Report wrong/ungrounded cases verbatim.
- `run_eval.py` → `EVAL_REPORT.md`: table (case, pass/fail, why), metrics: stats exactness, hard-constraint violation rate (target 0), hallucinated-ID rate (0), abstention correctness, evidence-citation coverage, system vs baseline accuracy. Include failures + causes.
- Five required demo transcripts saved in `eval/conversations/`: (1) penne → "I cannot have dairy" → "also no mushrooms" (multi-turn). (2) garlic AND onion count + % (aggregate). (3) tomato → 5 fewest steps. (4) eggs/onions/tomatoes/rice ≤6 steps no peanuts → "exclude eggs too" → impossible constraint (no-match). (5) banana bread minus eggs (evidence) + a weak/conflicting case + a refused case.

## 14. Config and run
`.env`: `GEMINI_API_KEY`, `GEMINI_MODEL`, `DATA_DIR`, `DB_PATH`. `Makefile`: `setup` (pip install), `data` (download), `build` (build_db + audit), `embed` (optional), `test`, `eval`, `cli`, `ui`. `build --sample 5000` for a quick demo build; the full build must finish in minutes on a laptop. README must be ≤1 page: prerequisites, the 5-command quickstart, example queries, structure, decisions, AI-tools disclosure.

## 15. Risk register
| Risk | Mitigation |
|---|---|
| Gemini free-tier rate limits | disk cache, backoff, slash-command fallback, small prompts |
| Embedding build slow on interviewer laptop | optional; BM25-only works; `--sample` |
| Messy ingredients break matching | form-aware matching, audit report, config files for aliases |
| Overbuilding | must-have cut line in BUILD_PLAN; no extra tabs, no agents, no training |
| LLM hallucinated IDs/numbers | verifier + code-rendered receipts + eval metric |
| Interview modification requests | rules in config; short modules; tests |
