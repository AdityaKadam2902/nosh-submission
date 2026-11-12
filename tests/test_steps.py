import pytest

from recipebot.steps import count_steps, split_sentences


def test_blocks_primary_and_sentence_alt():
    assert count_steps("Chop onions.\nSaute in oil. Add garlic.\nServe.") == (3, 4)


def test_single_paragraph_uses_sentences():
    assert count_steps("Mix flour and sugar. Add eggs. Bake 30 minutes at 350 degrees.") == (3, 3)


def test_advertisement_and_bare_numbering_ignored():
    assert count_steps("1.\nBoil water.\nADVERTISEMENT\n2.\nAdd pasta.\n  \n") == (2, 2)


def test_advertisement_inline_removed():
    assert count_steps("Stir well. ADVERTISEMENT Serve hot.") == (2, 2)


def test_numbering_inside_paragraph_not_counted():
    assert count_steps("1. Boil water. 2. Add pasta. 3. Drain.") == (3, 3)


def test_abbreviations_and_decimals_do_not_split():
    assert count_steps("Add 2 tbsp. Butter and 1.5 oz. Sugar. Stir.") == (2, 2)


def test_lowercase_continuation_not_split():
    assert split_sentences("Heat oil in a pan. then add onions.") == ["Heat oil in a pan. then add onions."]


@pytest.mark.parametrize("val", [None, "", "   ", "ADVERTISEMENT", "1.\n2.", 5])
def test_empty_inputs_are_zero(val):
    assert count_steps(val) == (0, 0)


def test_single_block_no_punctuation_is_one_step():
    assert count_steps("Mix everything and bake") == (1, 1)
