from django.test import SimpleTestCase

from spaces.importers.osm import parse_facilities
from spaces.models import FACILITY_FIELDS


class FacilityTagTests(SimpleTestCase):
    def facilities(self, tags):
        return parse_facilities(tags)[0]

    def test_absent_tags_remain_unknown(self):
        self.assertEqual(self.facilities({}), dict.fromkeys(FACILITY_FIELDS))

    def test_explicit_yes_and_no(self):
        mapping = {
            "indoor_seating": "indoor_seating", "outdoor_seating": "outdoor_seating",
            "has_wifi": "wifi", "has_outlets": "power_supply", "laptop_allowed": "laptop",
        }
        for field, tag in mapping.items():
            for value, expected in (("yes", True), ("no", False)):
                with self.subTest(field=field, value=value):
                    self.assertIs(self.facilities({tag: value})[field], expected)

    def test_documented_outdoor_values(self):
        self.assertIs(self.facilities({"outdoor_seating": "terrace;sidewalk"})["outdoor_seating"], True)

    def test_unsupported_seating_is_unknown_and_reported(self):
        for field, value in (("indoor_seating", "bar_table"), ("outdoor_seating", "seasonal")):
            values, issues = parse_facilities({field: value})
            self.assertIsNone(values[field])
            self.assertTrue(issues)

    def test_conflicting_seating_is_unknown(self):
        self.assertIsNone(self.facilities({"indoor_seating": "yes;no"})["indoor_seating"])

    def test_wifi_requires_wireless_evidence(self):
        for value in ("yes", "public", "wired", "terminal"):
            with self.subTest(value=value):
                self.assertIsNone(self.facilities({"internet_access": value})["has_wifi"])
        self.assertIs(self.facilities({"internet_access": "wired;wlan"})["has_wifi"], True)
        self.assertIs(self.facilities({"internet_access": "no"})["has_wifi"], False)

    def test_conflicting_or_unrecognised_wifi_is_unknown(self):
        for tags in (
            {"internet_access": "wlan", "wifi": "no"},
            {"internet_access": "no;wlan"},
            {"internet_access": "unrecognised", "wifi": "yes"},
        ):
            with self.subTest(tags=tags):
                values, issues = parse_facilities(tags)
                self.assertIsNone(values["has_wifi"])
                self.assertTrue(issues)

    def test_documented_wifi_free_tag_confirms_wifi(self):
        self.assertIs(self.facilities({"wifi": "free"})["has_wifi"], True)

    def test_sockets_do_not_infer_all_types_absent_or_accept_ev_usb(self):
        for tags in ({"socket:typeg": "0"}, {"socket:typeg": "no"},
                     {"socket:usb": "3"}, {"socket:type2": "2"}, {"electricity": "yes"}):
            with self.subTest(tags=tags):
                self.assertIsNone(self.facilities(tags)["has_outlets"])
        self.assertIs(self.facilities({"socket:typeg": "2"})["has_outlets"], True)
        self.assertIsNone(self.facilities({"socket:typeg": "2", "power_supply": "no"})["has_outlets"])

    def test_restrictions_are_not_unconditional_permission(self):
        values, issues = parse_facilities({"laptop": "restricted"})
        self.assertIsNone(values["laptop_allowed"])
        self.assertTrue(issues)
        for tags, field in (
            ({"laptop": "yes", "laptop:conditional": "no @ (12:00-14:00)"}, "laptop_allowed"),
            ({"indoor_seating": "yes", "indoor_seating:conditional": "no @ (winter)"}, "indoor_seating"),
            ({"outdoor_seating": "yes", "outdoor_seating:seasonal": "summer"}, "outdoor_seating"),
            ({"internet_access": "wlan", "internet_access:conditional": "no @ (night)"}, "has_wifi"),
            ({"power_supply": "yes", "power_supply:schedule": "daytime"}, "has_outlets"),
        ):
            with self.subTest(field=field):
                self.assertIsNone(self.facilities(tags)[field])

    def test_wifi_does_not_establish_laptop_permission(self):
        values = self.facilities({"internet_access": "wlan", "power_supply": "yes", "indoor_seating": "yes"})
        self.assertIsNone(values["laptop_allowed"])
