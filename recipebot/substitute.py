"""Task 3 substitution, Tier 1 (ARCHITECTURE §9 steps 1-5 + 8). Deterministic; NO LLM. Thresholds: config/roles.yaml.

substitute(recipe_id, target, constraints=None, conn=None) -> dict   (see keys at the bottom of this docstring)

Evidence before generation: suggestions are MINED from similar recipes (how recipes that lack the target do instead), graded by
rule, and the edited ingredient list is produced BY CODE. `can_fill` in roles.yaml only gates which candidates are role-compatible;
the dataset decides whether any is supported. Nothing here is a claim that the edited recipe works or is allergen-free.

Cohort: valid recipes (not the source) whose title shares the dish tokens (same-dish) or the dish class word (same-class) AND whose
ingredient set is similar (Jaccard, target/staples removed). C_with = cohort recipes containing the target; C_without = the rest.
Candidate x: share_without = |C_without using x| / |C_without|; share_with likewise; lift = share_without / max(share_with, eps).
Omission: C_without recipes that use NO can_fill item (reported separately; never graded above omit.max_grade).
Grades: strong | moderate | weak | conflicting | indirect | insufficient (rules: roles.yaml `grade`, text in the receipt `formula`).
Restrictions (constraints.check, 3-state): a candidate line that `contains` a restricted item (or an excluded ingredient) is BLOCKED;
`possible` -> uncertain list (never recommended); the edited list is re-checked and residual conflicts in OTHER lines are reported.

Result keys: status (ok | options | refused | blocked | no_target | no_edit_needed | unknown_recipe), recipe, target, roles, lines, cohort,
candidates (ranked, allowed), blocked, uncertain, omission, grade, grade_reason, selected, edits, edited_ingredients, constraints_before,
constraints_after, residual, edited_meets_constraints, refusal, notes, predictions ([] in Tier 1), receipt.
"""
from __future__ import annotations

import copy
import html
import math
import re
import statistics
from collections import Counter

from recipebot.constraints import check, resolve
from recipebot.db import connect, db_path
from recipebot.normalize import canon_name, clean_ingredients, load_yaml, matcher, tokens
from recipebot.receipt import dataset_counts, make_receipt
from recipebot.search import _load_ingredients, get_recipe

GRADES = ("strong", "moderate", "weak", "conflicting", "indirect", "insufficient")
POOL_SQL = "SELECT id, title FROM recipes WHERE is_valid=1 AND (title LIKE '%<dish token>%' OR ...)"
ING_SQL = "SELECT recipe_id,pos,raw,canon,forms,alts,qty,unit FROM ingredients WHERE recipe_id IN (<pool ids>) ORDER BY recipe_id,pos"
DISCLAIMER = "Dataset evidence about similar recipes, not a tested conversion; not medical advice; labels and cross-contamination are not verified."


# ---------------------------------------------------------------- config
def _merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def load_roles(config: dict | None = None) -> dict:
    """config/roles.yaml, optionally deep-merged with an override dict (tests / threshold experiments)."""
    base = load_yaml("roles")
    return _merge(base, config) if config else base


def _groups(entry: dict) -> list[list[str]]:
    """can_fill -> [[spellings of one candidate], ...] (canonical names, first = display name)."""
    out = []
    for it in entry.get("can_fill") or []:
        names = [canon_name(n) for n in (it if isinstance(it, list) else [it])]
        names = [n for n in dict.fromkeys(names) if n]
        if names:
            out.append(names)
    return out


def role_entry(target_canon: str, cfg: dict):
    """-> (key, entry, exact) | None. Exact key/alias first; else the longest key whose tokens occur inside the target."""
    ents = cfg.get("ingredients") or {}
    names = {}
    for k, e in ents.items():
        names[canon_name(k)] = k
        for a in e.get("aliases") or []:
            names.setdefault(canon_name(a), k)
    if target_canon in names:
        k = names[target_canon]
        return k, ents[k], True
    T = target_canon.split()
    best = None
    for n, k in names.items():
        N = n.split()
        if any(T[i:i + len(N)] == N for i in range(len(T) - len(N) + 1)) and (best is None or len(N) > len(best[0])):
            best = (N, k)
    return (best[1], ents[best[1]], False) if best else None


def _th(cfg: dict, entry: dict | None) -> dict:
    """defaults merged with the ingredient's optional `thresholds` override."""
    d = cfg["defaults"]
    return _merge(d, (entry or {}).get("thresholds") or {})


# ---------------------------------------------------------------- small helpers
def _clean(s) -> str:
    return re.sub(r"\s*ADVERTISEMENT\s*", " ", html.unescape(s or "")).strip()


def _fmt_q(q) -> str:
    return f"{q:g}"


def _pct(x) -> float:
    return round(100 * x, 1)


def _parse_constraints(constraints) -> tuple[list[str], list[str]]:
    if constraints is None:
        return [], []
    if isinstance(constraints, dict):
        restr, exc = constraints.get("restrictions") or [], constraints.get("exclude") or []
    else:
        restr, exc = list(constraints), []
    keys = []
    for r in restr:
        for k in resolve(r):  # unknown restriction -> ValueError (never silently ignored)
            if k not in keys:
                keys.append(k)
    return keys, [canon_name(e) for e in exc if canon_name(e)]


def _line_rows(text: str, pos: int) -> list[dict]:
    rows = clean_ingredients([text])
    for d in rows:
        d["pos"] = pos
    return rows


def _dish_tokens(title: str, th: dict) -> list[str]:
    stop = {canon_name(w) or w for w in th["title_stop"]} | set(th["title_stop"])
    return list(dict.fromkeys(t for t in tokens(html.unescape(title or "")) if t not in stop and len(t) > 1 and not t.isdigit()))


def _cm(name: str):
    """matcher for a CANDIDATE name. normalize.matcher compiles 'half and half' to token 'half_and_half' but canons are stored with spaces
    (known quirk, reported in ISSUES), so an exact canon equality is accepted too. Equality never bypasses distinct_pairs."""
    m, T = matcher(name), name.split()
    return lambda d: m(d) or (bool(d.get("canon")) and d["canon"].split() == T)


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a or b) else 0.0


# ---------------------------------------------------------------- cohort
def _build_cohort(conn, src_id: str, src_title: str, src_core_fn, is_target, th: dict):
    """-> (members, info). members: [{id,title,level,sim,rows,has_target}] ordered same-dish first, similarity desc, id."""
    c = th["cohort"]
    dtoks = _dish_tokens(src_title, th)
    classes = {canon_name(x) or x for x in th["dish_classes"]} | set(th["dish_classes"])
    cls = [t for t in dtoks if t in classes]
    info = {"dish_tokens": dtoks, "class_tokens": cls, "pool": 0, "same_dish": 0, "same_class": 0}
    if not dtoks:
        return [], info
    need = max(1, math.ceil(c["same_dish_title_frac"] * len(dtoks) - 1e-9))
    like = " OR ".join("title LIKE ? ESCAPE '\\'" for _ in dtoks)
    pats = ["%" + t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for t in dtoks]
    cand = []
    for rid, title in conn.execute(f"SELECT id, title FROM recipes WHERE is_valid=1 AND ({like})", pats):
        if rid == src_id:
            continue
        ts = set(tokens(html.unescape(title or "")))
        if len(ts & set(dtoks)) >= need:
            cand.append((rid, title, 1))
        elif cls and set(cls) <= ts:
            cand.append((rid, title, 2))
    info["pool"] = len(cand)
    src_core = src_core_fn()
    members = []
    ids = [x[0] for x in cand]
    rows_by = _load_ingredients(conn, ids) if ids else {}
    for rid, title, level in cand:
        rows = rows_by.get(rid, [])
        core = {d["canon"] for d in rows if d["canon"] and not is_target(d)} - _ignore_set(th)
        if not core:
            continue
        sim = _jaccard(src_core, core)
        if sim < (c["min_jaccard_same_dish"] if level == 1 else c["min_jaccard_same_class"]):
            continue
        members.append({"id": rid, "title": html.unescape(title or "").strip(), "level": level, "sim": sim, "rows": rows,
                        "has_target": any(is_target(d) for d in rows)})
    members.sort(key=lambda m: (m["level"], -m["sim"], m["id"]))
    members = members[: c["max_cohort"]]
    info["same_dish"] = sum(1 for m in members if m["level"] == 1)  # counted AFTER the cap, so it adds up with the cohort size
    info["same_class"] = sum(1 for m in members if m["level"] == 2)
    return members, info


def _ignore_set(th: dict) -> set:
    """canon names ignored when comparing recipes: staples.yaml default + roles.yaml similarity_ignore."""
    return {canon_name(x) or x for x in load_yaml("staples").get("default", [])} | {canon_name(x) or x for x in th["similarity_ignore"]}


# ---------------------------------------------------------------- grading
def _meets(c: dict, lvl: dict, lift_ok: bool) -> bool:
    return (c["share_without"] >= lvl["min_share"] and c["n_without"] >= lvl["min_support"]
            and (not lift_ok or c["lift"] is None or c["lift"] >= lvl["min_lift"]))


def _grade_candidate(c: dict, ranked: list[dict], W: int, same_dish_w: int, N_with: int, g: dict) -> tuple[str, str]:
    if W < g["min_without_any"]:
        return "insufficient", f"only {W} similar recipes lack the target (need >= {g['min_without_any']})"
    lift_ok = N_with >= g["min_with_for_lift"]
    rivals = [x for x in ranked if x is not c]
    rival = max(rivals, key=lambda x: x["share_without"]) if rivals else None
    if rival and rival["share_without"] >= c["share_without"] * (1 - g["tie_rel"]) and _meets(c, g["moderate"], lift_ok) and _meets(rival, g["moderate"], lift_ok):
        return "conflicting", (f"'{rival['name']}' ({rival['n_without']}/{W}) is within {int(g['tie_rel'] * 100)}% of '{c['name']}' "
                               f"({c['n_without']}/{W}): no single replacement stands out")
    if not lift_ok:
        return "indirect", f"only {N_with} similar recipes contain the target, so lift versus recipes WITH it is unreliable (need >= {g['min_with_for_lift']})"
    if W < g["min_without_direct"]:
        return "indirect", f"small cohort: {W} similar recipes without the target (direct evidence needs >= {g['min_without_direct']})"
    if same_dish_w < g["min_same_dish_without"]:
        return "indirect", f"only {same_dish_w} same-dish recipes without the target (need >= {g['min_same_dish_without']}); the rest are related dishes"
    s = g["strong"]
    leader = c is ranked[0]
    margin_ok = rival is None or rival["share_without"] <= c["share_without"] * (1 - s["margin_rel"])
    if leader and margin_ok and _meets(c, s, True):
        return "strong", f"{c['n_without']}/{W} similar recipes without the target use it vs {c['n_with']}/{N_with} with it (lift {_fl(c['lift'])}), clear margin over the runner-up"
    if _meets(c, g["moderate"], True):
        why = "" if leader else " (not the most frequent candidate)"
        return "moderate", f"{c['n_without']}/{W} without vs {c['n_with']}/{N_with} with (lift {_fl(c['lift'])}); below the strong thresholds or margin{why}"
    return "weak", f"only {c['n_without']}/{W} similar recipes without the target use it"


def _fl(x) -> str:
    return "n/a" if x is None else f"{x:.1f}"


# ---------------------------------------------------------------- amounts / lines
def _typical_amount(members_hit: list[dict], names: list[str], n_min: int):
    vals = []
    ms = [_cm(n) for n in names]
    for m in members_hit:
        for d in m["rows"]:
            if d["qty"] is not None and any(f(d) for f in ms):
                vals.append((d["unit"] or "", d["qty"]))
                break
    if not vals:
        return None
    unit = Counter(u for u, _ in vals).most_common(1)[0][0]
    qs = [q for u, q in vals if u == unit]
    n = len(qs)
    if n < n_min:
        return None
    return {"qty": statistics.median(qs), "unit": unit or None, "n": n}


def _new_line(name: str, amt) -> str:
    if not amt:
        return name
    return f"{_fmt_q(amt['qty'])} " + (f"{amt['unit']} " if amt["unit"] else "") + name


# ---------------------------------------------------------------- main
def substitute(recipe_id: str, target: str, constraints=None, conn=None, *, use: str | None = None, config: dict | None = None, db=None) -> dict:
    """See module docstring. `use` picks one MINED candidate by name (or 'omit'); anything else is refused (never invented)."""
    cfg = load_roles(config)
    restrictions, exclude = _parse_constraints(constraints)
    tcanon = canon_name(target or "")
    if not tcanon:
        raise ValueError("no recognizable target ingredient")
    own = conn is None
    conn = conn or connect(db or db_path(), readonly=True)
    try:
        return _run(conn, cfg, recipe_id, target, tcanon, restrictions, exclude, use)
    finally:
        if own:
            conn.close()


def _run(conn, cfg, recipe_id, target_in, tcanon, restrictions, exclude, use) -> dict:
    notes: list[str] = []
    rec = get_recipe(recipe_id, conn=conn)
    base = {"status": None, "recipe": {"id": recipe_id, "title": None}, "target": tcanon, "target_input": target_in, "roles": [], "lines": [],
            "cohort": None, "candidates": [], "blocked": [], "uncertain": [], "omission": None, "grade": "insufficient", "grade_reason": "",
            "selected": None, "edits": [], "edited_ingredients": None, "constraints_before": {}, "constraints_after": {}, "residual": [],
            "edited_meets_constraints": None, "refusal": None, "notes": notes, "predictions": [], "restrictions": restrictions, "exclude": exclude}
    counts = dataset_counts(conn)
    if rec is None:
        return {**base, "status": "unknown_recipe", "refusal": f"I don't have a recipe with id {recipe_id}.",
                "receipt": make_receipt("substitute", [f"recipe = {recipe_id}"], counts, recipe_ids=[])}
    title = _clean(rec["title"])
    base["recipe"]["title"] = title
    parsed = rec["parsed"]
    orig_lines = rec["ingredients"] or []

    # 1. role lookup (roles come from config, never from the LLM)
    hit = role_entry(tcanon, cfg)
    key, entry, exact = hit if hit else (None, None, False)
    th = _th(cfg, entry)
    g = th["grade"]
    names = [canon_name(key)] + [canon_name(a) for a in (entry.get("aliases") or [])] if (hit and exact) else [tcanon]
    names = [n for n in dict.fromkeys(names) if n]
    groups = _groups(entry) if entry else []
    tm = [matcher(n) for n in names]
    tm_alt = [matcher(n, use_alts=True) for n in names]
    tset = {t for n in names for t in n.split()}
    specific = [_cm(n) for grp in groups for n in grp if set(n.split()) > tset and not any(n == x for x in names)]
    is_target = lambda d: any(f(d) for f in tm) and not any(f(d) for f in specific)  # "almond flour" is a candidate for flour, not the target
    base["roles"] = list(entry.get("roles") or []) if entry else []
    base["role_key"] = key

    # 2. locate target lines (form-aware matcher); lines where it is only an "or" alternative need no substitution
    pos_rows: dict[int, list[dict]] = {}
    for d in parsed:
        pos_rows.setdefault(d["pos"], []).append(d)
    tpos = sorted({d["pos"] for d in parsed if is_target(d)})
    alt_pos = sorted({d["pos"] for d in parsed if d["pos"] not in tpos and any(f(d) for f in tm_alt) and not any(f(d) for f in specific)})
    base["lines"] = [{"pos": p, "raw": _clean(orig_lines[p]) if p < len(orig_lines) else "", "shared": len(pos_rows[p]) > 1} for p in tpos]
    filters = [f"recipe = {recipe_id} ({title})", f"target = {tcanon}" + (f" (role entry '{key}': {', '.join(base['roles'])})" if hit else " (NO role entry in config/roles.yaml)")]
    if restrictions: filters.append("restrictions (3-state; 'possible' -> uncertain, 'contains' -> blocked): " + ", ".join(restrictions))
    if exclude: filters.append("user excludes: " + ", ".join(exclude))
    rcpt = lambda **kw: make_receipt("substitute", filters, counts, recipe_ids=[recipe_id] + kw.pop("ids", []), **kw)
    if not tpos:
        if alt_pos:
            lines = "; ".join(f"line {p}: '{_clean(orig_lines[p])}'" for p in alt_pos)
            return {**base, "status": "no_edit_needed", "refusal": f"'{tcanon}' appears only as an 'or' alternative ({lines}); the recipe already offers another option, so no substitution is needed.",
                    "receipt": rcpt(formula="target located by form-aware matcher incl. 'or' alternatives")}
        return {**base, "status": "no_target", "refusal": f"{recipe_id} has no '{tcanon}' ingredient line, so there is nothing to substitute.",
                "receipt": rcpt(formula="target located by form-aware matcher (normalize.matcher)")}
    if not hit:
        msg = f"I have no role entry for '{tcanon}' in config/roles.yaml, so I will not guess what it does or what can replace it."
        return {**base, "status": "refused", "grade": "insufficient", "grade_reason": "target not in roles.yaml", "refusal": msg,
                "receipt": rcpt(formula="roles come from config/roles.yaml; unknown target -> insufficient")}

    # 3. cohort
    src_core = lambda: {d["canon"] for d in parsed if d["canon"] and not is_target(d)} - _ignore_set(th)
    members, info = _build_cohort(conn, recipe_id, title, src_core, is_target, th)
    C_with = [m for m in members if m["has_target"]]
    C_wo = [m for m in members if not m["has_target"]]
    W, NW = len(C_wo), len(C_with)
    same_dish_w = sum(1 for m in C_wo if m["level"] == 1)
    base["cohort"] = {"size": len(members), "with": NW, "without": W, "same_dish": info["same_dish"], "same_class": info["same_class"], "same_dish_without": same_dish_w,
                      "pool": info["pool"], "dish_tokens": info["dish_tokens"], "class_tokens": info["class_tokens"],
                      "ids_with": [m["id"] for m in C_with[: th["support_ids"]]], "ids_without": [m["id"] for m in C_wo[: th["support_ids"]]]}
    cc = th["cohort"]
    filters.append(f"cohort: valid recipes whose title shares >= {math.ceil(cc['same_dish_title_frac'] * max(1, len(info['dish_tokens'])) - 1e-9)} of the dish tokens {info['dish_tokens']} "
                   f"(same-dish, ingredient Jaccard >= {cc['min_jaccard_same_dish']}) or the dish class {info['class_tokens'] or '-'} (Jaccard >= {cc['min_jaccard_same_class']}); "
                   f"top {cc['max_cohort']} by similarity")

    # 4. candidates (role-compatible only) and omission
    src_has = lambda names_: any(_cm(n)(d) and not is_target(d) for n in names_ for d in parsed)
    rows_all, skipped = [], []
    below, noise = 0, []
    for grp in groups:
        if any(n in names for n in grp):
            continue
        if src_has(grp):
            skipped.append(grp[0])
            continue
        ms = [_cm(n) for n in grp]
        hits = lambda m: any(f(d) and not is_target(d) for f in ms for d in m["rows"])
        hw, hwith = [m for m in C_wo if hits(m)], [m for m in C_with if hits(m)]
        sw, sh = (len(hw) / W if W else 0.0), (len(hwith) / NW if NW else 0.0)
        lift = (sw / max(sh, th["candidate"]["lift_epsilon"])) if NW else None
        c = {"name": grp[0], "kind": "replace", "n_without": len(hw), "share_without": sw, "pct_without": _pct(sw), "n_with": len(hwith), "share_with": sh,
             "pct_with": _pct(sh), "lift": None if lift is None else round(lift, 2), "support_ids": [m["id"] for m in hw[: th["support_ids"]]],
             "typical_amount": _typical_amount(hw, grp, th["typical_amount_min_n"]), "variants": grp}
        if len(hw) < th["candidate"]["min_support"]:
            below += 1
            continue
        lift_ok = NW >= g["min_with_for_lift"]
        if lift_ok and lift is not None and lift < th["candidate"]["min_lift"]:
            if sw >= g["moderate"]["min_share"]:
                noise.append(c)
            below += 1
            continue
        c["new_line"] = _new_line(c["name"], c["typical_amount"])
        rows_all.append(c)
    base["skipped_already_in_recipe"] = skipped

    # restrictions / excludes on the candidate line itself
    allowed, uncertain, blocked = [], [], []
    ex_m = [(e, matcher(e)) for e in exclude]
    for c in rows_all:
        rows = _line_rows(c["new_line"], -1)
        st, ev = {}, []
        for r in restrictions:
            res = check(rows, r)
            st[r] = res["state"]
            ev += [{"restriction": r, "state": res["state"], "line": e[1], "reason": e[2]} for e in res["evidence"]]
        for e, f in ex_m:
            if any(f(d) for d in rows):
                st[f"exclude:{e}"] = "contains"
                ev.append({"restriction": f"exclude:{e}", "state": "contains", "line": c["new_line"], "reason": f"you excluded '{e}'"})
        c["constraint"] = {"state": max(st.values(), key=("free", "possible", "contains").index, default="free"), "by": st, "evidence": ev}
        {"contains": blocked, "possible": uncertain, "free": allowed}[c["constraint"]["state"]].append(c)
    rank = lambda c: (-c["share_without"], -(c["lift"] if c["lift"] is not None else 1e9), -c["n_without"], c["name"])
    for lst in (allowed, uncertain, blocked):
        lst.sort(key=rank)
    for c in allowed:
        c["grade"], c["grade_reason"] = _grade_candidate(c, allowed, W, same_dish_w, NW, g)
    for c in uncertain + blocked:
        c["grade"], c["grade_reason"] = _grade_candidate(c, allowed + [c], W, same_dish_w, NW, g)
        c["grade_reason"] += " [not eligible: restriction]"

    omit = None
    if entry.get("omit_ok") and W:
        allnames = [_cm(n) for grp in groups for n in grp]
        none_ids = [m["id"] for m in C_wo if not any(f(d) and not is_target(d) for f in allnames for d in m["rows"])]
        sh = len(none_ids) / W
        gr = "insufficient" if W < g["min_without_any"] else ("indirect" if (W < g["min_without_direct"] or same_dish_w < g["min_same_dish_without"]) else
                                                              (g["omit"]["max_grade"] if sh >= g["omit"]["min_share"] else "weak"))
        if len(none_ids) >= th["candidate"]["min_support"]:
            omit = {"name": "omit", "kind": "omit", "n_without": len(none_ids), "share_without": sh, "pct_without": _pct(sh), "lift": None, "n_with": None,
                    "support_ids": none_ids[: th["support_ids"]], "grade": gr, "new_line": None,
                    "grade_reason": f"{len(none_ids)}/{W} similar recipes without {tcanon} use no role-compatible replacement either (omission is common here; this does not show the dish works the same)"}
    base.update(candidates=allowed, blocked=blocked, uncertain=uncertain, omission=omit)

    # 5. overall grade, selection, refusal
    sel, grade, why = None, "insufficient", ""
    if W < g["min_without_any"]:
        why = f"only {W} similar recipes lack '{tcanon}' (cohort {len(members)}: {NW} with, {W} without; need >= {g['min_without_any']} without)"
    elif allowed:
        top = allowed[0]
        grade, why = top["grade"], top["grade_reason"]
        if grade != "conflicting":
            sel = top
    elif blocked or uncertain:
        grade = "insufficient"
        bl = ", ".join(f"{c['name']} ({c['n_without']}/{W})" for c in blocked + uncertain)
        why = f"every replacement the dataset supports conflicts with your restrictions: {bl}"
    elif noise:
        grade = "conflicting"
        why = "role-compatible items are frequent in recipes without the target, but just as frequent in recipes WITH it, so they are common ingredients, not replacements: " + ", ".join(
            f"{c['name']} ({c['n_without']}/{W} without vs {c['n_with']}/{NW} with)" for c in noise[:4])
    else:
        why = f"no role-compatible replacement is used in >= {th['candidate']['min_support']} similar recipes without '{tcanon}' (cohort {len(members)}: {NW} with, {W} without)"
    if sel is None and grade in ("insufficient", "weak") and omit and omit["grade"] in ("moderate", "indirect", "weak") and not allowed and W >= g["min_without_any"] and omit["share_without"] >= g["omit"]["min_share"]:
        sel, grade, why = omit, omit["grade"], omit["grade_reason"]
    base["grade"], base["grade_reason"] = grade, why

    # explicit choice by the user: only MINED candidates are acceptable
    if use:
        u = canon_name(use) or use.strip().lower()
        pool = allowed + uncertain + blocked + ([omit] if omit else [])
        pick = next((c for c in pool if u == c["name"] or u in [canon_name(v) for v in c.get("variants", [])]), None)
        if pick is None:
            base["refusal"] = f"'{use}' is not a replacement supported by the dataset evidence for '{tcanon}' in this cohort, so I will not propose it. Mined options: " + (", ".join(c["name"] for c in allowed) or "none")
            base["status"] = "refused"
            base["receipt"] = _receipt(rcpt, th, g, base, members, W, NW, below, restrictions, allowed, blocked, uncertain)
            return base
        if pick in blocked:
            ev = "; ".join(f"{e['restriction']}: {e['reason']}" for e in pick["constraint"]["evidence"][:2])
            base["refusal"] = f"BLOCKED: '{pick['name']}' violates your stated constraint ({ev})."
            base["status"] = "blocked"
            base["receipt"] = _receipt(rcpt, th, g, base, members, W, NW, below, restrictions, allowed, blocked, uncertain)
            return base
        if pick in uncertain:
            ev = "; ".join(f"{e['restriction']}: {e['reason']}" for e in pick["constraint"]["evidence"][:2])
            base["refusal"] = f"UNCERTAIN: '{pick['name']}' may violate your stated constraint ({ev}); I will not propose it as a replacement."
            base["status"] = "refused"
            base["receipt"] = _receipt(rcpt, th, g, base, members, W, NW, below, restrictions, allowed, blocked, uncertain)
            return base
        sel = pick
        notes.append(f"replacement chosen by you ('{pick['name']}'); its evidence grade is {pick['grade']}")
        base["grade"], base["grade_reason"] = pick["grade"], pick["grade_reason"]

    if sel is None:
        base["status"] = "options" if grade == "conflicting" and allowed else "refused"
        if base["status"] == "refused":
            base["refusal"] = f"I will not recommend a specific replacement for '{tcanon}' in {recipe_id}: {why}."
        else:
            base["refusal"] = f"No single replacement stands out ({why}). Pick one of the listed options with --use <name>."
    else:
        base["status"] = "ok"
        base["selected"] = sel["name"]
        _apply_edit(base, sel, rec, parsed, orig_lines, tpos, pos_rows, restrictions, notes)
    base["receipt"] = _receipt(rcpt, th, g, base, members, W, NW, below, restrictions, allowed, blocked, uncertain)
    return base


# ---------------------------------------------------------------- edit applied BY CODE
def _apply_edit(base, sel, rec, parsed, orig_lines, tpos, pos_rows, restrictions, notes):
    edits, replaced = [], set()
    for p in tpos:
        old = _clean(orig_lines[p])
        if len(pos_rows[p]) > 1:  # e.g. "salt and pepper": one line holds several ingredients; never rewrite it blindly
            edits.append({"op": "manual", "pos": p, "old": old, "new": None, "note": "this line holds several ingredients; edit it by hand"})
            notes.append(f"line {p} ('{old}') holds several ingredients: not edited automatically")
            continue
        replaced.add(p)
        if sel["kind"] == "omit":
            edits.append({"op": "remove", "pos": p, "old": old, "new": None})
        else:
            amt = sel.get("typical_amount")
            edits.append({"op": "replace", "pos": p, "old": old, "new": sel["new_line"],
                          "amount_basis": (f"median of {amt['n']} similar recipes that give an amount in the same unit (not a tested conversion)" if amt else
                                           "no reliable typical amount in the cohort: quantity not determined")})
    base["edits"] = edits
    ing_pos = {d["pos"] for d in parsed}
    final, marks = [], []
    for i, line in enumerate(orig_lines):
        if i not in ing_pos:
            continue
        e = next((x for x in edits if x["pos"] == i and x["op"] != "manual"), None)
        if e is None:
            final.append(_clean(line)); marks.append("unchanged")
        elif e["op"] == "replace":
            final.append(e["new"]); marks.append("replaced")
    base["edited_ingredients"], base["edit_marks"] = final, marks
    before = {r: check(parsed, r) for r in restrictions}
    after_rows = [d for d in parsed if d["pos"] not in replaced]
    if sel["kind"] == "replace":
        for p in sorted(replaced):
            after_rows += _line_rows(sel["new_line"], p)
    after = {r: check(after_rows, r) for r in restrictions}
    slim = lambda res: {r: {"state": v["state"], "evidence": [{"pos": e[0], "line": _clean(e[1]), "reason": e[2]} for e in v["evidence"]], "note": v["note"]} for r, v in res.items()}
    base["constraints_before"], base["constraints_after"] = slim(before), slim(after)
    base["residual"] = [{"restriction": r, "state": v["state"], "pos": e["pos"], "line": e["line"], "reason": e["reason"]}
                        for r, v in base["constraints_after"].items() for e in v["evidence"] if e["pos"] not in replaced]
    base["edited_meets_constraints"] = all(v["state"] == "free" for v in after.values()) if restrictions else None
    if restrictions and not base["edited_meets_constraints"]:
        notes.append("the edited recipe still has other lines that conflict with / may conflict with your restrictions (see residual); replacing the target alone does not resolve them")


def _receipt(rcpt, th, g, base, members, W, NW, below, restrictions, allowed, blocked, uncertain):
    ids = list(dict.fromkeys(i for c in allowed + base["uncertain"] + base["blocked"] + ([base["omission"]] if base["omission"] else []) for i in c["support_ids"]))
    c, s, m = th["candidate"], g["strong"], g["moderate"]
    return rcpt(
        ids=ids, n_analyzed=len(members),
        denominator=f"{W} similar recipes WITHOUT the target (share_without = recipes using the candidate / {W}); {NW} similar recipes WITH it (share_with = / {NW})",
        formula=(f"lift = share_without / max(share_with, {c['lift_epsilon']}); candidate kept if used in >= {c['min_support']} recipes without the target and lift >= {c['min_lift']}. "
                 f"insufficient: < {g['min_without_any']} without. indirect: < {g['min_without_direct']} without, < {g['min_same_dish_without']} same-dish without, or < {g['min_with_for_lift']} with (lift unreliable). "
                 f"conflicting: top two within {int(g['tie_rel'] * 100)}% (relative). strong: leader, share >= {s['min_share']}, lift >= {s['min_lift']}, support >= {s['min_support']}, runner-up <= {1 - s['margin_rel']:.2f} x leader. "
                 f"moderate: share >= {m['min_share']}, lift >= {m['min_lift']}, support >= {m['min_support']}. weak: otherwise. omission: share >= {g['omit']['min_share']}, graded at most {g['omit']['max_grade']}. Thresholds: config/roles.yaml"),
        ordering="candidates by share_without desc, lift desc, support desc, name; supporting ids = most similar cohort recipes first",
        normalization="form-aware ingredient matching (normalize.matcher); role-compatible candidates only (config/roles.yaml can_fill)",
        candidates=len(allowed) + len(blocked) + len(base["uncertain"]),
        dropped=f"below support/lift={below}, blocked by restrictions={len(blocked)}, uncertain (possible)={len(uncertain)}",
        sql=[POOL_SQL, ING_SQL], grade=base["grade"], disclaimer=DISCLAIMER)
