"""University campuses are fixed search starting points, not study-space records."""
import math
import re

from django.test import TestCase, override_settings
from django.urls import reverse

from spaces.models import StudySpace
from spaces.universities import CAMPUSES


class CampusListTests(TestCase):
    def test_campus_points_are_valid_and_in_dublin(self):
        self.assertEqual(len({campus.slug for campus in CAMPUSES}), len(CAMPUSES))
        for campus in CAMPUSES:
            with self.subTest(campus=campus.slug):
                self.assertTrue(math.isfinite(campus.latitude) and math.isfinite(campus.longitude))
                # Dublin is about 53.3 N, 6.3 W: catches swapped or mistyped coordinates.
                self.assertTrue(53.25 < campus.latitude < 53.45, campus.latitude)
                self.assertTrue(-6.45 < campus.longitude < -6.10, campus.longitude)
                # Each point is traceable to the OpenStreetMap element it was taken from.
                self.assertRegex(campus.osm_element, r"^(node|way|relation)/\d+$")

    def test_only_ucd_belfield_has_a_coverage_note(self):
        noted = [campus.slug for campus in CAMPUSES if campus.coverage_note]
        self.assertEqual(noted, ["ucd-belfield"])


@override_settings(ALLOWED_HOSTS=["testserver"])
class CampusSelectorTests(TestCase):
    def test_home_page_offers_each_campus_with_its_coordinates(self):
        content = self.client.get(reverse("spaces:home")).content.decode()
        for campus in CAMPUSES:
            with self.subTest(campus=campus.slug):
                option = re.search(rf'<option value="{campus.slug}"[^>]*>', content).group()
                self.assertIn(f'data-lat="{campus.latitude}"', option)
                self.assertIn(f'data-lng="{campus.longitude}"', option)

    def test_campuses_are_search_origins_not_study_spaces(self):
        self.client.get(reverse("spaces:home"))
        self.assertFalse(StudySpace.objects.exists())
        self.assertEqual(self.client.get(reverse("spaces:studyspace-list")).data, [])
