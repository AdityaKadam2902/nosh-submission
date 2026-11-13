"""Eval harness tests on a FIXED mini DB, mock LLM only (never the real one). Includes mutation tests: the harness must CATCH a wrong
stats answer, a hard-constraint leak and a hallucinated id."""
import copy
import json
import sys

import pytest

sys.path.insert(0, "tests")
from test_substitute import RAW as SUB_RAW  # noqa: E402

from eval import baseline_oneshot as bo  # noqa: E402
from eval import run_eval as ev  # noqa: E402
from recipebot.db import SOURCE_FILES, SOURCES  # noqa: E402
from recipebot.llm import LLM  # noqa: E402
from recipebot.planner import Plan  # noqa: E402
from scripts.build_db import build  # noqa: E402


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    t = tmp_path_factory.mktemp("e")
    raw = copy.deepcopy(SUB_RAW)
    raw["ar"]["sf0"] = {"title": "Saffron Rice", "ingredients": ["1 cup rice", "1 pinch saffron"], "instructions": "Boil.\nSteam.", "picture_link": None}
    raw["ar"]["pn1"] = {"title": "Penne Dairy", "ingredients": ["1 pound penne pasta", "1 cup milk", "1 tomato"], "instructions": "Boil.\nMix.\nServe.", "picture_link": None}
    raw["ar"]["pn2"] = {"title": "Penne Plain", "ingredients": ["1 pound penne pasta", "1 tomato", "1 onion"], "instructions": "Boil.\nMix.", "picture_link": None}
    d = t / "raw"
    d.mkdir()
    for s in SOURCES:
        (d / SOURCE_FILES[s]).write_text(json.dumps(raw[s]), encoding="utf-8")
    build(d, t / "e.db", log=lambda *_: None)
    return t / "e.db"


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the real LLM must never be constructed in tests")
    monkeypatch.setattr("recipebot.llm.GeminiBackend", boom)


def by_id(results):
    return {r["id"]: r for r in results}


def test_tools_only_run_all_pass_zero_violations_and_no_llm(db):
    cx, res = ev.run_all(db, llm=False)
    r = by_id(res)
    assert not [x for x in res if x["status"] == "fail"], [x for x in res if x["status"] == "fail"]
    assert cx.m["violations"] == 0 and cx.m["hallucinated_ids"] == 0 and cx.m["ids_checked"] > 20
    assert all(r[f"S{i:02d}"]["status"] == "pass" for i in range(1, 11)) and len(res) == 30
    for t in ("T01", "T02", "T03", "T04", "T05"):  # every T3 case found a recipe in this fixture and ran
        assert r[t]["status"] == "pass", r[t]
    assert "abstained" in r["T04"]["why"] and "grade=insufficient" in r["T04"]["why"] and r["M03"]["why"].startswith("NO_MATCH")
    assert all(r[c]["status"] == "skip" for c in ("C01", "C02", "C03", "C04"))  # chat needs --llm


def test_report_has_required_sections(db, tmp_path):
    out = tmp_path / "R.md"
    assert ev.main(["--tools-only", "--db", str(db), "--out", str(out)]) == 0
    t = out.read_text(encoding="utf-8")
    for s in ("## Summary", "| id | task | kind | result | why |", "## System vs one-shot baseline", "## Failures and causes", "hard-constraint violations", "hallucinated recipe ids", "No baseline answers are fabricated"):
        assert s in t
    assert (tmp_path / "R.md").exists()


def test_mutation_wrong_stats_number_is_caught(db, monkeypatch):
    import recipebot.stats as st
    real = st.run_stats

    def bad(spec, db=None, conn=None):
        r = real(spec, db=db, conn=conn)
        if spec["op"] == "count":
            r["answer_data"]["count"] += 1
        return r
    monkeypatch.setattr(st, "run_stats", bad)
    cx, res = ev.run_all(db, llm=False, only=["S01", "S05"])
    r = by_id(res)
    assert r["S01"]["status"] == "fail" and "reference" in r["S01"]["why"] and r["S05"]["status"] == "pass"


def test_mutation_dairy_leak_and_fake_id_are_caught(db, monkeypatch):
    import recipebot.search as se
    real = se.search

    def leaky(*a, **k):
        r = real(*a, **k)
        r["rows"] = r["rows"] + [{"id": "ar:pn1", "title": "x"}, {"id": "ar:does-not-exist", "title": "x"}]  # pn1 contains milk; second id is invented
        return r
    monkeypatch.setattr(se, "search", leaky)
    cx, res = ev.run_all(db, llm=False, only=["R01"])
    r = by_id(res)["R01"]
    assert r["status"] == "fail" and "HARD VIOLATION ar:pn1" in r["why"] and "does not exist" in r["why"]
    assert cx.m["violations"] >= 1 and cx.m["hallucinated_ids"] == 1
    assert ev.main(["--tools-only", "--db", str(db), "--cases", "R01", "--out", str(db.parent / "x.md")]) == 1  # non-zero exit for CI


def test_mutation_substitute_evidence_id_that_contains_target_is_caught(db, monkeypatch):
    import recipebot.substitute as sb
    real = sb.substitute

    def bad(*a, **k):
        r = real(*a, **k)
        for c in r["candidates"]:
            c["support_ids"] = ["ar:bb0"] + c["support_ids"][1:]  # bb0 contains egg
        return r
    monkeypatch.setattr(sb, "substitute", bad)
    _, res = ev.run_all(db, llm=False, only=["T01"])
    assert by_id(res)["T01"]["status"] == "fail" and "contains the target" in by_id(res)["T01"]["why"]


def test_match_no_match_case_must_abstain(db, monkeypatch):
    import recipebot.match as mt
    real = mt.match
    monkeypatch.setattr(mt, "match", lambda *a, **k: {**real(*a, **k), "no_match": False, "rows": [{"id": "ar:pn1"}]})
    _, res = ev.run_all(db, llm=False, only=["M03"])
    assert by_id(res)["M03"]["status"] == "fail"


def test_baseline_judging_and_report_shows_verbatim_wrong_answer(db, tmp_path, monkeypatch):
    assert bo.first_number("About 12,345 recipes.") == 12345.0 and bo.first_number("no idea") is None
    assert bo.judge("count", {"count": 10}, "10 recipes")[0] and not bo.judge("count", {"count": 10}, "about 11")[0]
    assert bo.judge("percentage", {"percentage": 12.34}, "12.3%")[0] and not bo.judge("percentage", {"percentage": 12.34}, "15%")[0]
    cache = {"S01": {"question": "q", "model": "m-test", "answer": "Roughly 99999 recipes contain garlic and onion."},
             "S02": {"question": "q", "model": "m-test", "answer": "unknown"}}
    monkeypatch.setattr(ev, "load_cache", lambda: cache)
    out = tmp_path / "B.md"
    ev.main(["--tools-only", "--baseline", "--db", str(db), "--cases", "S01", "S02", "--out", str(out)])
    t = out.read_text(encoding="utf-8")
    assert "Verbatim wrong one-shot answer (S01" in t and "Roughly 99999 recipes" in t and "WRONG" in t and "baseline" in t.lower()


def test_chat_case_with_mock_llm(db, monkeypatch):
    from recipebot.state import Op
    from recipebot.planner import ToolArgs
    plans = {"Find penne pasta": Plan(intent="search", tool_args=ToolArgs(query="penne pasta"), ops=[Op(field="dish_query", op="set", value="penne pasta")], new_topic=True),
             "I cannot have dairy": Plan(intent="followup_refine", ops=[Op(field="restrictions", op="add", value="dairy")]),
             "also no mushrooms": Plan(intent="followup_refine", ops=[Op(field="exclude", op="add", value="mushrooms")])}

    def backend(model, prompt, system, schema, timeout):
        return plans[prompt.split("USER MESSAGE: ", 1)[1]].model_dump_json()
    llm = LLM(model="m", backend=backend, cache_dir=None, sleep=lambda s: None, jitter=False, max_retries=0)
    monkeypatch.setenv("RECIPEBOT_WRITER", "off")
    monkeypatch.setattr("recipebot.llm.LLM", lambda: llm)
    cx, res = ev.run_all(db, llm=True, only=["C01"])
    r = by_id(res)["C01"]
    assert r["status"] == "pass", r  # restrictions persisted, ids exist, 0 'contains dairy'
    assert cx.m["hallucinated_ids"] == 0 and cx.m["violations"] == 0


def test_chat_case_skips_when_llm_down(db, monkeypatch):
    def backend(*a):
        raise TimeoutError("down")
    llm = LLM(model="m", backend=backend, cache_dir=None, sleep=lambda s: None, jitter=False, max_retries=0)
    monkeypatch.setattr("recipebot.llm.LLM", lambda: llm)
    _, res = ev.run_all(db, llm=True, only=["C02"])
    assert by_id(res)["C02"]["status"] == "skip" and "LLM unavailable" in by_id(res)["C02"]["why"]
