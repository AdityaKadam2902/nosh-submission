"""RecipeBot Streamlit UI.  Run: streamlit run app.py   (DB_PATH, GEMINI_API_KEY, GEMINI_MODEL from .env)
Chat via Orchestrator.turn(); every cited recipe id gets an evidence expander with the ORIGINAL recipe text; the sidebar shows the
conversation state with a reset button. If the LLM is unavailable, slash commands (/search /stats /match /sub /show) still work.
All logic lives in plain functions (testable without Streamlit); the UI is built in main()."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from recipebot.cli import handle
from recipebot.db import db_path
from recipebot.search import get_recipe
from recipebot.state import ConversationState
from recipebot.verifier import ID_RE

EXAMPLES = ["Find penne pasta", "I cannot have dairy", "How many recipes contain both garlic and onion, and what percentage is that?",
            "Which 5 recipes with tomato have the fewest steps?", "I have eggs, onions, tomatoes and rice. What can I cook in at most 6 steps, no peanuts?",
            "/sub 1 --replace egg", "/help"]
RECEIPT_MARK = "--- RECEIPT ---"
AD = re.compile(r"\s*ADVERTISEMENT\s*")
MAX_EVIDENCE = 12


# ---------------------------------------------------------------- logic (no Streamlit)
def open_conn(path=None) -> sqlite3.Connection:
    """Read-only connection usable from Streamlit's script threads."""
    p = Path(path or db_path())
    if not p.exists():
        raise FileNotFoundError(f"{p} not found. Build it: python -m scripts.build_db  (or set DB_PATH)")
    return sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True, check_same_thread=False)


def make_orchestrator(conn):
    """-> (Orchestrator | None, status message). Never raises: no key / no model / any init error -> slash-command-only mode."""
    try:
        from recipebot.llm import LLM
        from recipebot.orchestrator import Orchestrator
        llm = LLM()
        if not llm.model:
            return None, "LLM not configured (GEMINI_MODEL missing in .env): slash commands only"
        return Orchestrator(llm, conn), f"LLM: {llm.model}"
    except Exception as e:  # noqa: BLE001
        return None, f"LLM not available ({type(e).__name__}): slash commands only"


def split_receipt(text: str) -> tuple[str, str]:
    body, sep, rest = (text or "").partition(RECEIPT_MARK)
    return body.rstrip(), (RECEIPT_MARK + rest) if sep else ""


def cited_ids(text: str, extra=()) -> list[str]:
    """ids in the order cited (result ids first, then ids mentioned in the text), de-duplicated."""
    found = [m.group().rstrip(".,;:)]}'\"") for m in ID_RE.finditer(text or "")]
    return list(dict.fromkeys(list(extra) + found))


def respond(line: str, cli_state: dict, conn, orch) -> dict:
    """One chat turn -> {text, ids, intent, llm_down, notes}. Slash commands go to cli.handle (no LLM); free text needs the orchestrator."""
    line = (line or "").strip()
    if not line:
        return {"text": "", "ids": [], "intent": None, "llm_down": False}
    if line.startswith("/"):
        out = handle(line, cli_state, conn, orch)
        return {"text": out, "ids": cited_ids(out, cli_state.get("last_ids", [])[:MAX_EVIDENCE] if line.split()[0] in ("/search", "/match", "/stats") else []), "intent": line.split()[0], "llm_down": False}
    if orch is None:
        return {"text": "Free-text chat needs the LLM (GEMINI_API_KEY and GEMINI_MODEL in .env). Slash commands still work: try /help.", "ids": [], "intent": None, "llm_down": True}
    r = orch.turn(line)
    cli_state["last_ids"] = list(orch.state.last_ids)
    text = r.text + (f"\n\n(LLM unavailable right now: {r.error or 'see /help'}. Slash commands still work.)" if r.llm_down and r.error else "")
    return {"text": text, "ids": cited_ids(r.text, r.ids), "intent": r.intent, "llm_down": r.llm_down}


def evidence(conn, rid: str) -> dict | None:
    """Original recipe text for the evidence panel (display strips the literal 'ADVERTISEMENT'; the stored original is untouched)."""
    r = get_recipe(rid, conn=conn)
    if r is None:
        return None
    return {"id": rid, "title": AD.sub(" ", r["title"] or "").strip(), "source": r["source"], "valid": bool(r["is_valid"]), "n_steps": r["n_steps"],
            "ingredients": [AD.sub(" ", x).strip() for x in (r["ingredients"] or [])], "instructions": AD.sub(" ", r["instructions"] or "").strip()}


def state_rows(s: ConversationState) -> list[tuple[str, str]]:
    rows = [("dish query", s.dish_query), ("include", ", ".join(s.include)), ("exclude", ", ".join(s.exclude)), ("restrictions", ", ".join(s.restrictions)),
            ("max steps", s.max_steps), ("available", ", ".join(i.name for i in s.available)), ("preferences", ", ".join(s.preferences)),
            ("focus recipe", s.focus_recipe_id), ("last results", f"{len(s.last_ids)} recipes" if s.last_ids else None)]
    return [(k, str(v)) for k, v in rows if v not in (None, "", 0)]


# ---------------------------------------------------------------- UI
def main() -> None:  # pragma: no cover - exercised by streamlit
    import streamlit as st
    st.set_page_config(page_title="RecipeBot", page_icon="🍳", layout="wide")

    @st.cache_resource
    def get_conn():
        return open_conn()

    try:
        conn = get_conn()
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()
    ss = st.session_state
    if "orch" not in ss:  # one Orchestrator (= one conversation state) PER browser session, never shared
        ss.orch, ss.status = make_orchestrator(conn)
    orch, status = ss.orch, ss.status
    ss.setdefault("messages", [])
    ss.setdefault("cli_state", {})
    ss.setdefault("pending", None)

    with st.sidebar:
        st.header("RecipeBot")
        st.caption(f"DB: {db_path()}  \n{status}")
        st.subheader("Conversation state")
        rows = state_rows(orch.state) if orch else []
        if rows:
            for k, v in rows:
                st.markdown(f"**{k}:** {v}")
        else:
            st.caption("(empty)" if orch else "(state is kept only in LLM chat mode)")
        if st.button("Reset conversation"):
            if orch:
                orch.reset()
            ss.messages, ss.cli_state, ss.pending = [], {}, None
            st.rerun()
        st.subheader("Try")
        for i, ex in enumerate(EXAMPLES):
            if st.button(ex, key=f"ex{i}", use_container_width=True):
                ss.pending = ex
        st.caption("Evidence before generation: numbers, filters and ids are computed by code; the LLM only plans and phrases. Not medical advice; allergen labels and cross-contamination are not verified.")

    st.title("🍳 RecipeBot")
    for m in ss.messages:
        with st.chat_message(m["role"]):
            render(st, conn, m)
    line = st.chat_input("Ask in plain English, or use /search /stats /match /sub /show") or ss.pending
    ss.pending = None
    if line:
        ss.messages.append({"role": "user", "text": line})
        with st.chat_message("user"):
            st.write(line)
        with st.chat_message("assistant"):
            with st.spinner("working..."):
                try:
                    res = respond(line, ss.cli_state, conn, orch)
                except Exception as e:  # noqa: BLE001 - never a stack trace in the chat
                    res = {"text": f"Something went wrong ({type(e).__name__}: {e}). Try a slash command, see /help.", "ids": []}
            msg = {"role": "assistant", **res}
            ss.messages.append(msg)
        st.rerun()  # redraw from history so the sidebar state is current


def render(st, conn, m: dict) -> None:  # pragma: no cover
    if m["role"] == "user":
        st.write(m["text"])
        return
    body, receipt = split_receipt(m["text"])
    st.code(body, language=None) if "\n" in body else st.write(body)
    if receipt:
        with st.expander("Receipt (how this was computed)"):
            st.code(receipt, language=None)
    ids = m.get("ids", [])[:MAX_EVIDENCE]
    for rid in ids:
        ev = evidence(conn, rid)
        if ev is None:
            continue
        with st.expander(f"Evidence {rid}: {ev['title']}"):
            st.caption(f"source {ev['source']} | {ev['n_steps']} estimated steps | original text (display strips the literal 'ADVERTISEMENT')")
            st.markdown("**Ingredients**\n" + "\n".join(f"- {x}" for x in ev["ingredients"]))
            st.markdown("**Instructions**\n\n" + ev["instructions"])


if __name__ == "__main__":
    main()
