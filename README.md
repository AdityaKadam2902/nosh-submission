<div align="center">

# RecipeBot

### A recipe assistant that shows its work

Ask in plain English. Get answers computed by code over 122,918 recipes, each with a receipt you can verify.

![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-3776AB?style=flat-square)
![Tests](https://img.shields.io/badge/tests-282%20passing-2EA44F?style=flat-square)
![Eval](https://img.shields.io/badge/eval-26%2F26%20cases%20pass-2EA44F?style=flat-square)
![Constraint violations](https://img.shields.io/badge/hard--constraint%20violations-0-2EA44F?style=flat-square)
![Hallucinated ids](https://img.shields.io/badge/hallucinated%20ids-0-2EA44F?style=flat-square)
![LLM](https://img.shields.io/badge/LLM-optional-6E7781?style=flat-square)

</div>

<table align="center">
<tr>
<td align="center"><b>122,918</b><br>valid recipes<br>(3 sources)</td>
<td align="center"><b>4</b><br>capabilities:<br>search, stats, match, substitute</td>
<td align="center"><b>10 / 10</b><br>stats exact vs<br>independent recomputation</td>
<td align="center"><b>0</b><br>constraint violations,<br>0 invented ids</td>
</tr>
</table>

Built on the *Recipe Box* dataset (125,164 records from AllRecipes, Epicurious and Food Network).

| Capability | What it does |
|---|---|
| **Search** | Recipes under hard dietary constraints (allergens, exclusions, step limits), with multi-turn memory |
| **Dataset questions** | "How many / what percentage / which five / most common" with exact numbers over the whole corpus |
| **Cook with what I have** | Rank recipes by what you have, what is missing and how many steps they take |
| **Ingredient substitution** | Replacements mined from what similar recipes actually do, the ingredient list edited in code, optional validated revised steps |

**Design principle: evidence before generation.** LLMs are bad at counting, filtering and ranking, and good at reading intent and phrasing prose. So Gemini does exactly two things here: it turns your words into a typed plan, and it phrases a short summary around results that code already computed. Every number, filter, ranked row and ingredient edit comes from deterministic code over SQLite, and every answer ends with a **receipt**: the filters, the denominator, the normalization and step rules, the recipe ids and the exact SQL.

[Why](#why-this-design) · [Guarantees](#guarantees) · [Results](#results) · [Quickstart](#quickstart) · [Using it](#using-recipebot) · [How it works](#how-it-works) · [Receipt](#a-real-receipt) · [Substitution](#ingredient-substitution-in-depth) · [State](#conversation-state) · [Evaluation](#evaluation) · [Config](#configuration) · [Data](#the-data) · [Decisions](#design-decisions) · [Hard problems](#hard-problems-and-how-they-were-solved) · [Limitations](#known-limitations) · [Layout](#repository-layout) · [Ownership & AI use](#ownership-and-ai-use)

---

## Why this design
A naive recipe chatbot asks the LLM and repeats its answer. On a factual task that fails in three checkable ways:

| Failure mode | Looks like | RecipeBot's answer |
|---|---|---|
| **Invented numbers** | "About 40,000 recipes contain garlic and onion" (plausible, wrong) | Counts come from SQL over the full corpus; the receipt prints the SQL; an independent recomputation verifies it (`eval/reference.py`) |
| **Unverifiable claims** | "This recipe is safe for your allergy" | A verifier rejects "safe", "guaranteed", "allergen-free" and similar; the allergen engine never emits a "safe" verdict |
| **Silent constraint relaxation** | A "peanut-free" list that quietly includes peanut oil | `possible` matches are quarantined in a separate, labelled *Uncertain* list; nothing in the main list ever tests as `contains` |

It also **degrades honestly rather than breaking**: if the LLM is down, out of quota or returns invalid JSON, every feature still works through slash commands, and every LLM-written sentence passes a grounding check or is replaced by the code-rendered answer.

## Guarantees
Held for every answer, in chat and slash-command mode alike:
- **Receipts everywhere:** filters, N analysed, denominator and its definition, normalization mode, step rule, ordering, recipe ids and the SQL that produced the numbers.
- **Verifier on all LLM text:** every cited id must exist in the tool result, every number must appear in the result or receipt, banned claims are rejected. On failure: one repair attempt, then the code-rendered answer.
- **Three-state allergen logic:** `contains` / `possible` / `free`, with per-ingredient evidence. `possible` is never in the main list; `free` is always phrased "no *X*-listed ingredient found; label and cross-contamination not verified".
- **Hard constraints are never relaxed silently:** if nothing qualifies you get an explicit `NO_MATCH` plus a separate list of near-misses, each tagged with the constraint it violates.
- **Refuse before fabricate:** missing data (nutrition, cook time), an unknown ingredient role or a too-thin evidence cohort gives an explicit refusal with counts, never a confident guess.
- **Works without the LLM:** every feature is also a slash command; search, stats, matching and substitution evidence and edits are deterministic Python over SQLite.
- **Code computes, LLM phrases:** role tables, grade thresholds and banned-phrase lists live in YAML, not in prompts.

## Results
Run on the **full dataset** (122,918 valid recipes) with `python -m eval.run_eval --tools-only`, zero LLM calls:

| Check | Result |
|---|---|
| Offline test suite (mock LLM only, `pytest -q -k "not real"`) | **282 passed** (4.0 s); the full suite adds 9 real-data tests (7 pass, 2 skip as "synthetic only") |
| Golden cases on the full DB (stats, search, matching, substitution) | **26 pass, 0 fail** (4 multi-turn chat cases need the LLM: `--llm`) |
| Stats vs an **independent** recomputation from the original records | **10/10 exact** |
| Hard-constraint violations in returned rows (allergen, exclude, max steps) | **0** |
| Hallucinated recipe ids (230 checked against the DB) | **0** |
| Abstention correctness (refusal, forced-violation and no-match cases) | **3/3** |
| Evidence-citation coverage (substitution candidates with supporting ids) | **6/6** |

`EVAL_REPORT.md` lists every case with its result and cause. `eval/golden.yaml` contains **no hand-typed expected numbers**: truth is recomputed at run time by `eval/reference.py`, a pure-Python pass over the original records that touches neither the ingredients table, nor SQL filters, nor `stats.py`, so the same file validates the sample DB and the full DB alike. Five recorded demo conversations (real orchestrator + Gemini, receipts included) are in `eval/conversations/`.

## Quickstart
Windows PowerShell, Python 3.11 or 3.12. No GNU make needed.
```powershell
git clone <repo-url> recipebot; cd recipebot
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env             # set GEMINI_API_KEY and GEMINI_MODEL (optional: slash commands work without them)
python -m scripts.download_data    # 3 dataset JSON files -> data\raw (offline fallback: --zip <path>)
python -m scripts.build_db         # ~2 min -> data\recipes.db (+ FTS5 index + config SHA in meta)
streamlit run app.py               # web UI   |   python -m recipebot.cli   # CLI (REPL; add a command for one-shot mode)
```
Fast demo DB (seeded, split evenly across sources): `python -m scripts.build_db --sample 20000 --db data\sample.db`, then `$env:DB_PATH = "data\sample.db"`.
Verify: `python -m pytest -q -k "not real"` (offline, ~5 s, mock LLM only) and `python -m eval.run_eval --tools-only` (writes `EVAL_REPORT.md`). `python -m pytest -q` (~3.5 min) adds the real-data cross-checks. The optional FAISS/MiniLM index (`requirements-embed.txt`) is **not** built by default; BM25-only is the shipped configuration and the receipt says so.

## Using RecipeBot
**Chat (needs Gemini in `.env`).** Plain English; restrictions and exclusions persist across turns; every answer is followed by a receipt, and in the UI each cited id has an expandable panel with the original text.
```text
> Find penne pasta          > I cannot have dairy          > also no mushrooms          > show the second one
How many recipes contain both garlic and onion, and what percentage is that?
Which 5 recipes with tomato have the fewest steps?
I have eggs, onions, tomatoes and rice. What can I cook in at most 6 steps, no peanuts?   > exclude eggs too
Replace the eggs in the first one
```
**Slash commands (no LLM needed):**
| Command | Example |
|---|---|
| `/search <text> [--include ..] [--exclude ..] [--restrict ..] [--steps N] [-k N]` | `/search penne --restrict dairy --exclude mushroom --steps 6` |
| `/stats <op> [--all ..] [--any ..] [--exclude ..] [--title t] [--source ar\|epi\|fn] [--of-all ..] [-k N] [--order asc\|desc] [--skip-staples]` | `/stats percentage --all garlic onion` |
| `/match --have ... [--exclude ..] [--restrict ..] [--steps N] [--prefer fewest_missing most_matched fewest_steps] [--no-staples] [-k N]` | `/match --have eggs onions "2 tomatoes" rice --restrict peanut --steps 6` |
| `/sub <id or row> --replace <ingredient> [--restrict ..] [--exclude ..] [--use <mined candidate>] [--draft]` | `/sub 1 --replace egg --draft` |
| `/show <id or row>` · `/state` · `/reset` · `/help` · `/quit` | `/show ar:123` |

`/stats` ops: `count`, `percentage`, `top_ingredients`, `ingredient_count_summary`, `rank_steps`. Row numbers (`/sub 3`, "the second one") refer to the last result list.

<details><summary><b>Environment switches</b></summary>

| Variable | Effect |
|---|---|
| `GEMINI_API_KEY`, `GEMINI_MODEL` | LLM chat mode; without them CLI and UI run in slash-command-only mode |
| `GEMINI_FALLBACK_MODEL` | Used once per call when the primary model is retryably unavailable |
| `LLM_TIMEOUT_S`, `LLM_MIN_INTERVAL_S` | Per-call timeout (default 60 s) and pacing between calls |
| `RECIPEBOT_WRITER=off` | No LLM prose (1 call per turn instead of 2) **and** no LLM-drafted substitution steps; tables, receipts and Tier-1 evidence unaffected |
| `DB_PATH`, `DATA_DIR`, `DATA_URL` | Database location, raw-data directory, dataset archive URL |

LLM replies are cached on disk under `.cache/llm` (keyed by model, system prompt, prompt and schema), so repeats and re-runs are free.
</details>

## How it works
```
 user text ──▶ Planner (LLM ──▶ typed Plan) ──▶ state ops applied by CODE
                                                     │
          search │ stats │ match │ substitute   pure code over SQLite (FTS5, SQL, normalization)
                                                     │
        result + RECEIPT (code) ──▶ Writer (LLM phrases) ──▶ Verifier (ids, numbers, banned claims)
                                                     │                    fail ──▶ repair once ──▶ code-rendered answer
                                                 UI / CLI
```
A typical turn is 2 LLM calls (plan + prose), each cached; 1 with the writer off. The substitution draft adds 1–2 validated calls.

| Module | Role |
|---|---|
| `db.py` | Schema, namespaced ids (`ar:<key>`, `epi:<key>`, `fn:<key>`), validity; originals stored **untouched** and round-trip |
| `normalize.py` + `config/*.yaml` | Ingredient line → `{canon, qty, unit, forms, alts}`; aliases, forms, units, prep words |
| `steps.py` | Step estimation: newline blocks if ≥ 2 (86.9% of recipes), else sentences; both counts stored and shown |
| `constraints.py` + `config/allergens.yaml` | Three-state allergen / exclusion engine with evidence lines and per-canon cache |
| `search.py` | FTS5 BM25 over title + normalized ingredients (title 5×); hard filters applied in code afterwards |
| `stats.py` | Aggregates over the full filtered corpus (bypass search); SQL printed in the receipt |
| `match.py` | Candidates → hard filters → matched/missing/coverage → lexicographic key → code-written "why ranked here" |
| `substitute.py` + `config/roles.yaml` | Tier 1: cohort, mined candidates, evidence grades, code-applied edit; fully deterministic |
| `substitute_draft.py` | Tier 2: LLM drafts revised steps; a code validator checks them; unvalidated text is never returned |
| `planner.py`, `state.py`, `orchestrator.py` | Text → typed Plan (temperature 0, structured output); persistent state; tool routing and fallbacks |
| `verifier.py`, `receipt.py`, `writer.py` | Grounding checks, receipts, constrained prose |
| `llm.py` | Gemini client: disk cache, backoff on 429/5xx, pacing, fallback model, request budget |
| `app.py`, `recipebot/cli.py` | Streamlit UI (receipt + evidence expanders, sidebar state) and CLI |

<details><summary><b>Ingestion, normalization and steps</b></summary>

**Ingestion and validity.** The three raw JSON files (dicts keyed by original id) are loaded row by row. Original fields (title, ingredients list, instructions, picture link) are stored exactly as downloaded; all cleaning happens in derived columns and at display time. A recipe is **valid** when the title is non-blank, it has at least one clean ingredient line, and its instructions contain a letter after removing the literal `ADVERTISEMENT` token. Invalid records are kept with a machine-readable reason (`no_title,no_ingredients,...`) and excluded from every denominator; receipts show both numbers. Source SHA-256 hashes, the config hash and per-source field profiles are recorded in the `meta` table, so any database is self-describing.

**Normalization.** `normalize.py` turns `1/2 cup (120 g) chopped onion, divided` into `{canon: "onion"}` and `2 cups garlic powder` into `{canon: "garlic powder", forms: [...]}`. Pipeline: HTML-unescape → lowercase → drop parentheticals (balanced or not) → strip leading quantity (fractions, unicode fractions, ranges, "one") and unit → cut at commas and prep clauses ("for garnish", "to taste", "plus more") → handle "or" alternatives (first becomes canon, rest in `alts`) → drop prep words → alias map → singularize → edge-word trim → exact aliases → split multi-item lines ("salt and pepper" becomes two rows). Matching is **form-aware** at query time: scallion = green onion (aliases), but garlic powder ≠ garlic, butter ≠ peanut butter, eggplant ≠ egg, cream ≠ cream cheese (`forms.yaml` `distinct_pairs`); the mode is stated in every receipt. Quantities are parsed only when unambiguous (number + known unit); everything else gets `qty=NULL` rather than a guess.

**Steps.** Instruction text is cleaned (`ADVERTISEMENT`, blank lines, bare numbering like "2.") and split into newline blocks. Primary rule: **blocks if ≥ 2** (86.9% of recipes; ar 85.1%, epi 99.9%, fn 82.5%), otherwise the sentence count (abbreviation-safe splitter). The alternate rule (always sentences) is stored in `n_steps_alt` and shown beside the primary count in `rank_steps`. Step counts are labelled *estimated* everywhere.
</details>

<details><summary><b>Constraints, retrieval, stats and matching</b></summary>

**Constraints (`constraints.py`).** Each restriction key (dairy, egg, peanut, tree_nut, gluten, shellfish, soy, pork, beef, alcohol, vegetarian) has three token lists in `config/allergens.yaml`: `definite` → `contains`; `may_contain` → `possible` (margarine, chocolate, "natural flavors", broths...); `exceptions` / `global_exceptions` → a covering exception cancels a hit ("coconut milk" covers "milk"; "peanut oil" *downgrades* a covered "peanut" hit to `possible`; "oyster mushroom" is not shellfish; "butter lettuce" is not butter). A hit only in an "or" alternative ("butter or margarine") is `possible`, never `contains`. `check_all` returns per-restriction verdicts plus the worst state; a cached `Checker` makes bulk filtering of thousands of recipes fast with identical semantics. Free-form aliases ("lactose" → dairy, "vegan" → vegetarian + dairy + egg, "no peanuts" → peanut) resolve with explicit rejection of unknown keys, never silently ignored.

**Retrieval (`search.py`).** FTS5 BM25 over title (weight 5×) and normalized ingredient names with porter stemming. The query runs as AND first and widens to OR if that yields fewer hits than requested (stated in the receipt). Candidate cap 300 (1000 when filters are active). Include, exclude, restrictions (3-state) and max steps are then applied **in code**, so ranking can never override a constraint; the receipt reports how many candidates each filter dropped. `possible` recipes go to a separate *Uncertain* list with evidence lines. Ties break by id. Vector search is deliberately not built: BM25 alone is reproducible, fast to build and easy to explain. `get_recipe` powers `/show` and the UI evidence panels with the untouched original text.

**Stats (`stats.py`).** One entry point, `run_stats(spec)`, over the **full filtered corpus**; aggregates never run over search results, so "how many recipes contain X" is a property of the dataset, not of a retrieval window. Candidate ids come from a SQL prefilter plus form-aware matching in Python; the SQL is printed in the receipt. Ops: `count`, `percentage` (of all valid recipes or of a sub-denominator via `--of-all`), `top_ingredients` (once per recipe, canon-level, staples skippable), `ingredient_count_summary` (mean, median, min, max), `rank_steps` (ties by id, with a tie note when several recipes share the boundary value). The denominator and the validity definition are part of every receipt.

**Matching (`match.py`).** Candidates are every valid recipe sharing at least one non-staple canon with your list (inverted-index style `LIKE` + form-aware match, including "or" alternatives). Each is hard-filtered (exclude / restrictions 3-state / max steps) and scored: `matched` = required canon items covered by your list, `missing` = the rest (staples such as water, salt, black pepper are assumed available and shown in the receipt; `--no-staples` turns that off). A recipe must use at least `min_matched` of your ingredients (default `min(2, |available|)`; recipes below the bar are counted in the receipt). Ranking is a lexicographic key from your preferences (default: most matched → fewest missing → fewest steps → id), and each row carries a one-line **"why ranked here"** computed by code from the key comparison with its neighbour. With quantities and units, sufficiency is compared only within the same unit family (mass→grams, volume→millilitres, named piece units only against themselves); otherwise "name-level match; quantity sufficiency not verified". No eligible recipe → explicit `NO_MATCH` with the exact constraint list, plus separately labelled near-misses.
</details>

<details><summary><b>The LLM layer</b></summary>

- **Planner** (`planner.py`): Gemini structured output into a Pydantic `Plan{intent, tool_args, ops, new_topic, needs_clarification}` at temperature 0. Intents: `search`, `stats`, `match`, `substitute`, `recipe_detail`, `followup_refine`, `chat`, `out_of_scope`. It sees the current state summary and the last four turns and only *proposes* ops.
- **State** (`state.py`): ops (`set` / `add` / `remove` / `clear` on dish, include, exclude, restrictions, max steps, available, preferences, focus) are applied by deterministic code that never fails silently: unrecognized ingredients and unknown restrictions become user-visible notes, include/exclude clashes are resolved with a note.
- **Writer** (`writer.py`): 1–3 sentences summarizing the code-built result, told to use only the JSON payload and never to claim safety.
- **Verifier** (`verifier.py`): regex checks that ids ⊆ result ids, numbers ⊆ result/receipt numbers (rounding to prose precision allowed) and no banned claims. One repair attempt, then the fallback.
- **Client** (`llm.py`): disk cache keyed by sha256(model | system | prompt | schema), exponential backoff with jitter on 429/5xx, hard timeout, optional pacing, one-shot fallback model and a hard request budget. Failures are classified (`LLMUnavailable`, `LLMBadOutput`) so callers fall back gracefully.
</details>

### A real receipt
From the recorded transcript `eval/conversations/02_garlic_onion_percent.md`, answering *"How many recipes contain both garlic and onion, and what percentage of all recipes is that?"*:
```text
16,319 of 122,918 = 13.28%

--- RECEIPT ---
tool: stats.percentage
filters: contains ALL of: garlic, onion
dataset: 122,918 valid of 125,164 records (2,246 invalid, excluded)
analyzed: 122,918
denominator: 122,918 (all valid recipes)
formula: percentage = 100 * matching / denominator
normalization: form-aware token-sequence match on normalized names (aliases, singular forms);
  e.g. garlic powder is not counted as garlic; 'garlic' excludes items with: bread, chive,
  flake, oil, paste, powder...; 'onion' excludes items with: dip, flake, green, juice, powder, ring...
step rule: estimated instruction steps: newline-separated blocks if >=2 blocks, else sentences
  (ADVERTISEMENT/bare numbering removed; recipebot/steps.py)
valid = title non-blank AND >=1 clean ingredient line AND >=1 instruction step
duplicates: near-duplicate recipes (same title + ingredients, mostly across sources) are NOT removed;
  see docs/DATA_AUDIT.md section 4
sql: SELECT id FROM recipes WHERE is_valid=1
sql: SELECT i.recipe_id, i.canon, i.forms, i.alts FROM ingredients i JOIN recipes r ON r.id=i.recipe_id
     WHERE r.is_valid=1 AND i.canon LIKE '%garlic%'  -- then form-aware match in Python
sql: SELECT i.recipe_id, i.canon, i.forms, i.alts FROM ingredients i JOIN recipes r ON r.id=i.recipe_id
     WHERE r.is_valid=1 AND i.canon LIKE '%onion%'   -- then form-aware match in Python
```
Anyone with the dataset can re-run those queries and get 16,319 and 13.28%, and `eval/reference.py` does exactly that independently on every evaluation run.

## Ingredient substitution (in depth)
The most judgement-heavy task, designed so the LLM cannot invent evidence. Tier 1 is deterministic code (`substitute.py`); thresholds live in `config/roles.yaml`.

1. **Locate** the target lines with the form-aware matcher. If it appears only as an "or" alternative, no substitution is needed; if the recipe lacks it, say so. A line holding several ingredients ("salt and pepper") is never auto-edited, only flagged for manual editing.
2. **Role lookup** from `config/roles.yaml` (26 entries: egg, butter, milk, cream, flour, sugar, oil, yogurt, cheese...). Example: egg → binder, moisture, leavening, richness. Roles are configuration, not LLM guesses; an unknown target is immediately `insufficient` with an explicit "I will not guess" refusal.
3. **Cohort:** valid recipes (excluding the source) whose title shares ≥ 60% of the dish tokens (same-dish, ingredient Jaccard ≥ 0.20) or matches a dish-class word such as bread, cake, pasta, cookie (stricter: Jaccard ≥ 0.35), capped at the 500 most similar. Split into `C_with` (contain the target) and `C_without`; composition is printed in the receipt.
4. **Candidates** come only from the target's `can_fill` list (the role-compatibility gate); the **dataset** decides support. For each candidate x: `share_without` = fraction of `C_without` using x, `share_with` = same over `C_with`, `lift` = share_without / max(share_with, 0.05). Kept only if used in ≥ 2 recipes without the target and lift ≥ 1.5, so ingredients common in *all* recipes (milk, salt) drop out and are named as "common ingredients, not replacements". Candidates already in the recipe are skipped (and listed); candidates blocked by the user's restrictions are quarantined, never proposed; `possible` ones go to an uncertain list.
5. **Grade** by rule, with the reason spelled out: `strong` (leader, share ≥ 25%, lift ≥ 2.0, support ≥ 5, runner-up ≤ 0.70× leader) / `moderate` (share ≥ 15%, lift ≥ 1.5, support ≥ 2) / `weak` / `conflicting` (top two within 20% relative) / `indirect` (cohort < 8 without, < 4 same-dish without, or < 3 with so lift is unreliable) / `insufficient` (< 3 without → refuse). **Omitting** the ingredient is evaluated as a candidate too (at most `moderate`, chosen only when nothing else qualifies).
6. **Edit in code.** The removed line, the new line and the updated list come from the evidence, never the LLM. By default no amount is written into the edited line; the cohort's typical amount (median when ≥ 3 similar recipes give one in the same unit) is shown as information with a "not comparable to the removed line; set the quantity yourself" note. Before/after constraint checks run on the full edited list; conflicts remaining in *other* lines are reported as `residual`, not hidden.
7. **Draft (optional, Tier 2, `substitute_draft.py`).** The LLM may only reword the original steps around the edited list. A code validator rejects any draft that mentions an ingredient outside the edited list (dataset-vocabulary n-gram check), re-mentions the removed ingredient outside an "omitted / replaced / without" context, introduces a number not in the original steps or edited list, exceeds +2 steps / 400 characters per step / 2 cautions of ≤ 30 words, or makes a banned claim ("safe", "identical", "foolproof", "guaranteed"...). One repair attempt; then the draft is dropped and only dataset evidence is shown. Whatever survives is labelled by code as **prediction (not verified)**.
8. **Output** always ends with the receipt and the disclaimer: *dataset evidence about similar recipes, not a tested conversion; not medical advice; labels and cross-contamination not verified.*

A real example from `eval/conversations/05_banana_bread_substitution.md` ("Replace the eggs in the first one", Banana Banana Bread):
```text
cohort: 118 similar recipes (108 contain egg, 10 do not; 96 same-dish, 22 same-class related)
EVIDENCE GRADE: moderate  -- 4/10 without vs 15/108 with (lift 2.9); below the strong thresholds or margin
candidates (dataset-mined, role-compatible; n/10 recipes WITHOUT egg use it | n/108 WITH it | lift):
  1. buttermilk   4/10 = 40% | 15/108 = 13.9% | lift 2.88  [moderate]
       ids: fn:54fIX.3BAEv6ldUvjuy26bUDml2ljeG, ar:NDPVLC5JKV1rT1BciAqLCUl.sTnsydG, ...
not offered (already in this recipe): banana, baking soda

RESULT: buttermilk (evidence grade moderate)
  line 5: replace '2 eggs, beaten' -> 'buttermilk'
    [amount NOT inserted: similar recipes typically use 1 5/8 cup (median of 4),
     but that is not comparable to the removed line; set the quantity yourself]

UPDATED INGREDIENTS (edit applied by code):
   1. 2 cups all-purpose flour
   ...
   6. buttermilk   <- changed
   7. 2 1/3 cups mashed overripe bananas
```
`--use buttermilk` forces a choice from the mined options; anything the dataset does not support is refused, and a candidate that violates a stated restriction returns `BLOCKED` with the evidence.

## Conversation state
`ConversationState` persists across turns and is visible in the UI sidebar and `/state`. **Restrictions and exclusions persist** until explicitly removed ("I can eat dairy now"; the LLM is told never to clear them on its own). **A new dish topic** resets the dish query, include list and last results but keeps restrictions and exclusions, enforced by code whatever the planner says. **Ordinal references** ("the second one", "#3", "that recipe") are resolved by code from the last result ids, never by the LLM. **Every state mutation is reported** with user-visible notes.

## Evaluation
`python -m eval.run_eval` (offline by default) writes `EVAL_REPORT.md` plus `eval/results.json` and exits non-zero on any failure, hard-constraint violation or hallucinated id. 30 golden cases: 10 stats, 6 search, 5 matching, 5 substitution, 4 multi-turn chat.
- **Stats exactness:** compared with `eval/reference.py`, which re-parses the original records in plain Python (validity recomputed, not read from `is_valid`) and never uses the ingredients table, SQL filters, `stats.py`, `search.py`, `match.py` or `substitute.py`.
- **Row-level hard-constraint audit:** every returned search / match row is re-checked with `constraints.check` on freshly parsed originals: zero `contains` in the main list, `possible` only in the Uncertain list, include/exclude/step filters hold, every cited id exists.
- **Substitution invariants:** every evidence id exists, lacks the target and uses the candidate; no proposed candidate violates a stated restriction; no edit when the grade is `insufficient` or `conflicting`; abstentions return no edited list; predictions are labelled. The grade is *reported*, never asserted.
- **Mutation tests** (`tests/test_eval.py`) prove the harness catches a wrong count, a dairy leak and a fake id: the evaluator is tested, not just the system.
- **One-shot baseline:** `python -m eval.baseline_oneshot --n 6` asks Gemini the same scalar stats questions with no tools; answers are cached in `eval/baseline_cache.json` (reruns are free, nothing fabricated) and `--baseline` makes the report compare them with the independent truth, quoting one wrong baseline answer verbatim next to the system's receipt-backed answer.
- **`--llm`** adds the four multi-turn chat cases through the real planner (cached); `python -m eval.make_transcripts` records the demo conversations. Substitution cases pick their recipe by *selector* (first valid "banana bread AND contains egg", with fallbacks), so they skip gracefully on small sample DBs instead of failing.

## Configuration
All behaviour-critical numbers live in small YAML files, editable without touching code. Regenerate docs with `python -m scripts.audit` (`docs/DATA_AUDIT.md`) and `python -m scripts.gen_interfaces` (`docs/INTERFACES.md`).

| File | Contents |
|---|---|
| `config/aliases.yaml` | Pre-aliases (protect phrases containing prep words), aliases (scallion → green onion), exact aliases (pepper → black pepper), split aliases ("salt and pepper" → two rows) |
| `config/forms.yaml` | Canon forms (powder, paste, sauce...), soft forms (ground, canned...), prep words, multi-word drop phrases, edge words, shared heads ("olive or vegetable oil" → "olive oil"), `distinct_pairs` |
| `config/allergens.yaml` | 11 restriction families (definite / may_contain / exceptions / global_exceptions) plus free-text aliases (vegan, lactose, celiac...) |
| `config/units.yaml` | Unit families (mass base g, volume base ml, piece, length), conversion factors, aliases, size words |
| `config/staples.yaml` | Assumed-available pantry items (water, salt, black pepper) and UI toggles |
| `config/roles.yaml` | Every substitution threshold: cohort rules, candidate support/lift, all grade rules, omission policy, amount policy and the Tier-2 draft validator limits |

## The data
Profiled by `scripts/audit.py` into `docs/DATA_AUDIT.md` (full build):

| Source | File | Records | Valid | % valid |
|---|---|---|---|---|
| AllRecipes (ar) | `recipes_raw_nosource_ar.json` | 39,802 | 39,522 | 99.3% |
| Epicurious (epi) | `recipes_raw_nosource_epi.json` | 25,323 | 25,260 | 99.8% |
| Food Network (fn) | `recipes_raw_nosource_fn.json` | 60,039 | 58,136 | 96.8% |
| **All** | | **125,164** | **122,918** | 98.2% |

Quirks the system states rather than hides: **361,292 embedded `ADVERTISEMENT` strings** in AllRecipes lines (stripped only in derived columns and on display; originals untouched); **1,627 near-duplicates (1.3%)** in 1,523 groups, deliberately kept and noted in every receipt; **86.9% newline-block vs 12.6% single-paragraph instructions**, which is why the step rule is adaptive; tagged ingredient-line oddities (URLs, HTML entities, header-like lines, unbalanced parentheses, "or" alternatives in 49,373 distinct lines) that drove the normalization design. The dataset is *Recipe Box* by Eight Portions (https://eightportions.com/datasets/Recipes/), fetched by script and **not redistributed** (no clear license); raw data and built DB are git-ignored.

## Design decisions
- **Code computes, LLM phrases:** LLM counting is plausible-looking and wrong; here it is SQL, with a receipt as proof and an independent recomputation as the check.
- **BM25 only (no vector index):** reproducible, fast to build, easy to explain; hard filters run in code after retrieval either way. Embeddings are an optional extra and not built.
- **Refuse before fabricate:** missing data, thin cohorts and unknown roles produce explicit refusals with counts.
- **Fail soft:** LLM down, quota exhausted or invalid JSON never breaks a turn; the writer failure path still shows the full table and receipt.
- **Config over code:** aliases, forms, allergen families and *every* substitution threshold are YAML, reviewable and tunable without touching logic.
- **Originals are sacred:** noise is stripped in derived columns and on display; stored recipe text round-trips byte-identically, which the tests verify.
- **No external search:** everything shown comes from the dataset; substitution refuses any replacement the mined evidence does not support (`--use` can only pick from mined candidates).

## Known limitations
- **Gemini free tier** is small (about 20 requests per model per day); replies are cached, `RECIPEBOT_WRITER=off` halves calls per turn and a fallback model can absorb quota errors, but the free tier stays the ceiling for live chat.
- **Data coverage:** no nutrition, cook-time or allergen-label data, so the bot says so instead of guessing. About 1.3% near-duplicates kept. English only; images not used.
- **Estimates:** step counts are heuristic (both rules shown). Quantities compared only within a unit family. Matching is name-level by default (a recipe must use at least `min(2, |your list|)` of your ingredients; single-ingredient lists use a floor of 1).
- **Substitution evidence describes similar recipes**, not a tested conversion; typical amounts are shown but not inserted; allergen cross-contamination is not verified. Not medical advice.
- **Small cohorts** yield more `indirect` / `insufficient` grades by design (a 20k sample shrinks cohorts ~6×); thresholds were set on the full dataset and are editable in `config/roles.yaml`.
- **Verifier strictness:** prose is regex-checked, so a failing LLM sentence is dropped for the code-rendered table, occasionally losing a fluent sentence in exchange for guaranteed grounding.

## Repository layout
```
app.py            Streamlit UI                 recipebot/   engine (see module table)
config/           aliases, forms, allergens,   scripts/     download_data, build_db, build_fts, audit,
                  roles, units, staples                     gen_interfaces, top_canon, chat_script, llm_probe
eval/             golden.yaml, reference.py,   tests/       offline suite (mock LLM) + real-data cross-checks
                  run_eval.py, baseline_oneshot.py, make_transcripts.py, conversations/
docs/             ARCHITECTURE, INTERFACES, DATA_AUDIT, BUILD_PLAN, process/
EVAL_REPORT.md    generated report             PROGRESS.md  build log
```
Full design narrative: `docs/ARCHITECTURE.md`. Module contracts: `docs/INTERFACES.md`. Data profile: `docs/DATA_AUDIT.md`.

## Hard problems and how they were solved
The non-obvious problems in this project, each with the failure it prevents and the fix.

| Problem | Why it is hard | Solution |
|---|---|---|
| **LLMs cannot be trusted with numbers or safety claims** | A fluent "about 40,000 recipes" or "this is safe for your allergy" is plausible and unverifiable | LLM restricted to planning and phrasing; every number is SQL; a verifier checks ids, numbers and banned claims on all prose; failures fall back to the code-rendered answer |
| **Counting over a retrieval window gives wrong answers** | Search returns the top few hundred hits, so "how many recipes contain X" would silently depend on ranking | Aggregates bypass search and run over the full filtered corpus; the receipt prints the denominator definition and the SQL; verified against an independent recomputation (10/10 exact) |
| **Naive ingredient matching is wrong in both directions** | "garlic" matches garlic powder and "peanut" matches peanut oil; "egg" matches eggplant; "butter" matches peanut butter and butter lettuce | Form-aware matching (`distinct_pairs`, canon forms), exception lists, and a three-state allergen verdict where uncertain cases (`possible`) are quarantined instead of passed or blocked silently |
| **Dirty source data** | 361,292 embedded `ADVERTISEMENT` strings, ingredient lines with HTML entities, URLs, unbalanced parentheses and "or" alternatives (49,373 distinct lines), 2,246 invalid records, 1.3% duplicates | Originals stored untouched; cleaning only in derived columns; explicit validity rule with recorded reasons; duplicates kept but disclosed in every receipt |
| **No reliable step count** | 12.6% of recipes are one paragraph, the rest are newline blocks | Adaptive rule (blocks if at least 2, else sentences); both counts stored and shown; always labelled "estimated" |
| **Substitution without inventing evidence** | An LLM will happily suggest a plausible swap; common ingredients (milk, salt) look "supported" because they are in everything | Roles come from config, candidates are mined from similar recipes that do not use the target, ranked by lift against recipes that do; evidence graded by rule; an unknown role or a thin cohort refuses with counts |
| **LLM-drafted steps can reintroduce what was removed** | A rewritten step may mention the removed ingredient, add an unlisted one, or invent times and temperatures | Code validator checks every ingredient mention against the edited list, rejects new numbers and unsafe claims, allows one repair, otherwise returns evidence only; survivors are labelled "prediction (not verified)" |
| **Conversational state drifts** | "Also no mushrooms" or "the second one" can be mis-resolved or can silently drop an allergy | Typed plan, state ops applied by deterministic code, restrictions persist until explicitly removed, ordinal references resolved from stored result ids, every mutation reported |
| **Evaluating without trusting the system** | Tests that reuse the system's own code prove nothing | Independent reference implementation; row-level re-audit of every returned recipe; mutation tests showing the evaluator catches a wrong count, a dairy leak and a fake id |

## Ownership and AI use
RecipeBot was designed and directed by **Aditya Kadam**: the scope, the evidence-before-generation architecture, the three-state constraint and refusal rules, and the acceptance criteria were set by the owner up front. Implementation was done with AI coding assistance (Claude), working task by task against that specification, and Gemini (google-genai, free tier) is the runtime LLM. The owner reviewed the output, ran every test suite and the evaluation on the full dataset (122,918 valid recipes), and relied on checks that do not depend on the AI that wrote the code: the independent recomputation in `eval/reference.py` and `tests/test_stats_crosscheck.py`, and the mutation tests that prove the evaluator catches errors.

Integration issues found and resolved during validation on the full dataset:
- **Spec/code drift caught by an audit.** A line-by-line audit of this README against `config/roles.yaml`, the code, `EVAL_REPORT.md` and the recorded transcripts found documentation claims that did not match the code (a non-existent `RECIPEBOT_DRAFT` switch, an allergen-exception example that was really a tokenization rule, the real-data test count of 7 passing and 2 skipped). The README was corrected to match the code, never the reverse.
- **Small-sample evaluation gaps.** On a 16% sample DB the substitution cases could not find their recipes and the evidence cohorts were about 6x smaller, so thresholds are validated only on the full DB and the golden cases choose recipes by selector with fallbacks and skip (rather than fail) when none exists.
- **Integration breakages.** A merge that left out `app.py` broke test collection, and a stray `tests/__init__.py` experiment made imports worse. Both were traced and reverted; the suite is back to 282 passing.
- **Free-tier LLM quota.** Quota exhaustion mid-project forced the baseline answers and demo transcripts to be recorded once and cached (`eval/baseline_cache.json`, `eval/conversations/`) and is why every LLM-dependent path has a code-only fallback.
- **Stale generated docs.** `docs/INTERFACES.md` was found to lag the substitution modules and is regenerated with `python -m scripts.gen_interfaces`.