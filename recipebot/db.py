"""SQLite helpers + schema (ARCHITECTURE §2). M0 scope: schema, ids, validity, originals round-trip.

Originals (title, ingredients_json, instructions, picture_link) are stored untouched.
Normalization columns (n_ingredients, n_steps, n_steps_alt) and the `ingredients` table
stay empty until M1. recipes_fts is created in M2.
"""
from __future__ import annotations

import html
import json
import os
import re
import sqlite3
from pathlib import Path

try:  # optional: load .env if python-dotenv is installed
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

SOURCES = ("ar", "epi", "fn")
SOURCE_FILES = {s: f"recipes_raw_nosource_{s}.json" for s in SOURCES}
ORIGINAL_FIELDS = ("title", "ingredients", "instructions", "picture_link")
AD_TOKEN = "ADVERTISEMENT"

SCHEMA = """
CREATE TABLE recipes (
    id TEXT PRIMARY KEY,          -- "ar:<orig_key>" | "epi:<orig_key>" | "fn:<orig_key>"
    source TEXT NOT NULL,
    orig_key TEXT NOT NULL,
    title TEXT,                   -- ORIGINAL, untouched
    ingredients_json TEXT,        -- ORIGINAL list as JSON, untouched (incl. noise)
    instructions TEXT,            -- ORIGINAL, untouched
    picture_link TEXT,
    is_valid INT NOT NULL,
    invalid_reason TEXT,          -- comma-joined: malformed_record,no_title,no_ingredients,no_instructions
    n_ingredients INT,            -- M1
    n_steps INT,                  -- M1
    n_steps_alt INT               -- M1
);
CREATE INDEX idx_recipes_source ON recipes(source);
CREATE INDEX idx_recipes_valid ON recipes(is_valid);
CREATE TABLE ingredients (        -- filled in M1
    recipe_id TEXT, pos INT, raw TEXT, canon TEXT, qty REAL, unit TEXT, forms TEXT, alts TEXT
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


# ---------- paths / connection ----------
def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "data/raw"))


def db_path() -> Path:
    return Path(os.environ.get("DB_PATH", "data/recipes.db"))


def find_source_file(directory: Path, src: str) -> Path:
    """Canonical filename first, else any '*_<src>.json' in the directory."""
    directory = Path(directory)
    canonical = directory / SOURCE_FILES[src]
    if canonical.exists():
        return canonical
    matches = sorted(directory.glob(f"*_{src}.json"))
    if matches:
        return matches[0]
    raise FileNotFoundError(f"No JSON for source '{src}' in {directory} (expected {SOURCE_FILES[src]}). Run `make data`.")


def connect(path: Path | str | None = None, readonly: bool = False) -> sqlite3.Connection:
    path = Path(path or db_path())
    if readonly:
        if not path.exists():
            raise FileNotFoundError(f"{path} not found. Run `make build`.")
        return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path)


# ---------- ids ----------
def make_id(src: str, orig_key: str) -> str:
    return f"{src}:{orig_key}"


def split_id(recipe_id: str) -> tuple[str, str]:
    src, _, key = recipe_id.partition(":")
    return src, key


# ---------- cleaning helpers (DERIVED values only; originals are never modified) ----------
def _txt(s: str) -> str:
    return html.unescape(s).replace("\xa0", " ").strip()


def clean_ingredient_lines(ingredients) -> list[str]:
    """Non-blank, non-ADVERTISEMENT string lines. M1 may refine; M0 definition for is_valid."""
    if not isinstance(ingredients, list):
        return []
    out = []
    for x in ingredients:
        if isinstance(x, str):
            t = _txt(x)
            if t and t.upper() != AD_TOKEN:
                out.append(t)
    return out


def strip_ads(text: str) -> str:
    return text.replace(AD_TOKEN, "")


def has_instruction_text(instructions) -> bool:
    """At least one letter left after removing ADVERTISEMENT (bare numbering doesn't count)."""
    if not isinstance(instructions, str):
        return False
    return re.search(r"[^\W\d_]", _txt(strip_ads(instructions))) is not None


def validate(rec) -> tuple[int, str | None]:
    """is_valid = title non-empty AND >=1 clean ingredient AND >=1 instruction text (ARCHITECTURE §2)."""
    if not isinstance(rec, dict):
        return 0, "malformed_record"
    reasons = []
    title = rec.get("title")
    if not (isinstance(title, str) and _txt(title)):
        reasons.append("no_title")
    if not clean_ingredient_lines(rec.get("ingredients")):
        reasons.append("no_ingredients")
    if not has_instruction_text(rec.get("instructions")):
        reasons.append("no_instructions")
    return (0, ",".join(reasons)) if reasons else (1, None)


# ---------- ingest / round-trip ----------
def recipe_row(src: str, orig_key: str, rec, derived: tuple | None = None) -> tuple:
    """derived = (is_valid, reason, n_ingredients, n_steps, n_steps_alt) from M1; None -> M0 validity, NULL counts."""
    r = rec if isinstance(rec, dict) else {}
    is_valid, reason = validate(rec)
    extra = (None, None, None)
    if derived:
        is_valid, reason, *extra = derived
    return (
        make_id(src, orig_key), src, orig_key,
        r.get("title"),
        json.dumps(r.get("ingredients"), ensure_ascii=False),
        r.get("instructions"),
        r.get("picture_link"),
        is_valid, reason, *extra,
    )


INSERT_SQL = (
    "INSERT INTO recipes (id, source, orig_key, title, ingredients_json, instructions, picture_link, "
    "is_valid, invalid_reason, n_ingredients, n_steps, n_steps_alt) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
)
ING_INSERT_SQL = "INSERT INTO ingredients (recipe_id, pos, raw, canon, qty, unit, forms, alts) VALUES (?,?,?,?,?,?,?,?)"


def get_original(conn: sqlite3.Connection, recipe_id: str) -> dict | None:
    """Reconstruct the original JSON record (the 4 dataset fields) from the DB row."""
    row = conn.execute(
        "SELECT title, ingredients_json, instructions, picture_link FROM recipes WHERE id=?", (recipe_id,)
    ).fetchone()
    if row is None:
        return None
    title, ij, instructions, pic = row
    return {"title": title, "ingredients": json.loads(ij), "instructions": instructions, "picture_link": pic}
