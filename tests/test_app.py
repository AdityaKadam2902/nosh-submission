"""UI logic tests (no Streamlit needed) + an AppTest smoke test when streamlit is installed. Mock LLM only."""
import json
import threading

import pytest

import app
from recipebot.db import SOURCE_FILES, SOURCES
from recipebot.llm import LLM
from recipebot.orchestrator import Orchestrator
from recipebot.planner import Plan
from recipebot.state import ConversationState, Ingredient
from scripts.build_db import build

RAW = {"ar": {"a1": {"title": "Garlic Onion Soup ADVERTISEMENT", "ingredients": ["2 cloves garlic ADVERTISEMENT", "1 onion"], "instructions": "Chop.\nSimmer.\nServe ADVERTISEMENT", "picture_link": None},
              "a2": {"title": "Tomato Soup", "ingredients": ["4 tomatoes", "1 onion"], "instructions": "Cook.\nBlend.", "picture_link": None}},
       "epi": {}, "fn": {}}


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    t = tmp_path_factory.mktemp("a")
    d = t / "raw"
    d.mkdir()
    for s in SOURCES:
        (d / SOURCE_FILES[s]).write_text(json.dumps(RAW[s]), encoding="utf-8")
    build(d, t / "a.db", log=lambda *_: None)
    return t / "a.db"


@pytest.fixture
def conn(db):
    c = app.open_conn(db)
    yield c
    c.close()


def mock_orch(conn, plans):
    def backend(model, prompt, system, schema, timeout):
        return plans[prompt.split("USER MESSAGE: ", 1)[1]].model_dump_json()
    return Orchestrator(LLM(model="m", backend=backend, cache_dir=None, sleep=lambda s: None, jitter=False, max_retries=0), conn, use_writer=False)


def test_app_imports_without_running_ui_and_missing_db_is_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="build_db"):
        app.open_conn(tmp_path / "nope.db")


def test_connection_is_usable_from_another_thread(conn):
    out = []
    t = threading.Thread(target=lambda: out.append(conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]))
    t.start(); t.join()
    assert out == [2]


def test_slash_commands_work_without_llm(conn):
    st = {}
    r = app.respond("/stats percentage --all garlic onion", st, conn, None)
    assert "50" in r["text"] and "--- RECEIPT ---" in r["text"] and r["llm_down"] is False
    r = app.respond("/search soup", st, conn, None)
    assert set(r["ids"]) >= {"ar:a1", "ar:a2"} and r["intent"] == "/search"
    assert app.respond("/show ar:a1", st, conn, None)["ids"] == ["ar:a1"]
    assert app.respond("   ", st, conn, None)["text"] == ""


def test_free_text_without_llm_degrades_gracefully(conn):
    r = app.respond("find soup", {}, conn, None)
    assert r["llm_down"] and "/help" in r["text"] and r["ids"] == []


def test_free_text_with_mock_orchestrator_keeps_state_and_ids(conn):
    from recipebot.planner import ToolArgs
    from recipebot.state import Op
    plans = {"find soup": Plan(intent="search", tool_args=ToolArgs(query="soup"), ops=[Op(field="dish_query", op="set", value="soup")], new_topic=True)}
    o, st = mock_orch(conn, plans), {}
    r = app.respond("find soup", st, conn, o)
    assert r["intent"] == "search" and "ar:a1" in r["ids"] and st["last_ids"] == o.state.last_ids
    assert ("dish query", "soup") in app.state_rows(o.state)


def test_llm_down_message_keeps_slash_hint(conn):
    def backend(*a):
        raise TimeoutError("down")
    o = Orchestrator(LLM(model="m", backend=backend, cache_dir=None, sleep=lambda s: None, jitter=False, max_retries=0), conn)
    r = app.respond("find soup", {}, conn, o)
    assert r["llm_down"] and "/search" in r["text"]


def test_make_orchestrator_never_raises_without_config(conn):
    o, msg = app.make_orchestrator(conn)  # conftest removes GEMINI_* env
    assert o is None and "slash commands only" in msg


def test_split_receipt_and_cited_ids():
    body, rc = app.split_receipt("answer\n\n--- RECEIPT ---\ntool: x\nrecipe ids: ar:a1, ar:a2")
    assert body == "answer" and rc.startswith("--- RECEIPT ---") and app.split_receipt("no receipt") == ("no receipt", "")
    assert app.cited_ids("see ar:a2, then ar:a1.", ["ar:a1"]) == ["ar:a1", "ar:a2"]


def test_evidence_shows_original_text_without_advertisement_noise(conn):
    ev = app.evidence(conn, "ar:a1")
    assert ev["title"] == "Garlic Onion Soup" and ev["ingredients"][0] == "2 cloves garlic" and "ADVERTISEMENT" not in ev["instructions"] and ev["instructions"].startswith("Chop.")
    assert app.evidence(conn, "ar:nope") is None
    stored = conn.execute("SELECT title FROM recipes WHERE id='ar:a1'").fetchone()[0]
    assert "ADVERTISEMENT" in stored  # display strips it; the stored original is untouched


def test_state_rows_only_non_empty():
    s = ConversationState(restrictions=["dairy"], max_steps=6, available=[Ingredient(name="egg")], last_ids=["ar:a1"])
    assert dict(app.state_rows(s)) == {"restrictions": "dairy", "max steps": "6", "available": "egg", "last results": "1 recipes"}
    assert app.state_rows(ConversationState()) == []


def test_streamlit_smoke(db, monkeypatch):
    pytest.importorskip("streamlit")
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("DB_PATH", str(db))
    at = AppTest.from_file(str(Path(__file__).resolve().parent.parent / "app.py"), default_timeout=30).run()
    assert not at.exception
    at.chat_input[0].set_value("/stats count --all onion").run()
    assert not at.exception and any("RECEIPT" in str(c.value) for c in at.code)
