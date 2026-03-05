"""
Module 8: Meal Plan and Supplement Extraction (v2 — Fully Automated)

Detects the base meal plan of the contract (BB, RO, HB, FB, AI).
Extracts HB and FB supplement amounts per person per night.
These are stored on room records — no separate supplement objects needed.
"""

import re
from typing import Dict, Optional, Tuple

MEAL_PLAN_KEYWORDS: Dict[str, list] = {
    "RO":  ["ro", "room only", "room-only", "bed only", "no meals"],
    "BB":  ["bb", "b&b", "bed & breakfast", "bed and breakfast", "breakfast included",
            "breakfast only", "with breakfast"],
    "HB":  ["hb", "half board", "half-board", "map", "modified american"],
    "FB":  ["fb", "full board", "full-board", "ap", "american plan"],
    "AI":  ["ai", "all inclusive", "all-inclusive", "ul", "ultra all-inclusive", "uai"],
}

HB_SUPP_PATTERNS = [r"half\s*board\s+supp", r"hb\s+supp", r"add\s+half\s+board"]
FB_SUPP_PATTERNS = [r"full\s*board\s+supp", r"fb\s+supp", r"add\s+full\s+board"]


def detect_base_meal_plan(text: str) -> str:
    """
    Detect the base meal plan code from contract text.
    Returns one of: RO, BB, HB, FB, AI.
    Defaults to BB if ambiguous.
    """
    text_lower = text.lower()
    # Check in priority order: AI → FB → HB → BB → RO
    for code in ["AI", "FB", "HB", "BB", "RO"]:
        for kw in MEAL_PLAN_KEYWORDS[code]:
            if kw in text_lower:
                return code
    return "BB"


def extract_supplements(text: str) -> Tuple[float, float]:
    """
    Extract HB and FB supplement amounts from text.
    Returns (hb_supplement, fb_supplement).
    Looks for explicit supplement lines; if not found returns 0.0.
    """
    hb = _find_supplement(text, HB_SUPP_PATTERNS)
    fb = _find_supplement(text, FB_SUPP_PATTERNS)
    return hb, fb


def _find_supplement(text: str, patterns: list) -> float:
    """Return the first numeric rate found on a line matching any pattern."""
    for line in text.splitlines():
        ll = line.lower()
        if any(re.search(p, ll) for p in patterns):
            val = _parse_rate(line)
            if val is not None:
                return val
    return 0.0


def _parse_rate(cell: str) -> Optional[float]:
    cleaned = re.sub(r"[€$£,]", "", str(cell))
    cleaned = re.sub(r"\b[A-Z]{3}\b", "", cleaned).strip()
    m = re.search(r"(\d+(?:\.\d{1,2})?)", cleaned)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None
