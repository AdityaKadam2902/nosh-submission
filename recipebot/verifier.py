"""Verifier (ARCHITECTURE §11): checks LLM prose against the code-built result + receipt. verify(prose, result, receipt) -> VerifyResult.
Checks: (1) every recipe id in prose exists in the result/receipt; (2) every number in prose appears in the result/receipt
(rounding to the prose precision allowed); (3) no banned claims (safe/guaranteed/allergen-free...)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

ID_RE = re.compile(r"\b(?:ar|epi|fn):\S+")
NUM_RE = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?%?")
BANNED = [(re.compile(p, re.I), label) for p, label in (
    (r"\bsafe(?:ly)?\b", "'safe'"), (r"\bguarantee[ds]?\b", "'guarantee'"), (r"\ballerg(?:y|en)[- ]free\b", "'allergen-free'"),
    (r"\brisk[- ]free\b", "'risk-free'"), (r"\b100\s*%\s*(?:free|safe|sure)\b", "'100% free'"), (r"\bdefinitely (?:free|safe)\b", "'definitely free'"))]
TRAIL = ".,;:!?)]}'\""


@dataclass
class VerifyResult:
    ok: bool
    problems: list[str] = field(default_factory=list)


def _walk(o, ids: set, nums: list):
    if isinstance(o, dict):
        for k, v in o.items():
            _walk(v, ids, nums)
    elif isinstance(o, (list, tuple, set)):
        nums.append(float(len(o)))
        for v in o:
            _walk(v, ids, nums)
    elif isinstance(o, bool) or o is None:
        pass
    elif isinstance(o, (int, float)):
        nums.append(float(o))
    elif isinstance(o, str):
        for tok in ID_RE.findall(o):
            ids.add(_clean_id(tok, None))
        if re.fullmatch(r"(?:ar|epi|fn):\S+", o.strip()):
            ids.add(o.strip())
        for m in NUM_RE.findall(re.sub(r"(?:ar|epi|fn):\S+", " ", o)):
            nums.append(_to_num(m))


def _to_num(s: str) -> float:
    return float(s.replace(",", "").rstrip("%"))


def _clean_id(tok: str, allowed: set | None) -> str:
    cand = tok
    if allowed is None:
        return cand
    while cand and cand not in allowed and cand[-1] in TRAIL:
        cand = cand[:-1]
    return cand if cand in allowed else tok


def collect(result, receipt) -> tuple[set, list]:
    ids, nums = set(), []
    _walk(result, ids, nums)
    _walk(receipt, ids, nums)
    return {i for i in ids if i}, nums


def _num_ok(p: float, decimals: int, nums: list) -> bool:
    for s in nums:
        if s == p or (not float(s).is_integer() or decimals > 0) and round(s, decimals) == round(p, decimals):
            return True
        if decimals == 0 and round(s) == p:  # "13%" for 13.28
            return True
    return False


def verify(prose: str, result, receipt=None) -> VerifyResult:
    ids, nums = collect(result, receipt)
    problems = []
    for tok in ID_RE.findall(prose):
        if _clean_id(tok, ids) not in ids:
            problems.append(f"unknown recipe id: {tok}")
    body = ID_RE.sub(" ", prose)
    for m in NUM_RE.findall(body):
        raw = m.rstrip("%")
        dec = len(raw.split(".")[1]) if "." in raw else 0
        if not _num_ok(_to_num(m), dec, nums):
            problems.append(f"number not in result/receipt: {m}")
    for rx, label in BANNED:
        if rx.search(prose):
            problems.append(f"banned claim: {label}")
    return VerifyResult(not problems, problems)
