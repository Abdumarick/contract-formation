"""
Module 7: Children and Age Policy Interpretation (v2 — Fully Automated)

Rules:
  - Infant/child age bands are defined in the contract.
  - Adults are always the base (min_age=13, max_age=99 unless contract says otherwise).
  - Free of charge → cost = 0.
  - Supported discounts (e.g. 50%) → applied to derive child cost.
  - Unsupported discounts (e.g. 75%) → NO row is created. Silently dropped.
  - Season names are NOT carried through — only dates will be used downstream.
"""

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


# Discounts that are SUPPORTED (row is created)
SUPPORTED_DISCOUNTS = {0.0, 50.0, 100.0}
# Any discount NOT in this set → no row created


@dataclass
class AgeBandRule:
    band_label: str          # "infant", "child", "adult"
    age_from: int
    age_to: int
    discount_pct: float      # 0 = free (FOC), 50 = half price, 100 = full price (adult)
    free_of_charge: bool     # True when discount_pct == 0 (cost will be 0)
    supported: bool          # False → skip, create no row
    notes: str = ""

    def __str__(self):
        if not self.supported:
            return f"Age {self.age_from}-{self.age_to}: {self.discount_pct:.0f}% [UNSUPPORTED — no row]"
        if self.free_of_charge:
            return f"Age {self.age_from}-{self.age_to}: FREE"
        return f"Age {self.age_from}-{self.age_to}: {self.discount_pct:.0f}% of adult cost"


FREE_PATTERNS = [
    r"free\s+of\s+charge", r"\bfoc\b", r"complimentary",
    r"no\s+charge", r"\b0\s*%", r"100\s*%\s*discount",
]

DISCOUNT_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")

# Default adult band if not specified in contract
DEFAULT_ADULT = AgeBandRule(
    band_label="adult",
    age_from=13,
    age_to=99,
    discount_pct=100.0,
    free_of_charge=False,
    supported=True,
)


def extract_children_policy(policy_text: str) -> List[AgeBandRule]:
    """
    Parse children/age policy text into AgeBandRule objects.
    Always includes an adult rule.
    Unsupported discount rules are included in the list with supported=False
    so the logger can record them, but downstream mapping will skip them.
    """
    rules: List[AgeBandRule] = []

    # First try to extract explicit age band definitions
    band_rules = _extract_band_definitions(policy_text)
    rules.extend(band_rules)

    # Always ensure there is an adult band
    has_adult = any(r.band_label == "adult" for r in rules)
    if not has_adult:
        rules.append(DEFAULT_ADULT)

    rules.sort(key=lambda r: r.age_from)
    return rules


def _extract_band_definitions(text: str) -> List[AgeBandRule]:
    """Try to parse age band definitions from free text."""
    rules = []
    lines = text.splitlines()

    # First pass: look for explicit "adult" age range
    adult_range = _find_adult_range(text)

    for line in lines:
        line = line.strip()
        if not line:
            continue
        rule = _parse_policy_line(line)
        if rule:
            rules.append(rule)

    # Patch adult age_from if we found an explicit adult range
    if adult_range:
        for r in rules:
            if r.band_label == "adult":
                r.age_from, r.age_to = adult_range
        # Add adult if still missing
        if not any(r.band_label == "adult" for r in rules):
            rules.append(AgeBandRule(
                band_label="adult",
                age_from=adult_range[0],
                age_to=adult_range[1],
                discount_pct=100.0,
                free_of_charge=False,
                supported=True,
            ))

    return rules


def _find_adult_range(text: str) -> Optional[Tuple[int, int]]:
    """Try to find an explicit adult age range like '13 to 99 as adult'."""
    m = re.search(
        r"(\d+)\s*(?:to|-|–)\s*(\d+)\s*(?:years?)?\s*(?:as\s+)?adult",
        text, re.I
    )
    if m:
        return int(m.group(1)), int(m.group(2))
    # "adult: 13+" pattern
    m = re.search(r"adult[s]?\s*[:\-–]\s*(\d+)\s*\+", text, re.I)
    if m:
        return int(m.group(1)), 99
    return None


def _parse_policy_line(line: str) -> Optional[AgeBandRule]:
    """Parse a single policy line into an AgeBandRule, or None."""
    ll = line.lower()

    # Skip lines with no age reference
    if not re.search(r"\bage\b|\byear\b|\binfant\b|\bchild\b|\badult\b|\bunder\b|\bup to\b", ll):
        return None

    # Determine band label
    if re.search(r"\binfant\b|\bbaby\b|\bbabies\b", ll):
        band_label = "infant"
    elif re.search(r"\bchild\b|\bchildren\b|\bkid\b", ll):
        band_label = "child"
    elif re.search(r"\badult\b", ll):
        band_label = "adult"
    else:
        band_label = "child"  # default non-adult

    # Is it free?
    is_free = any(re.search(p, ll) for p in FREE_PATTERNS)

    # Discount percentage
    m = DISCOUNT_PCT_RE.search(ll)
    discount_pct = float(m.group(1)) if m else None

    if band_label == "adult":
        discount_pct = 100.0
        is_free = False
    elif is_free and discount_pct is None:
        discount_pct = 0.0
    elif discount_pct is None:
        return None  # can't determine discount

    # Check if supported
    is_supported = (band_label == "adult") or (discount_pct in SUPPORTED_DISCOUNTS)

    # Extract age range
    age_from, age_to = _extract_age_range(line, band_label)

    return AgeBandRule(
        band_label=band_label,
        age_from=age_from,
        age_to=age_to,
        discount_pct=discount_pct,
        free_of_charge=(discount_pct == 0.0),
        supported=is_supported,
        notes=line[:120],
    )


def _extract_age_range(line: str, band_label: str) -> Tuple[int, int]:
    """Return (age_from, age_to) for the given line."""
    ll = line.lower()

    # Infant with no explicit range → 0-2 default
    if band_label == "infant" and not re.search(r"\d", line):
        return 0, 2

    # "under X" / "below X" / "up to X"
    m = re.search(r"(?:under|below|up\s+to)\s+(\d+)", ll)
    if m:
        return 0, int(m.group(1)) - 1

    # "X years and under" / "X and below"
    m = re.search(r"(\d+)\s+(?:years?\s+)?(?:and\s+)?(?:under|below|or\s+less)", ll)
    if m:
        return 0, int(m.group(1))

    # Range "X to Y" / "X - Y"
    m = re.search(r"(?:from\s+)?(\d+)\s*(?:to|-|–)\s*(\d+)\s*(?:years?)?", ll)
    if m:
        return int(m.group(1)), int(m.group(2))

    # "age X"
    m = re.search(r"age[ds]?\s+(\d+)", ll)
    if m:
        age = int(m.group(1))
        return age, age

    # Default fallbacks by label
    defaults = {"infant": (0, 2), "child": (3, 12), "adult": (13, 99)}
    return defaults.get(band_label, (0, 99))


def format_rules_summary(rules: List[AgeBandRule]) -> str:
    if not rules:
        return "No age band rules found."
    lines = ["Age Band Rules:"]
    for r in rules:
        lines.append(f"  {r}")
    return "\n".join(lines)
