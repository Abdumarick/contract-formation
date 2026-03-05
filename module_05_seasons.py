"""
Module 5: Season and Date Extraction
Reads the season section and extracts exact start/end dates.
Converts written date ranges into proper date objects.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Tuple


MONTH_MAP = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

# Ordinal suffixes
ORDINAL_RE = re.compile(r"(\d+)(st|nd|rd|th)", re.IGNORECASE)


@dataclass
class Season:
    name: str
    start_date: date
    end_date: date

    def __str__(self):
        return f"{self.name}: {self.start_date} → {self.end_date}"


def extract_seasons(season_text: str, fallback_year: Optional[int] = None) -> List[Season]:
    """
    Parse all season definitions from the season section text.
    Returns a list of Season objects with exact dates.
    """
    seasons: List[Season] = []
    lines = season_text.splitlines()
    year = fallback_year or datetime.now().year

    for line in lines:
        line = line.strip()
        if not line:
            continue

        season = _parse_season_line(line, year)
        if season:
            seasons.append(season)

    # Deduplicate by name, keeping first occurrence
    seen = set()
    unique = []
    for s in seasons:
        if s.name not in seen:
            seen.add(s.name)
            unique.append(s)

    return unique


def _parse_season_line(line: str, year: int) -> Optional[Season]:
    """
    Try to parse a single line into a Season.
    Handles patterns like:
      - "High Season: 01 Jan 2025 - 28 Feb 2025"
      - "Low Season  Jul 01 to Aug 31"
      - "Peak: January 7 – 31"
      - "S1 | 2025-01-07 | 2025-03-31"
    """
    line_lower = line.lower()

    # Extract season name: word(s) before colon, dash, pipe, or "season"
    name = _extract_season_name(line)
    if not name:
        return None

    # Find date range in the line
    date_range = _extract_date_range(line, year)
    if not date_range:
        return None

    start, end = date_range
    return Season(name=name, start_date=start, end_date=end)


def _extract_season_name(line: str) -> Optional[str]:
    """Extract the season name from a line."""
    # Pattern: NAME: ... or NAME - ... or NAME |
    match = re.match(r"^([A-Za-z][A-Za-z0-9 /\-_]{1,40}?)[\s:|\-–—]+", line.strip())
    if match:
        name = match.group(1).strip().rstrip("-:| ")
        if len(name) >= 2:
            return name.title()

    # Try keywords like Low/High/Peak/Shoulder/Off Season
    match = re.search(r"(low|high|peak|shoulder|off|mid|super|value)[\s\-]*(season)?", line, re.IGNORECASE)
    if match:
        return match.group(0).strip().title()

    # Season codes like S1, S2, A, B, C
    match = re.match(r"^([A-Z]\d?)\b", line.strip())
    if match:
        return match.group(1)

    return None


def _extract_date_range(line: str, year: int) -> Optional[Tuple[date, date]]:
    """Try multiple date range patterns."""
    # ISO dates: 2025-01-07 to 2025-03-31
    iso = re.findall(r"(\d{4}[-/]\d{2}[-/]\d{2})", line)
    if len(iso) >= 2:
        try:
            start = datetime.strptime(iso[0].replace("/", "-"), "%Y-%m-%d").date()
            end = datetime.strptime(iso[1].replace("/", "-"), "%Y-%m-%d").date()
            return start, end
        except ValueError:
            pass

    # DD/MM/YYYY or DD.MM.YYYY
    dmy = re.findall(r"(\d{1,2}[/\.]\d{1,2}[/\.]\d{4})", line)
    if len(dmy) >= 2:
        for fmt in ["%d/%m/%Y", "%d.%m.%Y"]:
            try:
                start = datetime.strptime(dmy[0], fmt).date()
                end = datetime.strptime(dmy[1], fmt).date()
                return start, end
            except ValueError:
                continue

    # DD MMM YYYY - DD MMM YYYY (e.g. "01 Jan 2025 - 28 Feb 2025")
    dmy_text = re.findall(r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})", line)
    if len(dmy_text) >= 2:
        try:
            start = _parse_text_date(dmy_text[0])
            end = _parse_text_date(dmy_text[1])
            if start and end:
                return start, end
        except Exception:
            pass

    # "Month Day to Month Day" without year (use fallback year)
    # e.g. "January 7 to 31" or "Jul 01 to Aug 31"
    month_day = re.findall(
        r"([A-Za-z]{3,9})\s+(\d{1,2})\s*(?:to|[-–—])\s*(?:([A-Za-z]{3,9})\s+)?(\d{1,2})", line
    )
    if month_day:
        m1_str, d1, m2_str, d2 = month_day[0]
        m1 = MONTH_MAP.get(m1_str.lower())
        m2 = MONTH_MAP.get(m2_str.lower()) if m2_str else m1
        if m1 and m2:
            try:
                start = date(year, m1, int(d1))
                end = date(year, m2, int(d2))
                return start, end
            except ValueError:
                pass

    # "DD Month – DD Month" e.g. "7 January - 31 March"
    day_month = re.findall(
        r"(\d{1,2})\s+([A-Za-z]{3,9})\s*(?:to|[-–—])\s*(\d{1,2})\s+([A-Za-z]{3,9})", line
    )
    if day_month:
        d1, m1_str, d2, m2_str = day_month[0]
        m1 = MONTH_MAP.get(m1_str.lower())
        m2 = MONTH_MAP.get(m2_str.lower())
        if m1 and m2:
            try:
                start = date(year, m1, int(d1))
                end = date(year, m2, int(d2))
                return start, end
            except ValueError:
                pass

    return None


def _parse_text_date(text: str) -> Optional[date]:
    """Parse a text date like '01 Jan 2025' or '1 January 2025'."""
    text = ORDINAL_RE.sub(r"\1", text).strip()
    for fmt in ["%d %b %Y", "%d %B %Y", "%B %d %Y", "%b %d %Y"]:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


if __name__ == "__main__":
    sample = """
    Low Season: 01 Jan 2025 - 30 Apr 2025
    High Season: 01 May 2025 - 31 Oct 2025
    Peak Season: 01 Nov 2025 - 31 Dec 2025
    """
    for s in extract_seasons(sample, 2025):
        print(s)
