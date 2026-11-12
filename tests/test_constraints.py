import pytest

from recipebot.constraints import check, check_all, resolve


def st(ings, r):
    return check(ings, r)["state"]


def test_coconut_milk_not_dairy():
    assert st(["1 cup coconut milk"], "dairy") == "free"


def test_milk_and_butter_are_dairy():
    assert st(["1 cup whole milk"], "dairy") == "contains" and st(["2 tbsp unsalted butter"], "dairy") == "contains"


def test_butternut_squash_not_dairy_and_eggplant_not_egg():
    assert st(["1 butternut squash"], "dairy") == "free" and st(["1 eggplant"], "egg") == "free"


def test_nutmeg_not_tree_nut_and_almond_is():
    assert st(["1/4 tsp ground nutmeg"], "tree_nut") == "free" and st(["1/2 cup sliced almonds"], "tree_nut") == "contains"


def test_peanut_oil_is_possible_for_peanut():
    r = check(["2 tablespoons peanut oil"], "peanut")
    assert r["state"] == "possible" and r["evidence"][0][0] == 0 and "peanut oil" in r["evidence"][0][2]


def test_peanut_oil_definite_when_config_says_so():
    cfg = {"restrictions": {"peanut": {"definite": ["peanut", "peanut oil"], "may_contain": [], "exceptions": [], "global_exceptions": []}}}
    assert check(["peanut oil"], "peanut", config=cfg)["state"] == "contains"


def test_peanut_butter_contains_peanut_but_not_dairy():
    assert st(["1 cup peanut butter"], "peanut") == "contains" and st(["1 cup peanut butter"], "dairy") == "free"


def test_cocoa_butter_and_apple_butter_not_dairy():
    assert st(["1 oz cocoa butter"], "dairy") == "free" and st(["1 cup apple butter"], "dairy") == "free"


def test_cream_of_tartar_not_dairy_but_heavy_cream_is():
    assert st(["1 tsp cream of tartar"], "dairy") == "free" and st(["1 cup heavy cream"], "dairy") == "contains"


def test_margarine_and_chocolate_are_possible_dairy():
    assert st(["1/2 cup margarine"], "dairy") == "possible" and st(["1 cup chocolate chips"], "dairy") == "possible"


def test_state_is_worst_of_all_ingredients_with_all_evidence():
    r = check(["1 cup flour", "1 cup margarine", "2 tbsp butter"], "dairy")
    assert r["state"] == "contains" and [e[0] for e in r["evidence"]] == [1, 2]


def test_free_has_note_and_no_evidence():
    r = check(["2 cups rice", "1 tsp salt"], "dairy")
    assert r["state"] == "free" and r["evidence"] == [] and "not verified" in r["note"]


def test_global_exception_dairy_free_butter():
    assert st(["1 cup dairy-free butter"], "dairy") == "free" and st(["1 cup vegan cheese"], "dairy") == "free"


def test_alternative_hit_is_possible():
    r = check(["1/2 cup olive oil or butter"], "dairy")
    assert r["state"] == "possible" and "alternative" in r["evidence"][0][2]


def test_main_hit_beats_alternative():
    assert st(["1/2 cup butter or margarine"], "dairy") == "contains"


def test_gluten_flour_and_gluten_free_flour():
    assert st(["2 cups all-purpose flour"], "gluten") == "contains" and st(["2 cups gluten-free flour blend"], "gluten") == "free"
    assert st(["1 cup rice flour"], "gluten") == "free"


def test_gluten_soy_sauce_possible_and_pasta_contains():
    assert st(["2 tbsp soy sauce"], "gluten") == "possible" and st(["1 lb penne pasta"], "gluten") == "contains"


def test_egg_mayonnaise_and_egg_replacer():
    assert st(["1/2 cup mayonnaise"], "egg") == "contains" and st(["1 tbsp egg replacer"], "egg") == "free"
    assert st(["2 large eggs"], "egg") == "contains"


def test_shellfish_and_oyster_mushroom():
    assert st(["1 lb shrimp, peeled"], "shellfish") == "contains" and st(["8 oz oyster mushrooms"], "shellfish") == "free"
    assert st(["1 lb prawns"], "shellfish") == "contains"


def test_soy_tofu_contains_and_vegetable_oil_possible():
    assert st(["1 block tofu"], "soy") == "contains" and st(["2 tbsp vegetable oil"], "soy") == "possible"


def test_pork_bacon_vs_turkey_bacon():
    assert st(["4 slices bacon"], "pork") == "contains" and st(["4 slices turkey bacon"], "pork") == "free"
    assert st(["1 cup chicken broth"], "pork") == "free" and st(["1 cup broth"], "pork") == "possible"


def test_beef_ground_beef_and_tuna_steak():
    assert st(["1 lb ground beef"], "beef") == "contains" and st(["1 tuna steak"], "beef") == "free"
    assert st(["1 steak"], "beef") == "possible"


def test_alcohol_wine_vs_wine_vinegar_and_vanilla():
    assert st(["1/2 cup dry red wine"], "alcohol") == "contains" and st(["2 tbsp red wine vinegar"], "alcohol") == "free"
    assert st(["1 tsp vanilla extract"], "alcohol") == "possible" and st(["1 cup ginger beer"], "alcohol") == "free"


def test_vegetarian_meat_fish_and_veg_broth():
    assert st(["1 lb chicken breast"], "vegetarian") == "contains" and st(["2 cups vegetable broth"], "vegetarian") == "free"
    assert st(["2 cups broth"], "vegetarian") == "possible" and st(["2 eggs", "1 cup milk"], "vegetarian") == "free"
    assert st(["1 stalk celery rib"], "vegetarian") == "free"


def test_restriction_aliases_and_unknown():
    assert resolve("dairy-free") == ["dairy"] and resolve("No Peanuts") == ["peanut"] and resolve("nuts") == ["tree_nut", "peanut"]
    assert resolve("vegan") == ["vegetarian", "dairy", "egg"]
    with pytest.raises(ValueError):
        check(["egg"], "unobtainium")


def test_multi_key_alias_merges_worst_state():
    r = check(["1 cup peanut butter"], "nuts")
    assert r["state"] == "contains" and r["restriction"] == "tree_nut+peanut"


def test_check_all_overall():
    r = check_all(["1 cup milk", "2 eggs"], ["dairy", "egg", "peanut"])
    assert r["_overall"] == "contains" and r["peanut"]["state"] == "free"


def test_accepts_parsed_dicts_with_original_positions():
    parsed = [{"canon": "flour", "raw": "1 cup flour", "pos": 0}, {"canon": "milk", "raw": "1 cup milk", "pos": 3}]
    assert check(parsed, "dairy")["evidence"][0][:2] == (3, "1 cup milk")
