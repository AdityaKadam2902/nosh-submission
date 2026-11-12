"""M0 ingest tests. Always runs on a synthetic dataset; also runs on the real data if `make data` was done."""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from recipebot.db import ORIGINAL_FIELDS, SOURCES, SOURCE_FILES, connect, data_dir, db_path, find_source_file, get_original, make_id
from scripts.build_db import build

SYNTH = {
    "ar": {
        "k1": {"title": "Garlic &amp; Onion Soup", "ingredients": ["1 clove garlic, minced", "1/2 cup (120 g) chopped onion, divided", "ADVERTISEMENT"],
               "instructions": "Chop.\nSimmer.\nServe. ADVERTISEMENT", "picture_link": "http://x/1.jpg"},
        "k2": {"title": "", "ingredients": ["1 egg"], "instructions": "Cook it.", "picture_link": None},
        "k3": {"title": "No ingredients", "ingredients": [], "instructions": "Cook it.", "picture_link": None},
        "k4": {"title": "Only ads", "ingredients": ["ADVERTISEMENT", "  "], "instructions": "Cook it.", "picture_link": None},
        "k5": {"title": "No steps", "ingredients": ["1 egg"], "instructions": "ADVERTISEMENT\n  ", "picture_link": None},
        "k6": {"title": "  Crème brûlée 🍮  ", "ingredients": ["½ cup sugar", "2\u00a0egg yolks  "], "instructions": "Mix. Bake.", "picture_link": ""},
        "k7": {"title": "AR style", "ingredients": ["2 tablespoons butter ADVERTISEMENT", "1 egg ADVERTISEMENT", "ADVERTISEMENT"],
               "instructions": "Mix.\nBake.", "picture_link": "x"},  # real ar lines carry a trailing ADVERTISEMENT
    },
    "epi": {
        "k1": {"title": "Garlic & Onion Soup", "ingredients": ["1 clove garlic, minced", "1/2 cup (120 g) chopped onion, divided"],
               "instructions": "Chop.\nSimmer.", "picture_link": "http://x/2.jpg"},  # same orig key as ar:k1 + near-duplicate
        "k2": {"title": "Pasta", "ingredients": ["1 lb penne"], "instructions": "1.\nBoil.\n2.\nDrain.", "picture_link": None},
    },
    "fn": {
        "k9": {"title": "Salad", "ingredients": ["1 tomato"], "instructions": "Slice.", "picture_link": "http://x/9.jpg"},
        "k10": {"title": "Title only"},
        "k11": None,
    },
}
EXPECTED_VALID = {"ar:k1", "ar:k6", "ar:k7", "epi:k1", "epi:k2", "fn:k9"}
EXPECTED_REASONS = {"ar:k2": "no_title", "ar:k3": "no_ingredients", "ar:k4": "no_ingredients", "ar:k5": "no_instructions",
                    "fn:k10": "no_ingredients,no_instructions", "fn:k11": "malformed_record"}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _load(directory: Path) -> dict:
    return {s: json.load(open(find_source_file(directory, s), encoding="utf-8")) for s in SOURCES}


@pytest.fixture(scope="module", params=["synthetic", "real"])
def ds(request, tmp_path_factory):
    tmp = tmp_path_factory.mktemp(request.param)
    if request.param == "synthetic":
        d = tmp / "raw"
        d.mkdir()
        for s in SOURCES:
            (d / SOURCE_FILES[s]).write_text(json.dumps(SYNTH[s], ensure_ascii=False), encoding="utf-8")
    else:
        d = data_dir()
        try:
            [find_source_file(d, s) for s in SOURCES]
        except FileNotFoundError:
            pytest.skip("real data not downloaded (run `make data`)")
    before = {s: sha(find_source_file(d, s)) for s in SOURCES}
    if request.param == "real":  # reuse the already-built DB (no second multi-GB build in the temp dir)
        db = db_path()
        if not db.exists():
            pytest.skip("build the DB first: python -m scripts.build_db")
        c = connect(db, readonly=True)
        sampled = c.execute("SELECT value FROM meta WHERE key='sample'").fetchone()[0]
        c.close()
        if sampled:
            pytest.skip("DB is a --sample build; rebuild in full to run real-data tests")
    else:
        db = tmp / "t.db"
        build(d, db, log=lambda *_: None)
    return SimpleNamespace(kind=request.param, dir=d, db=db, before=before, src=_load(d), conn=connect(db, readonly=True))


def test_counts_match_source_files(ds):
    for s in SOURCES:
        in_db = ds.conn.execute("SELECT COUNT(*) FROM recipes WHERE source=?", (s,)).fetchone()[0]
        assert in_db == len(ds.src[s])
        assert ds.conn.execute("SELECT value FROM meta WHERE key=?", (f"source_records:{s}",)).fetchone()[0] == str(len(ds.src[s]))
    assert ds.conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0] == sum(len(v) for v in ds.src.values())


def test_ids_namespaced_and_unique(ds):
    rows = ds.conn.execute("SELECT id, source, orig_key FROM recipes").fetchall()
    assert len({r[0] for r in rows}) == len(rows)
    assert all(re.fullmatch(r"(ar|epi|fn):.+", r[0]) and r[0] == make_id(r[1], r[2]) for r in rows)
    if ds.kind == "synthetic":  # same original key in two sources must coexist
        assert {"ar:k1", "epi:k1"} <= {r[0] for r in rows}


def test_roundtrip_every_record_identical_to_original(ds):
    extra = set()
    for s in SOURCES:
        for key, rec in ds.src[s].items():
            got = get_original(ds.conn, make_id(s, key))
            assert got is not None, f"{s}:{key} missing"
            r = rec if isinstance(rec, dict) else {}
            assert got == {f: r.get(f) for f in ORIGINAL_FIELDS}, f"{s}:{key} differs"
            extra |= set(r) - set(ORIGINAL_FIELDS)
    assert not extra, f"dataset has fields the schema drops: {extra}"  # real data surprise => decide in M1


def test_source_files_not_modified(ds):
    assert {s: sha(find_source_file(ds.dir, s)) for s in SOURCES} == ds.before
    for s in SOURCES:
        assert ds.conn.execute("SELECT value FROM meta WHERE key=?", (f"sha256:{s}",)).fetchone()[0] == ds.before[s]


def test_originals_keep_noise_untouched(ds):
    if ds.kind != "synthetic":
        pytest.skip("synthetic only")
    got = get_original(ds.conn, "ar:k1")
    assert got["title"] == "Garlic &amp; Onion Soup" and got["ingredients"][-1] == "ADVERTISEMENT" and got["instructions"].endswith("ADVERTISEMENT")
    assert get_original(ds.conn, "ar:k6")["title"] == "  Crème brûlée 🍮  "


def test_validity_flags(ds):
    if ds.kind != "synthetic":
        pytest.skip("synthetic only")
    got = {r[0]: (r[1], r[2]) for r in ds.conn.execute("SELECT id, is_valid, invalid_reason FROM recipes")}
    assert {i for i, (v, _) in got.items() if v} == EXPECTED_VALID
    assert {i: r for i, (v, r) in got.items() if not v} == EXPECTED_REASONS


def test_m1_columns_filled_and_consistent(ds):
    c = ds.conn
    assert c.execute("SELECT COUNT(*) FROM recipes WHERE n_ingredients IS NULL OR n_steps IS NULL OR n_steps_alt IS NULL").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM recipes WHERE is_valid=1 AND (n_ingredients<1 OR n_steps<1)").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM recipes r WHERE n_ingredients != (SELECT COUNT(*) FROM ingredients i WHERE i.recipe_id=r.id)").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM ingredients WHERE canon IS NULL OR canon=''").fetchone()[0] == 0
    if ds.kind == "synthetic":
        assert c.execute("SELECT n_ingredients, n_steps FROM recipes WHERE id='ar:k1'").fetchone() == (2, 3)
        assert c.execute("SELECT canon, qty, unit FROM ingredients WHERE recipe_id='ar:k1' ORDER BY pos").fetchall() == [("garlic", 1.0, "clove"), ("onion", 0.5, "cup")]


def test_sample_build_is_deterministic_and_faithful(tmp_path):
    d = tmp_path / "raw"
    d.mkdir()
    for s in SOURCES:
        (d / SOURCE_FILES[s]).write_text(json.dumps(SYNTH[s], ensure_ascii=False), encoding="utf-8")
    ids = []
    for i in range(2):
        db = tmp_path / f"s{i}.db"
        build(d, db, sample=6, log=lambda *_: None)
        c = connect(db, readonly=True)
        ids.append(sorted(r[0] for r in c.execute("SELECT id FROM recipes")))
        assert len(ids[-1]) == 6
        assert c.execute("SELECT value FROM meta WHERE key='sample'").fetchone()[0] == "6"
        assert c.execute("SELECT value FROM meta WHERE key='source_records:ar'").fetchone()[0] == "7"
        for rid in ids[-1]:
            s, k = rid.split(":", 1)
            r = SYNTH[s][k] or {}
            assert get_original(c, rid) == {f: r.get(f) for f in ORIGINAL_FIELDS}
    assert ids[0] == ids[1]


def test_download_extract_handles_nested_zip(tmp_path):
    from scripts.download_data import extract_zip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("__MACOSX/._recipes_raw_nosource_ar.json", "junk")
        for s in SOURCES:
            z.writestr(f"recipes_raw/{SOURCE_FILES[s]}", json.dumps(SYNTH[s]))
    zp = tmp_path / "x.zip"
    zp.write_bytes(buf.getvalue())
    out = extract_zip(zp, tmp_path / "raw")
    assert {s: p.name for s, p in out.items()} == SOURCE_FILES
    assert json.load(open(out["fn"])) == SYNTH["fn"]


def test_audit_smoke(ds, tmp_path):
    from scripts.audit import main
    out = tmp_path / "A.md"
    assert main(["--db", str(ds.db), "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    for h in ("## 1. Records per file", "## 3. ADVERTISEMENT", "## 4. Duplicates", "## 5. Instruction format", "## 7. Ingredient-line oddities"):
        assert h in text
