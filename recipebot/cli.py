"""CLI (ARCHITECTURE §12). Slash commands only until M3 adds free-text chat.
  python -m recipebot.cli                      # REPL
  python -m recipebot.cli "/stats percentage --all garlic onion"   # one-shot (for transcripts)
"""
from __future__ import annotations

import argparse
import os
import re
import shlex
import sys

from recipebot.db import connect, db_path
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass
from recipebot.match import match
from recipebot.receipt import render_receipt
from recipebot.search import get_recipe, search
from recipebot.stats import OPS, run_stats

HELP = """commands:
  /search <text> [--include a b] [--exclude a b] [--restrict dairy peanut] [--steps N] [-k N]
  /match --have eggs onions "2 tomatoes" rice [--exclude a b] [--restrict peanut] [--steps N] [--prefer fewest_missing most_matched fewest_steps] [--no-staples] [-k N]
  /stats <op> [--all a b] [--any a b] [--exclude a b] [--title t] [--source ar|epi|fn] [-k N] [--order asc|desc] [--of-all a b] [--skip-staples]
      ops: count | percentage | top_ingredients | ingredient_count_summary | rank_steps
  /sub <id | n> --replace egg [--restrict dairy] [--exclude a b] [--use <mined candidate>]   evidence-based ingredient substitution (n = row number)
  /show <id | n>     (n = row number from the last result)     /state   /reset   /help   /quit
  (free-text chat arrives in M3)"""


class _P(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def _parsers():
    s = _P(prog="/search", add_help=False)
    s.add_argument("text", nargs="*")
    s.add_argument("--include", nargs="+", default=[])
    s.add_argument("--exclude", nargs="+", default=[])
    s.add_argument("--restrict", nargs="+", default=[])
    s.add_argument("--steps", type=int, default=None)
    s.add_argument("-k", type=int, default=10)
    t = _P(prog="/stats", add_help=False)
    t.add_argument("op", choices=OPS)
    t.add_argument("--all", nargs="+", default=[])
    t.add_argument("--any", nargs="+", default=[])
    t.add_argument("--exclude", nargs="+", default=[])
    t.add_argument("--title", default=None)
    t.add_argument("--source", choices=["ar", "epi", "fn"], default=None)
    t.add_argument("--of-all", nargs="+", default=[])
    t.add_argument("-k", type=int, default=10)
    t.add_argument("--order", default="asc")
    t.add_argument("--skip-staples", action="store_true")
    m = _P(prog="/match", add_help=False)
    m.add_argument("--have", nargs="+", required=True)
    m.add_argument("--exclude", nargs="+", default=[])
    m.add_argument("--restrict", nargs="+", default=[])
    m.add_argument("--steps", type=int, default=None)
    m.add_argument("--prefer", nargs="+", default=[])
    m.add_argument("--no-staples", action="store_true")
    m.add_argument("-k", type=int, default=10)
    u = _P(prog="/sub", add_help=False)
    u.add_argument("recipe", nargs="?")
    u.add_argument("--replace", nargs="+", required=True)
    u.add_argument("--restrict", nargs="+", default=[])
    u.add_argument("--exclude", nargs="+", default=[])
    u.add_argument("--use", nargs="+", default=None)
    return s, t, m, u


def _fmt_substitute(res: dict) -> str:
    """Code-rendered T3 answer: grade + counts + ids + edit by code. Predictions (Tier 2) are labelled separately; no 'safe' claims."""
    clean = lambda x: re.sub(r"\s*ADVERTISEMENT\s*", " ", x or "").strip()
    out = [f"SUBSTITUTE '{res['target']}' in {res['recipe']['id']}  {res['recipe']['title'] or ''}".rstrip()]
    if res["status"] in ("unknown_recipe", "no_target", "no_edit_needed"):
        return "\n".join(out + [res["refusal"]])
    if res.get("lines"):
        out.append("target lines: " + "; ".join(f"{l['pos']}: '{l['raw']}'" for l in res["lines"]))
    if res["roles"]:
        out.append("roles of the target (config/roles.yaml): " + ", ".join(res["roles"]))
    co = res["cohort"]
    if co:
        out.append(f"cohort: {co['size']} similar recipes ({co['with']} contain {res['target']}, {co['without']} do not; {co['same_dish']} same-dish, {co['same_class']} same-class related)")
    out.append(f"EVIDENCE GRADE: {res['grade']}" + (f"  -- {res['grade_reason']}" if res["grade_reason"] else ""))
    if co and res["candidates"]:
        out.append(f"candidates (dataset-mined, role-compatible; n/{co['without']} recipes WITHOUT {res['target']} use it | n/{co['with']} WITH it | lift):")
        for i, c in enumerate(res["candidates"], 1):
            amt = c.get("typical_amount")
            out.append(f"  {i}. {c['name']:18} {c['n_without']}/{co['without']} = {c['pct_without']:g}% | {c['n_with']}/{co['with']} = {c['pct_with']:g}% | lift {'n/a' if c['lift'] is None else c['lift']}  [{c['grade']}]"
                       + (f"  typical amount {amt['qty']:g}{(' ' + amt['unit']) if amt['unit'] else ''} (n={amt['n']})" if amt else ""))
            out.append(f"       ids: {', '.join(c['support_ids'])}")
    if res.get("omission"):
        o = res["omission"]
        out.append(f"omission: {o['n_without']}/{co['without']} = {o['pct_without']:g}% [{o['grade']}]  {o['grade_reason']}\n       ids: {', '.join(o['support_ids'])}")
    for label, lst in (("BLOCKED by your constraints (never proposed)", res["blocked"]), ("UNCERTAIN (may violate a constraint; NOT proposed)", res["uncertain"])):
        for c in lst:
            ev = "; ".join(f"{e['restriction']}: {e['reason']}" for e in c["constraint"]["evidence"][:2])
            out.append(f"{label}: {c['name']} ({c['n_without']}/{co['without']} recipes without {res['target']} use it) -- {ev}")
    if res.get("skipped_already_in_recipe"):
        out.append("not offered (already in this recipe): " + ", ".join(res["skipped_already_in_recipe"]))
    if res["refusal"]:
        out.append("\n" + res["refusal"])
    if res["selected"]:
        out.append(f"\nRESULT: {res['selected'] if res['selected'] != 'omit' else 'omit it'} (evidence grade {res['grade']})")
        for e in res["edits"]:
            out.append(f"  line {e['pos']}: {e['op']} '{e['old']}'" + (f" -> '{e['new']}'" if e.get("new") else "") + (f"   [{e['amount_basis']}]" if e.get("amount_basis") else "") + (f"   [{e['note']}]" if e.get("note") else ""))
        out.append("\nUPDATED INGREDIENTS (edit applied by code):")
        for i, (t, m) in enumerate(zip(res["edited_ingredients"], res["edit_marks"]), 1):
            out.append(f"  {i:2}. {t}" + ("   <- changed" if m != "unchanged" else ""))
        for r, v in res["constraints_after"].items():
            ev = "; ".join(f"line {e['pos']} '{e['line']}' -> {e['reason']}" for e in v["evidence"][:3])
            out.append(f"constraint {r} (edited list): {v['state']}" + (f" ({ev})" if ev else "") + (f" -- {v['note']}" if v["note"] else ""))
    for n in res["notes"]:
        out.append("note: " + n)
    out.append("predictions (not dataset evidence): none in this tier")
    out.append("(dataset evidence about similar recipes, not a tested conversion; not medical advice; labels and cross-contamination not verified)")
    return "\n".join(out)


def _fmt_match(res: dict) -> str:
    out = []
    q = lambda r: "; ".join(f"{c}: {v['status']} (need {v['need']}, have {v['have']})" for c, v in r["quantity"].items())
    if res["no_match"]:
        out.append(res["message"])
        if res["n_uncertain"]:
            out.append(f"{res['n_uncertain']} recipes are possible matches but UNCERTAIN (an ingredient only may contain a restricted item).")
        if res["violating_alternatives"]:
            out.append("\nClosest recipes that VIOLATE a constraint (not recommendations):")
            for r in res["violating_alternatives"]:
                out.append(f"  - {r['id']}  {r['title']}  [{', '.join(r['violates'])}]  matched {len(r['matched'])}, missing {len(r['missing'])}")
        return "\n".join(out)
    out.append(f"{res['n_eligible']} eligible recipes; showing {len(res['rows'])}:")
    for i, r in enumerate(res["rows"], 1):
        out.append(f"{i:2}. {r['id']}  {r['title']}  [{r['n_steps']} steps]  coverage {r['coverage']:.0%}")
        out.append(f"      matched: {', '.join(r['matched']) or '-'} | missing: {', '.join(r['missing']) or 'none'}")
        flags = " ".join(f"{k}:{v['state']}" for k, v in r["restrictions"].items())
        out.append(f"      why: {r['why']}" + (f" | constraints: {flags}" if flags else ""))
        out.append("      quantity: " + (q(r) if r["quantity"] else "name-level match; quantity sufficiency not verified"))
    if res["n_uncertain"]:
        out.append(f"\nUncertain ({res['n_uncertain']} total; NOT in the list above, may contain a restricted item):")
        for r in res["uncertain"][:5]:
            ev = "; ".join(f"line {e[0]} '{e[1].replace('ADVERTISEMENT', '').strip()}' -> {e[2]}" for v in r["restrictions"].values() for e in v["evidence"][:1])
            out.append(f"  - {r['id']}  {r['title']}  ({ev})")
    return "\n".join(out)


def _fmt_search(res: dict) -> str:
    out = [f"{res['post_filter_count']} recipes passed all filters (of {res['total_candidates']} retrieved candidates); showing {len(res['rows'])}:"]
    for i, r in enumerate(res["rows"], 1):
        flags = " ".join(f"{k}:{v['state']}" for k, v in r["restrictions"].items())
        out.append(f"{i:2}. {r['id']}  {r['title']}  [{r['n_steps']} steps, {r['n_ingredients']} ingredients]{'  ' + flags if flags else ''}")
    if res["n_uncertain"]:
        out.append(f"\nUncertain (possible match for a restriction; NOT in the list above; {res['n_uncertain']} total):")
        for r in res["uncertain"][:5]:
            ev = "; ".join(f"line {e[0]} '{e[1].replace('ADVERTISEMENT', '').strip()}' -> {e[2]}" for v in r["restrictions"].values() for e in v["evidence"][:2])
            out.append(f"  - {r['id']}  {r['title']}  ({ev})")
    return "\n".join(out)


def _fmt_stats(spec: dict, res: dict) -> str:
    d, op = res["answer_data"], spec["op"]
    if op == "count":
        return f"{d['count']:,} of {d['denominator']:,} valid recipes match."
    if op == "percentage":
        p = "n/a" if d["percentage"] is None else f"{d['percentage']:.2f}%"
        return f"{d['count']:,} of {d['denominator']:,} = {p}"
    if op == "top_ingredients":
        return f"Top ingredients over {d['n_recipes']:,} recipes:\n" + "\n".join(
            f"{i:2}. {x['canon']:30} {x['recipes']:8,}  {x['percent']:.1f}%" for i, x in enumerate(d["items"], 1))
    if op == "ingredient_count_summary":
        return f"ingredients per recipe over {d['n']:,} recipes: mean {d['mean']:.2f}, median {d['median']}, min {d['min']}, max {d['max']}"
    return f"{'Fewest' if d['order'] == 'asc' else 'Most'} estimated steps:\n" + "\n".join(
        f"{i:2}. {x['id']}  {x['title']}  [{x['n_steps']} steps by primary rule; {x['n_steps_alt']} by sentence count]" for i, x in enumerate(d["items"], 1))


def _fmt_show(r: dict) -> str:
    clean = lambda s: re.sub(r"\s*ADVERTISEMENT\s*", " ", s or "").strip()
    out = [f"{r['id']}  {clean(r['title'])}", f"source {r['source']} | valid={bool(r['is_valid'])} | {r['n_ingredients']} ingredients | {r['n_steps']} estimated steps",
           "(display strips the literal 'ADVERTISEMENT' noise; the stored original is untouched)", "", "INGREDIENTS (original -> normalized):"]
    parsed = {p["pos"]: p["canon"] for p in r["parsed"]}
    for i, line in enumerate(r["ingredients"] or []):
        out.append(f"  {i:2}. {clean(line)}  ->  {parsed.get(i, '(not an ingredient)')}")
    out += ["", "INSTRUCTIONS:", clean(r["instructions"]).replace("\n", "\n")]
    return "\n".join(out)


def handle(line: str, state: dict, conn, orch=None) -> str:
    line = line.strip()
    if not line:
        return ""
    if not line.startswith("/"):
        if orch is None:
            return "Free-text chat needs GEMINI_API_KEY and GEMINI_MODEL in .env. Use /search, /stats, /show (see /help)."
        r = orch.turn(line)
        return r.text + (f"\n(reason: {r.error})" if r.llm_down and r.error else "")
    if orch is not None:  # keep slash commands and chat sharing the same last results
        state["last_ids"] = list(orch.state.last_ids)
    try:
        parts = shlex.split(line)
    except ValueError as e:
        return f"parse error: {e}"
    cmd, args = parts[0].lower(), parts[1:]
    sp, tp, mp, up = _parsers()
    try:
        if cmd == "/help":
            return HELP
        if cmd == "/reset":
            state.clear()
            if orch is not None:
                orch.reset()
            return "state cleared"
        if cmd == "/state":
            if orch is not None:
                from recipebot.state import state_summary
                return state_summary(orch.state)
            return f"last_ids: {state.get('last_ids', [])}"
        if cmd == "/search":
            a = sp.parse_args(args)
            res = search(" ".join(a.text), a.include, a.exclude, a.restrict, a.steps, a.k, conn=conn)
            state["last_ids"] = [r["id"] for r in res["rows"]]
            if orch is not None:
                from recipebot.state import set_results
                orch.state = set_results(orch.state, state["last_ids"], "search")
            return _fmt_search(res) + "\n\n" + render_receipt(res["receipt"])
        if cmd == "/match":
            a = mp.parse_args(args)
            res = match(a.have, a.exclude, a.restrict, a.steps, a.prefer, [] if a.no_staples else None, a.k, conn=conn)
            state["last_ids"] = [r["id"] for r in res["rows"]]
            if orch is not None:
                from recipebot.state import set_results
                orch.state = set_results(orch.state, state["last_ids"], "match")
            return _fmt_match(res) + "\n\n" + render_receipt(res["receipt"])
        if cmd == "/stats":
            a = tp.parse_args(args)
            spec = {"op": a.op, "k": a.k, "order": a.order, "skip_staples": a.skip_staples,
                    "filters": {"contains_all": a.all, "contains_any": a.any, "exclude": a.exclude, "title_contains": a.title, "source": a.source},
                    "of": {"contains_all": a.of_all} if a.of_all else None}
            res = run_stats(spec, conn=conn)
            if a.op == "rank_steps":
                state["last_ids"] = [x["id"] for x in res["answer_data"]["items"]]
            return _fmt_stats(spec, res) + "\n\n" + render_receipt(res["receipt"])
        if cmd == "/sub":
            from recipebot.substitute import substitute
            a = up.parse_args(args)
            if not a.recipe:
                return "usage: /sub <recipe id | row number> --replace <ingredient> [--restrict dairy] [--exclude a b] [--use <candidate>]"
            rid = a.recipe
            if rid.isdigit():
                ids = state.get("last_ids", [])
                if not 1 <= int(rid) <= len(ids):
                    return "no such row in the last result"
                rid = ids[int(rid) - 1]
            res = substitute(rid, " ".join(a.replace), {"restrictions": a.restrict, "exclude": a.exclude}, conn=conn, use=" ".join(a.use) if a.use else None)
            if orch is not None:
                orch.state.focus_recipe_id = rid
            return _fmt_substitute(res) + "\n\n" + render_receipt(res["receipt"])
        if cmd == "/show":
            if not args:
                return "usage: /show <id | row number>"
            rid = args[0]
            if rid.isdigit():
                ids = state.get("last_ids", [])
                if not 1 <= int(rid) <= len(ids):
                    return "no such row in the last result"
                rid = ids[int(rid) - 1]
            r = get_recipe(rid, conn=conn)
            return _fmt_show(r) if r else f"unknown recipe id: {rid}"
        return f"unknown command {cmd}; try /help"
    except (ValueError, FileNotFoundError) as e:
        return f"error: {e}"


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    argv = sys.argv[1:] if argv is None else argv
    conn = connect(db_path(), readonly=True)
    state: dict = {}
    orch = None
    if os.environ.get("GEMINI_MODEL") and os.environ.get("GEMINI_API_KEY"):
        from recipebot.llm import LLM
        from recipebot.orchestrator import Orchestrator
        orch = Orchestrator(LLM(), conn)
    if argv:
        print(handle(" ".join(argv), state, conn, orch))
        return 0
    print("RecipeBot. Ask in plain English" + ("" if orch else " (LLM not configured: slash commands only)") + "; /help for commands.")
    while True:
        try:
            line = input("> ")
        except (EOFError, KeyboardInterrupt):
            return 0
        if line.strip().lower() in ("/quit", "/exit"):
            return 0
        print(handle(line, state, conn, orch), "\n")


if __name__ == "__main__":
    sys.exit(main())
