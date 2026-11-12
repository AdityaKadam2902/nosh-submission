import pytest

from recipebot.state import ConversationState, Op, apply_ops, resolve_reference, set_results, state_summary


def ops(*specs):
    return [Op(field=f, op=o, values=v if isinstance(v, list) else [v]) for f, o, v in specs]


def test_restrictions_persist_through_refine_and_new_topic():
    s = ConversationState()
    s, _ = apply_ops(s, ops(("dish_query", "set", "penne pasta")))
    s, _ = apply_ops(s, ops(("restrictions", "add", "dairy")))
    s, _ = apply_ops(s, ops(("exclude", "add", "mushrooms")))
    assert (s.dish_query, s.restrictions, s.exclude) == ("penne pasta", ["dairy"], ["mushroom"])
    s = set_results(s, ["ar:1", "ar:2"], "search")
    s, notes = apply_ops(s, ops(("dish_query", "set", "tomato soup"), ("include", "add", "basil")), new_topic=True)
    assert s.restrictions == ["dairy"] and s.exclude == ["mushroom"] and s.include == ["basil"] and s.last_ids == [] and notes


def test_restriction_aliases_and_unknown():
    s, notes = apply_ops(ConversationState(), ops(("restrictions", "add", ["dairy-free", "No Peanuts", "nuts", "gravity"])))
    assert s.restrictions == ["dairy", "peanut", "tree_nut"] and any("gravity" in n for n in notes)


def test_restriction_removed_only_when_explicit():
    s, _ = apply_ops(ConversationState(restrictions=["dairy", "egg"]), ops(("restrictions", "remove", "dairy")))
    assert s.restrictions == ["egg"]
    s, _ = apply_ops(s, ops(("restrictions", "clear", [])))
    assert s.restrictions == []


def test_include_exclude_are_canonicalized_and_deduped():
    s, _ = apply_ops(ConversationState(), ops(("include", "add", ["Scallions", "green onions", "Onions"]), ("exclude", "add", "eggs")))
    assert s.include == ["green onion", "onion"] and s.exclude == ["egg"]


def test_adding_to_include_removes_from_exclude_with_note():
    s, notes = apply_ops(ConversationState(exclude=["egg"]), ops(("include", "add", "eggs")))
    assert s.exclude == [] and s.include == ["egg"] and notes


def test_exclude_removal_and_clear():
    s, _ = apply_ops(ConversationState(exclude=["egg", "mushroom"]), ops(("exclude", "remove", "eggs")))
    assert s.exclude == ["mushroom"]


def test_max_steps_set_clear_and_garbage():
    s, _ = apply_ops(ConversationState(), ops(("max_steps", "set", "6 steps")))
    assert s.max_steps == 6
    s, notes = apply_ops(s, ops(("max_steps", "set", "few")))
    assert s.max_steps == 6 and notes
    s, _ = apply_ops(s, ops(("max_steps", "clear", [])))
    assert s.max_steps is None


def test_available_parses_quantities_and_merges():
    s, _ = apply_ops(ConversationState(), ops(("available", "add", ["2 eggs", "1 onion", "rice"])))
    assert [(i.name, i.qty) for i in s.available] == [("egg", 2.0), ("onion", 1.0), ("rice", None)]
    s, _ = apply_ops(s, ops(("available", "add", "4 eggs"), ("available", "remove", "rice")))
    assert [(i.name, i.qty) for i in s.available] == [("egg", 4.0), ("onion", 1.0)]


def test_apply_ops_is_pure():
    s0 = ConversationState(exclude=["egg"])
    apply_ops(s0, ops(("exclude", "add", "milk")))
    assert s0.exclude == ["egg"]


def test_unknown_ingredient_noted_not_added():
    s, notes = apply_ops(ConversationState(), ops(("exclude", "add", "ADVERTISEMENT")))
    assert s.exclude == [] and notes


@pytest.mark.parametrize("text,expect", [("show the second one", "b"), ("tell me about #3", "c"), ("option 1 please", "a"), ("the 2nd recipe", "b"),
                                          ("the last one", "c"), ("show 3", "c"), ("what about the fifth one", None), ("show #9", None)])
def test_resolve_reference_from_last_ids(text, expect):
    assert resolve_reference(text, ConversationState(last_ids=["a", "b", "c"])) == expect


def test_resolve_that_recipe_uses_focus_or_single_result():
    assert resolve_reference("how long does that recipe take", ConversationState(focus_recipe_id="x", last_ids=["a", "b"])) == "x"
    assert resolve_reference("show that one", set_results(ConversationState(), ["only"], "search")) == "only"
    assert resolve_reference("show that one", ConversationState(last_ids=["a", "b"])) is None


def test_set_results_updates_last_ids_and_intent():
    s = set_results(ConversationState(), ["a", "b"], "search")
    assert s.last_ids == ["a", "b"] and s.last_intent == "search" and s.focus_recipe_id is None


def test_state_summary_mentions_restrictions():
    assert "dairy" in state_summary(ConversationState(restrictions=["dairy"]))


def test_new_topic_note_only_when_something_was_cleared():
    _, notes = apply_ops(ConversationState(), ops(("dish_query", "set", "penne")), new_topic=True)
    assert notes == []
    _, notes = apply_ops(ConversationState(dish_query="soup"), ops(("dish_query", "set", "penne")), new_topic=True)
    assert notes and "new topic" in notes[0]
