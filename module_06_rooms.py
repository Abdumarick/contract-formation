"""
Module 6: Room and Rate Table Parsing (v2 — Fully Automated)
Extracts room categories, names, max_cap, min_pax, max_pax, base cost,
single_supplement, hb_supplement, and fb_supplement.
Currency is always normalised to USD.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import pdfplumber


@dataclass
class RoomRate:
    room_name: str
    room_description: str
    max_cap: int              # maximum total occupancy
    min_pax: int              # always 1
    max_pax: int              # = max_cap
    season_name: str
    cost: float               # base adult cost (per night)
    single_supplement: float  # 0 if not applicable / not found
    hb_supplement: float      # half board supplement per person
    fb_supplement: float      # full board supplement per person
    currency: str = "USD"
    base_meal_plan: str = "BB"
    extra_notes: str = ""


CAPACITY_PATTERNS = [
    (r"\bsgl\b|\bsingle\b",               1),
    (r"\bdbl\b|\bdouble\b|\btwn\b|\btwin\b", 2),
    (r"\btrpl?\b|\btriple\b",             3),
    (r"\bquad\b|\bquadruple\b",           4),
    (r"\bfamily\b",                       4),
    (r"\bjunior\s+suite\b",               2),
    (r"\bsuite\b",                        2),
    (r"\bstudio\b",                       2),
]

HB_KEYWORDS  = [r"half\s*board", r"\bhb\b", r"map\b"]
FB_KEYWORDS  = [r"full\s*board", r"\bfb\b", r"\bap\b"]
SGL_KEYWORDS = [r"single\s+supp", r"sgl\s+supp", r"single\s+occ"]


def parse_room_rates(
    rates_text: str,
    seasons: list,
    file_path: Optional[str] = None,
) -> List[RoomRate]:
    records: List[RoomRate] = []

    if file_path:
        records = _parse_pdf_tables(file_path, seasons)

    if not records:
        records = _parse_text_rates(rates_text, seasons)

    return _deduplicate(records)


# ── PDF table extraction ──────────────────────────────────────────────────────

def _parse_pdf_tables(file_path: str, seasons: list) -> List[RoomRate]:
    records: List[RoomRate] = []
    season_names = [s.name for s in seasons]
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                for table in (page.extract_tables() or []):
                    records.extend(_interpret_table(table, season_names))
    except Exception:
        pass
    return records


def _interpret_table(table: List[List], season_names: List[str]) -> List[RoomRate]:
    if not table or len(table) < 2:
        return []
    table = [[str(c).strip() if c else "" for c in row] for row in table]

    header_idx, headers = _find_header_row(table, season_names)
    if header_idx is None:
        return []

    season_col_map: Dict[int, str] = {}
    room_col = 0
    sgl_col = hb_col = fb_col = None

    for ci, h in enumerate(headers):
        hl = h.lower()
        for sname in season_names:
            if sname.lower() in hl or hl in sname.lower():
                season_col_map[ci] = sname
                break
        if re.search(r"\broom\b|\btype\b|\bcategory\b|\baccommodation\b", hl):
            room_col = ci
        if any(re.search(p, hl) for p in SGL_KEYWORDS):
            sgl_col = ci
        if any(re.search(p, hl) for p in HB_KEYWORDS):
            hb_col = ci
        if any(re.search(p, hl) for p in FB_KEYWORDS):
            fb_col = ci

    if not season_col_map:
        for ci, h in enumerate(headers):
            if ci not in {room_col, sgl_col, hb_col, fb_col}:
                if re.search(r"\d|season|rate|price|cost", h, re.I):
                    season_col_map[ci] = h or f"Season_{ci}"

    records = []
    for row in table[header_idx + 1:]:
        if not row or not row[room_col]:
            continue
        room_name = row[room_col].strip()
        if not room_name or _is_header_like(room_name):
            continue

        max_cap = _infer_capacity(room_name)
        min_pax, max_pax = 1, max_cap

        sgl = (_parse_rate(row[sgl_col]) or 0.0) if sgl_col and sgl_col < len(row) else 0.0
        hb  = (_parse_rate(row[hb_col])  or 0.0) if hb_col  and hb_col  < len(row) else 0.0
        fb  = (_parse_rate(row[fb_col])  or 0.0) if fb_col  and fb_col  < len(row) else 0.0
        # Single supplement only applies when room capacity > 1
        effective_sgl = sgl if max_cap > 1 else 0.0

        for ci, sname in season_col_map.items():
            if ci >= len(row):
                continue
            cost = _parse_rate(row[ci])
            if cost is None:
                continue
            records.append(RoomRate(
                room_name=room_name,
                room_description=room_name,
                max_cap=max_cap,
                min_pax=min_pax,
                max_pax=max_pax,
                season_name=sname,
                cost=cost,
                single_supplement=effective_sgl,
                hb_supplement=hb,
                fb_supplement=fb,
                currency="USD",
            ))
    return records


def _find_header_row(table, season_names):
    for i, row in enumerate(table[:5]):
        rt = " ".join(row).lower()
        if (re.search(r"\broom\b|\btype\b|\bcategory\b|\brate\b|\bprice\b|\bcost\b", rt)
                or any(s.lower() in rt for s in season_names)):
            return i, row
    return None, []


def _is_header_like(text: str) -> bool:
    return bool(re.search(
        r"^\s*(room|type|category|description|rate|price|season|cost)\s*$", text, re.I
    ))


# ── Text fallback ─────────────────────────────────────────────────────────────

def _parse_text_rates(text: str, seasons: list) -> List[RoomRate]:
    records = []
    season_names = [s.name for s in seasons] or ["Default"]

    # Harvest global supplement values first
    sgl_rate = hb_rate = fb_rate = 0.0
    for line in text.splitlines():
        ll = line.lower().strip()
        r = _parse_rate(line)
        if r is None:
            continue
        if any(re.search(p, ll) for p in SGL_KEYWORDS):
            sgl_rate = r
        elif any(re.search(p, ll) for p in HB_KEYWORDS):
            hb_rate = r
        elif any(re.search(p, ll) for p in FB_KEYWORDS):
            fb_rate = r

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        ll = line.lower()
        if any(re.search(p, ll) for p in SGL_KEYWORDS + HB_KEYWORDS + FB_KEYWORDS):
            continue

        cost = _parse_rate(line)
        if cost is None:
            continue

        m = re.match(r"^([A-Za-z][A-Za-z\s/\-]{3,50}?)\s*[:\-–]", line)
        room_name = m.group(1).strip() if m else "Room"

        max_cap = _infer_capacity(room_name)
        effective_sgl = sgl_rate if max_cap > 1 else 0.0

        matched_season = season_names[0]
        for sname in season_names:
            if sname.lower() in ll:
                matched_season = sname
                break

        records.append(RoomRate(
            room_name=room_name,
            room_description=room_name,
            max_cap=max_cap,
            min_pax=1,
            max_pax=max_cap,
            season_name=matched_season,
            cost=cost,
            single_supplement=effective_sgl,
            hb_supplement=hb_rate,
            fb_supplement=fb_rate,
            currency="USD",
        ))
    return records


# ── Helpers ───────────────────────────────────────────────────────────────────

def _infer_capacity(room_name: str) -> int:
    nl = room_name.lower()
    m = re.search(r"\((\d)\s*\+\s*(\d)\)", nl)
    if m:
        return int(m.group(1)) + int(m.group(2))
    m = re.search(r"\((\d)\)", nl)
    if m:
        return int(m.group(1))
    for pattern, cap in CAPACITY_PATTERNS:
        if re.search(pattern, nl):
            return cap
    return 2


def _parse_rate(cell) -> Optional[float]:
    if not cell:
        return None
    cleaned = re.sub(r"[€$£,]", "", str(cell))
    cleaned = re.sub(r"\b[A-Z]{3}\b", "", cleaned).strip()
    m = re.search(r"(\d+(?:\.\d{1,2})?)", cleaned)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def _deduplicate(records: List[RoomRate]) -> List[RoomRate]:
    seen = set()
    unique = []
    for r in records:
        key = (r.room_name, r.season_name, r.cost)
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique
