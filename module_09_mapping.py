"""
Module 9: Data Mapping to CSV Schema (v2 — Fully Automated)

Maps all structured data to the exact 21-column CRM schema.
Season names are dropped — only start_date and end_date are used.
Currency is always USD. Margin is always 0.
Adult rows first, then child/infant rows derived from adult cost.
Unsupported age band rules (supported=False) create NO rows.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Exact column order required by CRM ───────────────────────────────────────
CSV_COLUMNS = [
    "location_name",
    "hotel_name",
    "hotel_group",
    "hotel_desc",
    "inside_restricted_area",
    "margin",
    "ignore_proposal_margin",
    "currency",
    "room_name",
    "room_desc",
    "max_cap",
    "min_age",
    "max_age",
    "min_pax",
    "max_pax",
    "cost",
    "single_supplement",
    "hb_supplement",
    "fb_supplement",
    "start_date",
    "end_date",
]

# Columns that exist but are always left empty
LEAVE_EMPTY_COLUMNS = {"location_name", "hotel_group", "hotel_desc", "inside_restricted_area",
                       "ignore_proposal_margin"}


@dataclass
class CSVRow:
    location_name: str = ""
    hotel_name: str = ""
    hotel_group: str = ""
    hotel_desc: str = ""
    inside_restricted_area: str = ""
    margin: float = 0.0
    ignore_proposal_margin: str = ""
    currency: str = "USD"
    room_name: str = ""
    room_desc: str = ""
    max_cap: int = 1
    min_age: int = 0
    max_age: int = 99
    min_pax: int = 1
    max_pax: int = 1
    cost: float = 0.0
    single_supplement: float = 0.0
    hb_supplement: float = 0.0
    fb_supplement: float = 0.0
    start_date: str = ""
    end_date: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "location_name":          self.location_name,
            "hotel_name":             self.hotel_name,
            "hotel_group":            self.hotel_group,
            "hotel_desc":             self.hotel_desc,
            "inside_restricted_area": self.inside_restricted_area,
            "margin":                 self.margin,
            "ignore_proposal_margin": self.ignore_proposal_margin,
            "currency":               self.currency,
            "room_name":              self.room_name,
            "room_desc":              self.room_desc,
            "max_cap":                self.max_cap,
            "min_age":                self.min_age,
            "max_age":                self.max_age,
            "min_pax":                self.min_pax,
            "max_pax":                self.max_pax,
            "cost":                   round(self.cost, 2),
            "single_supplement":      round(self.single_supplement, 2),
            "hb_supplement":          round(self.hb_supplement, 2),
            "fb_supplement":          round(self.fb_supplement, 2),
            "start_date":             self.start_date,
            "end_date":               self.end_date,
        }


def map_to_csv_rows(
    hotel_name: str,
    room_rates: list,       # List[RoomRate] from module 6
    seasons: list,          # List[Season] from module 5
    age_band_rules: list,   # List[AgeBandRule] from module 7
) -> List[CSVRow]:
    """
    Produce rows by combining each room_rate × each season × each age band.

    Row order per room/season:
      1. Adult row
      2. Child rows (one per supported non-adult band)
      3. Infant rows (one per supported infant band)

    Season names are not included — only start_date and end_date.
    """
    rows: List[CSVRow] = []

    # Build season date lookup
    season_map = {s.name: s for s in seasons}

    # Separate age bands
    adult_bands  = [r for r in age_band_rules if r.band_label == "adult"  and r.supported]
    child_bands  = [r for r in age_band_rules if r.band_label == "child"  and r.supported]
    infant_bands = [r for r in age_band_rules if r.band_label == "infant" and r.supported]

    # ALWAYS generate infant rows — even if free of charge.
    # If the contract did not define an infant band, create a default 0-2 free band.
    if not infant_bands:
        from module_07_children import AgeBandRule
        infant_bands = [AgeBandRule(
            band_label="infant",
            age_from=0, age_to=2,
            discount_pct=0.0,
            free_of_charge=True,
            supported=True,
            notes="Default infant band (contract did not specify)",
        )]

    for rr in room_rates:
        season = season_map.get(rr.season_name)
        start_str = season.start_date.isoformat() if season else ""
        end_str   = season.end_date.isoformat()   if season else ""

        # ── Adult rows ────────────────────────────────────────────────────
        for band in adult_bands:
            rows.append(CSVRow(
                hotel_name=hotel_name,
                room_name=rr.room_name,
                room_desc=rr.room_description,
                max_cap=rr.max_cap,
                min_age=band.age_from,
                max_age=band.age_to,
                min_pax=rr.min_pax,
                max_pax=rr.max_pax,
                cost=rr.cost,
                single_supplement=rr.single_supplement,
                hb_supplement=rr.hb_supplement,
                fb_supplement=rr.fb_supplement,
                start_date=start_str,
                end_date=end_str,
                currency="USD",
                margin=0.0,
            ))

        # ── Child rows ────────────────────────────────────────────────────
        for band in child_bands:
            if band.free_of_charge:
                child_cost = 0.0
                child_sgl  = 0.0
                child_hb   = 0.0
                child_fb   = 0.0
            else:
                factor = 1.0 - band.discount_pct / 100.0
                child_cost = rr.cost * factor
                child_sgl  = rr.single_supplement * factor
                child_hb   = rr.hb_supplement * factor
                child_fb   = rr.fb_supplement * factor

            rows.append(CSVRow(
                hotel_name=hotel_name,
                room_name=rr.room_name,
                room_desc=rr.room_description,
                max_cap=rr.max_cap,
                min_age=band.age_from,
                max_age=band.age_to,
                min_pax=rr.min_pax,
                max_pax=rr.max_pax,
                cost=child_cost,
                single_supplement=child_sgl,
                hb_supplement=child_hb,
                fb_supplement=child_fb,
                start_date=start_str,
                end_date=end_str,
                currency="USD",
                margin=0.0,
            ))

        # ── Infant rows ───────────────────────────────────────────────────
        for band in infant_bands:
            rows.append(CSVRow(
                hotel_name=hotel_name,
                room_name=rr.room_name,
                room_desc=rr.room_description,
                max_cap=rr.max_cap,
                min_age=band.age_from,
                max_age=band.age_to,
                min_pax=rr.min_pax,
                max_pax=rr.max_pax,
                cost=0.0,                    # infants always free
                single_supplement=0.0,
                hb_supplement=0.0,
                fb_supplement=0.0,
                start_date=start_str,
                end_date=end_str,
                currency="USD",
                margin=0.0,
            ))

    return rows
