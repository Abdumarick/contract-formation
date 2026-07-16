"""
Module 12: Import generated CRM CSV back into the manual editor shape.

The exported CRM CSV is flat: one lodge produces many rows across rooms,
date ranges, and age bands. This module groups those rows back into the
JSON structure consumed by the manual editor.
"""

import csv
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation


REQUIRED_COLUMNS = {
    "hotel_name",
    "currency",
    "room_name",
    "max_cap",
    "min_age",
    "max_age",
    "cost",
    "single_supplement",
    "hb_supplement",
    "fb_supplement",
    "start_date",
    "end_date",
}


def import_generated_csv(csv_path):
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = [{k: (v or "").strip() for k, v in row.items()} for row in reader]

    if not rows:
        raise ValueError("CSV has no data rows")

    missing = sorted(REQUIRED_COLUMNS - set(rows[0].keys()))
    if missing:
        raise ValueError("CSV is missing required columns: " + ", ".join(missing))

    rows = [row for row in rows if row.get("room_name") and row.get("start_date") and row.get("end_date")]
    if not rows:
        raise ValueError("CSV has no usable room/date rows")

    hotel_name = _first_value(rows, "hotel_name")
    location_name = _first_value(rows, "location_name")
    hotel_desc = _first_value(rows, "hotel_desc")
    room_desc = _first_value(rows, "room_desc")
    currency = _first_value(rows, "currency") or "USD"
    restricted = _first_value(rows, "inside_restricted_area") or "FALSE"
    ignore_margin = _first_value(rows, "ignore_proposal_margin") or "FALSE"

    date_keys = []
    for row in rows:
        key = (_normalise_date(row.get("start_date")), _normalise_date(row.get("end_date")))
        if key not in date_keys:
            date_keys.append(key)

    season_rows = [
        {"sid": f"csv_season_{idx}", "name": f"Season {idx}"}
        for idx, _ in enumerate(date_keys, start=1)
    ]
    sid_by_dates = {dates: season_rows[idx]["sid"] for idx, dates in enumerate(date_keys)}
    date_ranges = [
        {"sid": sid_by_dates[dates], "start": dates[0], "end": dates[1]}
        for dates in date_keys
    ]

    room_keys = []
    for row in rows:
        key = (row.get("room_name") or "Room", _int(row.get("max_cap"), 1))
        if key not in room_keys:
            room_keys.append(key)

    room_cols = []
    for idx, (room_name, max_cap) in enumerate(room_keys, start=1):
        col_id = f"csv_room_{idx}"
        room_cols.append({
            "colId": col_id,
            "name": room_name,
            "max_cap": max(max_cap, 1),
            "cost_basis": "per_person",
            "sgl_override": 0,
            "sgl_override_type": "usd",
        })

    col_by_room = {(room["name"], room["max_cap"]): room["colId"] for room in room_cols}
    cost_matrix = {season["sid"]: {} for season in season_rows}

    age_keys = []
    for row in rows:
        key = (_int(row.get("min_age"), 0), _int(row.get("max_age"), 99))
        if key not in age_keys:
            age_keys.append(key)

    adult_key = _choose_adult_key(age_keys)
    adult_rows = []
    by_room_date_age = defaultdict(list)
    for row in rows:
        dates = (_normalise_date(row.get("start_date")), _normalise_date(row.get("end_date")))
        room_key = (row.get("room_name") or "Room", _int(row.get("max_cap"), 1))
        age_key = (_int(row.get("min_age"), 0), _int(row.get("max_age"), 99))
        by_room_date_age[(room_key, dates, age_key)].append(row)
        if age_key == adult_key:
            adult_rows.append(row)

    for room_key, dates, _age_key in by_room_date_age:
        adult = _first_row(by_room_date_age.get((room_key, dates, adult_key), []))
        if not adult:
            adult = _first_row(by_room_date_age.get((room_key, dates, _age_key), []))
        sid = sid_by_dates[dates]
        col_id = col_by_room[room_key]
        cost_matrix[sid][col_id] = _number(adult.get("cost"))

    adult_hb = _mode_number(row.get("hb_supplement") for row in adult_rows)
    adult_fb = _mode_number(row.get("fb_supplement") for row in adult_rows)

    for room in room_cols:
        matching = [
            row for row in adult_rows
            if (row.get("room_name") or "Room", _int(row.get("max_cap"), 1)) == (room["name"], room["max_cap"])
        ]
        sgl = _mode_number(row.get("single_supplement") for row in matching)
        expected_auto = _mode_number(row.get("cost") for row in matching) if room["max_cap"] > 1 else 0
        if sgl and sgl != expected_auto:
            room["sgl_override"] = sgl

    age_bands = []
    for min_age, max_age in age_keys:
        label = _age_label((min_age, max_age), adult_key)
        discount, discount_type = _infer_discount(
            rows=rows,
            age_key=(min_age, max_age),
            adult_key=adult_key,
            grouped=by_room_date_age,
        )
        hbfb_mode, child_hb, child_fb = _infer_hbfb_mode(
            rows=rows,
            age_key=(min_age, max_age),
            adult_hb=adult_hb,
            adult_fb=adult_fb,
            label=label,
        )
        age_bands.append({
            "label": label,
            "min_age": min_age,
            "max_age": max_age,
            "discount": discount,
            "discount_type": discount_type,
            "hbfb_mode": hbfb_mode,
            "child_hb": child_hb,
            "child_fb": child_fb,
            "notes": "Imported from generated CSV",
        })

    year = _year_from_dates(date_ranges)
    return {
        "success": True,
        "source": "csv_import",
        "hotel_name": hotel_name,
        "location_name": location_name,
        "contract_year": year,
        "base_plan": "BB",
        "hotel_desc": hotel_desc,
        "room_desc": room_desc,
        "inside_restricted_area": restricted,
        "ignore_proposal_margin": ignore_margin,
        "notes": "Imported from an existing generated CSV. Review before exporting.",
        "season_rows": season_rows,
        "room_cols": room_cols,
        "cost_matrix": cost_matrix,
        "date_ranges": date_ranges,
        "age_bands": age_bands,
        "hb_supplement": adult_hb,
        "fb_supplement": adult_fb,
        "single_supplement": _mode_number(row.get("single_supplement") for row in adult_rows),
        "meal_costs": {"breakfast": 0, "lunch": 0, "dinner": 0},
        "extra_supplements": [],
        "currency": currency,
        "import_summary": {
            "rows": len(rows),
            "rooms": len(room_cols),
            "date_ranges": len(date_ranges),
            "age_bands": len(age_bands),
        },
    }


def _first_value(rows, key):
    return next((row.get(key, "") for row in rows if row.get(key, "")), "")


def _first_row(rows):
    return rows[0] if rows else None


def _int(value, default):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _number(value):
    try:
        return float(Decimal(str(value or "0").replace(",", "")))
    except (InvalidOperation, ValueError):
        return 0.0


def _normalise_date(value):
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%d/%m/%Y")
        except ValueError:
            pass
    return value


def _choose_adult_key(age_keys):
    return max(age_keys, key=lambda key: (key[1], key[0]))


def _age_label(age_key, adult_key):
    min_age, max_age = age_key
    if age_key == adult_key:
        return "adult"
    if min_age <= 2 or max_age <= 5:
        return "infant"
    return "child"


def _infer_discount(rows, age_key, adult_key, grouped):
    if age_key == adult_key:
        return 100, "pct"

    ratios = []
    fixed_values = []
    for group_key, age_rows in grouped.items():
        room_key, dates, current_age = group_key
        if current_age != age_key:
            continue
        adult = _first_row(grouped.get((room_key, dates, adult_key), []))
        child = _first_row(age_rows)
        if not child:
            continue
        child_cost = _number(child.get("cost"))
        fixed_values.append(child_cost)
        adult_cost = _number(adult.get("cost")) if adult else 0
        if adult_cost:
            ratios.append(round((child_cost / adult_cost) * 100, 2))

    ratio = _stable_value(ratios)
    if ratio is not None:
        return _clean_number(ratio), "pct"

    fixed = _stable_value(fixed_values)
    if fixed is not None:
        return _clean_number(fixed), "usd"

    return 0, "pct"


def _infer_hbfb_mode(rows, age_key, adult_hb, adult_fb, label):
    if label == "adult":
        return "apply_discount", 0, 0

    pairs = [
        (_number(row.get("hb_supplement")), _number(row.get("fb_supplement")))
        for row in rows
        if (_int(row.get("min_age"), 0), _int(row.get("max_age"), 99)) == age_key
    ]
    pair = _stable_value(pairs)
    if pair is None:
        return "apply_discount", 0, 0
    hb, fb = pair
    if hb == adult_hb and fb == adult_fb:
        return "same_as_adult", 0, 0
    if hb == 0 and fb == 0:
        return "custom", 0, 0
    return "custom", hb, fb


def _mode_number(values):
    nums = [_number(value) for value in values if str(value or "").strip() != ""]
    stable = _stable_value(nums)
    return _clean_number(stable) if stable is not None else 0


def _stable_value(values):
    if not values:
        return None
    counts = Counter(values)
    value, count = counts.most_common(1)[0]
    if count == len(values):
        return value
    if count / len(values) >= 0.8:
        return value
    return None


def _clean_number(value):
    if value is None:
        return 0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if number.is_integer():
        return int(number)
    return round(number, 2)


def _year_from_dates(date_ranges):
    for item in date_ranges:
        date_value = item.get("start", "")
        try:
            return str(datetime.strptime(date_value, "%d/%m/%Y").year)
        except ValueError:
            pass
    return ""
