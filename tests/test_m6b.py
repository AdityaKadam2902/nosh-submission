from recipebot.llm import LLM
from recipebot.orchestrator import Orchestrator
from recipebot.planner import Plan, ToolArgs
from tests.test_orchestrator import conn  # noqa: F401  (fixture: small DB with 6 valid recipes)


class Script:
    def __call__(self, model, prompt, system, schema, timeout):
        return Plan(intent="stats", tool_args=ToolArgs(stats_op="count", contains_all=["garlic", "onion"])).model_dump_json()


def test_count_plus_percentage_question_returns_both(conn):
    o = Orchestrator(LLM(model="m", backend=Script(), cache_dir=None), conn, use_writer=False)
    t = o.turn("How many recipes contain both garlic and onion, and what percentage is that?").text
    assert "2 of 6 = 33.33%" in t
    t2 = o.turn("How many recipes contain both garlic and onion?").text
    assert "2 of 6 valid recipes match" in t2  # plain count questions stay plain counts
