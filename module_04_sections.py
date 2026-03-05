"""
Module 4: Logical Section Detection
Reads cleaned text and splits it into named logical sections
using keyword and pattern matching.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# Ordered list of section names and their keyword triggers
SECTION_PATTERNS: List[tuple] = [
    ("hotel_details",       [r"hotel\s+details?", r"property\s+info", r"accommodation\s+details?"]),
    ("season_definitions",  [r"season\s+dates?", r"seasons?", r"validity\s+period", r"contract\s+period"]),
    ("room_rates",          [r"room\s+rates?", r"rate\s+table", r"tariff", r"price\s+list", r"room\s+types?"]),
    ("meal_plans",          [r"meal\s+plan", r"board\s+basis", r"supplement", r"breakfast", r"half\s+board",
                              r"full\s+board", r"all\s+inclusive"]),
    ("children_policy",     [r"child(ren)?'?s?\s+polic", r"infant", r"age\s+polic", r"child\s+discount",
                              r"free\s+of\s+charge.*child", r"child.*free"]),
    ("general_conditions",  [r"general\s+condition", r"terms\s+and\s+condition", r"booking\s+condition",
                              r"cancellation\s+polic", r"payment\s+polic"]),
    ("special_offers",      [r"special\s+offer", r"early\s+booking", r"discount", r"promotion"]),
]

# Fallback section for text that does not match any known section
UNKNOWN_SECTION = "other"


@dataclass
class Section:
    name: str
    content: str
    start_line: int = 0
    end_line: int = 0


def detect_sections(clean_text: str) -> Dict[str, Section]:
    """
    Split clean text into logical sections.
    Returns a dict mapping section_name -> Section.
    Multiple blocks of the same section are merged.
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

    result: Dict[str, Section] = {}
    for name, content_lines in sections.items():
        if content_lines:
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
    Returns a section name if the line looks like a section heading,
    otherwise returns None.
    """
    line_lower = line.lower().strip()
    if not line_lower:
        return None

    # Section headings are usually short lines (< 80 chars) possibly in caps
    if len(line_lower) > 100:
        return None

    for section_name, patterns in SECTION_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, line_lower):
                return section_name

    return None


def get_section_text(sections: Dict[str, Section], name: str) -> str:
    """Helper to safely get section content."""
    if name in sections:
        return sections[name].content
    return ""


def summarise_sections(sections: Dict[str, Section]) -> None:
    """Print a summary of detected sections."""
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
