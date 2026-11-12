"""Task 3 substitution (Tier 1): deterministic evidence on a FIXED mini-DB, honest grades, refusals, blocked candidates,
edits applied by code, CLI /sub and orchestrator wiring (mock LLM only; never the real one). Thresholds come from config/roles.yaml."""
import json

import pytest

from recipebot.cli import handle
from recipebot.db import SOURCE_FILES, SOURCES, connect
from recipebot.llm import LLM
from recipebot.normalize import canon_name, matcher, parse_ingredient
from recipebot.orchestrator import Orchestrator
from recipebot.planner import Plan, ToolArgs
from recipebot.state import Op
from recipebot.substitute import _cm, _groups, load_roles, role_entry, substitute
from scripts.build_db import build

N = {"n": 0}


def R(title, ings):
    return {"title": title, "ingredients": ings, "instructions": "Mix.\nBake.", "picture_link": None}


RAW = {"ar": {}, "epi": {}, "fn": {}}


def add(key, title, ings):
    RAW["ar"][key] = R(title, ings)


# ---- banana bread: 1 source (with egg) + 6 similar WITH egg + 10 similar WITHOUT egg
BASE = ["3 ripe bananas", "2 cups flour", "1 cup sugar", "1 teaspoon baking soda", "1/2 cup butter", "1 teaspoon vanilla extract"]
add("bb0", "Banana Bread", ["2 large eggs"] + BASE)
for i in range(1, 7):  # WITH egg; milk in 3 of 6
    add(f"bbw{i}", "Moist Banana Bread", ["2 eggs"] + BASE + (["1/4 cup milk"] if i <= 3 else []))
WITHOUT = {1: "1/4 cup applesauce", 2: "1/4 cup applesauce", 3: "1/2 cup applesauce", 4: "1/4 cup applesauce", 5: "1/4 cup applesauce",
           6: "1/2 cup yogurt", 7: "1/2 cup yogurt", 8: "1/4 cup mayonnaise", 9: "1/4 cup mayonnaise", 10: None}
for i, extra in WITHOUT.items():  # WITHOUT egg; milk in 5 of 10 (as common as in the egg recipes => not a replacement)
    add(f"bbo{i}", "Eggless Banana Bread", BASE + ([extra] if extra else []) + (["1/4 cup milk"] if i <= 5 else []))
add("bbm1", "Banana Muffins", ["2 eggs"] + BASE)  # different dish class: must NOT be in the cohort
add("zb1", "Zucchini Bread", ["2 eggs", "2 cups zucchini", "2 cups flour", "1/2 cup vegetable oil", "1 teaspoon cinnamon"])  # same class, low similarity

# ---- creamy chicken pasta: cream -> (milk 5, coconut milk 4) in the 10 recipes without cream
PBASE = ["1 pound pasta", "2 cloves garlic", "1 pound chicken breast", "1 tablespoon olive oil"]
add("pa0", "Creamy Chicken Pasta", ["1 cup heavy cream"] + PBASE)
add("pa_parm", "Creamy Parmesan Chicken Pasta", ["1 cup heavy cream", "1/2 cup parmesan cheese"] + PBASE)  # source with other dairy (residual test)
for i in range(1, 5):
    add(f"paw{i}", "Garlic Chicken Pasta", ["1 cup cream"] + PBASE)
for i in range(1, 11):
    add(f"pao{i}", "Garlic Chicken Pasta", PBASE + (["1 cup milk"] if i <= 5 else ["1 cup coconut milk"] if i <= 9 else []))

# ---- oatmeal cookies: small cohort (3 with butter, 4 without; margarine in 3 of the 4) -> indirect
CB = ["1 cup rolled oats", "1 cup flour", "1/2 cup sugar", "1 teaspoon cinnamon"]
add("oc0", "Oatmeal Cookies", ["1/2 cup butter"] + CB)
for i in range(1, 4):
    add(f"ocw{i}", "Oatmeal Cookies", ["1/2 cup butter"] + CB)
for i in range(1, 5):
    add(f"oco{i}", "Oatmeal Cookies", CB + (["1/2 cup margarine"] if i <= 3 else []))

# ---- zucchini fritters: only 1 similar recipe without egg -> insufficient
add("zf0", "Zucchini Fritters", ["2 eggs", "2 cups zucchini", "1/2 cup flour", "1 teaspoon salt"])
add("zf1", "Zucchini Fritters", ["2 eggs", "2 cups zucchini", "1/2 cup flour"])
add("zf2", "Zucchini Fritters", ["2 cups zucchini", "1/2 cup flour", "1 tablespoon olive oil"])

# ---- garlic bread: cheese is mostly just left out (no role-compatible replacement used) -> omission option
GBASE = ["4 slices bread", "3 cloves garlic", "1 tablespoon parsley"]
add("gb0", "Garlic Bread", GBASE + ["1 cup cheese"])
for i in range(1, 4):
    add(f"gbw{i}", "Garlic Bread", GBASE + ["1 cup cheese"])
for i in range(1, 9):
    add(f"gbo{i}", "Garlic Bread", GBASE)

# ---- "butter or margarine" line (target only as an alternative) and a shared line
add("alt0", "Toast Plate", ["2 slices bread", "2 tablespoons butter or margarine"])
add("sp0", "Pepper Steak", ["1 pound beef", "salt and pepper", "1 onion"])


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    t = tmp_path_factory.mktemp("s")
    d = t / "raw"
    d.mkdir()
    for s in SOURCES:
        (d / SOURCE_FILES[s]).write_text(json.dumps(RAW[s]), encoding="utf-8")
    build(d, t / "s.db", log=lambda *_: None)
    return connect(t / "s.db", readonly=True)


def cnames(res, key="candidates"):
    return [c["name"] for c in res[key]]


def ref_counts(target_term, cand_terms, src_key, title_tokens, extra_ok=lambda k: True):
    """independent recount straight from RAW: among same-title (all dish tokens) recipes, how many lack/contain the target and use each candidate."""
    tm = matcher(target_term)
    out = {"with": 0, "without": 0, "use": {c: [] for c in cand_terms}}
    for k, r in RAW["ar"].items():
        if k == src_key or not all(t in r["title"].lower() for t in title_tokens) or not extra_ok(k):
            continue
        rows = [parse_ingredient(x) for x in r["ingredients"]]
        if any(tm(d) for d in rows):
            out["with"] += 1
        else:
            out["without"] += 1
            for c in cand_terms:
                if any(matcher(c)(d) for d in rows):
                    out["use"][c].append("ar:" + k)
    return out


# ================= acceptance 1: banana bread minus eggs -> graded evidence, counts + ids, edit by code
def test_banana_bread_minus_eggs_strong_with_counts_ids_and_edit(conn):
    res = substitute("ar:bb0", "eggs", conn=conn)
    ref = ref_counts("egg", ["applesauce", "yogurt", "mayonnaise"], "bb0", ["banana", "bread"], lambda k: k != "zb1" and k != "bbm1")
    co = res["cohort"]
    assert (co["with"], co["without"]) == (ref["with"], ref["without"]) == (6, 10) and co["same_dish_without"] == 10
    assert res["status"] == "ok" and res["grade"] == "strong" and res["selected"] == "applesauce"
    top = res["candidates"][0]
    assert top["n_without"] == 5 and top["n_with"] == 0 and top["share_without"] == pytest.approx(0.5) and top["lift"] == pytest.approx(10.0)
    assert set(top["support_ids"]) == set(ref["use"]["applesauce"]) and len(top["support_ids"]) == 5
    assert [c["name"] for c in res["candidates"]][:3] == ["applesauce", "mayonnaise", "yogurt"]  # yogurt/mayonnaise tie at 2/10: ordered by name
    assert "milk" not in cnames(res)  # as common WITH egg as without => a common ingredient, not a replacement (lift < min_lift)
    assert "baking soda" not in cnames(res)  # already in the source recipe
    # edit applied by code, on the right line, typical amount from the cohort (median of 1/4, 1/4, 1/2, 1/4, 1/4 cup)
    e = res["edits"][0]
    assert e["op"] == "replace" and e["old"] == "2 large eggs" and e["new"] == "0.25 cup applesauce" and "median of 5" in e["amount_basis"]
    assert res["edited_ingredients"][0] == "0.25 cup applesauce" and "2 large eggs" not in res["edited_ingredients"] and len(res["edited_ingredients"]) == 7
    assert res["predictions"] == []  # Tier 1: no LLM text
    r = res["receipt"]
    assert r["tool"] == "substitute" and "ar:bb0" in r["recipe_ids"] and set(top["support_ids"]) <= set(r["recipe_ids"]) and r["n_analyzed"] == 16
    assert "config/roles.yaml" in r["formula"] and "lift" in r["formula"]
    assert r["dataset"]["valid"] == len(RAW["ar"])


def test_cohort_excludes_other_dish_class_and_low_similarity(conn):
    ids = set(substitute("ar:bb0", "egg", conn=conn)["receipt"]["recipe_ids"])
    assert "ar:bbm1" not in ids and "ar:zb1" not in ids  # muffins: other class; zucchini bread: same class but Jaccard < min_jaccard_same_class


# ================= acceptance 2: cream -> dairy-free in a pasta recipe
def test_cream_to_dairy_free_pasta_blocks_milk_and_picks_coconut_milk(conn):
    res = substitute("ar:pa0", "cream", ["dairy"], conn=conn)
    assert res["status"] == "ok" and res["selected"] == "coconut milk"
    assert [c["name"] for c in res["blocked"]] == ["milk"] and res["blocked"][0]["constraint"]["state"] == "contains"
    assert res["blocked"][0]["n_without"] == 5 and res["cohort"]["with"] == 5 and res["cohort"]["without"] == 10  # with = 4 + the parmesan variant
    assert res["edits"][0]["old"] == "1 cup heavy cream" and res["edits"][0]["new"].endswith("coconut milk")
    after = res["constraints_after"]["dairy"]
    assert after["state"] == "free" and "not verified" in after["note"] and res["edited_meets_constraints"] is True
    assert res["constraints_before"]["dairy"]["state"] == "contains"


def test_residual_dairy_in_other_lines_is_reported_not_hidden(conn):
    res = substitute("ar:pa_parm", "cream", ["dairy"], conn=conn)
    assert res["status"] == "ok" and res["selected"] == "coconut milk"
    assert res["edited_meets_constraints"] is False and res["constraints_after"]["dairy"]["state"] == "contains"
    assert any("parmesan" in x["line"] for x in res["residual"]) and any("residual" in n for n in res["notes"])


# ================= acceptance 3: conflicting / indirect reported honestly
def test_conflicting_when_two_candidates_are_within_tie_rel(conn):
    res = substitute("ar:pa0", "cream", conn=conn)  # milk 5/10 vs coconut milk 4/10 (within 20% relative)
    assert res["grade"] == "conflicting" and res["status"] == "options" and res["selected"] is None and res["edited_ingredients"] is None
    assert cnames(res)[:2] == ["milk", "coconut milk"] and "within 20%" in res["grade_reason"] and "--use" in res["refusal"]
    pick = substitute("ar:pa0", "cream", conn=conn, use="coconut milk")  # the user chooses among MINED options
    assert pick["status"] == "ok" and pick["selected"] == "coconut milk" and pick["edits"][0]["new"].endswith("coconut milk")


def test_indirect_when_cohort_is_small(conn):
    res = substitute("ar:oc0", "butter", conn=conn)
    assert res["cohort"]["with"] == 3 and res["cohort"]["without"] == 4
    assert res["grade"] == "indirect" and res["selected"] == "margarine" and "small cohort" in res["grade_reason"]
    assert res["candidates"][0]["n_without"] == 3 and res["edited_ingredients"][0].endswith("margarine")


# ================= acceptance 4: insufficient refuses with counts
def test_insufficient_refuses_with_counts_and_no_edit(conn):
    res = substitute("ar:zf0", "egg", conn=conn)
    assert res["status"] == "refused" and res["grade"] == "insufficient" and res["selected"] is None
    assert res["edited_ingredients"] is None and res["edits"] == []
    assert res["cohort"]["without"] == 1 and "only 1 similar recipes lack" in res["grade_reason"] and "will not recommend" in res["refusal"]


def test_unknown_target_is_refused_not_guessed(conn):
    res = substitute("ar:bb0", "vanilla extract", conn=conn)
    assert res["status"] == "refused" and "roles.yaml" in res["refusal"] and res["edited_ingredients"] is None


# ================= acceptance 5: allergy-violating request blocked
def test_candidate_violating_stated_allergy_is_blocked(conn):
    res = substitute("ar:bb0", "egg", ["egg"], conn=conn)
    assert "mayonnaise" in cnames(res, "blocked") and "mayonnaise" not in cnames(res)  # mayonnaise = definite egg
    assert res["selected"] == "applesauce"
    asked = substitute("ar:bb0", "egg", ["egg"], conn=conn, use="mayonnaise")
    assert asked["status"] == "blocked" and asked["edited_ingredients"] is None and asked["refusal"].startswith("BLOCKED") and "mayonnaise" in asked["refusal"]


def test_dairy_blocks_yogurt_even_if_asked(conn):
    res = substitute("ar:bb0", "egg", ["dairy"], conn=conn, use="yogurt")
    assert res["status"] == "blocked" and "yogurt" in cnames(res, "blocked")


def test_user_exclude_blocks_candidate(conn):
    res = substitute("ar:bb0", "egg", {"exclude": ["applesauce"]}, conn=conn)
    assert "applesauce" in cnames(res, "blocked") and res["selected"] == "yogurt" or res["grade"] == "conflicting"


def test_possible_goes_to_uncertain_never_recommended(conn):
    res = substitute("ar:oc0", "butter", ["dairy"], conn=conn)  # margarine is 'possible' for dairy
    assert "margarine" in cnames(res, "uncertain") and "margarine" not in cnames(res) and res["selected"] is None and res["edited_ingredients"] is None
    assert res["status"] == "refused" and "conflicts with your restrictions" in res["grade_reason"]
    assert substitute("ar:oc0", "butter", ["dairy"], conn=conn, use="margarine")["status"] == "refused"


def test_unmined_replacement_is_refused_never_invented(conn):
    res = substitute("ar:bb0", "egg", conn=conn, use="unicorn tears")
    assert res["status"] == "refused" and "not a replacement supported by the dataset evidence" in res["refusal"] and res["edited_ingredients"] is None


def test_omission_is_evidence_based_and_only_chosen_when_no_replacement_qualifies(conn):
    res = substitute("ar:gb0", "cheese", conn=conn)
    assert res["candidates"] == [] and res["omission"]["n_without"] == 8 and res["omission"]["grade"] == "moderate"  # capped by omit.max_grade, never strong
    assert res["status"] == "ok" and res["selected"] == "omit" and res["edits"][0]["op"] == "remove" and res["edits"][0]["old"] == "1 cup cheese"
    assert res["edited_ingredients"] == ["4 slices bread", "3 cloves garlic", "1 tablespoon parsley"] and "does not show the dish works the same" in res["omission"]["grade_reason"]
    assert res["cohort"]["same_dish"] == res["cohort"]["size"] == 11  # same-dish count adds up with the cohort size


# ================= edge cases
def test_no_target_unknown_recipe_alt_only_and_shared_line(conn):
    assert substitute("ar:bb0", "butter milk", conn=conn)["status"] == "no_target"
    assert substitute("ar:nope", "egg", conn=conn)["status"] == "unknown_recipe"
    alt = substitute("ar:alt0", "margarine", conn=conn)
    assert alt["status"] in ("no_edit_needed", "refused", "no_target")  # margarine is only the 'or' alternative of butter
    assert substitute("ar:alt0", "butter", conn=conn)["lines"][0]["pos"] == 1


def test_bad_restriction_raises(conn):
    with pytest.raises(ValueError):
        substitute("ar:bb0", "egg", ["gravity"], conn=conn)


def test_thresholds_live_in_config_and_change_the_grade(conn):
    base = substitute("ar:bb0", "egg", conn=conn)
    assert base["grade"] == "strong"
    tight = substitute("ar:bb0", "egg", conn=conn, config={"defaults": {"grade": {"min_without_direct": 11}}})
    assert tight["grade"] == "indirect"  # only the config changed
    strict = substitute("ar:bb0", "egg", conn=conn, config={"defaults": {"grade": {"strong": {"min_share": 0.6}}}})
    assert strict["grade"] == "moderate"
    assert "11" in tight["receipt"]["formula"]  # receipt shows the thresholds actually used


def test_roles_yaml_is_complete_and_consistent():
    cfg = load_roles()
    ents = cfg["ingredients"]
    assert len(ents) >= 25 and {"egg", "butter", "milk", "cream", "flour", "sugar", "oil", "yogurt", "cheese", "sour cream", "buttermilk", "honey", "baking powder", "breadcrumb"} <= set(ents)
    for k, e in ents.items():
        assert canon_name(k) == k and e["roles"] and e["can_fill"] and isinstance(e.get("omit_ok"), bool), k
        for grp in _groups(e):
            for n in grp:
                assert canon_name(n) == n and _cm(n)(parse_ingredient(f"1 cup {n}")), (k, n)
    assert role_entry("heavy cream", cfg)[0] == "cream" and role_entry("egg white", cfg)[0] == "egg" and role_entry("bread crumb", cfg)[0] == "breadcrumb"
    assert role_entry("sour cream", cfg)[0] == "sour cream" and role_entry("saffron", cfg) is None
    for key in ("defaults",):
        for k in ("cohort", "candidate", "grade", "typical_amount_min_n", "support_ids"):
            assert k in cfg[key]


# ================= CLI + orchestrator
def test_cli_sub_command(conn):
    st = {}
    out = handle("/sub ar:bb0 --replace egg --restrict egg", st, conn)
    assert "EVIDENCE GRADE: strong" in out and "applesauce" in out and "BLOCKED" in out.upper() and "mayonnaise" in out and "--- RECEIPT ---" in out
    assert "UPDATED INGREDIENTS" in out and "0.25 cup applesauce" in out and "safe" not in out.lower().replace("not verified", "")
    st2 = {"last_ids": ["ar:pa0", "ar:bb0"]}
    assert "ar:bb0" in handle("/sub 2 --replace egg", st2, conn)
    assert "usage" in handle("/sub", {}, conn).lower() or "error" in handle("/sub", {}, conn).lower()
    assert handle("/sub ar:zf0 --replace egg", {}, conn).count("will not recommend") >= 1
    assert "error" in handle("/sub ar:bb0 --replace egg --restrict gravity", {}, conn)


def op(f, o, v=None):
    return Op(field=f, op=o, value=v)


class Script:
    def __init__(self, plans):
        self.plans, self.writer_calls = plans, 0

    def __call__(self, model, prompt, system, schema, timeout):
        if "PLANNER" in system:
            return self.plans[prompt.split("USER MESSAGE: ", 1)[1]].model_dump_json()
        self.writer_calls += 1
        return "Applesauce is the best-supported replacement."


def mk(conn, plans, **kw):
    return Orchestrator(LLM(model="m", backend=Script(plans), cache_dir=None, sleep=lambda s: None, jitter=False, max_retries=1), conn, use_writer=kw.get("use_writer", False))


def test_orchestrator_substitute_uses_focus_recipe_restrictions_and_code_evidence(conn):
    plans = {"I can't eat dairy": Plan(intent="followup_refine", ops=[op("restrictions", "add", "dairy")]),
             "swap the cream in ar:pa0": Plan(intent="substitute", tool_args=ToolArgs(target="cream", recipe_id="ar:pa0")),
             "swap the eggs": Plan(intent="substitute", tool_args=ToolArgs(target="egg")),
             "swap the cream in it": Plan(intent="substitute", tool_args=ToolArgs(target="cream")),
             "replace something": Plan(intent="substitute", tool_args=ToolArgs(recipe_id="ar:bb0"))}
    o = mk(conn, plans)
    assert "Which recipe" in o.turn("swap the eggs").text  # no recipe known yet: asks, does not guess
    o.turn("I can't eat dairy")
    r = o.turn("swap the cream in ar:pa0")
    assert r.intent == "substitute" and "coconut milk" in r.text and "EVIDENCE GRADE" in r.text and "--- RECEIPT ---" in r.text and "ar:pa0" in r.ids
    assert o.state.focus_recipe_id == "ar:pa0" and o.state.restrictions == ["dairy"]  # stated restrictions persisted and were applied by code
    assert "milk" in r.text and "BLOCKED" in r.text.upper()
    assert "coconut milk" in o.turn("swap the cream in it").text  # 'it' -> focus recipe
    assert "Which ingredient" in o.turn("replace something").text


def test_orchestrator_writer_prose_is_verified_against_substitute_payload(conn):
    plans = {"swap the eggs in ar:bb0": Plan(intent="substitute", tool_args=ToolArgs(target="egg", recipe_id="ar:bb0"))}
    sc = Script(plans)
    o = Orchestrator(LLM(model="m", backend=sc, cache_dir=None, sleep=lambda s: None, jitter=False, max_retries=1), conn, use_writer=True)
    r = o.turn("swap the eggs in ar:bb0")
    assert sc.writer_calls >= 1 and not r.fallback and "Applesauce is the best-supported replacement." in r.text and "applesauce" in r.text
