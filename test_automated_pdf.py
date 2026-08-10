import unittest
from datetime import date

from module_01_intake import _guess_hotel_name
from module_05_seasons import Season, extract_seasons
from module_06_rooms import _deduplicate, _interpret_table
from module_08_meals import detect_base_meal_plan, extract_supplements


class AutomatedPdfRegressionTests(unittest.TestCase):
    def test_sto_column_is_used_and_rack_column_is_ignored(self):
        table = [
            ["ROOMTYPE", "STO", "RACK"],
            ["Standard Queen", "US$ 79", "US$ 120"],
            ["Business Room", "US$ 90", "US$ 140"],
        ]

        rows = _interpret_table(table, ["Annual"])

        self.assertEqual([row.room_name for row in rows], ["Standard Queen", "Business Room"])
        self.assertEqual([row.cost for row in rows], [39.5, 45.0])
        self.assertTrue(all(row.season_name == "Annual" for row in rows))

    def test_repeated_rate_table_does_not_duplicate_room_and_season(self):
        first = _interpret_table(
            [["ROOMTYPE", "STO", "RACK"], ["Suite", "$100", "$150"]],
            ["Annual"],
        )
        second = _interpret_table(
            [["ROOMTYPE", "STO", "RACK"], ["Suite", "$110", "$160"]],
            ["Annual"],
        )

        self.assertEqual(len(_deduplicate(first + second)), 1)

    def test_supplement_mentions_do_not_override_breakfast_base_plan(self):
        text = (
            "Rates are inclusive of Breakfast for single occupancy\n"
            "Half Board Supplement - $22 per person and "
            "Full Board Supplement - $44 per person"
        )

        base_plan = detect_base_meal_plan(text)

        self.assertEqual(base_plan, "BB")
        self.assertEqual(extract_supplements(text, base_plan), (0.0, 22.0, 44.0))

    def test_invalid_season_range_is_not_returned(self):
        self.assertEqual(extract_seasons("Peak: 22 Dec 2027 - 07 Dec 2027", 2027), [])

    def test_upload_timestamp_is_not_part_of_hotel_name(self):
        name = _guess_hotel_name(
            "20260725_174403_STO_RATES_2027_ONOMO.pdf",
            "ONOMO HOTEL DAR ES SALAAM\nSTO RATES 2027",
        )
        self.assertEqual(name, "ONOMO HOTEL DAR ES SALAAM")


if __name__ == "__main__":
    unittest.main()
