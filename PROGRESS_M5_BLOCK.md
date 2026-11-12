## M5 Tier 1 (chat A) - paste into PROGRESS.md
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
