"""Evaluation runner -> EVAL_REPORT.md (ARCHITECTURE §13).
  python -m eval.run_eval --tools-only           offline, zero LLM calls (search/stats/match/substitute called directly)   [default]
  python -m eval.run_eval --llm                  + multi-turn chat cases through the planner (LLM; cached in .cache/llm)
  python -m eval.run_eval --baseline             + compare with eval/baseline_cache.json (made by: python -m eval.baseline_oneshot)
Truth is recomputed by eval/reference.py or checked as invariants on tool output; no expected numbers are typed in golden.yaml."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import yaml

from eval.baseline_oneshot import judge, load_cache
from eval.reference import Reference
from recipebot.constraints import check
from recipebot.db import connect, db_path
from recipebot.normalize import canon_name, clean_ingredients, matcher
from recipebot.receipt import dataset_counts
from recipebot.verifier import ID_RE

HERE = Path(__file__).parent
ROOT = HERE.parent


class Ctx:
    def __init__(self, conn):
        self.conn, self.ref = conn, Reference(conn)
        self.all_ids = {r[0] for r in conn.execute("SELECT id FROM recipes")}
        self.counts = dataset_counts(conn)
        self.m = {"violations": 0, "hallucinated_ids": 0, "ids_checked": 0, "cand": 0, "cand_with_ids": 0}

    def ids_ok(self, ids, where: str, probs: list):
        for i in ids:
            self.m["ids_checked"] += 1
            if i not in self.all_ids:
                self.m["hallucinated_ids"] += 1
                probs.append(f"{where}: id {i} does not exist in the DB")

    def violation(self, msg: str, probs: list):
        self.m["violations"] += 1
        probs.append(msg)


def R(status, why="", detail="", cause=""):
    return {"status": status, "why": why, "detail": detail, "cause": cause}


# ------------------------------------------------------------------ stats
def _sys_stats(spec, conn):
    from recipebot.stats import run_stats
    d = run_stats(spec, conn=conn)["answer_data"]
    if spec["op"] == "top_ingredients":
        return {"items": [(x["canon"], x["recipes"]) for x in d["items"]]}, d
    if spec["op"] == "rank_steps":
        return {"items": [(x["id"], x["n_steps"]) for x in d["items"]]}, d
    return d, d


def run_stats_case(c, cx):
    got, raw = _sys_stats(c["spec"], cx.conn)
    want = cx.ref.stats(c["spec"])
    probs = []
    for k, v in want.items():
        g = got.get(k)
        same = (abs(g - v) < 1e-6) if isinstance(v, float) and g is not None else g == v
        if not same:
            probs.append(f"{k}: system={g!r} reference={v!r}")
    if c["spec"]["op"] == "rank_steps":
        cx.ids_ok([i for i, _ in got["items"]], c["id"], probs)
    if probs:
        return R("fail", "; ".join(probs)[:400], cause="stats.py/DB disagrees with the independent recomputation (normalization, filter or step-count difference)")
    n = want.get("count", want.get("n"))
    return R("pass", "system == independent recomputation", detail=f"{json.dumps({k: v for k, v in want.items() if k != 'items'}) if 'items' not in want else str(want['items'][:3])}")


# ------------------------------------------------------------------ row-level hard-constraint audit (search / match / substitute)
def audit_rows(rows, cx, probs, restrictions=(), include=(), exclude=(), max_steps=None, where=""):
    for r in rows:
        rec = cx.ref.by_id.get(r["id"])
        if rec is None:
            probs.append(f"{where}{r['id']}: not a valid recipe by independent recomputation")
            continue
        for x in restrictions:
            if check(rec["ings"], x)["state"] == "contains":
                cx.violation(f"HARD VIOLATION {r['id']}: contains '{x}' ({[e[2] for e in check(rec['ings'], x)['evidence']][:1]})", probs)
        for t in exclude:
            if cx.ref.has(rec, t):
                cx.violation(f"HARD VIOLATION {r['id']}: contains excluded '{t}'", probs)
        for t in include:
            if not cx.ref.has(rec, t):
                probs.append(f"{r['id']}: does not contain required '{t}'")
        if max_steps is not None and rec["steps"] > max_steps:
            probs.append(f"{r['id']}: {rec['steps']} steps > {max_steps}")


def run_search_case(c, cx):
    from recipebot.search import search
    a = c["args"]
    res = search(a.get("query", ""), a.get("include"), a.get("exclude"), a.get("restrictions"), a.get("max_steps"), a.get("k", 10), conn=cx.conn)
    probs = []
    cx.ids_ok([r["id"] for r in res["rows"] + res["uncertain"]], c["id"], probs)
    audit_rows(res["rows"], cx, probs, a.get("restrictions", []), a.get("include", []), a.get("exclude", []), a.get("max_steps"))
    if {r["id"] for r in res["rows"]} & {r["id"] for r in res["uncertain"]}:
        probs.append("a 'possible' recipe is also in the main list")
    for r in res["uncertain"]:  # uncertain rows must really be 'possible' (not 'contains') for some restriction
        rec = cx.ref.by_id.get(r["id"])
        if rec and any(check(rec["ings"], x)["state"] == "contains" for x in a.get("restrictions", [])):
            cx.violation(f"HARD VIOLATION {r['id']}: in the uncertain list but 'contains'", probs)
    if probs:
        return R("fail", "; ".join(probs)[:400], cause="search filter let a recipe through that the independent audit rejects")
    return R("pass", f"{len(res['rows'])} main rows, 0 hard violations, 0 'possible' in main", detail=f"{res['post_filter_count']} after filters, {res['n_uncertain']} uncertain")


def run_match_case(c, cx):
    from recipebot.match import match
    a = c["args"]
    res = match(a["available"], a.get("exclude"), a.get("restrictions"), a.get("max_steps"), a.get("preferences"), k=10, conn=cx.conn)
    probs = []
    cx.ids_ok([r["id"] for r in res["rows"] + res["uncertain"]] + [r["id"] for r in res["violating_alternatives"]], c["id"], probs)
    audit_rows(res["rows"], cx, probs, a.get("restrictions", []), (), a.get("exclude", []), a.get("max_steps"))
    if c.get("expect_no_match"):
        if not res["no_match"] or res["rows"]:
            probs.append("expected an explicit NO_MATCH (every candidate violates the restriction) but got rows")
        if res["rows"] == [] and not res["message"]:
            probs.append("no-match without an explanation")
    if probs:
        return R("fail", "; ".join(probs)[:400], cause="matching returned a violating row or failed to abstain")
    return R("pass", "NO_MATCH reported with explanation" if res["no_match"] else f"{len(res['rows'])} rows, 0 hard violations", detail=(res["message"] or "")[:120])


# ------------------------------------------------------------------ substitution (invariants; the grade is whatever the data supports)
def run_sub_case(c, cx):
    from recipebot.substitute import substitute
    hit = cx.ref.first(c["pick"])
    if hit is None:
        return R("skip", f"no recipe matches {c['pick']} in this DB (sample too small?)")
    rid, sel = hit
    res = substitute(rid, sel.get("target", c["target"]), {"restrictions": c.get("restrictions", [])}, conn=cx.conn, use=c.get("use"))
    probs, rs = [], c.get("restrictions", [])
    tm = matcher(res["target"])
    cands = res["candidates"] + res["blocked"] + res["uncertain"] + ([res["omission"]] if res.get("omission") else [])
    cx.ids_ok([rid] + [i for k in cands for i in k["support_ids"]] + res["receipt"]["recipe_ids"], c["id"], probs)
    for k in cands:
        cx.m["cand"] += 1
        cx.m["cand_with_ids"] += bool(k["support_ids"])
        cm = [matcher(n) for n in [k["name"]] + list(k.get("variants", []))]
        for i in k["support_ids"]:
            rec = cx.ref.by_id.get(i)
            if rec is None:
                continue
            if any(tm(d) for d in rec["ings"]):
                probs.append(f"evidence id {i} for '{k['name']}' contains the target (not a 'without' recipe)")
            if k.get("kind") != "omit" and not any(f(d) for f in cm for d in rec["ings"]):
                probs.append(f"evidence id {i} does not contain candidate '{k['name']}'")
    for k in res["candidates"]:  # proposed (allowed) candidates must pass every stated restriction
        line = clean_ingredients([k["name"]])
        for x in rs:
            if check(line, x)["state"] != "free":
                cx.violation(f"HARD VIOLATION: proposed candidate '{k['name']}' is not 'free' for {x}", probs)
    exp_s, exp_g = c.get("expect_status"), c.get("expect_grade")
    if exp_s and res["status"] not in exp_s:
        probs.append(f"status {res['status']} not in {exp_s}")
    if exp_g and res["grade"] not in exp_g:
        probs.append(f"grade {res['grade']} not in {exp_g}")
    if res["status"] == "ok":
        ed = res["edited_ingredients"] or []
        if not ed:
            probs.append("status ok without an edited ingredient list")
        if not any(e["op"] == "manual" for e in res["edits"]) and any(tm(d) for d in clean_ingredients(ed)):
            probs.append("target still present in the edited list")
        for x in rs:
            free = all(check([d for d in clean_ingredients(ed)], x)["state"] == "free" for _ in [0])
            if res["edited_meets_constraints"] and not free:
                cx.violation(f"HARD VIOLATION: system says edited list meets '{x}' but the recheck disagrees", probs)
        if res["grade"] in ("insufficient", "conflicting"):
            probs.append(f"edit proposed although grade is {res['grade']}")
    elif res["edited_ingredients"]:
        probs.append(f"status {res['status']} but an edited list was returned")
    if any(p["label"] != "prediction (not verified)" for p in res.get("predictions", [])):
        probs.append("unlabelled prediction")
    abst = res["status"] in ("refused", "blocked")
    if probs:
        return R("fail", "; ".join(probs)[:400], cause="evidence/edit invariant broken (see message)")
    co = res["cohort"]
    return R("pass", f"{rid}: status={res['status']} grade={res['grade']}" + (f" selected={res['selected']}" if res["selected"] else "") + (" (abstained)" if abst else ""),
             detail=(f"cohort {co['size']} ({co['with']} with / {co['without']} without)" if co else res["refusal"] or ""))


# ------------------------------------------------------------------ chat (LLM)
def run_chat_case(c, cx, llm_state):
    from recipebot.llm import LLM, LLMUnavailable
    from recipebot.orchestrator import Orchestrator
    llm = llm_state.setdefault("llm", LLM())
    orch = Orchestrator(llm, cx.conn)
    probs, r = [], None
    try:
        for t in c["turns"]:
            r = orch.turn(t)
            if r.llm_down:
                return R("skip", f"LLM unavailable at turn '{t}': {r.error}")
    except LLMUnavailable as e:
        return R("skip", f"LLM unavailable: {e}")
    cx.ids_ok(r.ids, c["id"], probs)
    cx.ids_ok([m.group().rstrip(".,;:)") for m in ID_RE.finditer(r.text)], c["id"] + " text", probs)
    if sorted(orch.state.restrictions) != sorted(c.get("expect_restrictions", orch.state.restrictions)):
        probs.append(f"restrictions {orch.state.restrictions} != {c['expect_restrictions']}")
    for e in c.get("expect_exclude", []):
        if e not in orch.state.exclude:
            probs.append(f"'{e}' missing from exclude {orch.state.exclude}")
    if r.intent in ("search", "match"):
        audit_rows([{"id": i} for i in r.ids], cx, probs, orch.state.restrictions, (), orch.state.exclude, orch.state.max_steps)
    for sid in ([c["expect_numbers_from"]] if isinstance(c.get("expect_numbers_from"), str) else c.get("expect_numbers_from", [])):
        sc = next(x for x in CASES if x["id"] == sid)
        w = cx.ref.stats(sc["spec"])
        if sc["spec"]["op"] == "count" and not re.search(rf"(?<![\d,.]){w['count']:,}(?![\d,])|(?<![\d,.]){w['count']}(?![\d,])", r.text):
            probs.append(f"count {w['count']:,} ({sid}) not in the answer")
        if sc["spec"]["op"] == "percentage" and w["percentage"] is not None and not any(f"{w['percentage']:.{d}f}" in r.text for d in (1, 2)):
            probs.append(f"percentage {w['percentage']:.2f} ({sid}) not in the answer")
    if c.get("expect_ids_from"):
        want = [i for i, _ in cx.ref.stats(next(x for x in CASES if x["id"] == c["expect_ids_from"])["spec"])["items"]]
        if r.ids[:len(want)] != want:
            probs.append(f"ids {r.ids[:len(want)]} != reference {want}")
    if r.fallback:
        probs.append(f"writer prose dropped by verifier ({r.problems[:2]}); code table shown instead")
    if probs:
        hard = any("HARD" in p for p in probs)
        return R("fail", "; ".join(probs)[:400], cause="planner/orchestrator result differs from code truth" + (" (hard-constraint)" if hard else ""))
    return R("pass", f"{len(c['turns'])} turn(s), intent={r.intent}, ids verified", detail=f"LLM calls so far: {llm.calls} (cache hits {llm.cache_hits})")


# ------------------------------------------------------------------ main
CASES: list[dict] = []


def run_all(db, llm: bool, only=None):
    global CASES
    CASES = yaml.safe_load((HERE / "golden.yaml").read_text(encoding="utf-8"))["cases"]
    conn = connect(db or db_path(), readonly=True)
    cx, results, st = Ctx(conn), [], {}
    for c in CASES:
        if only and c["id"] not in only:
            continue
        try:
            if c["kind"] == "chat" and not llm:
                r = R("skip", "needs --llm (planner)")
            elif c["kind"] == "chat":
                r = run_chat_case(c, cx, st)
            else:
                r = {"stats": run_stats_case, "search": run_search_case, "match": run_match_case, "substitute": run_sub_case}[c["kind"]](c, cx)
        except Exception as e:  # noqa: BLE001 - a crash is a failed case with its cause, not a dead run
            r = R("fail", f"{type(e).__name__}: {e}"[:300], cause="exception in the tool under test")
        results.append({"id": c["id"], "task": c["task"], "kind": c["kind"], "q": c.get("question") or c.get("turns") or c.get("args") or c.get("target"), **r})
    return cx, results


def baseline_rows(cx, results):
    cache, rows = load_cache(), []
    for c in CASES:
        if not c.get("baseline") or c["id"] not in cache:
            continue
        truth = cx.ref.stats(c["spec"])
        ok, got = judge(c["baseline"], truth, cache[c["id"]]["answer"])
        sysr = next((r for r in results if r["id"] == c["id"]), None)
        rows.append({"id": c["id"], "question": c["question"], "truth": truth.get(c["baseline"]), "baseline_ok": ok, "baseline_num": got, "answer": cache[c["id"]]["answer"], "model": cache[c["id"]].get("model"),
                     "system_ok": bool(sysr and sysr["status"] == "pass")})
    return rows


def report(cx, results, mode: str, db, base) -> str:
    n = lambda s: sum(r["status"] == s for r in results)
    ran = [r for r in results if r["status"] != "skip"]
    stats = [r for r in ran if r["kind"] == "stats"]
    absts = [r for r in ran if r["id"] in ("T04", "T05", "M03")]
    m = cx.m
    L = [f"# EVAL REPORT", f"_generated {dt.datetime.now():%Y-%m-%d %H:%M} by `python -m eval.run_eval {mode}`; DB `{db}`: {cx.counts['valid']:,} valid of {cx.counts['total_records']:,} records._"]
    if cx.counts["valid"] < 100000:
        L.append(f"> **Sample DB** ({cx.counts['valid']:,} valid recipes; the full set is 122,918): cohorts are smaller, so some T3 cases skip or grade lower than on the full DB.")
    L += ["", "## Summary", "| metric | result | target |", "|---|---|---|",
          f"| cases run / pass / fail / skipped | {len(ran)} / {n('pass')} / {n('fail')} / {n('skip')} | no fails |",
          f"| stats exactness vs independent recomputation | {sum(r['status']=='pass' for r in stats)}/{len(stats)} | all |",
          f"| hard-constraint violations (rows audited with constraints.check on re-parsed originals) | {m['violations']} | 0 |",
          f"| hallucinated recipe ids ({m['ids_checked']} ids checked against the DB) | {m['hallucinated_ids']} | 0 |",
          f"| abstention correctness (T04 insufficient, T05 forced violation, M03 no-match) | {sum(r['status']=='pass' for r in absts)}/{len(absts)} | all |",
          f"| evidence-citation coverage (T3 candidates with >=1 supporting id) | {m['cand_with_ids']}/{m['cand']} | all |"]
    if base:
        L.append(f"| system vs one-shot baseline (scalar stats questions) | {sum(b['system_ok'] for b in base)}/{len(base)} vs {sum(b['baseline_ok'] for b in base)}/{len(base)} | system > baseline |")
    L += ["", "## Cases", "| id | task | kind | result | why |", "|---|---|---|---|---|"]
    for r in results:
        L.append(f"| {r['id']} | {r['task']} | {r['kind']} | {r['status'].upper()} | {r['why'].replace('|', '/')[:160]} |")
    L += ["", "## System vs one-shot baseline (Gemini, no tools)"]
    if not base:
        L.append("_Baseline not recorded in this run._ Record it once (cached afterwards): `python -m eval.baseline_oneshot --n 6`, then `python -m eval.run_eval --baseline`. No baseline answers are fabricated.")
    else:
        L += ["| id | question | independent truth | one-shot answer (first number) | one-shot | system |", "|---|---|---|---|---|---|"]
        for b in base:
            L.append(f"| {b['id']} | {b['question']} | {b['truth']:g} | {b['baseline_num']} | {'ok' if b['baseline_ok'] else 'WRONG'} | {'exact' if b['system_ok'] else 'FAIL'} |")
        wrong = next((b for b in base if not b["baseline_ok"]), None)
        if wrong:
            L += ["", f"### Verbatim wrong one-shot answer ({wrong['id']}, model {wrong['model']})", f"> **Q:** {wrong['question']}", ">", "> **One-shot answer:** " + wrong["answer"].strip().replace("\n", "\n> "),
                  "", f"**System:** answers from code: independent truth = **{wrong['truth']:g}**; the system's number matches it ({'yes' if wrong['system_ok'] else 'NO: see failures'}), with receipt (filters, denominator, SQL)."]
    fails = [r for r in results if r["status"] == "fail"]
    L += ["", "## Failures and causes"]
    L += [f"- **{r['id']}**: {r['why']}\n  - cause: {r['cause']}" for r in fails] or ["None in this run."]
    sk = [r for r in results if r["status"] == "skip"]
    if sk:
        L += ["", "## Skipped"] + [f"- {r['id']}: {r['why']}" for r in sk]
    L += ["", "## Method", "- Truth: `eval/reference.py` re-parses original records (not the ingredients table / SQL / stats.py); the golden file contains no typed expected numbers.",
          "- Hard-constraint audit re-runs `constraints.check` on re-parsed originals for every returned row (main list must have no `contains`; `possible` only in the uncertain list).",
          "- T3 invariants: evidence ids exist, lack the target and use the candidate; no proposed candidate violates a stated restriction; edit only when grade allows; abstentions return no edit. The grade itself is whatever the data supports (reported, not asserted).",
          "- `--tools-only` makes zero LLM calls; `--llm` adds the multi-turn chat cases (cached)."]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tools-only", action="store_true")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--db", default=None)
    ap.add_argument("--out", type=Path, default=ROOT / "EVAL_REPORT.md")
    ap.add_argument("--cases", nargs="+", default=None)
    a = ap.parse_args(argv)
    cx, results = run_all(a.db, a.llm and not a.tools_only, a.cases)
    base = baseline_rows(cx, results) if a.baseline else []
    mode = " ".join(x for x, on in (("--tools-only", not a.llm), ("--llm", a.llm), ("--baseline", a.baseline)) if on)
    a.out.write_text(report(cx, results, mode, a.db or db_path(), base), encoding="utf-8")
    (HERE / "results.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    c = {s: sum(r["status"] == s for r in results) for s in ("pass", "fail", "skip")}
    print(f"{c} violations={cx.m['violations']} hallucinated_ids={cx.m['hallucinated_ids']} -> {a.out}")
    return 1 if c["fail"] or cx.m["violations"] or cx.m["hallucinated_ids"] else 0


if __name__ == "__main__":
    sys.exit(main())
