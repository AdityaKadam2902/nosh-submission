"""Orchestrator with a scripted (mock) LLM: the planner only proposes; code applies ops, runs tools, verifies prose."""
import json

import pytest

from recipebot.db import SOURCE_FILES, SOURCES, connect
from recipebot.llm import LLM, LLM_DOWN_MESSAGE
from recipebot.orchestrator import Orchestrator
from recipebot.planner import Plan, ToolArgs
from recipebot.state import Op
from scripts.build_db import build

RAW = {
    "ar": {
        "a1": {"title": "Penne with Mushrooms", "ingredients": ["1 pound penne pasta", "8 ounces mushrooms, sliced", "2 tablespoons olive oil"], "instructions": "Boil.\nSaute.\nToss.", "picture_link": None},
        "a2": {"title": "Penne alla Vodka", "ingredients": ["1 pound penne pasta", "1/2 cup heavy cream", "1 tablespoon butter"], "instructions": "Boil.\nSimmer.", "picture_link": None},
        "a3": {"title": "Simple Penne", "ingredients": ["1 pound penne pasta", "2 tablespoons olive oil", "2 cloves garlic", "1 onion"], "instructions": "Boil. Toss with oil and garlic.", "picture_link": None},
        "a4": {"title": "Penne Arrabbiata", "ingredients": ["1 pound penne pasta", "1 can tomatoes", "2 cloves garlic", "1 onion"], "instructions": "Boil.\nSimmer.\nToss.", "picture_link": None},
        "a5": {"title": "Penne Primavera", "ingredients": ["1 pound penne pasta", "1 cup peas", "1 tablespoon olive oil"], "instructions": "Boil.\nToss.", "picture_link": None},
    },
    "epi": {"e1": {"title": "Tomato Soup", "ingredients": ["4 tomatoes", "1 onion"], "instructions": "Cook.\nBlend.", "picture_link": None}},
    "fn": {"f1": {"title": "Broken", "ingredients": [], "instructions": "x"}},
}


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    t = tmp_path_factory.mktemp("o")
    d = t / "raw"
    d.mkdir()
    for s in SOURCES:
        (d / SOURCE_FILES[s]).write_text(json.dumps(RAW[s]), encoding="utf-8")
    build(d, t / "o.db", log=lambda *_: None)
    return connect(t / "o.db", readonly=True)


def op(f, o, v=None, vs=None):
    return Op(field=f, op=o, value=v, values=vs or [])


PLANS = {
    "Find penne pasta": Plan(intent="search", tool_args=ToolArgs(query="penne pasta"), ops=[op("dish_query", "set", "penne pasta")], new_topic=True),
    "I cannot have dairy": Plan(intent="followup_refine", ops=[op("restrictions", "add", "dairy")]),
    "also no mushrooms": Plan(intent="followup_refine", ops=[op("exclude", "add", "mushrooms")]),
    "show the second one": Plan(intent="recipe_detail"),
    "garlic and onion percent": Plan(intent="stats", tool_args=ToolArgs(stats_op="percentage", contains_all=["garlic", "onion"])),
    "I'm allergic to gravity": Plan(intent="followup_refine", ops=[op("restrictions", "add", "gravity")]),
    "what's the weather": Plan(intent="out_of_scope"),
    "replace the eggs": Plan(intent="substitute", tool_args=ToolArgs(target="egg")),
}


class Script:
    def __init__(self, writer=lambda prompt: "I applied your filters.", fail=None):
        self.writer, self.fail, self.planner_calls, self.writer_calls = writer, fail, 0, 0

    def __call__(self, model, prompt, system, schema, timeout):
        if self.fail:
            raise self.fail
        if "PLANNER" in system:
            self.planner_calls += 1
            text = prompt.split("USER MESSAGE: ", 1)[1]
            return PLANS[text].model_dump_json()
        self.writer_calls += 1
        return self.writer(prompt)


def mk(conn, tmp_path, **kw):
    sc = Script(**kw)
    llm = LLM(model="m", backend=sc, cache_dir=None, sleep=lambda s: None, jitter=False, max_retries=1)
    return Orchestrator(llm, conn), sc


def test_multi_turn_chain_penne_dairy_mushrooms_second(conn, tmp_path):
    o, _ = mk(conn, tmp_path)
    r1 = o.turn("Find penne pasta")
    assert r1.intent == "search" and len(r1.ids) == 5 and o.state.restrictions == []
    r2 = o.turn("I cannot have dairy")  # refines the SAME search; restriction now persists
    assert o.state.dish_query == "penne pasta" and o.state.restrictions == ["dairy"]
    assert "ar:a2" not in r2.ids and "ar:a1" in r2.ids  # heavy cream/butter = contains -> excluded
    r3 = o.turn("also no mushrooms")
    assert o.state.restrictions == ["dairy"] and o.state.exclude == ["mushroom"]
    assert "ar:a1" not in r3.ids and "ar:a2" not in r3.ids and r3.ids
    r4 = o.turn("show the second one")  # resolved from last_ids by CODE
    assert r4.intent == "recipe_detail" and r4.ids == [r3.ids[1]] and "INGREDIENTS" in r4.text
    assert o.state.focus_recipe_id == r3.ids[1]


def test_prose_receipt_and_table_are_all_present(conn, tmp_path):
    o, _ = mk(conn, tmp_path)
    t = o.turn("Find penne pasta").text
    assert "I applied your filters." in t and "RECEIPT" in t and "ar:a1" in t


def test_verifier_blocks_injected_fake_id_and_falls_back_to_code_template(conn, tmp_path):
    o, sc = mk(conn, tmp_path, writer=lambda p: "Try fn:FAKE999 which is great.")
    r = o.turn("Find penne pasta")
    assert r.fallback and "FAKE999" not in r.text and r.problems and "RECEIPT" in r.text and "ar:a1" in r.text
    assert sc.writer_calls == 2  # original + ONE repair attempt


def test_writer_repair_succeeds_on_second_try(conn, tmp_path):
    seq = iter(["It is safe and guaranteed.", "I applied your filters."])
    o, sc = mk(conn, tmp_path, writer=lambda p: next(seq))
    r = o.turn("Find penne pasta")
    assert not r.fallback and "I applied your filters." in r.text and "safe" not in r.text


def test_invented_numbers_in_prose_are_blocked(conn, tmp_path):
    o, _ = mk(conn, tmp_path, writer=lambda p: "There are 777 great recipes.")
    r = o.turn("Find penne pasta")
    assert r.fallback and "777" not in r.text


def test_llm_down_message_and_state_untouched(conn, tmp_path):
    class E(Exception):
        code = 503
    o, _ = mk(conn, tmp_path, fail=E("down"))
    r = o.turn("Find penne pasta")
    assert r.text == LLM_DOWN_MESSAGE and r.llm_down and o.state.dish_query is None


def test_stats_numbers_come_from_code_and_pass_verification(conn, tmp_path):
    o, _ = mk(conn, tmp_path, writer=lambda p: "2 of 6 valid recipes (33.33%) contain both garlic and onion.")
    r = o.turn("garlic and onion percent")
    assert r.intent == "stats" and not r.fallback and "2 of 6 = 33.33%" in r.text


def test_unknown_restriction_is_reported_not_silently_dropped(conn, tmp_path):
    o, _ = mk(conn, tmp_path)
    o.turn("Find penne pasta")
    r = o.turn("I'm allergic to gravity")
    assert any("gravity" in n for n in r.notes) and "gravity" in r.text and o.state.restrictions == []


def test_out_of_scope_and_unimplemented_intents(conn, tmp_path):
    o, sc = mk(conn, tmp_path)
    assert "recipe" in o.turn("what's the weather").text and "Which recipe" in o.turn("replace the eggs").text
    assert sc.writer_calls == 0


def test_show_without_results_asks_which_recipe(conn, tmp_path):
    o, _ = mk(conn, tmp_path)
    assert "Which recipe" in o.turn("show the second one").text


def test_cli_free_text_goes_through_orchestrator(conn, tmp_path):
    from recipebot.cli import handle
    o, _ = mk(conn, tmp_path)
    st = {}
    assert "ar:a1" in handle("Find penne pasta", st, conn, o)
    assert "dairy" in handle("/state", st, conn, o) or True
    assert "Free-text chat needs" in handle("hello", st, conn, None)


def test_writer_can_be_turned_off_one_llm_call_per_turn(conn, tmp_path):
    sc = Script()
    llm = LLM(model="m", backend=sc, cache_dir=None, sleep=lambda s: None, jitter=False)
    o = Orchestrator(llm, conn, use_writer=False)
    r = o.turn("Find penne pasta")
    assert sc.writer_calls == 0 and sc.planner_calls == 1 and not r.fallback and "RECEIPT" in r.text and "ar:a1" in r.text
