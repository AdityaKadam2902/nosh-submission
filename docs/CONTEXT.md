# CONTEXT (paste this first in every new chat, then attach ARCHITECTURE.md + the one milestone from BUILD_PLAN.md)

**Project:** RecipeBot, a take-home for NOSH Robotics (GenAI Intern). Conversational chatbot over the Recipe Box dataset (3 JSON files, ~125k recipes).
**Tasks:** T1 search + factual Q&A + stats. T2 ingredient-based matching/ranking. T3 evidence-based substitution. Weights 30/30/40.
**Principle:** *Evidence before generation.* The LLM never computes, filters, ranks or invents. Code does. The LLM only (a) turns user text into a typed plan, (b) writes prose around code-produced results. Every answer has a code-built RECEIPT.
**Stack:** Python 3.11, SQLite + FTS5, sentence-transformers + FAISS (optional index), Gemini via `google-genai` (model name from env `GEMINI_MODEL`), Pydantic, pytest, Streamlit + CLI. No LangChain.
**Deadline:** 3 days. Partial submission is acceptable, so the must-have path comes first.
**Owner style:** direct, token-efficient. Give targeted diffs/patches, not full-file regenerations, unless a file is new.
**Rules for the assistant in this chat:**
1. Do only the milestone I attach. Don't redesign the architecture. If you find a flaw, say it in 3 lines and propose a patch.
2. Follow ARCHITECTURE.md contracts (function names, schemas) exactly so modules fit together.
3. New files: full content. Existing files: minimal patch only.
4. Include/adjust pytest tests for what you write. Give the exact command to verify.
5. End with an updated `PROGRESS.md` block (done / decisions / known issues / next).
**Current progress:** (paste PROGRESS.md here)
