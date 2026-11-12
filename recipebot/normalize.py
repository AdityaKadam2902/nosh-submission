"""Ingredient line -> structured (ARCHITECTURE §3). Config-driven: config/{aliases,forms,units}.yaml.

parse_ingredient(raw) -> {canon, qty, unit, forms, alts, raw}
  canon "" = not an ingredient (blank / ADVERTISEMENT / header / no letters).
  qty: float or None (None for ranges "1-2" or no number); unit: canonical unit name or None (None + qty = count).
contains(recipe_ingredients, query, strict=False, ignore_forms=False, use_alts=False) -> bool
  default = form-aware token-sequence containment (garlic powder is not garlic).
  strict=True: canon equality. ignore_forms=True: skip distinct_pairs (the "loose" mode).
"""
from __future__ import annotations

import html
import os
import re
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_DIR = Path(os.environ.get("RECIPEBOT_CONFIG_DIR") or Path(__file__).resolve().parent.parent / "config")
AD = "ADVERTISEMENT"


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / f"{name}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ---------------- singularize ----------------
_NO_SING = {"molasses", "grits", "hummus", "couscous", "asparagus", "watercress", "lemongrass", "swiss", "citrus", "bass",
            "series", "species", "lees", "tahini", "harissa", "pita", "gas"}
_IRREG = {"leaves": "leaf", "halves": "half", "loaves": "loaf", "calves": "calf", "knives": "knife", "chilies": "chili"}
_IES_KEEP = {"cookies", "brownies", "smoothies", "veggies", "pies", "goodies", "calories", "zombies", "freebies"}


def singularize(w: str) -> str:
    if "_" in w or w.isdigit() or len(w) <= 3 or w in _NO_SING:
        return w
    if w in _IRREG:
        return _IRREG[w]
    if w.endswith(("ss", "us", "is")):
        return w
    if w.endswith("ies"):
        return w[:-1] if (w in _IES_KEEP or len(w) <= 4) else w[:-3] + "y"
    if w.endswith(("ches", "shes", "xes", "zes", "oes")):
        return w[:-2]
    if w.endswith("s"):
        return w[:-1]
    return w


def tokens(text: str) -> list[str]:
    """lowercase, drop apostrophes, hyphens/punctuation -> spaces, singularize."""
    t = text.lower().replace("'", "").replace("\u2019", "")
    return [singularize(w) for w in re.findall(r"[a-z0-9_]+", t)]


# ---------------- config compile ----------------
def _phrase_table(d: dict) -> dict[str, list[tuple[tuple, tuple]]]:
    table: dict[str, list] = {}
    for k, v in (d or {}).items():
        kt, vt = tuple(tokens(str(k))), tuple(tokens(str(v)))
        if kt:
            table.setdefault(kt[0], []).append((kt, vt))
    for lst in table.values():
        lst.sort(key=lambda x: -len(x[0]))
    return table


class _Cfg:
    def __init__(self):
        forms, al, un = load_yaml("forms"), load_yaml("aliases"), load_yaml("units")
        self.pre = _phrase_table(al.get("pre_aliases"))
        self.alias = _phrase_table(al.get("aliases"))
        self.exact = {tuple(tokens(str(k))): tuple(tokens(str(v))) for k, v in (al.get("exact_aliases") or {}).items()}
        self.canon_forms = {singularize(w) for w in forms.get("canon_forms", [])}
        self.soft = {singularize(w) for w in forms.get("soft_forms", [])}
        self.prep = {singularize(w) for w in forms.get("prep_words", [])}
        self.drop_phrases = [tuple(singularize(w) for w in p) for p in forms.get("drop_phrases", [])]
        self.edge = set(forms.get("edge_words", []))
        self.shared_heads = {singularize(w) for w in forms.get("shared_heads", [])}
        self.distinct = {tuple(tokens(k)): {singularize(x) for x in v} for k, v in (forms.get("distinct_pairs") or {}).items()}
        self.size_words = [w.lower() for w in un.get("size_words", [])]
        self.units: dict[str, dict] = {}
        amap: dict[str, str] = {}
        for name, info in un["units"].items():
            self.units[name] = {"family": info["family"], "to_base": info["to_base"]}
            for a in [name] + list(info.get("aliases", [])):
                amap[str(a).lower().rstrip(".")] = name
        self.unit_alias = amap
        parts = []
        for a in sorted(amap, key=len, reverse=True):
            parts.append(r"\.?\s+".join(re.escape(x) for x in a.split()))
        self.unit_re = re.compile(r"(?P<unit>" + "|".join(parts) + r")\.?(?![a-z])")


_CFG: _Cfg | None = None


def cfg() -> _Cfg:
    global _CFG
    if _CFG is None:
        _CFG = _Cfg()
    return _CFG


def reset_config() -> None:
    """Drop cached config (tests / live edits)."""
    global _CFG
    _CFG = None
    load_yaml.cache_clear()
    parse_ingredient.cache_clear()


def canon_unit(unit: str | None) -> str | None:
    """'cups' -> 'cup', 'tbsp' -> 'tablespoon'; None if unknown."""
    return cfg().unit_alias.get(str(unit).lower().strip().rstrip(".")) if unit else None


def unit_info(unit: str | None) -> dict | None:
    return cfg().units.get(unit) if unit else None


def apply_phrases(toks: list[str], table: dict) -> list[str]:
    out, i = [], 0
    while i < len(toks):
        for kt, vt in table.get(toks[i], ()):
            if tuple(toks[i:i + len(kt)]) == kt:
                out.extend(vt)
                i += len(kt)
                break
        else:
            out.append(toks[i])
            i += 1
    return out


def term_tokens(term: str) -> tuple:
    """Tokens for a config term (allergen lists etc): tokenized + aliases, NO prep/soft dropping."""
    return tuple(apply_phrases(tokens(term), cfg().alias))


# ---------------- numbers / quantity ----------------
_FR = {"½": .5, "⅓": 1 / 3, "⅔": 2 / 3, "¼": .25, "¾": .75, "⅛": .125, "⅜": .375, "⅝": .625, "⅞": .875, "⅕": .2, "⅖": .4, "⅗": .6, "⅘": .8, "⅙": 1 / 6, "⅚": 5 / 6}
_FRC = "".join(_FR)
_NUM = rf"(?:\d+[\s-]\d+/\d+|\d+/\d+|\d+\s*[{_FRC}]|[{_FRC}]|\d*\.\d+|\d+)"
_QTY = re.compile(rf"^\s*(?P<q1>{_NUM})(?:(?:\s*[-–—]\s*|\s+(?:to|or)\s+)(?P<q2>{_NUM}))?(?![\d/])")


def _to_float(tok: str):
    tok = tok.strip()
    try:
        if m := re.fullmatch(r"(\d+)[\s-](\d+)/(\d+)", tok):
            return int(m[1]) + int(m[2]) / int(m[3])
        if m := re.fullmatch(r"(\d+)/(\d+)", tok):
            return int(m[1]) / int(m[2])
        if m := re.fullmatch(rf"(\d+)\s*([{_FRC}])", tok):
            return int(m[1]) + _FR[m[2]]
        if tok in _FR:
            return _FR[tok]
        return float(tok)
    except ZeroDivisionError:
        return None


_HEADER = re.compile(r"^\s*(?:for|ingredients?|to serve|to garnish|special equipment|equipment)\b[^\d]{0,40}:?\s*$", re.I)
_CUTS = re.compile(
    r"\b(?:for (?:the )?(?:garnish|serving|dusting|frying|greasing|brushing|topping|sprinkling|decorating|coating|dipping|drizzling|glaze|pan)\b.*"
    r"|to taste\b.*|as needed\b.*|if desired\b.*|plus\b.*|such as\b.*|cut (?:in|into)\b.*|at room temperature\b.*|or to taste\b.*"
    r"|optional\b.*|divided\b.*)$")


def _strip_parens(s: str) -> str:
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"\([^()]*\)|\[[^\[\]]*\]", " ", s)
    s = re.sub(r"[(\[].*$", " ", s)  # unclosed
    return s


def _name(text: str):
    """name text -> (canon tokens, forms). No quantity handling."""
    c = cfg()
    toks = apply_phrases(tokens(text), c.pre)
    # drop multi-word descriptors
    i, kept = 0, []
    while i < len(toks):
        for p in c.drop_phrases:
            if tuple(toks[i:i + len(p)]) == p:
                i += len(p)
                break
        else:
            kept.append(toks[i])
            i += 1
    soft, keep = [], []
    for t in kept:
        if t in c.prep or t.isdigit():
            continue
        if t in c.soft:
            soft.append(t)
            continue
        keep.append(t)
    keep = apply_phrases(keep, c.alias)
    while keep and keep[0] in c.edge:
        keep.pop(0)
    while keep and keep[-1] in c.edge:
        keep.pop()
    if tuple(keep) in c.exact:
        keep = list(c.exact[tuple(keep)])
    forms = [t for t in keep if t in c.canon_forms]
    for s in soft:
        if s not in forms:
            forms.append(s)
    return keep, forms


def _empty(raw):
    return {"canon": "", "qty": None, "unit": None, "forms": [], "alts": [], "raw": raw}


@lru_cache(maxsize=500_000)
def _parse(raw: str):
    c = cfg()
    s = html.unescape(raw).replace("\xa0", " ").replace("–", "-").replace("—", "-").lower()
    s = re.sub(r"[®™*•]", " ", s.replace(AD.lower(), " ")).strip()  # AR lines end with " ADVERTISEMENT"
    s = _strip_parens(s)
    s = re.sub(r"^[\s\-]+", "", s).strip()
    if not s or not re.search(r"[a-z]", s) or s.endswith(":") or _HEADER.match(s):
        return ("", None, None, (), ())
    # "juice of 2 lemons" -> "lemons juice"
    if m := re.match(r"^(juice|zest|rind)\s+of\s+(?:[\d½¼¾/.\s-]+)?(?:(?:large|small|medium)\s+)?(.+)$", s):
        s = f"{m[2]} {m[1]}"
    qty = unit = None
    s = re.sub(r"^(?:an?|one)\s+(?=\w)", "1 ", s)
    m = _QTY.match(s)
    if m:
        q1 = _to_float(m["q1"])
        qty = None if m["q2"] else q1
        s = s[m.end():]
        sw = "|".join(map(re.escape, c.size_words))
        s = re.sub(rf"^[\s-]*(?:(?:{sw})\s+)*", "", s)
        mu = c.unit_re.match(s)
        if mu:
            unit = c.unit_alias[re.sub(r"\.?\s+", " ", mu["unit"]).lower().rstrip(".")]
            s = s[mu.end():]
        s = re.sub(r"^\s*(?:of\s+)?", "", s)
        if unit and not s.strip():
            return (unit, qty, None, (), ())  # "2 cloves": the unit word is the ingredient
    s = _CUTS.sub("", s)
    s = re.sub(r"(?<=[a-z])/(?=[a-z])", " or ", s)
    canon_toks, forms, alts = [], [], []
    for seg in re.split(r"[,;]|\s-\s|\s--\s", s):
        if not seg.strip():
            continue
        parts = re.split(r"\s+or\s+", seg)
        res = [_name(p) for p in parts]
        res = [r for r in res if r[0]]
        if not res:
            continue
        (canon_toks, forms), rest = res[0], res[1:]
        if rest and len(canon_toks) == 1 and len(rest[0][0]) >= 2 and rest[0][0][-1] in c.shared_heads:
            canon_toks = canon_toks + [rest[0][0][-1]]
            forms = [t for t in canon_toks if t in c.canon_forms] + [f for f in forms if f not in canon_toks]
        alts = [" ".join(r[0]) for r in rest if r[0] != canon_toks]
        break
    canon = " ".join(canon_toks).replace("_", " ")
    return (canon, qty, unit, tuple(forms), tuple(alts))


@lru_cache(maxsize=500_000)
def parse_ingredient(raw) -> dict:
    # NOTE: cached object is returned; treat as read-only (use dict(...) to copy).
    if not isinstance(raw, str):
        return _empty(raw)
    canon, qty, unit, forms, alts = _parse(raw)
    return {"canon": canon, "qty": qty, "unit": unit, "forms": list(forms), "alts": list(alts), "raw": raw}


def parse_ingredients(raws) -> list[dict]:
    """Parse a list; each dict gets pos = index in the ORIGINAL list. Non-ingredient lines (canon '') are kept."""
    out = []
    for pos, raw in enumerate(raws or []):
        d = dict(parse_ingredient(raw))
        d["pos"] = pos
        out.append(d)
    return out


def clean_ingredients(raws) -> list[dict]:
    """Non-empty ingredient dicts. aliases.yaml `split_aliases` expands e.g. "salt and pepper" into two rows with the same pos."""
    split = {" ".join(tokens(k)): v for k, v in (load_yaml("aliases").get("split_aliases") or {}).items()}
    out = []
    for d in parse_ingredients(raws):
        if not d["canon"]:
            continue
        names = split.get(d["canon"])
        if not names:
            out.append(d)
            continue
        for n in names:
            nd = dict(d, canon=n, qty=None, unit=None, alts=[])
            nd["forms"] = [] if n == "salt" else d["forms"]
            out.append(nd)
    return out


def canon_name(text: str) -> str:
    """Canonical name for a user-supplied ingredient name / query."""
    t, _ = _name(re.sub(AD, " ", text, flags=re.I))
    return " ".join(t).replace("_", " ")


# ---------------- matching ----------------
def _as_parsed(item, i):
    if isinstance(item, str):
        d = dict(parse_ingredient(item))
        d["pos"] = i
        return d
    d = dict(item)
    d.setdefault("pos", i)
    if isinstance(d.get("forms"), str):
        d["forms"] = [f for f in d["forms"].split(",") if f]
    d.setdefault("forms", [])
    d.setdefault("alts", [])
    d.setdefault("raw", d.get("canon", ""))
    return d


def _span_match(T: list[str], Q: list[str], distinct: set | None) -> bool:
    q = len(Q)
    for i in range(len(T) - q + 1):
        if T[i:i + q] == Q:
            extras = T[:i] + T[i + q:]
            if distinct and any(x in distinct for x in extras):
                continue
            return True
    return False


def matcher(query: str, strict: bool = False, ignore_forms: bool = False, use_alts: bool = False):
    """Compile a query once -> fn(parsed_ingredient_dict) -> bool. Dict needs canon; forms/alts optional (list or str)."""
    qtoks, qforms = _name(query)
    if not qtoks:
        return lambda d: False
    distinct = None if ignore_forms else cfg().distinct.get(tuple(qtoks))
    qf = set(qforms)

    def m(d) -> bool:
        canon = d.get("canon") or ""
        if not canon:
            return False
        forms = d.get("forms") or []
        if isinstance(forms, str):
            forms = [f for f in forms.split(",") if f]
        cands = [canon] + (list(d.get("alts") or []) if use_alts else [])
        for cand in cands:
            T = cand.split()
            ok = (T == qtoks) if strict else _span_match(T, qtoks, distinct)
            if ok and qf and not qf <= set(forms) | set(T):
                ok = False
            if ok:
                return True
        return False
    return m


def query_info(query: str, ignore_forms: bool = False) -> dict:
    """{'canon': str, 'forms': [...], 'distinct': [...]}: what a query normalizes to and which modifiers make an item 'different'."""
    qtoks, qforms = _name(query)
    dist = None if ignore_forms else cfg().distinct.get(tuple(qtoks))
    return {"canon": " ".join(qtoks).replace("_", " "), "forms": qforms, "distinct": sorted(dist) if dist else []}


def find_matches(recipe_ingredients, query: str, strict: bool = False, ignore_forms: bool = False, use_alts: bool = False) -> list[dict]:
    m = matcher(query, strict, ignore_forms, use_alts)
    return [d for d in (_as_parsed(it, i) for i, it in enumerate(recipe_ingredients or [])) if m(d)]


def contains(recipe_ingredients, query: str, strict: bool = False, ignore_forms: bool = False, use_alts: bool = False) -> bool:
    return bool(find_matches(recipe_ingredients, query, strict, ignore_forms, use_alts))
