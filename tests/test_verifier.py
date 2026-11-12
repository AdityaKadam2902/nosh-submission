import pytest

from recipebot.verifier import verify

RESULT = {"rows": [{"id": "ar:abc.DEF/ghi", "title": "Penne", "n_steps": 3}, {"id": "fn:zzz..", "title": "Salad", "n_steps": 2}],
          "count": 16319, "percentage": 13.2790, "denominator": 122918}
RECEIPT = {"recipe_ids": ["ar:abc.DEF/ghi", "fn:zzz.."], "dataset": {"valid": 122918}}


def v(prose):
    return verify(prose, RESULT, RECEIPT)


def test_clean_prose_passes_with_rounding_and_separators():
    r = v("16,319 of 122,918 recipes (13.28%, about 13%) match; ar:abc.DEF/ghi has 3 steps.")
    assert r.ok, r.problems


def test_injected_fake_id_is_blocked():
    r = v("Try ar:abc.DEF/ghi or fn:FAKE123.")
    assert not r.ok and any("fn:FAKE123" in p for p in r.problems)


def test_id_with_trailing_punctuation_is_matched():
    assert v("See fn:zzz.. now.").ok and v("(ar:abc.DEF/ghi), then fn:zzz...").ok  # a trailing sentence period is tolerated


def test_id_followed_by_sentence_period_ok():
    assert v("Best is ar:abc.DEF/ghi.").ok


def test_invented_number_blocked():
    r = v("It has 4 steps.")
    assert not r.ok and any("4" in p for p in r.problems)


def test_number_inside_id_not_treated_as_prose_number():
    assert v("ar:abc.DEF/ghi is fine.").ok


def test_count_of_items_is_allowed():
    assert v("Here are 2 recipes.").ok


@pytest.mark.parametrize("text", ["This is safe for you.", "Guaranteed dairy-free.", "It is allergen-free.", "100% free of nuts", "risk-free"])
def test_banned_claims(text):
    assert not v(text).ok


def test_unsafe_word_not_flagged_as_safe_claim():
    assert v("Not verified; cross-contamination is possible.").ok


def test_wrong_percentage_blocked():
    assert not v("That is 14% of recipes.").ok
