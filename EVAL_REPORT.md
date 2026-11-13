# EVAL REPORT
_generated 2026-11-13 12:35 by `python -m eval.run_eval --tools-only`; DB `data\recipes.db`: 122,918 valid of 125,164 records._

## Summary
| metric | result | target |
|---|---|---|
| cases run / pass / fail / skipped | 26 / 26 / 0 / 4 | no fails |
| stats exactness vs independent recomputation | 10/10 | all |
| hard-constraint violations (rows audited with constraints.check on re-parsed originals) | 0 | 0 |
| hallucinated recipe ids (230 ids checked against the DB) | 0 | 0 |
| abstention correctness (T04 insufficient, T05 forced violation, M03 no-match) | 3/3 | all |
| evidence-citation coverage (T3 candidates with >=1 supporting id) | 6/6 | all |

## Cases
| id | task | kind | result | why |
|---|---|---|---|---|
| S01 | T1 | stats | PASS | system == independent recomputation |
| S02 | T1 | stats | PASS | system == independent recomputation |
| S03 | T1 | stats | PASS | system == independent recomputation |
| S04 | T1 | stats | PASS | system == independent recomputation |
| S05 | T1 | stats | PASS | system == independent recomputation |
| S06 | T1 | stats | PASS | system == independent recomputation |
| S07 | T1 | stats | PASS | system == independent recomputation |
| S08 | T1 | stats | PASS | system == independent recomputation |
| S09 | T1 | stats | PASS | system == independent recomputation |
| S10 | T1 | stats | PASS | system == independent recomputation |
| R01 | T1 | search | PASS | 10 main rows, 0 hard violations, 0 'possible' in main |
| R02 | T1 | search | PASS | 10 main rows, 0 hard violations, 0 'possible' in main |
| R03 | T1 | search | PASS | 10 main rows, 0 hard violations, 0 'possible' in main |
| R04 | T1 | search | PASS | 10 main rows, 0 hard violations, 0 'possible' in main |
| R05 | T1 | search | PASS | 10 main rows, 0 hard violations, 0 'possible' in main |
| R06 | T1 | search | PASS | 10 main rows, 0 hard violations, 0 'possible' in main |
| M01 | T2 | match | PASS | 10 rows, 0 hard violations |
| M02 | T2 | match | PASS | 10 rows, 0 hard violations |
| M03 | T2 | match | PASS | NO_MATCH reported with explanation |
| M04 | T2 | match | PASS | 10 rows, 0 hard violations |
| M05 | T2 | match | PASS | 10 rows, 0 hard violations |
| T01 | T3 | substitute | PASS | ar:.LVTAbd.H6F8XNOTQGLT3xw1/zp2WTK: status=ok grade=weak selected=applesauce |
| T02 | T3 | substitute | PASS | ar:.ES1BL77XWcA0uZJUyEg649Xa44hlGG: status=refused grade=conflicting (abstained) |
| T03 | T3 | substitute | PASS | ar:.1puHuHtjioOdTS3jkiNtfbqGyKpOvu: status=ok grade=indirect selected=shortening |
| T04 | T3 | substitute | PASS | ar:.7QTeYyVOOAaGYAnQUCErVmbXuRISau: status=refused grade=insufficient (abstained) |
| T05 | T3 | substitute | PASS | ar:.ES1BL77XWcA0uZJUyEg649Xa44hlGG: status=refused grade=conflicting (abstained) |
| C01 | T1 | chat | SKIP | needs --llm (planner) |
| C02 | T1 | chat | SKIP | needs --llm (planner) |
| C03 | T1 | chat | SKIP | needs --llm (planner) |
| C04 | T2 | chat | SKIP | needs --llm (planner) |

## System vs one-shot baseline (Gemini, no tools)
_Baseline not recorded in this run._ Record it once (cached afterwards): `python -m eval.baseline_oneshot --n 6`, then `python -m eval.run_eval --baseline`. No baseline answers are fabricated.

## Failures and causes
None in this run.

## Skipped
- C01: needs --llm (planner)
- C02: needs --llm (planner)
- C03: needs --llm (planner)
- C04: needs --llm (planner)

## Method
- Truth: `eval/reference.py` re-parses original records (not the ingredients table / SQL / stats.py); the golden file contains no typed expected numbers.
- Hard-constraint audit re-runs `constraints.check` on re-parsed originals for every returned row (main list must have no `contains`; `possible` only in the uncertain list).
- T3 invariants: evidence ids exist, lack the target and use the candidate; no proposed candidate violates a stated restriction; edit only when grade allows; abstentions return no edit. The grade itself is whatever the data supports (reported, not asserted).
- `--tools-only` makes zero LLM calls; `--llm` adds the multi-turn chat cases (cached).
