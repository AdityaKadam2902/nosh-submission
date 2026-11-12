# WORKSTREAMS: parallel plan (deadline ~2026-11-13)

## Ownership (avoids merge conflicts)
| Chat | Scope | OWNS (may create/edit) | Must NOT edit |
|---|---|---|---|
| **A: M5 substitution (T3, 40%)** | substitute.py engine, roles.yaml, /sub, planner+orchestrator wiring for intent `substitute` | `recipebot/substitute.py`, `config/roles.yaml`, `tests/test_substitute.py`, and ONLY these hunks: `orchestrator.py` (`_run_substitute`, NOT_YET), `planner.py` (substitute prompt/examples), `cli.py` (/sub), `state.py` (only if needed) | everything else |
| **B: M6 eval** | golden set, baseline one-shot, runner, report, transcripts | `eval/**`, `tests/test_eval.py`, `Makefile` target is irrelevant (no make) | `recipebot/**` (report bugs as ISSUES) |
| **C: M7 UI + README** | Streamlit app, README, docs polish | `app.py`, `README.md`, `docs/*.md` (not INTERFACES/ARCHITECTURE), `.streamlit/**`, `tests/test_app.py` | `recipebot/**` |
| **Owner (+ integrator chat)** | merge zips, run tests, live Gemini verification, M8 clean-clone, video, submit | everything at merge time | |

## Timeline (hours from launch; submit with 4 h spare)
- **H0:** owner applies `recipebot_m4.zip`, runs pytest, builds sample DB (below), launches A, B, C with their prompts.
- **H0-H5:** A builds M5 Tier 1 (deterministic evidence). B builds golden.yaml (T1+T2 cases now, T3 later) + baseline + runner. C builds app.py + README skeleton.
- **H5:** MERGE 1 (A Tier 1 + B + C). Run tests. Owner runs real-data checks.
- **H5-H9:** A adds Tier 2 (LLM draft + validator) + wiring. B adds T3 cases + report + transcripts. C finishes README (decisions, limits, AI-tools disclosure).
- **H9:** MERGE 2. Full `pytest -q`. Owner runs `eval` once with LLM quota available (or billing).
- **H9-H13:** M8: clean-clone test, remove secrets, public repo, video (3-5 min). **Buffer: last 4 h.**
If behind: ship CLI + README + eval; skip Streamlit polish; ship M5 Tier 1 only.

## Sample DB (give each chat realistic data; the full DB is too big)
```
python -m scripts.build_db --sample 20000 --db data\sample.db
```
Attach `data\sample.db` (and the source zip) to each chat. Chats run with `DB_PATH=<path to sample.db>`. Real-data numbers are verified by the owner locally.

## Attach to every chat
`HANDOFF.md`, this file (only the chat's own brief is needed), `docs/ARCHITECTURE.md`, `docs/INTERFACES.md`, `recipebot_src.zip` (current source + config + tests), `data\sample.db`.

---
## BRIEF A: M5 Substitution engine (T3, weight 40%, the most valuable remaining work)
Spec: ARCHITECTURE §9 + BUILD_PLAN M5. Principle: *evidence before generation*: substitution suggestions are mined from the dataset (how other recipes in the same role replace/omit the ingredient), graded honestly, and the LLM never invents substitutions or counts.
**Tier 1 (MUST, deterministic, no LLM):**
1. `config/roles.yaml`: roles + `can_fill` + thresholds for ~25 common ingredients (egg, butter, milk, cream, flour, sugar, oil, yogurt, cheese, sour cream, buttermilk, honey, baking powder, breadcrumbs...), incl. evidence-grade thresholds (min cohort size etc.).
2. `recipebot/substitute.py`: `substitute(recipe_id, target, constraints=None, conn=None) -> dict` implementing steps 1-5: resolve recipe + target line (form-aware via `normalize.matcher`); build the COHORT (similar recipes: same dish type via title/ingredient overlap) from the DB; for each candidate replacement (or omission) count in the cohort how often recipes that lack the target use X instead; compute evidence grades `strong | moderate | weak | conflicting | indirect | insufficient` with counts + recipe IDS; apply user restrictions with `constraints.check` (a candidate violating a stated allergy is BLOCKED, `possible` goes to uncertain); output updated ingredient list with the edit applied BY CODE; receipt via `receipt.make_receipt`.
3. Refusals: `insufficient` evidence => refuse and say why with counts; `conflicting`/`indirect` reported honestly.
4. `/sub <recipe-id|row> --replace egg [--restrict dairy]` in cli.py; planner intent `substitute` (state field `focus_recipe_id`; ordinals resolve via `state.resolve_reference`); orchestrator `_run_substitute` (+ remove `substitute` from NOT_YET).
5. Tests (`tests/test_substitute.py`) on a FIXED mini-DB fixture (see tests/test_match.py for the pattern): banana-bread-minus-eggs graded evidence with counts + ids; cream -> dairy-free in a pasta recipe; one conflicting/indirect case; one insufficient case refuses; request violating a stated allergy is blocked.
**Tier 2 (if time):** LLM drafts revised steps from the code-produced edit list (`llm.generate_json`, mock in tests), a validator checks that the draft only uses ingredients present in the edited list and flags unsupported claims, labelled "prediction", never as dataset evidence.
**Acceptance (BUILD_PLAN):** banana bread minus eggs -> graded evidence (counts + IDs) + updated list + labelled predictions; cream -> dairy-free in a pasta recipe; one conflicting/indirect case; one insufficient case refuses; allergy-violating request blocked. Verify: `pytest tests/test_substitute.py` + full offline suite.

## BRIEF B: M6 Evaluation harness
Spec: ARCHITECTURE §13 + BUILD_PLAN M6. Build `eval/golden.yaml` (~30 cases across T1/T2/T3, each with expected checks computed from CODE paths, not hand-typed numbers where avoidable), `eval/baseline_oneshot.py` (a naive "ask Gemini directly" baseline), `eval/run_eval.py`, auto-generated `EVAL_REPORT.md` (system-vs-baseline table; >=1 verbatim wrong one-shot answer next to the system's correct handling; failures section with causes), and 5 saved transcripts in `eval/conversations/` (use `scripts/chat_script.py`). Metrics: hard-constraint violations = 0, hallucinated ids = 0, numeric correctness vs code recomputation.
**Quota-aware design (important):** Gemini free tier ~20 requests/model/day. Make the runner support `--tools-only` (call search/stats/match/substitute directly, zero LLM calls), `--llm` (planner end-to-end, cached), and a baseline mode that samples N cases and caches every reply so reruns are free. T3 cases are added after Chat A's merge (stub them as `skip` until `recipebot/substitute.py` exists).
**Acceptance:** `python -m eval.run_eval --tools-only` regenerates `EVAL_REPORT.md` offline; report contains the table, a wrong one-shot example (may be pre-recorded fixtures if quota is out, clearly labelled), and a failures section.

## BRIEF C: M7 Streamlit UI + README
Spec: BUILD_PLAN M7. `app.py`: Streamlit chat using `Orchestrator.turn()` (see docs/INTERFACES.md: `TurnResult.text/ids/intent/...`), evidence expander per cited id showing ORIGINAL recipe text via `search.get_recipe` (display may strip the literal `ADVERTISEMENT`), sidebar showing `state_summary`/restrictions with a reset button, graceful behaviour when the LLM is down (slash commands via `cli.handle` still work). `README.md` (<= 1 page quickstart: fresh clone -> 5 commands -> working chat) plus decisions: retrieval, normalization, ranking, computation, uncertainty, external search + AI-tools disclosure + known limitations. Windows-friendly commands.
**Acceptance:** `streamlit run app.py` works against `data/recipes.db`; fresh-clone steps verified by the owner (M8).

---
## START PROMPTS (copy one per new chat; attach the files listed above)
**A:** "You are a senior engineer on a 24-hour take-home (NOSH Robotics, GenAI Intern). Read HANDOFF.md, WORKSTREAMS.md (BRIEF A and the ownership table), docs/ARCHITECTURE.md (§9, §5, §10), docs/INTERFACES.md. The code is in recipebot_src.zip (unzip; tests run with `python -m pytest -q -k "not real"`); sample data in data/sample.db (set DB_PATH). Do BRIEF A, Tier 1 first, then return: a zip of new/changed files (repo-relative paths), minimal patches for existing files, an updated PROGRESS.md block, exact verify commands, and an ISSUES list. Be terse; do not redesign; do not edit files you do not own."
**B:** same preamble, "Do BRIEF B ... never call the real LLM in tests."
**C:** same preamble, "Do BRIEF C ..."
**Integrator (this chat or a fresh one):** "Merge the zip from chat X into the repo, run the offline suite, report failures with the last 30 lines."

## Merge checklist (owner, each time)
1. `Expand-Archive -Force <zip> "D:\Nosh Submission"` 2. `python -m pytest -q -k "not real"` green 3. `git add -A; git commit -m "<chat>: <what>"` 4. paste any ISSUES to the owning chat 5. regenerate `python -m scripts.gen_interfaces` and re-attach `docs/INTERFACES.md` to chats that start later.
