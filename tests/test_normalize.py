import pytest

from recipebot.normalize import (canon_name, clean_ingredients, contains, find_matches, parse_ingredient, parse_ingredients, singularize, unit_info)

CANON = [
    ("1/2 cup (120 g) chopped onion, divided", "onion"),
    ("3 scallions, chopped", "green onion"),
    ("4 spring onions", "green onion"),
    ("2 large eggs", "egg"),
    ("1 (14.5 ounce) can diced tomatoes, drained", "tomato"),
    ("2 cups all-purpose flour", "flour"),
    ("3 tablespoons extra-virgin olive oil", "olive oil"),
    ("1 pound ground beef", "beef"),
    ("1/4 teaspoon ground nutmeg", "nutmeg"),
    ("2 cloves garlic, minced", "garlic"),
    ("1 teaspoon garlic powder", "garlic powder"),
    ("1 butternut squash, peeled and cubed", "butternut squash"),
    ("1 eggplant", "eggplant"),
    ("1 cup coconut milk", "coconut milk"),
    ("2 (6 ounce) skinless, boneless chicken breast halves", "chicken breast"),
    ("4 cups low-sodium chicken broth", "chicken broth"),
    ("2 tablespoons confectioners' sugar", "powdered sugar"),
    ("1 cup packed light brown sugar", "brown sugar"),
    ("1 tablespoon fresh lemon juice", "lemon juice"),
    ("1 bunch fresh cilantro, chopped", "cilantro"),
    ("1 cup shredded cheddar cheese", "cheddar cheese"),
    ("1 (1 ounce) square unsweetened chocolate", "chocolate"),
    ("1 cup half-and-half", "half and half"),
    ("2 tablespoons kosher salt", "salt"),
    ("3 aubergines", "eggplant"),
    ("1 cup yellow onion, diced", "onion"),
    ("1/2 cup butter or margarine, softened", "butter"),
    ("1 cup cherries, pitted", "cherry"),
    ("6 potatoes, peeled", "potato"),
    ("2 bay leaves", "bay leaf"),
]


@pytest.mark.parametrize("raw,canon", CANON)
def test_canon(raw, canon):
    assert parse_ingredient(raw)["canon"] == canon


@pytest.mark.parametrize("raw", ["ADVERTISEMENT", "  ", "", "For the sauce:", "Ingredients:", "1", "---"])
def test_non_ingredient_lines_have_empty_canon(raw):
    assert parse_ingredient(raw)["canon"] == ""


def test_advertisement_lines_dropped_from_clean_list():
    got = clean_ingredients(["1 egg", "ADVERTISEMENT", "2 cups flour"])
    assert [d["canon"] for d in got] == ["egg", "flour"]
    assert [d["pos"] for d in got] == [0, 2]  # pos = index in the ORIGINAL list


def test_parse_ingredients_keeps_positions():
    assert [d["pos"] for d in parse_ingredients(["a", "ADVERTISEMENT", "b"])] == [0, 1, 2]


def test_qty_unit_fraction_and_parens():
    p = parse_ingredient("1/2 cup (120 g) chopped onion, divided")
    assert (p["qty"], p["unit"]) == (0.5, "cup")


@pytest.mark.parametrize("raw,qty,unit", [
    ("1 1/2 cups milk", 1.5, "cup"), ("1½ cups sugar", 1.5, "cup"), ("½ teaspoon salt", 0.5, "teaspoon"),
    ("2 eggs", 2.0, None), ("1 (8 ounce) package cream cheese", 1.0, "package"), ("a pinch of salt", 1.0, "pinch"),
    ("2-3 tablespoons olive oil", None, "tablespoon"), ("1 to 2 cups water", None, "cup"), ("3 lbs. chicken thighs", 3.0, "pound"),
    ("1.5 oz vodka", 1.5, "ounce"), ("salt to taste", None, None), ("1-1/2 cups flour", 1.5, "cup"),
])
def test_qty_unit(raw, qty, unit):
    p = parse_ingredient(raw)
    assert (p["qty"], p["unit"]) == (qty, unit)


def test_unit_family_info():
    assert unit_info("cup")["family"] == "volume" and unit_info("pound")["family"] == "mass" and unit_info("clove")["family"] == "piece"


def test_alternatives_stored_in_alts():
    p = parse_ingredient("1/2 cup butter or margarine, softened")
    assert p["canon"] == "butter" and p["alts"] == ["margarine"]


def test_alternatives_shared_head():
    p = parse_ingredient("1 cup chicken or vegetable broth")
    assert p["canon"] == "chicken broth" and p["alts"] == ["vegetable broth"]


def test_forms_recorded():
    p = parse_ingredient("1 teaspoon garlic powder")
    assert p["forms"] == ["powder"]
    assert parse_ingredient("1 pound ground beef")["forms"] == ["ground"]  # soft form: recorded, not in canon


def test_juice_of_pattern():
    assert parse_ingredient("juice of 1 lemon")["canon"] == "lemon juice"


def test_singularize_rules():
    assert [singularize(w) for w in ["tomatoes", "leaves", "berries", "cookies", "molasses", "asparagus", "radishes", "eggs", "hummus"]] == \
        ["tomato", "leaf", "berry", "cookie", "molasses", "asparagus", "radish", "egg", "hummus"]


def test_canon_name_for_queries():
    assert canon_name("Scallions") == "green onion" and canon_name("onions") == "onion" and canon_name("ground beef") == "beef"


# ---- contains(): form-aware token-sequence matching ----
def test_scallion_equals_green_onion():
    assert contains(["3 scallions, chopped"], "green onion") and contains(["2 green onions"], "scallion")


def test_garlic_powder_is_not_garlic():
    ings = ["1 teaspoon garlic powder"]
    assert not contains(ings, "garlic")
    assert contains(ings, "garlic powder")
    assert contains(ings, "garlic", ignore_forms=True)  # explicit loose mode


def test_butternut_squash_not_butter_and_eggplant_not_egg():
    assert not contains(["1 butternut squash"], "butter")
    assert not contains(["1 eggplant"], "egg")


def test_nutmeg_not_nut_and_peanut_butter_not_butter():
    assert not contains(["1/4 teaspoon ground nutmeg"], "nut")
    assert not contains(["1 cup peanut butter"], "butter")
    assert contains(["1 cup peanut butter"], "peanut butter")
    assert not contains(["1 cup peanut butter"], "peanut")


def test_coconut_milk_not_milk_and_tomato_paste_not_tomato():
    assert not contains(["1 cup coconut milk"], "milk")
    assert not contains(["2 tablespoons tomato paste"], "tomato")
    assert contains(["2 plum tomatoes"], "tomato")


def test_plain_containment_and_plurals():
    assert contains(["2 large eggs"], "eggs") and contains(["1 red onion, sliced"], "onion") and contains(["1 egg yolk"], "egg")


def test_green_onion_is_not_plain_onion():
    assert not contains(["3 green onions"], "onion")


def test_strict_means_canon_equality():
    assert contains(["1 red onion"], "onion") and not contains(["1 red onion"], "onion", strict=True)
    assert contains(["1 onion"], "onions", strict=True)


def test_query_soft_forms_must_be_present():
    assert contains(["1 pound ground beef"], "ground beef") and not contains(["1 pound beef chuck"], "ground beef")
    assert contains(["1 pound ground beef"], "beef")


def test_alts_only_when_flagged():
    ings = ["1/2 cup butter or margarine"]
    assert not contains(ings, "margarine") and contains(ings, "margarine", use_alts=True)


def test_find_matches_returns_positions():
    got = find_matches(["1 egg", "ADVERTISEMENT", "2 onions", "1 red onion"], "onion")
    assert [d["pos"] for d in got] == [2, 3]


def test_contains_accepts_parsed_dicts_and_db_style_forms():
    parsed = [{"canon": "garlic powder", "forms": "powder", "pos": 0, "raw": "x"}]
    assert not contains(parsed, "garlic") and contains(parsed, "garlic powder")


def test_non_string_items_do_not_crash():
    assert parse_ingredient(None)["canon"] == "" and parse_ingredient(5)["canon"] == ""


def test_embedded_advertisement_is_stripped_not_dropped():
    p = parse_ingredient("2 tablespoons butter ADVERTISEMENT")
    assert (p["canon"], p["qty"], p["unit"]) == ("butter", 2.0, "tablespoon")
    assert parse_ingredient("1 cup corn chips (such as Fritos®, crushed ADVERTISEMENT")["canon"] == "corn chip"
    assert parse_ingredient("1 (1.69 ounce) package candy-coated milk chocolate pieces (such as M&M;'s®) ADVERTISEMENT")["canon"]


def test_salt_and_pepper_splits_into_two_rows_same_pos():
    got = clean_ingredients(["1 egg", "Salt and freshly ground black pepper to taste"])
    assert [(d["canon"], d["pos"]) for d in got] == [("egg", 0), ("salt", 1), ("black pepper", 1)]
    assert [d["canon"] for d in clean_ingredients(["salt and pepper"])] == ["salt", "black pepper"]


def test_unbleached_flour_fine_sea_salt_and_links_unit():
    assert parse_ingredient("1/3 cup unbleached all purpose flour")["canon"] == "flour"
    assert parse_ingredient("1/4 teaspoon fine sea salt")["canon"] == "salt"
    p = parse_ingredient("6 links hot Italian sausage")
    assert (p["canon"], p["qty"], p["unit"]) == ("hot italian sausage", 6.0, "link")
