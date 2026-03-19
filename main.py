"""
hotel_contract_parser v2 — Fully Automated Pipeline
────────────────────────────────────────────────────
Usage:
    python main.py path/to/contract.pdf [--output ./output] [--year 2025] [--excel]

No human intervention required. File is rejected automatically if critical data
cannot be extracted, and the rejection reason is written to the audit log.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "modules"))

from module_01_intake     import identify_pdf
from module_02_extraction import extract_text
from module_03_cleaning   import clean_text
from module_04_sections   import detect_sections, get_section_text
from module_05_seasons    import extract_seasons
from module_06_rooms      import parse_room_rates
from module_07_children   import extract_children_policy, format_rules_summary
from module_08_meals      import detect_base_meal_plan, extract_supplements
from module_09_mapping    import map_to_csv_rows
from module_10_validation import validate_rows, CriticalValidationError
from module_11_export     import export_csv, export_excel, preview_csv
from module_12_logging    import init_logger


def parse_pdf(
    pdf_path: str,
    output_dir: str = "./output",
    year_override: Optional[str] = None,
    export_excel_too: bool = False,
) -> dict:
    """
    Full automated pipeline: PDF → CSV (and optionally XLSX).
    Returns dict with keys 'csv' and optionally 'xlsx', plus 'audit_txt' and 'audit_json'.
    Raises CriticalValidationError if the file must be rejected.
    """
    # ── M1: Intake ────────────────────────────────────────────────────────────
    _section("1", "PDF Intake")
    meta = identify_pdf(pdf_path)
    hotel_name    = meta.hotel_name_guess or "Unknown Hotel"
    contract_year = year_override or meta.contract_year_guess or ""
    _print(f"Type: {meta.pdf_type} | Pages: {meta.total_pages} | "
           f"Hotel: {hotel_name} | Year: {contract_year}")

    log = init_logger(hotel_name, log_dir=os.path.join(output_dir, "logs"))
    log.info("module_01", f"PDF type={meta.pdf_type}, pages={meta.total_pages}")
    log.guessed("module_01", "hotel_name", hotel_name)
    if contract_year:
        log.guessed("module_01", "contract_year", contract_year)

    # ── M2: Text Extraction ───────────────────────────────────────────────────
    _section("2", "Text Extraction")
    raw_text = extract_text(pdf_path, meta.pdf_type)
    _print(f"Extracted {len(raw_text):,} characters")
    log.extracted("module_02", "raw_text", f"{len(raw_text)} chars")

    # ── M3: Cleaning ──────────────────────────────────────────────────────────
    _section("3", "Text Cleaning")
    clean = clean_text(raw_text)
    _print(f"Cleaned: {len(clean):,} chars  (was {len(raw_text):,})")
    log.info("module_03", f"Text: {len(raw_text)} → {len(clean)} chars")

    # ── M4: Section Detection ─────────────────────────────────────────────────
    _section("4", "Section Detection")
    sections = detect_sections(clean)
    for name, sec in sections.items():
        lines = sec.content.count("\n") + 1
        _print(f"  [{name}] {lines} lines")
        log.extracted("module_04", "section", name)

    # ── M5: Season Extraction ─────────────────────────────────────────────────
    _section("5", "Season Extraction")
    season_text = get_section_text(sections, "season_definitions") or clean
    fallback_yr = int(contract_year) if contract_year and contract_year.isdigit() else None
    seasons = extract_seasons(season_text, fallback_year=fallback_yr)

    if not seasons:
        reason = "No season date ranges could be extracted from the contract."
        log.rejected("module_05", reason)
        raise CriticalValidationError(reason)

    for s in seasons:
        _print(f"  {s}")
        log.extracted("module_05", "season", str(s))

    # ── M6: Room Rate Parsing ─────────────────────────────────────────────────
    _section("6", "Room Rate Parsing")
    rates_text = get_section_text(sections, "room_rates") or clean
    room_rates = parse_room_rates(rates_text, seasons, file_path=pdf_path)

    if not room_rates:
        reason = "No room rates could be extracted from the contract."
        log.rejected("module_06", reason)
        raise CriticalValidationError(reason)

    _print(f"Found {len(room_rates)} room-rate record(s)")
    for rr in room_rates[:6]:
        _print(f"  {rr.room_name} | {rr.season_name} | cost={rr.cost} "
               f"sgl_supp={rr.single_supplement} hb={rr.hb_supplement} fb={rr.fb_supplement}")
    if len(room_rates) > 6:
        _print(f"  … and {len(room_rates)-6} more")
    for rr in room_rates:
        log.extracted("module_06", "room_rate",
                      f"{rr.room_name}/{rr.season_name}/{rr.cost}")

    # ── M7: Age Band / Children Policy ────────────────────────────────────────
    _section("7", "Age Band / Children Policy")
    child_text = get_section_text(sections, "children_policy") or ""
    age_rules  = extract_children_policy(child_text)
    _print(format_rules_summary(age_rules))
    for r in age_rules:
        if not r.supported:
            log.skipped("module_07", "age_rule", str(r),
                        f"Unsupported discount {r.discount_pct:.0f}% — no row will be created")
        else:
            log.extracted("module_07", "age_rule", str(r))

    # ── M8: Meal Plan Detection ────────────────────────────────────────────────
    _section("8", "Meal Plan & Supplements")
    # Search meal section + full clean text so supplements are always found
    # regardless of which section they appear in.
    meal_text   = get_section_text(sections, "meal_plans") or ""
    search_text = meal_text + "\n" + clean

    base_plan                        = detect_base_meal_plan(search_text)
    sgl_global, hb_global, fb_global = extract_supplements(search_text, base_plan)

    _print(f"Base meal plan    : {base_plan}")
    _print(f"Single supplement : {sgl_global}")
    _print(f"HB supplement     : {hb_global}")
    _print(f"FB supplement     : {fb_global}")
    log.extracted("module_08", "base_meal_plan",    base_plan)
    log.extracted("module_08", "single_supplement", sgl_global)
    log.extracted("module_08", "hb_supplement",     hb_global)
    log.extracted("module_08", "fb_supplement",     fb_global)

    # Push globally extracted supplements onto room records that still have 0.
    # single_supplement only applies to rooms with capacity > 1.
    for rr in room_rates:
        if rr.single_supplement == 0.0 and sgl_global > 0 and rr.max_cap > 1:
            rr.single_supplement = sgl_global
        if rr.hb_supplement == 0.0 and hb_global > 0:
            rr.hb_supplement = hb_global
        if rr.fb_supplement == 0.0 and fb_global > 0:
            rr.fb_supplement = fb_global

    # ── M9: CSV Mapping ───────────────────────────────────────────────────────
    _section("9", "Mapping to CSV Schema")
    csv_rows = map_to_csv_rows(
        hotel_name=hotel_name,
        room_rates=room_rates,
        seasons=seasons,
        age_band_rules=age_rules,
    )
    _print(f"Generated {len(csv_rows)} CSV row(s)")
    log.info("module_09", f"Generated {len(csv_rows)} CSV rows")

    # ── M10: Validation ───────────────────────────────────────────────────────
    _section("10", "Validation")
    try:
        report = validate_rows(csv_rows, auto_reject=True)
    except CriticalValidationError as exc:
        log.rejected("module_10", str(exc))
        raise

    _print(report.summary())
    for e in report.errors:
        log.error("module_10", str(e))
    for w in report.warnings:
        log.warning("module_10", str(w))

    # ── M11: Export ───────────────────────────────────────────────────────────
    _section("11", "Export")
    preview_csv(csv_rows, max_rows=6)
    output_paths = {}
    output_paths["csv"] = export_csv(
        csv_rows, hotel_name, contract_year, output_dir
    )
    if export_excel_too:
        output_paths["xlsx"] = export_excel(
            csv_rows, hotel_name, contract_year, output_dir
        )
    log.extracted("module_11", "output_csv", output_paths["csv"])

    # ── M12: Audit Trail ──────────────────────────────────────────────────────
    _section("12", "Audit Trail")
    output_paths["audit_txt"]  = log.save_txt()
    output_paths["audit_json"] = log.save_json()
    log.print_summary()

    print(f"\n{'='*60}")
    print(f"  ✅  Pipeline complete for: {hotel_name}")
    print(f"  Output: {output_paths['csv']}")
    print(f"{'='*60}\n")

    return output_paths


def _section(num: str, title: str):
    print(f"\n{'─'*60}")
    print(f"  MODULE {num} — {title}")
    print(f"{'─'*60}")


def _print(msg: str):
    print(f"  {msg}")


# ── Type alias ────────────────────────────────────────────────────────────────
from typing import Optional


def main():
    parser = argparse.ArgumentParser(
        description="Hotel Contract PDF → CRM CSV/Excel  (Fully Automated)"
    )
    parser.add_argument("pdf",   help="Path to the hotel contract PDF")
    parser.add_argument("--output",  default="./output",
                        help="Output directory (default: ./output)")
    parser.add_argument("--year",    default=None,
                        help="Override contract year, e.g. 2025")
    parser.add_argument("--excel",   action="store_true",
                        help="Also export an .xlsx file alongside the CSV")
    args = parser.parse_args()

    if not os.path.exists(args.pdf):
        print(f"ERROR: File not found: {args.pdf}")
        sys.exit(1)

    try:
        parse_pdf(
            pdf_path=args.pdf,
            output_dir=args.output,
            year_override=args.year,
            export_excel_too=args.excel,
        )
    except CriticalValidationError as exc:
        print(f"\n❌  FILE REJECTED: {exc}")
        sys.exit(2)


if __name__ == "__main__":
    main()


def extract_for_manual(
    pdf_path: str,
    year_override: Optional[str] = None,
) -> dict:
    """
    Runs modules 1-8 on the PDF and returns a structured dict that the
    manual-entry UI can use to pre-populate its form.

    Returns:
    {
        hotel_name, contract_year, base_plan,
        single_supplement, hb_supplement, fb_supplement,
        seasons:   [{name, start, end}],
        age_bands: [{label, min_age, max_age, discount, notes}],
        rooms:     [{name, max_cap, season, cost, single_supplement,
                     hb_supplement, fb_supplement, cost_basis}],
    }
    """
    # M1
    meta = identify_pdf(pdf_path)
    hotel_name    = meta.hotel_name_guess or "Unknown Hotel"
    contract_year = year_override or meta.contract_year_guess or ""

    # M2-M3
    raw_text = extract_text(pdf_path, meta.pdf_type)
    clean    = clean_text(raw_text)

    # M4
    sections = detect_sections(clean)

    # M5 – seasons
    season_text = get_section_text(sections, "season_definitions") or clean
    fallback_yr = int(contract_year) if contract_year and contract_year.isdigit() else None
    seasons = extract_seasons(season_text, fallback_year=fallback_yr)

    seasons_out = [
        {"name": s.name, "start": s.start_date.isoformat(),
         "end":  s.end_date.isoformat()}
        for s in seasons
    ]

    # M6 – rooms
    rates_text = get_section_text(sections, "room_rates") or clean
    room_rates = parse_room_rates(rates_text, seasons, file_path=pdf_path)

    # M7 – age bands
    child_text = get_section_text(sections, "children_policy") or ""
    age_rules  = extract_children_policy(child_text)

    age_bands_out = []
    for r in age_rules:
        if not r.supported:
            continue
        age_bands_out.append({
            "label":    r.band_label,
            "min_age":  r.age_from,
            "max_age":  r.age_to,
            "discount": 0 if r.free_of_charge else int(100 - r.discount_pct),
            "notes":    r.notes or "",
        })

    # M8 – supplements
    meal_text   = get_section_text(sections, "meal_plans") or ""
    search_text = meal_text + "\n" + clean
    base_plan                        = detect_base_meal_plan(search_text)
    sgl_global, hb_global, fb_global = extract_supplements(search_text, base_plan)

    # Push globals to rooms
    for rr in room_rates:
        if rr.single_supplement == 0.0 and sgl_global > 0 and rr.max_cap > 1:
            rr.single_supplement = sgl_global
        if rr.hb_supplement == 0.0 and hb_global > 0:
            rr.hb_supplement = hb_global
        if rr.fb_supplement == 0.0 and fb_global > 0:
            rr.fb_supplement = fb_global

    rooms_out = [
        {
            "name":              rr.room_name,
            "max_cap":           rr.max_cap,
            "season":            rr.season_name,
            "cost":              rr.cost,
            "single_supplement": rr.single_supplement,
            "hb_supplement":     rr.hb_supplement,
            "fb_supplement":     rr.fb_supplement,
            "cost_basis":        rr.cost_basis,
        }
        for rr in room_rates
    ]

    return {
        "hotel_name":        hotel_name,
        "contract_year":     contract_year,
        "base_plan":         base_plan,
        "single_supplement": sgl_global,
        "hb_supplement":     hb_global,
        "fb_supplement":     fb_global,
        "seasons":           seasons_out,
        "age_bands":         age_bands_out,
        "rooms":             rooms_out,
    }
