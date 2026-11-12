"""Data audit over the built DB -> docs/DATA_AUDIT.md  (python -m scripts.audit)."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from recipebot.db import AD_TOKEN, SOURCES, clean_ingredient_lines, connect, db_path, has_instruction_text, strip_ads

ENTITY = re.compile(r"&(#\d+|#x[0-9a-f]+|[a-z]+);", re.I)
ODD_CHARS = set("*†‡®™?![]{}|_=+<>~#@^\\")
BARE_NUM = re.compile(r"^\s*\(?\d+[.)]?\s*$")
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
LEAD_QTY = re.compile(r"^\s*[\d½⅓⅔¼¾⅛⅜⅝⅞⅕⅖⅗⅘⅙⅚]")
# tag -> weight (weight 0 = informational only, excluded from the weirdness score)
WEIGHTS = {"advertisement": 5, "blank": 5, "no_letters": 5, "url": 4, "too_long": 3, "too_short": 3, "header_like": 3,
           "unbalanced_parens": 3, "newline_or_tab": 3, "html_entity": 2, "all_caps": 2, "odd_chars": 2,
           "digits_glued_to_word": 1, "multi_space": 1, "no_leading_quantity": 0, "has_or_alternative": 0}


def oddities(line: str) -> list[str]:
    t = []
    s = line.strip()
    if AD_TOKEN in line: t.append("advertisement")
    if not s: t.append("blank")
    elif not re.search(r"[^\W\d_]", s): t.append("no_letters")
    if re.search(r"https?:|www\.", line, re.I): t.append("url")
    if len(s) > 150: t.append("too_long")
    if 0 < len(s) <= 2: t.append("too_short")
    if s.endswith(":") or re.match(r"^(ingredients?|for the\b.*)$", s, re.I): t.append("header_like")
    if line.count("(") != line.count(")"): t.append("unbalanced_parens")
    if re.search(r"[\n\r\t]", line): t.append("newline_or_tab")
    if ENTITY.search(line): t.append("html_entity")
    letters = re.sub(r"[^A-Za-z]", "", s)
    if len(letters) >= 3 and letters.isupper() and AD_TOKEN not in line: t.append("all_caps")
    if any(c in ODD_CHARS for c in line): t.append("odd_chars")
    if re.search(r"\d[a-z]{2,}", line, re.I): t.append("digits_glued_to_word")
    if "  " in line: t.append("multi_space")
    if s and not LEAD_QTY.match(line): t.append("no_leading_quantity")
    if re.search(r"\bor\b", line, re.I): t.append("has_or_alternative")
    return t


def norm_title(t) -> str:
    return re.sub(r"[^a-z0-9]+", " ", html.unescape(t or "").lower()).strip()


def norm_line(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s).lower()).strip()


def n(x) -> str: return f"{x:,}"
def pct(a, b) -> str: return f"{100 * a / b:.1f}%" if b else "n/a"
def cell(s, limit=140) -> str:
    s = str(s).replace("\n", "⏎").replace("\r", "⏎").replace("\t", "→").replace("|", "\\|").replace("`", "'")
    return s if len(s) <= limit else s[:limit] + "…"
def code(s) -> str: return f"`{cell(s)}`"
def med(xs): return statistics.median(xs) if xs else "n/a"
def table(head, rows) -> list[str]:
    return ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"] + ["| " + " | ".join(map(str, r)) + " |" for r in rows] + [""]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=Path("docs/DATA_AUDIT.md"))
    a = ap.parse_args(argv)
    conn = connect(a.db or db_path(), readonly=True)
    meta = dict(conn.execute("SELECT key, value FROM meta"))

    cnt = {s: Counter() for s in SOURCES}
    reasons = {s: Counter() for s in SOURCES}
    n_blocks = {s: [] for s in SOURCES}
    n_sents = {s: [] for s in SOURCES}
    line_cnt: Counter = Counter()
    dup = defaultdict(list)

    cur = conn.execute("SELECT id, source, title, ingredients_json, instructions, picture_link, is_valid, invalid_reason FROM recipes")
    for rid, src, title, ij, instr, pic, valid, reason in cur:
        c = cnt[src]
        c["records"] += 1
        c["valid" if valid else "invalid"] += 1
        for r in (reason or "").split(","):
            if r: reasons[src][r] += 1
        ings = json.loads(ij) if ij else None
        # --- empty fields
        if not (isinstance(title, str) and title.strip()): c["empty_title"] += 1
        if not isinstance(ings, list): c["ingredients_not_list"] += 1
        elif not ings: c["ingredients_empty_list"] += 1
        elif not clean_ingredient_lines(ings): c["ingredients_no_clean_line"] += 1
        if not (isinstance(instr, str) and instr.strip()): c["instructions_empty"] += 1
        elif not has_instruction_text(instr): c["instructions_no_text_after_ad_strip"] += 1
        if not (isinstance(pic, str) and pic.strip()): c["picture_empty"] += 1
        # --- advertisement
        if isinstance(title, str) and AD_TOKEN in title: c["ad_title"] += 1
        if isinstance(instr, str) and AD_TOKEN in instr:
            c["ad_instr_records"] += 1
            c["ad_instr_occ"] += instr.count(AD_TOKEN)
        rec_ad = False
        for x in ings if isinstance(ings, list) else []:
            if not isinstance(x, str):
                c["ing_non_string_items"] += 1
                continue
            line_cnt[x] += 1
            if not x.strip(): c["ing_blank_lines"] += 1
            if x.strip() == AD_TOKEN: c["ad_ing_exact_lines"] += 1; rec_ad = True
            elif AD_TOKEN in x: c["ad_ing_embedded_lines"] += 1; rec_ad = True
            c["ing_lines"] += 1
        if rec_ad: c["ad_ing_records"] += 1
        # --- instruction format (after ADVERTISEMENT + bare-numbering removal)
        if isinstance(instr, str):
            blocks = [l.strip() for l in strip_ads(instr).splitlines() if l.strip() and not BARE_NUM.match(l)]
            if len(blocks) >= 2:
                c["fmt_blocks"] += 1; n_blocks[src].append(len(blocks))
            elif len(blocks) == 1:
                c["fmt_single"] += 1; n_sents[src].append(len([s for s in SENT_SPLIT.split(blocks[0]) if s.strip()]))
            else:
                c["fmt_empty"] += 1
        # --- duplicates (valid only)
        if valid:
            key = (norm_title(title), tuple(sorted(norm_line(x) for x in clean_ingredient_lines(ings))))
            dup[hashlib.md5(repr(key).encode()).digest()].append(rid)

    tot = Counter()
    for s in SOURCES: tot.update(cnt[s])
    L: list[str] = ["# DATA AUDIT", ""]
    built = f"sample build ({meta.get('sample')} records)" if meta.get("sample") else "full build"
    L += [f"Generated by `scripts/audit.py` from the built DB ({built}, built {meta.get('built_at', '?')}). "
          "Counts are over **all loaded records**, including invalid ones, unless stated.", ""]
    L += ["Fields seen per source (key → #records): " + "; ".join(f"**{s}** {meta.get(f'fields:{s}', '?')}" for s in SOURCES), ""]

    L += ["## 1. Records per file", ""]
    L += table(["source", "file", "records in file", "loaded", "valid", "invalid", "% valid"],
               [(s, meta.get(f"source_file:{s}", "?"), n(int(meta.get(f"source_records:{s}", 0))), n(cnt[s]["records"]), n(cnt[s]["valid"]),
                 n(cnt[s]["invalid"]), pct(cnt[s]["valid"], cnt[s]["records"])) for s in SOURCES]
               + [("**all**", "", n(sum(int(meta.get(f"source_records:{s}", 0)) for s in SOURCES)), n(tot["records"]), n(tot["valid"]), n(tot["invalid"]), pct(tot["valid"], tot["records"]))])
    L += ["`is_valid` (M0 definition) = title non-blank AND ≥1 non-blank, non-ADVERTISEMENT ingredient line AND ≥1 letter in instructions after removing ADVERTISEMENT. M1 may tighten it with `steps.py`/`normalize.py`.", ""]

    L += ["## 2. Invalid records by reason", "", "A record can carry several reasons, so rows can sum to more than the invalid total.", ""]
    all_reasons = sorted({r for s in SOURCES for r in reasons[s]})
    L += table(["reason"] + list(SOURCES) + ["all"], [(r, *[n(reasons[s][r]) for s in SOURCES], n(sum(reasons[s][r] for s in SOURCES))) for r in all_reasons]
               + [("**invalid records (distinct)**", *[n(cnt[s]["invalid"]) for s in SOURCES], n(tot["invalid"]))])

    L += ["## 3. ADVERTISEMENT occurrences", ""]
    rows = [("ingredient lines exactly ADVERTISEMENT", "ad_ing_exact_lines"), ("ingredient lines containing it (embedded)", "ad_ing_embedded_lines"),
            ("records with it in ingredients", "ad_ing_records"), ("records with it in instructions", "ad_instr_records"),
            ("total occurrences in instructions", "ad_instr_occ"), ("titles containing it", "ad_title")]
    L += table(["where"] + list(SOURCES) + ["all"], [(lbl, *[n(cnt[s][k]) for s in SOURCES], n(tot[k])) for lbl, k in rows])

    groups = [g for g in dup.values() if len(g) > 1]
    redundant = sum(len(g) - 1 for g in groups)
    cross = [g for g in groups if len({i.split(":")[0] for i in g}) > 1]
    n_valid = tot["valid"]
    L += ["## 4. Duplicates (valid records; normalized title + identical set of normalized raw ingredient lines)", "",
          "Raw-line based (M0). The canon-set definition from ARCHITECTURE §2 is re-run after M1.", ""]
    L += table(["metric", "value"], [("duplicate groups (size ≥ 2)", n(len(groups))), ("records beyond the first in each group (redundant)", f"{n(redundant)} ({pct(redundant, n_valid)} of valid)"),
                                     ("groups spanning more than one source", n(len(cross))), ("largest group", n(max((len(g) for g in groups), default=0)))])
    top = sorted(groups, key=lambda g: (-len(g), g[0]))[:8]
    if top:
        titles = dict(conn.execute(f"SELECT id, title FROM recipes WHERE id IN ({','.join('?' * len(top))})", [g[0] for g in top]))
        L += ["Largest groups:", ""] + table(["size", "title", "example ids"], [(len(g), cell(titles[g[0]], 60), cell(", ".join(sorted(g)[:3]), 80)) for g in top])

    L += ["## 5. Instruction format (decides the `steps.py` primary rule)", "",
          "Blocks = ≥2 non-empty newline-separated lines after stripping ADVERTISEMENT and bare numbering. Single = exactly 1 such line.", ""]
    L += table(["format"] + list(SOURCES) + ["all"],
               [("blocks (count)", *[n(cnt[s]["fmt_blocks"]) for s in SOURCES], n(tot["fmt_blocks"])),
                ("blocks %", *[pct(cnt[s]["fmt_blocks"], cnt[s]["records"]) for s in SOURCES], pct(tot["fmt_blocks"], tot["records"])),
                ("single paragraph (count)", *[n(cnt[s]["fmt_single"]) for s in SOURCES], n(tot["fmt_single"])),
                ("single paragraph %", *[pct(cnt[s]["fmt_single"], cnt[s]["records"]) for s in SOURCES], pct(tot["fmt_single"], tot["records"])),
                ("no usable text", *[n(cnt[s]["fmt_empty"]) for s in SOURCES], n(tot["fmt_empty"])),
                ("median #blocks (blocks format)", *[med(n_blocks[s]) for s in SOURCES], med(sum(n_blocks.values(), []))),
                ("median #sentences (single format)", *[med(n_sents[s]) for s in SOURCES], med(sum(n_sents.values(), [])))])
    dom = "blocks" if tot["fmt_blocks"] >= tot["fmt_single"] else "single paragraph"
    L += [f"Dominant format overall: **{dom}**. Per-source differences above matter if one source is the opposite format.", ""]

    L += ["## 6. Empty / missing fields", ""]
    rows = [("title blank/missing", "empty_title"), ("ingredients not a list", "ingredients_not_list"), ("ingredients = empty list", "ingredients_empty_list"),
            ("ingredients list with no clean line", "ingredients_no_clean_line"), ("instructions blank/missing", "instructions_empty"),
            ("instructions with no text after ADVERTISEMENT strip", "instructions_no_text_after_ad_strip"), ("picture_link null/blank", "picture_empty"),
            ("blank ingredient lines (line level)", "ing_blank_lines"), ("non-string ingredient items", "ing_non_string_items")]
    L += table(["field"] + list(SOURCES) + ["all"], [(lbl, *[n(cnt[s][k]) for s in SOURCES], n(tot[k])) for lbl, k in rows])

    # --- ingredient line oddities
    tag_lines, tag_occ = Counter(), Counter()
    scored = []
    for line, k in line_cnt.items():
        tags = oddities(line)
        for t in tags: tag_lines[t] += 1; tag_occ[t] += k
        if line.strip() and line.strip() != AD_TOKEN:
            score = sum(WEIGHTS[t] for t in tags)
            if score > 0: scored.append((-score, -k, line, tags))
    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    L += ["## 7. Ingredient-line oddities", "", f"Distinct raw lines: {n(len(line_cnt))}; total lines: {n(tot['ing_lines'])}. "
          "Weight 0 = informational (not scored). Exact `ADVERTISEMENT` and blank lines are excluded from the top-30 list (see §3, §6).", ""]
    L += table(["tag", "weight", "distinct lines", "occurrences"], [(t, WEIGHTS[t], n(tag_lines[t]), n(tag_occ[t])) for t in sorted(WEIGHTS, key=lambda t: (-WEIGHTS[t], t))])
    L += ["### Top 30 weirdest lines (score, then frequency)", ""]
    L += table(["#", "score", "count", "tags", "line"], [(i + 1, -s, -k, ", ".join(t for t in tags if WEIGHTS[t]), code(line)) for i, (s, k, line, tags) in enumerate(scored[:30])])

    L += ["## 8. Inputs for M1 [VERIFY] items", "",
          f"- Instruction format → primary step rule candidate: dominant = **{dom}** (§5). Confirm per-source before fixing `steps.py`.",
          f"- Noise to strip in derived columns: ADVERTISEMENT ({n(tot['ad_ing_exact_lines'])} exact ingredient lines), HTML entities ({n(tag_lines['html_entity'])} distinct lines), header-like lines ({n(tag_lines['header_like'])}).",
          f"- `or` alternatives appear in {n(tag_lines['has_or_alternative'])} distinct lines → `alts` handling matters.", ""]

    text = "\n".join(L)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n[audit] wrote {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
