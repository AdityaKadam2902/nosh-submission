import json

import pytest

from recipebot.cli import handle
from recipebot.db import SOURCE_FILES, SOURCES, connect
from recipebot.search import get_recipe, search
from scripts.build_db import build

RAW = {
    "ar": {
        "a1": {"title": "Penne with Mushrooms", "ingredients": ["1 pound penne pasta ADVERTISEMENT", "8 ounces mushrooms, sliced ADVERTISEMENT", "2 tablespoons olive oil"], "instructions": "Boil.\nSaute.\nToss.", "picture_link": None},
        "a2": {"title": "Penne alla Vodka", "ingredients": ["1 pound penne pasta", "1/2 cup heavy cream", "1 tablespoon butter"], "instructions": "Boil.\nSimmer.", "picture_link": None},
        "a3": {"title": "Simple Penne", "ingredients": ["1 pound penne pasta", "2 tablespoons olive oil", "2 cloves garlic"], "instructions": "Boil. Toss with oil and garlic.", "picture_link": None},
        "a4": {"title": "Margarine Penne", "ingredients": ["1 pound penne pasta", "2 tablespoons margarine"], "instructions": "Boil.\nToss.", "picture_link": None},
    },
    "epi": {"e1": {"title": "Tomato Soup", "ingredients": ["4 tomatoes", "1 onion"], "instructions": "Cook.\nBlend.", "picture_link": None}},
    "fn": {"f1": {"title": "Broken", "ingredients": [], "instructions": "x"}},
}


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    t = tmp_path_factory.mktemp("s")
    d = t / "raw"
    d.mkdir()
    for s in SOURCES:
        (d / SOURCE_FILES[s]).write_text(json.dumps(RAW[s]), encoding="utf-8")
    build(d, t / "s.db", log=lambda *_: None)
    return connect(t / "s.db", readonly=True)


def test_fts_finds_titles(conn):
    ids = [r["id"] for r in search("penne", conn=conn, k=10)["rows"]]
    assert set(ids) == {"ar:a1", "ar:a2", "ar:a3", "ar:a4"}


def test_exclude_and_include_filters(conn):
    assert "ar:a1" not in [r["id"] for r in search("penne", exclude=["mushroom"], conn=conn)["rows"]]
    assert [r["id"] for r in search("penne", include=["garlic"], conn=conn)["rows"]] == ["ar:a3"]


def test_restriction_filters_contains_and_uncertain(conn):
    res = search("penne", restrictions=["dairy"], conn=conn)
    assert "ar:a2" not in [r["id"] for r in res["rows"]]  # heavy cream = contains
    assert [r["id"] for r in res["uncertain"]] == ["ar:a4"]  # margarine = possible, never in main list
    assert res["dropped"]["restriction_contains"] == 1


def test_max_steps_filter(conn):
    assert all(r["n_steps"] <= 2 for r in search("penne", max_steps=2, conn=conn)["rows"])


def test_no_text_query_with_include_terms(conn):
    assert [r["id"] for r in search("", include=["tomato"], conn=conn)["rows"]] == ["epi:e1"]


def test_empty_query_raises(conn):
    with pytest.raises(ValueError):
        search("", conn=conn)


def test_get_recipe_returns_untouched_original(conn):
    r = get_recipe("ar:a1", conn=conn)
    assert r["ingredients"][0].endswith("ADVERTISEMENT") and r["n_steps"] == 3


def test_cli_stats_search_show(conn):
    st = {}
    out = handle("/stats percentage --all penne", st, conn)
    assert "4 of 5 = 80.00%" in out and "RECEIPT" in out
    out = handle("/search penne --restrict dairy -k 3", st, conn)
    assert "Uncertain" in out and st["last_ids"]
    assert "Penne" in handle("/show 1", st, conn)
    assert "error" in handle("/stats nonsense", st, conn)
    assert "unknown recipe id" in handle("/show zz:nope", st, conn)
