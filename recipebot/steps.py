"""Step counting (ARCHITECTURE §4). count_steps(instructions) -> (primary, alt).

Cleaning: remove ADVERTISEMENT, empty lines, bare numbering lines ("1.", "Step 2").
Primary rule: >=2 non-empty newline-separated blocks -> number of blocks; otherwise sentence count.
  (Adaptive, so it is correct for both block-style and single-paragraph records. Audit block/paragraph %
  decides nothing here except what is reported in the receipt; see PROGRESS "Decisions".)
Alt rule: sentence count always (sensitivity report). Label results "estimated instruction steps".
"""
from __future__ import annotations

import re

AD = "ADVERTISEMENT"
_BARE = re.compile(r"^\s*(?:step\s*)?\(?\d+[.):]?\s*$", re.I)
_LETTER = re.compile(r"[^\W\d_]")
_BOUND = re.compile(r"([.!?]+)([\"')\]]*)\s+(?=[\"'(\[]*[A-Z0-9])")
_ABBR = {"oz", "lb", "lbs", "tsp", "tbsp", "approx", "min", "mins", "hr", "hrs", "sec", "etc", "vs", "fig", "dr", "mr", "mrs", "ms",
         "st", "e.g", "i.e", "inc", "co", "temp", "pkg", "qt", "pt", "gal", "max", "ca", "cf", "fl", "dia", "sq"}


def blocks(text: str) -> list[str]:
    out = []
    for line in text.replace(AD, "").splitlines():
        line = line.strip()
        if line and not _BARE.match(line) and _LETTER.search(line):
            out.append(line)
    return out


def split_sentences(text: str) -> list[str]:
    out, start = [], 0
    for m in _BOUND.finditer(text):
        w = re.search(r"([A-Za-z.]+)$", text[:m.start()])
        word = w.group(1).lower().rstrip(".") if w else ""
        if m.group(1) == "." and (word in _ABBR or len(word) == 1):
            continue
        out.append(text[start:m.end()].strip())
        start = m.end()
    out.append(text[start:].strip())
    return [s for s in out if _LETTER.search(s)]


def count_steps(instructions) -> tuple[int, int]:
    if not isinstance(instructions, str):
        return 0, 0
    bl = blocks(instructions)
    if not bl:
        return 0, 0
    alt = len(split_sentences(" ".join(bl)))
    primary = len(bl) if len(bl) >= 2 else alt
    return primary, alt
