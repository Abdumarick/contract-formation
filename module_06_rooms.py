"""
Module 6: Room and Rate Table Parsing (v3)

BUSINESS RULES:
─────────────────────────────────────────────────────────────────
COST (stored in the 'cost' column):
  Always stored as PER PERSON PER NIGHT.
  If the contract states cost per room → divide by max_cap to get per-person cost.
  If ambiguous (no explicit per-room or per-person indicator) → treat as per-person
  for single rooms, and per-room for multi-pax rooms (industry default).

SINGLE SUPPLEMENT:
  Only applies to rooms with max_cap > 1 (double, triple, family, etc.).
  Formula: single_supplement = cost_per_person × (max_cap - 1)
  This means: a single traveller in a double room pays:
    cost (= 1 person share) + single_supplement (= the unused person share)
    Total = cost × max_cap  (= full room cost)

  If the contract states single supplement explicitly → use that directly.
  If not stated → derive from per-person cost as above.
─────────────────────────────────────────────────────────────────
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import pdfplumber

from module_08_meals import is_per_room, is_per_person


@dataclass
class RoomRate:
    room_name: str
    room_description: str
    max_cap: int              # maximum total occupancy
    min_pax: int              # always 1
    max_pax: int              # = max_cap
    season_name: str
    cost: float               # per-person per-night (always)
    single_supplement: float  # per-person; 0 if single room
    hb_supplement: float      # per-person per-night
    fb_supplement: float      # per-person per-night
    currency: str = "USD"
    base_meal_plan: str = "BB"
    cost_basis: str = "per_person"   # "per_person" | "per_room" (recorded for audit)
    extra_notes: str = ""


# ── Capacity look-up ──────────────────────────────────────────────────────────
CAPACITY_PATTERNS = [
    (r"\bsgl\b|\bsingle\b",                  1),
    (r"\bdbl\b|\bdouble\b|\btwn\b|\btwin\b", 2),
    (r"\btrpl?\b|\btriple\b",                3),
    (r"\bquad\b|\bquadruple\b",              4),
    (r"\bfamily\b",                          4),
    (r"\bjunior\s+suite\b",                  2),
    (r"\bsuite\b",                           2),
    (r"\bstudio\b",                          2),
]

# ── Supplement keyword patterns ───────────────────────────────────────────────
HB_KEYWORDS  = [r"half[\s\-]*board", r"\bhb\b", r"\bmap\b", r"demi[\s\-]*pension"]
FB_KEYWORDS  = [r"full[\s\-]*board", r"\bfb\b", r"\bap\b", r"pension\s+complet"]
SGL_KEYWORDS = [r"single[\s\-]*(room\s+)?supp", r"sgl[\s\-]*supp",
                r"single\s+occ", r"single\s+use"]


def parse_room_rates(
    rates_text: str,
    seasons: list,
    file_path: Optional[str] = None,
) -> List[RoomRate]:
    """
    Main entry: parse room rates. Returns list of RoomRate objects.
    Cost is always normalised to per-person before returning.
    """
    records: List[RoomRate] = []

    if file_path:
        records = _parse_pdf_tables(file_path, seasons)

    if not records:
        records = _parse_text_rates(rates_text, seasons)

    return _deduplicate(records)


# ─────────────────────────────────────────────────────────────────────────────
# PDF table extraction
# ─────────────────────────────────────────────────────────────────────────────

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

    # Detect per-room / per-person from header row
    header_text = " ".join(headers).lower()
    header_per_room   = is_per_room(header_text)
    header_per_person = is_per_person(header_text)

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

        sgl_stated = (_parse_rate_cell(row[sgl_col]) or 0.0) if sgl_col and sgl_col < len(row) else 0.0
        hb  = (_parse_rate_cell(row[hb_col])  or 0.0) if hb_col  and hb_col  < len(row) else 0.0
        fb  = (_parse_rate_cell(row[fb_col])  or 0.0) if fb_col  and fb_col  < len(row) else 0.0

        for ci, sname in season_col_map.items():
            if ci >= len(row):
                continue
            raw_cost = _parse_rate_cell(row[ci])
            if raw_cost is None:
                continue

            # Detect per-room from cell or header
            cell_per_room   = header_per_room   or is_per_room(row[ci])
            cell_per_person = header_per_person or is_per_person(row[ci])

            cost_pp, basis, sgl = _normalise_cost(
                raw_cost, max_cap, cell_per_room, cell_per_person, sgl_stated
            )

            records.append(RoomRate(
                room_name=room_name,
                room_description=room_name,
                max_cap=max_cap,
                min_pax=1,
                max_pax=max_cap,
                season_name=sname,
                cost=cost_pp,
                single_supplement=sgl,
                hb_supplement=hb,
                fb_supplement=fb,
                currency="USD",
                cost_basis=basis,
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


# ─────────────────────────────────────────────────────────────────────────────
# Text fallback
# ─────────────────────────────────────────────────────────────────────────────

def _parse_text_rates(text: str, seasons: list) -> List[RoomRate]:
    """Parse rates from free text. Normalises per-room costs and derives single supplement."""
    records = []
    season_names = [s.name for s in seasons] or ["Default"]

    # ── Pass 1: harvest explicit global supplement values ─────────────────────
    sgl_stated = hb_rate = fb_rate = 0.0
    for line in text.splitlines():
        ll = line.lower().strip()
        r = _parse_rate_after_colon(line)
        if r is None:
            continue
        if any(re.search(p, ll) for p in SGL_KEYWORDS):
            sgl_stated = r
        elif any(re.search(p, ll) for p in HB_KEYWORDS):
            hb_rate = r
        elif any(re.search(p, ll) for p in FB_KEYWORDS):
            fb_rate = r

    # ── Pass 2: parse room rate lines ─────────────────────────────────────────
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        ll = line.lower()

        # Skip supplement lines
        if any(re.search(p, ll) for p in SGL_KEYWORDS + HB_KEYWORDS + FB_KEYWORDS):
            continue

        # Rate must come from after the colon to avoid digits in room name
        raw_cost = _parse_rate_after_colon(line)
        if raw_cost is None:
            continue

        # Room name: everything before the colon (allow digits for "(2+2)" etc.)
        m = re.match(r"^([A-Za-z][A-Za-z0-9\s/\-\(\)\+]{3,60}?)\s*:", line)
        room_name = m.group(1).strip() if m else "Room"

        max_cap = _infer_capacity(room_name)

        # Detect per-room / per-person from this line
        line_per_room   = is_per_room(line)
        line_per_person = is_per_person(line)

        cost_pp, basis, sgl = _normalise_cost(
            raw_cost, max_cap, line_per_room, line_per_person, sgl_stated
        )

        # Season matching
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
            cost=cost_pp,
            single_supplement=sgl,
            hb_supplement=hb_rate,
            fb_supplement=fb_rate,
            currency="USD",
            cost_basis=basis,
        ))
    return records


# ─────────────────────────────────────────────────────────────────────────────
# Core cost normalisation logic
# ─────────────────────────────────────────────────────────────────────────────

def _normalise_cost(
    raw_cost: float,
    max_cap: int,
    per_room: bool,
    per_person: bool,
    sgl_stated: float,
) -> Tuple[float, str, float]:
    """
    Convert raw cost to per-person and derive single supplement.

    Returns: (cost_per_person, basis_label, single_supplement)

    Rules:
    ─────
    1. If per_person is explicitly stated → cost is already per-person.
    2. If per_room is explicitly stated → divide by max_cap.
    3. If ambiguous:
       - Single room (max_cap=1) → treat as per-person (no difference).
       - Multi-pax room → treat as per-room (industry default when unclear).

    Single supplement (only for max_cap > 1):
    ─────────────────────────────────────────
    If stated explicitly in contract → use that.
    If not stated → derive:
      sgl_supplement = cost_per_person × (max_cap - 1)
      Rationale: single traveller pays 1 person-share (cost) + the remaining
      (max_cap - 1) shares they are covering alone.
    """
    if per_person:
        cost_pp = raw_cost
        basis   = "per_person"
    elif per_room:
        cost_pp = raw_cost / max_cap if max_cap > 0 else raw_cost
        basis   = "per_room"
    else:
        # Ambiguous: single rooms → per person; multi-pax → per room
        if max_cap == 1:
            cost_pp = raw_cost
            basis   = "per_person"
        else:
            cost_pp = raw_cost / max_cap
            basis   = "per_room"

    cost_pp = round(cost_pp, 2)

    # Single supplement
    if max_cap <= 1:
        sgl = 0.0
    elif sgl_stated > 0:
        sgl = sgl_stated
    else:
        # Derived: cost_per_person × (max_cap - 1)
        sgl = round(cost_pp * (max_cap - 1), 2)

    return cost_pp, basis, sgl


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

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


def _parse_rate_cell(cell) -> Optional[float]:
    """Parse rate from a raw table cell."""
    if not cell:
        return None
    return _parse_rate_after_colon(str(cell))


def _parse_rate_after_colon(line: str) -> Optional[float]:
    """Extract numeric rate from after the colon (or full string if no colon)."""
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


def _deduplicate(records: List[RoomRate]) -> List[RoomRate]:
    seen = set()
    unique = []
    for r in records:
        key = (r.room_name, r.season_name, r.cost)
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique
