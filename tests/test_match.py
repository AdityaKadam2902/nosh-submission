"""Task 2 matching: deterministic, hard filters in code, honest NO_MATCH, quantity checks, plus an independent brute-force reference."""
import json

import pytest

from recipebot.db import SOURCE_FILES, SOURCES, connect
from recipebot.llm import LLM
from recipebot.match import match, normalize_available, parse_preferences, rank_order
from recipebot.normalize import clean_ingredients, matcher
from recipebot.orchestrator import Orchestrator
from recipebot.planner import Plan, ToolArgs
from recipebot.state import Op
from recipebot.steps import count_steps
from scripts.build_db import build


def R(title, ings, steps):
    return {"title": title, "ingredients": ings, "instructions": "\n".join(f"Do step {i}." for i in range(steps)), "picture_link": None}


RAW = {
    "ar": {
        "r1": R("Egg Fried Rice", ["2 eggs", "1 cup rice", "1 onion", "2 tablespoons soy sauce"], 3),
        "r2": R("Tomato Rice", ["3 tomatoes", "2 cups rice", "1 tablespoon olive oil", "1 teaspoon salt"], 2),
        "r3": R("Shakshuka", ["4 eggs", "4 tomatoes", "1 onion", "1 red bell pepper", "1 teaspoon cumin"], 4),
        "r4": R("Peanut Fried Rice", ["1 cup rice", "2 eggs", "1 onion", "1/2 cup peanuts"], 3),
        "r5": R("Long Egg Dish", ["2 eggs", "1 onion", "2 tomatoes", "1 cup rice"], 8),
        "r6": R("Plain Omelette", ["3 eggs", "salt and pepper"], 2),
        "r7": R("Onion Soup", ["4 onions", "2 tablespoons butter", "4 cups beef broth"], 3),
        "r8": R("Tomato Paste Pasta", ["2 tablespoons tomato paste", "1 pound pasta"], 3),
        "r9": R("Red Onion Salad", ["2 red onions", "2 tablespoons olive oil"], 2),
        "r10": R("Margarine Cake", ["2 eggs", "2 cups flour", "1/2 cup margarine"], 2),
        "r11": R("Butter or Margarine Toast", ["1 egg", "2 tablespoons butter or margarine", "2 slices bread"], 2),
    },
    "epi": {}, "fn": {},
}
AVAIL = ["eggs", "onions", "tomatoes", "rice"]


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    t = tmp_path_factory.mktemp("m")
    d = t / "raw"
    d.mkdir()
    for s in SOURCES:
        (d / SOURCE_FILES[s]).write_text(json.dumps(RAW[s]), encoding="utf-8")
    build(d, t / "m.db", log=lambda *_: None)
    return connect(t / "m.db", readonly=True)


def ids(res, key="rows"):
    return [r["id"] for r in res[key]]


def test_spec_example_eggs_onions_tomatoes_rice(conn):
    res = match(AVAIL, restrictions=["peanut"], max_steps=6, preferences=["fewest extra ingredients"], conn=conn)
    got = ids(res)
    assert "ar:r4" not in got and "ar:r5" not in got  # peanut / >6 steps are hard-filtered
    assert "ar:r6" not in got and got == ["ar:r1", "ar:r2", "ar:r3"]  # default min_matched=2: one-ingredient recipes are skipped
    top = res["rows"][0]
    assert top["missing"] == ["soy sauce"] and top["matched"] == ["egg", "rice", "onion"] and top["n_steps"] == 3 and top["why"]
    assert res["order"] == ["fewest_missing", "most_matched", "fewest_steps"]


def test_default_ranking_most_matched_then_fewest_missing(conn):
    res = match(AVAIL, restrictions=["peanut"], max_steps=6, conn=conn)
    assert res["order"] == ["most_matched", "fewest_missing", "fewest_steps"]
    assert ids(res)[:3] == ["ar:r1", "ar:r3", "ar:r2"]  # 3 matched/1 missing, 3/2, 2/1
    r1 = res["rows"][0]
    assert r1["matched"] == ["egg", "rice", "onion"] and r1["missing"] == ["soy sauce"] and r1["coverage"] == pytest.approx(0.75)
    assert "fewer extra ingredients" in r1["why"] and "(1 vs 2)" in r1["why"]


def test_staples_are_not_missing_and_can_be_turned_off(conn):
    r2 = next(r for r in match(AVAIL, conn=conn)["rows"] if r["id"] == "ar:r2")
    assert "salt" not in r2["missing"] and r2["missing"] == ["olive oil"]
    r6 = next(r for r in match(AVAIL, staples=[], min_matched=1, conn=conn)["rows"] if r["id"] == "ar:r6")
    assert set(r6["missing"]) == {"salt", "black pepper"}  # "salt and pepper" counts as two items; without staples they are missing


def test_form_aware_matching_of_available_items(conn):
    assert "ar:r8" not in ids(match(["tomatoes"], conn=conn))  # tomato paste is not a tomato
    assert "ar:r9" in ids(match(["onion"], conn=conn))  # onion is contained in "red onion"
    assert "ar:r7" in ids(match(["onion"], conn=conn)) and match(["red onion"], conn=conn)["rows"][0]["id"] == "ar:r9"


def test_or_alternatives_count_as_matched(conn):
    res = match(["margarine", "eggs"], conn=conn)
    r = next(x for x in res["rows"] if x["id"] == "ar:r11")
    assert "butter" in r["matched"]  # user has margarine; the line says butter OR margarine


def test_exclude_ingredient_is_a_hard_filter(conn):
    assert all(i not in ids(match(AVAIL, exclude=["eggs"], conn=conn)) for i in ("ar:r1", "ar:r3", "ar:r5", "ar:r6"))


def test_restriction_possible_goes_to_uncertain_not_main_list(conn):
    res = match(["eggs", "flour"], restrictions=["dairy"], conn=conn)
    assert "ar:r10" not in ids(res) and "ar:r10" in ids(res, "uncertain") and res["n_uncertain"] >= 1


def test_impossible_constraint_gives_no_match_and_labelled_violators(conn):
    res = match(["eggs"], restrictions=["egg"], conn=conn)
    assert res["no_match"] and res["rows"] == [] and res["message"].startswith("NO_MATCH")
    assert res["violating_alternatives"] and all(any("violates: egg" in v for v in r["violates"]) for r in res["violating_alternatives"])
    res2 = match(AVAIL, max_steps=1, conn=conn)
    assert res2["no_match"] and any("max_steps" in v for r in res2["violating_alternatives"] for v in r["violates"])


def test_quantity_sufficiency_same_family(conn):
    ok = match(["1 cup rice", "2 eggs"], conn=conn)["rows"]
    r1 = next(r for r in ok if r["id"] == "ar:r1")
    assert r1["quantity"]["rice"]["status"] == "sufficient" and r1["quantity"]["egg"]["status"] == "sufficient"
    r2 = next(r for r in match(["1 cup rice"], conn=conn)["rows"] if r["id"] == "ar:r2")
    assert r2["quantity"]["rice"]["status"] == "insufficient"  # recipe needs 2 cups


def test_quantity_unverified_when_units_incomparable_or_missing(conn):
    r2 = next(r for r in match(["1 pound rice"], conn=conn)["rows"] if r["id"] == "ar:r2")
    assert r2["quantity"]["rice"]["status"] == "unverified"  # mass vs volume
    r1 = next(r for r in match(["rice"], conn=conn)["rows"] if r["id"] == "ar:r1")
    assert r1["quantity"] == {}  # no qty given -> name-level match only


def test_available_accepts_strings_dicts_and_objects():
    from recipebot.state import Ingredient
    got = normalize_available(["2 eggs", {"name": "Onions", "qty": 1, "unit": "cups"}, Ingredient(name="rice", qty=3.0, unit="cup"), "eggs", "ADVERTISEMENT"])
    assert [(a["name"], a["qty"], a["unit"]) for a in got] == [("egg", 2.0, None), ("onion", 1, "cup"), ("rice", 3.0, "cup")]


def test_preference_parsing():
    assert parse_preferences(["prefer fewest extra ingredients", "fewest steps"]) == ["fewest_missing", "fewest_steps"]
    assert parse_preferences(["use the most of my ingredients"]) == ["most_matched"] and parse_preferences(["blue"]) == []
    assert rank_order(["quick"]) == ["fewest_steps", "most_matched", "fewest_missing"]


def test_preferences_change_the_order(conn):
    a = ids(match(AVAIL, max_steps=6, preferences=["fewest_steps"], conn=conn))
    b = ids(match(AVAIL, max_steps=6, preferences=["most_matched"], conn=conn))
    assert a != b and a[0] == "ar:r2" and b[0] == "ar:r1"


def test_no_recognizable_ingredients_raises(conn):
    with pytest.raises(ValueError):
        match(["ADVERTISEMENT"], conn=conn)


def test_receipt_lists_staples_filters_and_ids(conn):
    rc = match(AVAIL, restrictions=["peanut"], max_steps=6, conn=conn)["receipt"]
    assert rc["tool"] == "match" and "black pepper" in rc["normalization"] and rc["recipe_ids"] and any("max estimated steps" in f for f in rc["filters"])
    assert "not verified" in rc["formula"]


def reference_match(raw, available, exclude, restrictions, max_steps, order, min_matched=None):
    """Independent brute force over the raw dict (no SQL, no match.py)."""
    from recipebot.constraints import check
    from recipebot.normalize import canon_name
    staples = {"water", "salt", "black pepper"}
    ms = [matcher(canon_name(a), use_alts=True) for a in available]
    exc = [matcher(t) for t in exclude]
    out = []
    for s in SOURCES:
        for key, rec in raw[s].items():
            L = clean_ingredients(rec["ingredients"])
            steps, _ = count_steps(rec["instructions"])
            if not rec["title"].strip() or not L or steps < 1:
                continue
            req = {}
            for d in L:
                if d["canon"] not in staples:
                    req.setdefault(d["canon"], d)
            matched = [c for c, d in req.items() if any(m(d) for m in ms)]
            if len(matched) < (min(2, len(available)) if min_matched is None else min_matched) or any(any(m(d) for d in L) for m in exc) or (max_steps is not None and steps > max_steps):
                continue
            if any(check(L, r)["state"] != "free" for r in restrictions):
                continue
            row = {"id": f"{s}:{key}", "matched": matched, "missing": [c for c in req if c not in matched], "n_steps": steps}
            out.append(row)
    keyf = {"most_matched": lambda r: -len(r["matched"]), "fewest_missing": lambda r: len(r["missing"]), "fewest_steps": lambda r: r["n_steps"]}
    return [r["id"] for r in sorted(out, key=lambda r: tuple(keyf[o](r) for o in order) + (r["id"],))]


@pytest.mark.parametrize("kw", [dict(), dict(restrictions=["peanut"], max_steps=6), dict(exclude=["egg"], preferences=["fewest steps"]),
                                dict(restrictions=["dairy"], preferences=["fewest extra"], max_steps=4)])
def test_matches_independent_reference_on_generated_data(tmp_path, kw):
    from tests.test_stats_crosscheck import make_raw
    raw = make_raw(n=80, seed=3)
    d = tmp_path / "raw"
    d.mkdir()
    for s in SOURCES:
        (d / SOURCE_FILES[s]).write_text(json.dumps(raw[s]), encoding="utf-8")
    build(d, tmp_path / "g.db", log=lambda *_: None)
    c = connect(tmp_path / "g.db", readonly=True)
    avail = ["eggs", "onions", "tomatoes", "rice"]
    res = match(avail, kw.get("exclude"), kw.get("restrictions"), kw.get("max_steps"), kw.get("preferences"), k=500, conn=c)
    ref = reference_match(raw, avail, kw.get("exclude", []), kw.get("restrictions", []), kw.get("max_steps"), rank_order(kw.get("preferences")))
    assert ids(res) == ref and len(ref) > 0


# ---- through the orchestrator (mock LLM): "Exclude eggs too" updates state and re-runs the SAME match ----
def _op(f, o, v=None, vs=None):
    return Op(field=f, op=o, value=v, values=vs or [])


PLANS = {
    "I have eggs, onions, tomatoes and rice, at most 6 steps, no peanuts, prefer fewest extra ingredients": Plan(intent="match", ops=[
        _op("available", "set", vs=AVAIL), _op("max_steps", "set", "6"), _op("restrictions", "add", "peanut"), _op("preferences", "add", "fewest extra ingredients")]),
    "Exclude eggs too": Plan(intent="followup_refine", ops=[_op("exclude", "add", "eggs")]),
    "at most 1 step": Plan(intent="followup_refine", ops=[_op("max_steps", "set", "1")]),
}


class Script:
    def __call__(self, model, prompt, system, schema, timeout):
        if "PLANNER" in system:
            return PLANS[prompt.split("USER MESSAGE: ", 1)[1]].model_dump_json()
        return "I applied your filters."


def test_exclude_eggs_too_updates_state_and_reruns_match(conn):
    o = Orchestrator(LLM(model="m", backend=Script(), cache_dir=None), conn)
    r1 = o.turn("I have eggs, onions, tomatoes and rice, at most 6 steps, no peanuts, prefer fewest extra ingredients")
    assert r1.intent == "match" and r1.ids[0] == "ar:r1" and o.state.restrictions == ["peanut"] and o.state.max_steps == 6 and "why:" in r1.text
    r2 = o.turn("Exclude eggs too")
    assert o.state.exclude == ["egg"] and o.state.last_intent == "match" and r2.ids and all(i not in r2.ids for i in ("ar:r1", "ar:r6", "ar:r3"))
    assert "RECEIPT" in r2.text and "excludes: egg" in r2.text
    r3 = o.turn("at most 1 step")  # every recipe needs >= 2 steps -> explicit NO_MATCH + labelled violators
    assert "NO_MATCH" in r3.text and "VIOLATE" in r3.text and "max_steps" in r3.text and r3.ids == []


def test_cli_match_command(conn):
    from recipebot.cli import handle
    out = handle('/match --have eggs onions tomatoes rice --steps 6 --restrict peanut --prefer fewest_missing', {}, conn)
    assert "ar:r1" in out and "why:" in out and "RECEIPT" in out and "name-level match" in out and "at least 2 of your ingredients" in out
    assert "NO_MATCH" in handle("/match --have eggs --restrict egg", {}, conn)


def test_min_matched_override_and_receipt(conn):
    assert "ar:r6" in ids(match(AVAIL, min_matched=1, conn=conn)) and "ar:r6" not in ids(match(AVAIL, conn=conn))
    assert match(["eggs"], conn=conn)["rows"]  # a single ingredient list still works (min = 1)
    assert any("at least 2 of your ingredients" in f for f in match(AVAIL, conn=conn)["receipt"]["filters"])
