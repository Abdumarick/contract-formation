"""
Module 8: Meal Plan and Supplement Extraction (v3)

BUSINESS RULES:
─────────────────────────────────────────────────────────────────
HB supplement = cost to upgrade from base plan to Half Board.
  If base = BB:  HB supplement = Dinner cost
  If base = RO:  HB supplement = Breakfast + Dinner

FB supplement = cost to upgrade from base plan to Full Board.
  If base = BB:  FB supplement = Lunch + Dinner
  If base = RO:  FB supplement = Breakfast + Lunch + Dinner
  If base = HB:  FB supplement = Lunch only

When the contract states HB/FB supplement amounts directly → use those.
When it only lists individual meal costs → compose from the rules above.
─────────────────────────────────────────────────────────────────
"""

import re
from typing import Dict, Optional, Tuple

# ── Meal plan detection ───────────────────────────────────────────────────────
MEAL_PLAN_PRIORITY = ["AI", "FB", "HB", "BB", "RO"]
MEAL_PLAN_KEYWORDS: Dict[str, list] = {
    "RO":  ["room only", "room-only", "bed only", "no meals"],
    "BB":  ["bed & breakfast", "bed and breakfast", "breakfast included",
            "breakfast only", "with breakfast", r"\bbb\b", r"\bb&b\b"],
    "HB":  ["half board", "half-board", "modified american", r"\bhb\b", r"\bmap\b",
            "demi-pension", "demi pension"],
    "FB":  ["full board", "full-board", "american plan", r"\bfb\b",
            "pension complet"],
    "AI":  ["all inclusive", "all-inclusive", "ultra all-inclusive",
            r"\bai\b", r"\buai\b"],
}

# ── Per-person / per-room detection ──────────────────────────────────────────
PER_ROOM_RE   = re.compile(
    r"per\s+room|p\.?r\.?n?\.?|per\s+night\s+room|per\s+unit", re.I)
PER_PERSON_RE = re.compile(
    r"per\s+person|p\.?p\.?n?\.?|pppn|pp\b|per\s+pax|per\s+adult", re.I)

# ── Individual meal keyword patterns ─────────────────────────────────────────
BREAKFAST_RE = re.compile(r"\bbreakfast\b|\bbf\b|\bbb\b", re.I)
LUNCH_RE     = re.compile(r"\blunch\b|\bml\b|\bmidday\b|\bluncheon\b", re.I)
DINNER_RE    = re.compile(r"\bdinner\b|\bmd\b|\bevening\s+meal\b|\bsupper\b", re.I)

# ── Supplement line patterns ──────────────────────────────────────────────────
SGL_PATTERNS = [
    r"single[\s\-]*(room\s+)?supp",
    r"sgl[\s\-]*supp",
    r"single\s+occ",
    r"single\s+use",
]
HB_PATTERNS = [
    r"half[\s\-]*board",
    r"\bhb\b",
    r"demi[\s\-]*pension",
]
FB_PATTERNS = [
    r"full[\s\-]*board",
    r"\bfb\b",
    r"pension\s+complet",
]


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def detect_base_meal_plan(text: str) -> str:
    """Return dominant meal plan code: AI / FB / HB / BB / RO. Default BB."""
    tl = text.lower()
    for code in MEAL_PLAN_PRIORITY:
        for kw in MEAL_PLAN_KEYWORDS[code]:
            if kw.startswith(r"\b"):
                if re.search(kw, tl):
                    return code
            elif kw in tl:
                return code
    return "BB"


def extract_supplements(text: str, base_plan: str = "BB") -> Tuple[float, float, float]:
    """
    Extract single_supplement, hb_supplement, fb_supplement.

    Strategy (in order of preference):
      1. If contract states HB/FB supplement amounts directly → use them.
      2. If contract lists individual meal costs → compose from base_plan rules.
      3. Return 0.0 for anything that cannot be determined.

    Returns:
        (single_supplement, hb_supplement, fb_supplement)
        All amounts are per-person per-night.
    """
    # ── Step 1: harvest individual meal costs and direct supplement lines ─────
    meal_costs = _extract_individual_meal_costs(text)
    sgl        = _find_supplement_value(text, SGL_PATTERNS, exclude=HB_PATTERNS + FB_PATTERNS)
    hb_direct  = _find_supplement_value(text, HB_PATTERNS,  exclude=FB_PATTERNS)
    fb_direct  = _find_supplement_value(text, FB_PATTERNS,  exclude=[])

    # ── Step 2: compose HB/FB if direct values missing ────────────────────────
    bfast  = meal_costs.get("breakfast", 0.0)
    lunch  = meal_costs.get("lunch",     0.0)
    dinner = meal_costs.get("dinner",    0.0)

    hb = hb_direct
    fb = fb_direct

    if hb == 0.0:
        hb = _compose_hb(base_plan, bfast, lunch, dinner)

    if fb == 0.0:
        fb = _compose_fb(base_plan, bfast, lunch, dinner, hb)

    return sgl, hb, fb


# ─────────────────────────────────────────────────────────────────────────────
# HB / FB composition rules
# ─────────────────────────────────────────────────────────────────────────────

def _compose_hb(base_plan: str, bfast: float, lunch: float, dinner: float) -> float:
    """
    HB supplement = what you add on top of the base plan to get Half Board.
    HB = base meals + dinner (HB always includes breakfast + dinner).
      base=BB → add dinner only
      base=RO → add breakfast + dinner
      base=HB/FB/AI → already includes it, supplement = 0
    """
    if base_plan == "BB":
        return dinner
    elif base_plan == "RO":
        return bfast + dinner
    return 0.0


def _compose_fb(base_plan: str, bfast: float, lunch: float, dinner: float,
                hb_amount: float) -> float:
    """
    FB supplement = what you add on top of the base plan to get Full Board.
    FB = breakfast + lunch + dinner.
      base=BB → add lunch + dinner
      base=RO → add breakfast + lunch + dinner
      base=HB → add lunch only (HB already has breakfast + dinner)
      base=FB/AI → 0
    """
    if base_plan == "BB":
        return lunch + dinner
    elif base_plan == "RO":
        return bfast + lunch + dinner
    elif base_plan == "HB":
        # If we have a direct HB amount, FB = HB + lunch
        if hb_amount > 0 and lunch > 0:
            return hb_amount + lunch
        return lunch
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Individual meal cost extraction
# ─────────────────────────────────────────────────────────────────────────────

def _extract_individual_meal_costs(text: str) -> Dict[str, float]:
    """
    Find breakfast / lunch / dinner costs from individual meal lines.
    Only reads lines that mention EXACTLY one meal type.
    """
    costs: Dict[str, float] = {}
    for line in text.splitlines():
        ll = line.lower().strip()
        if not ll:
            continue

        has_b = bool(BREAKFAST_RE.search(ll))
        has_l = bool(LUNCH_RE.search(ll))
        has_d = bool(DINNER_RE.search(ll))

        # Only parse if exactly one meal type mentioned (avoid HB/FB lines)
        n_meals = sum([has_b, has_l, has_d])
        if n_meals != 1:
            continue

        val = _parse_rate_after_colon(line)
        if val is None:
            continue

        if has_b and "breakfast" not in costs:
            costs["breakfast"] = val
        elif has_l and "lunch" not in costs:
            costs["lunch"] = val
        elif has_d and "dinner" not in costs:
            costs["dinner"] = val

    return costs


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_supplement_value(text: str, include_patterns: list,
                           exclude: list) -> float:
    """
    Return the per-person value from the first matching supplement line.
    Lines matched by any exclude pattern are skipped.
    """
    for line in text.splitlines():
        ll = line.lower().strip()
        if not ll:
            continue
        if not any(re.search(p, ll) for p in include_patterns):
            continue
        if any(re.search(p, ll) for p in exclude):
            continue
        val = _parse_rate_after_colon(line)
        if val is not None:
            return val
    return 0.0


def _parse_rate_after_colon(line: str) -> Optional[float]:
    """Parse a number from after the colon, or from the whole line."""
    text = line.split(":", 1)[1] if ":" in line else line
    cleaned = re.sub(r"[€$£,]", "", text)
    cleaned = re.sub(r"\b[A-Z]{3}\b", "", cleaned).strip()
    m = re.search(r"(\d+(?:\.\d{1,2})?)", cleaned)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def is_per_room(line: str) -> bool:
    """Return True if the line explicitly states a per-room rate."""
    return bool(PER_ROOM_RE.search(line))


def is_per_person(line: str) -> bool:
    """Return True if the line explicitly states a per-person rate."""
    return bool(PER_PERSON_RE.search(line))
