"""
Module 4: Logical Section Detection (v3 — Fixed)
Reads cleaned text and splits it into named logical sections.

Key fixes:
  - Heading detection now REQUIRES the line to look like a heading:
    short, no price/currency numbers, no date patterns.
  - Dangerous broad patterns (e.g. "discount", "season", "supplement",
    "infant") are ONLY allowed when the line has no data noise.
  - Section patterns use stricter anchoring to avoid firing on data lines.
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional


# ── Heading-only patterns (strict) ───────────────────────────────────────────
# These fire ONLY on lines that pass the _is_heading_line() guard.
SECTION_PATTERNS: List[tuple] = [
    ("hotel_details",      [r"hotel\s+details?", r"property\s+info",
                             r"accommodation\s+details?", r"hotel\s+info"]),
    ("season_definitions", [r"season\s+dates?", r"validity\s+dates?",
                             r"contract\s+period", r"validity\s+period",
                             r"^seasons?$"]),          # only bare "Seasons" heading
    ("room_rates",         [r"room\s+rates?", r"rate\s+table", r"tariff",
                             r"price\s+list", r"room\s+types?\s*$",
                             r"accommodation\s+rates?"]),
    ("meal_plans",         [r"meal\s+plan", r"board\s+basis",
                             r"supplement\s*$",        # bare "Supplements" heading only
                             r"meal\s+supplement",
                             r"^breakfast\s*$",        # bare heading only
                             r"half\s+board\s+supplement",
                             r"full\s+board\s+supplement"]),
    ("children_policy",    [r"child(ren)?'?s?\s+polic",
                             r"age\s+polic",
                             r"infant\s+polic",
                             r"child(ren)?\s+rates?",
                             r"age\s+band"]),
    ("general_conditions", [r"general\s+condition", r"terms\s+and\s+condition",
                             r"booking\s+condition", r"cancellation\s+polic",
                             r"payment\s+polic"]),
    ("special_offers",     [r"special\s+offer", r"early\s+booking\s+discount",
                             r"promotion"]),           # removed bare "discount"
]

UNKNOWN_SECTION = "other"

# Patterns that indicate a line is DATA, not a heading
_PRICE_RE   = re.compile(r"\b\d{2,6}(?:\.\d{1,2})?\s*(?:usd|eur|gbp|aed|€|\$|£)?", re.I)
_DATE_RE    = re.compile(r"\b\d{1,2}[\s/\-\.]\w+[\s/\-\.]\d{2,4}\b"
                          r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2}", re.I)
_COLON_DATA = re.compile(r":\s*\d")          # "Room: 150" style data lines


@dataclass
class Section:
    name: str
    content: str
    start_line: int = 0


def detect_sections(clean_text: str) -> Dict[str, "Section"]:
    """
    Split clean text into logical sections.
    Returns a dict mapping section_name -> Section.
    """
    lines = clean_text.splitlines()
    sections: Dict[str, List[str]] = {name: [] for name, _ in SECTION_PATTERNS}
    sections[UNKNOWN_SECTION] = []

    current_section = UNKNOWN_SECTION
    section_line_starts: Dict[str, int] = {}

    for line_no, line in enumerate(lines):
        detected = _detect_section_from_line(line)
        if detected:
            current_section = detected
            if detected not in section_line_starts:
                section_line_starts[detected] = line_no
        sections[current_section].append(line)

    result: Dict[str, "Section"] = {}
    for name, content_lines in sections.items():
        content = "\n".join(content_lines).strip()
        if content:
            result[name] = Section(
                name=name,
                content=content,
                start_line=section_line_starts.get(name, 0),
            )
    return result


def _detect_section_from_line(line: str) -> Optional[str]:
    """
    Return a section name only if the line looks like a section HEADING.
    Data lines (prices, dates, colon-number patterns) are always ignored.
    """
    stripped = line.strip()
    ll = stripped.lower()

    if not ll:
        return None

    # Hard cap on heading length
    if len(ll) > 80:
        return None

    # Skip lines that look like data
    if not _is_heading_line(stripped):
        return None

    for section_name, patterns in SECTION_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, ll):
                return section_name

    return None


def _is_heading_line(line: str) -> bool:
    """
    Return True if this line looks like a section heading rather than data.
    Headings:
      - Do NOT contain a price/amount (two or more digits followed optionally by currency)
      - Do NOT contain a date
      - Do NOT look like "Key: numeric_value"
      - Are reasonably short (enforced upstream)
    """
    # Contains "colon + number" → data line (e.g. "Low Season: 150 USD")
    if _COLON_DATA.search(line):
        return False

    # Contains a date pattern → data line
    if _DATE_RE.search(line):
        return False

    # Contains a standalone price amount (2+ digits with optional currency)
    if _PRICE_RE.search(line):
        return False

    return True


def get_section_text(sections: Dict[str, "Section"], name: str) -> str:
    """Helper to safely get section content, empty string if missing."""
    return sections[name].content if name in sections else ""


def summarise_sections(sections: Dict[str, "Section"]) -> None:
    print(f"\nDetected {len(sections)} section(s):")
    for name, sec in sections.items():
        lines = sec.content.count("\n") + 1
        preview = sec.content[:80].replace("\n", " ")
        print(f"  [{name}] {lines} lines | {preview}...")


if __name__ == "__main__":
    import sys
    text = open(sys.argv[1]).read() if len(sys.argv) > 1 else ""
    secs = detect_sections(text)
    summarise_sections(secs)
