"""3-state restriction engine (ARCHITECTURE §5). Config: config/allergens.yaml.

check(ingredients, restriction, config=None) -> {"state": contains|possible|free, "evidence": [(pos, raw, reason)], ...}
  ingredients: raw strings or parsed dicts (canon/raw/pos/alts). Policy: contains -> excluded; possible -> excluded from the
  main list ("Uncertain"); free -> included with evidence; never "safe".
Hit resolution per ingredient: exception covering a hit cancels it; a longer may_contain phrase covering a definite hit
downgrades it to possible; global_exceptions clear the restriction for that ingredient; hits found only in an
alternative ("butter or margarine") are reported as possible.
"""
from __future__ import annotations

from recipebot.normalize import load_yaml, parse_ingredient, term_tokens

STATES = ("free", "possible", "contains")
FREE_NOTE = "no {r}-listed ingredient found; label and cross-contamination not verified"
_COMPILED: dict = {}


def default_config() -> dict:
    return load_yaml("allergens")


def _compile(key: str, cfg: dict):
    ck = (id(cfg), key)
    hit = _COMPILED.get(ck)
    if hit and hit[0] is cfg:
        return hit[1]
    r = cfg["restrictions"][key]
    comp = {name: [(t, term_tokens(t)) for t in (r.get(name) or []) if term_tokens(t)]
            for name in ("definite", "may_contain", "exceptions", "global_exceptions")}
    _COMPILED[ck] = (cfg, comp)
    return comp


def resolve(restriction: str, cfg: dict | None = None) -> list[str]:
    cfg = cfg or default_config()
    name = str(restriction).strip().lower().replace("-", "_").replace(" ", "_")
    cands = [name]
    for pre in ("no_", "non_"):
        if name.startswith(pre):
            cands.append(name[len(pre):])
    for suf in ("_free", "_allergy", "_intolerance"):
        if name.endswith(suf):
            cands.append(name[: -len(suf)])
    cands += [c[:-1] for c in list(cands) if c.endswith("s")]
    for c in cands:
        if c in cfg["restrictions"]:
            return [c]
        a = (cfg.get("restriction_aliases") or {}).get(c)
        if a:
            return [a] if isinstance(a, str) else list(a)
    raise ValueError(f"Unknown restriction: {restriction!r}")


def _spans(T: tuple, terms):
    out = []
    for term, tt in terms:
        n = len(tt)
        for i in range(len(T) - n + 1):
            if T[i:i + n] == tt:
                out.append((i, i + n, term))
    return out


def _hits(canon: str, comp) -> list[tuple[str, str]]:
    """[(state, term)] for one canon string."""
    T = tuple(canon.split())
    if not T:
        return []
    for _, g in comp["global_exceptions"]:
        n = len(g)
        if any(T[i:i + n] == g for i in range(len(T) - n + 1)):
            return []
    D, M, X = _spans(T, comp["definite"]), _spans(T, comp["may_contain"]), _spans(T, comp["exceptions"])
    cand = [("contains", s, e, t) for s, e, t in D] + [("possible", s, e, t) for s, e, t in M]
    cand = [c for c in cand if not any(xs <= c[1] and c[2] <= xe for xs, xe, _ in X)]
    cand = [c for c in cand if not (c[0] == "contains" and any(m[0] == "possible" and m[1] <= c[1] and c[2] <= m[2] and (m[2] - m[1]) > (c[2] - c[1]) for m in cand))]
    seen, out = set(), []
    for st, s, e, t in cand:
        if (s, e, st) not in seen:
            seen.add((s, e, st))
            out.append((st, t))
    return out


def _check_one(ingredients, key: str, cfg: dict, cache: dict | None = None) -> dict:
    comp = _compile(key, cfg)

    def hits(c):
        if cache is None:
            return _hits(c, comp)
        k = (key, c)
        if k not in cache:
            cache[k] = _hits(c, comp)
        return cache[k]

    evidence, state = [], "free"
    for i, item in enumerate(ingredients or []):
        d = parse_ingredient(item) if isinstance(item, str) else item
        canon = d.get("canon") or ""
        if not canon:
            continue
        pos, raw = d.get("pos", i), d.get("raw", canon)
        found = [(st, f"{'definite' if st == 'contains' else 'may_contain'}: '{t}'") for st, t in hits(canon)]
        if not found:
            for alt in d.get("alts") or []:
                for st, t in hits(alt):
                    found.append(("possible", f"alternative '{alt}': '{t}'"))
        for st, reason in found:
            evidence.append((pos, raw, reason))
            if STATES.index(st) > STATES.index(state):
                state = st
    return {"state": state, "evidence": evidence, "restriction": key,
            "note": FREE_NOTE.format(r=key) if state == "free" else None}


def check(ingredients, restriction: str, config: dict | None = None) -> dict:
    cfg = config or default_config()
    keys = resolve(restriction, cfg)
    results = [_check_one(ingredients, k, cfg) for k in keys]
    if len(results) == 1:
        return results[0]
    state = max((r["state"] for r in results), key=STATES.index)
    return {"state": state, "evidence": [e for r in results for e in r["evidence"]], "restriction": "+".join(keys),
            "note": FREE_NOTE.format(r="/".join(keys)) if state == "free" else None}


def check_all(ingredients, restrictions, config: dict | None = None) -> dict:
    """{restriction: result} plus overall worst state under key '_overall'."""
    out = {r: check(ingredients, r, config) for r in restrictions}
    out["_overall"] = max((v["state"] for v in out.values()), key=STATES.index, default="free")
    return out


class Checker:
    """check() with a per-canon cache, for bulk use (matching thousands of recipes). Same semantics as check()."""

    def __init__(self, restriction: str, config: dict | None = None):
        self.cfg = config or default_config()
        self.keys = resolve(restriction, self.cfg)
        self.restriction = "+".join(self.keys)
        self.cache: dict = {}

    def __call__(self, ingredients) -> dict:
        results = [_check_one(ingredients, k, self.cfg, self.cache) for k in self.keys]
        if len(results) == 1:
            return results[0]
        state = max((r["state"] for r in results), key=STATES.index)
        return {"state": state, "evidence": [e for r in results for e in r["evidence"]], "restriction": self.restriction,
                "note": FREE_NOTE.format(r="/".join(self.keys)) if state == "free" else None}
