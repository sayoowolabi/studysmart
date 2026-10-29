import os
import re
import subprocess
import sys
from pathlib import Path
from unittest import mock

from django.contrib.gis.gdal import SpatialReference
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.contrib.gis.geos import Point
from django.db import DatabaseError, connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from spaces.models import FACILITY_FIELDS, StudySpace


@override_settings(ALLOWED_HOSTS=["testserver"])
class HomePageTests(TestCase):  # The page counts confirmed facilities, so it needs the database.
    def test_home_page(self):
        response = self.client.get(reverse("spaces:home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "spaces/home.html")
        self.assertContains(response, "StudySmart")

    def test_home_page_loads_map_with_api_urls(self):
        response = self.client.get(reverse("spaces:home"))
        self.assertContains(response, 'id="map"')
        # URLs come from {% url %}, so the JavaScript never hard-codes API paths.
        for attribute, route in (
            ("spaces", "studyspace-list"), ("nearby", "studyspace-nearby"),
            ("nearest", "studyspace-nearest"), ("areas", "area-list"), ("coverage", "area-coverage"),
        ):
            self.assertContains(response, f'data-{attribute}-url="{reverse(f"spaces:{route}")}"')
        self.assertContains(response, f'<script type="module" src="{static("spaces/js/map.js")}">')
        self.assertContains(response, static("spaces/css/map.css"))
        self.assertContains(response, 'role="status"')

    def test_filter_controls_match_api_parameters(self):
        content = self.client.get(reverse("spaces:home")).content.decode()
        types = re.findall(r'name="type" value="([^"]+)"', content)
        facilities = re.findall(r'name="facility" value="([^"]+)"', content)
        self.assertEqual(sorted(types), sorted(StudySpace.SpaceType.values))
        self.assertEqual(facilities, ["indoor_seating", "has_wifi", "has_outlets"])
        self.assertTrue(set(facilities) <= set(FACILITY_FIELDS))

    def test_every_form_control_has_a_label(self):
        content = self.client.get(reverse("spaces:home")).content.decode()
        control_ids = re.findall(r'<(?:input|select)[^>]*\bid="([^"]+)"', content)
        labelled_ids = set(re.findall(r'<label[^>]*\bfor="([^"]+)"', content))
        self.assertIn("radius", control_ids)
        self.assertEqual(set(control_ids) - labelled_ids, set())

    def test_location_selection_mode_controls(self):
        content = self.client.get(reverse("spaces:home")).content.decode()
        self.assertRegex(content, r'<button type="button" id="choose-location"[^>]*aria-pressed="false"')
        self.assertRegex(content, r'<div id="choose-banner"[^>]*hidden>')
        self.assertIn('id="cancel-choosing"', content)

    def test_area_statistics_are_labelled_as_unfiltered(self):
        response = self.client.get(reverse("spaces:home"))
        self.assertContains(response, "All Recorded Study Spaces by Area")
        self.assertContains(response, "filters above")

    def test_cdn_assets_are_pinned_with_integrity_hashes(self):
        content = self.client.get(reverse("spaces:home")).content.decode()
        for asset in ("leaflet@1.9.4/dist/leaflet.css", "leaflet@1.9.4/dist/leaflet.js",
                      "bootstrap@5.3.3/dist/css/bootstrap.min.css"):
            tag = re.search(rf"<(?:link|script)[^>]*{re.escape(asset)}[^>]*>", content)
            self.assertIsNotNone(tag, asset)
            self.assertRegex(tag.group(), r'integrity="sha(256|384)-[A-Za-z0-9+/=]+"')

    def test_map_script_attributes_openstreetmap(self):
        script = Path(finders.find("spaces/js/map.js")).read_text(encoding="utf-8")
        self.assertIn("https://www.openstreetmap.org/copyright", script)
        # Without a Referer the OSM tile server returns "Access blocked" tiles.
        self.assertIn('referrerPolicy: "strict-origin-when-cross-origin"', script)

    def test_scripts_never_insert_api_data_as_html(self):
        for name in ("api", "areas", "map", "markers", "search", "status"):
            script = Path(finders.find(f"spaces/js/{name}.js")).read_text(encoding="utf-8")
            for unsafe in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
                self.assertNotIn(unsafe, script, f"{name}.js uses {unsafe}")

    def facility_checkbox(self, field):
        content = self.client.get(reverse("spaces:home")).content.decode()
        checkbox = re.search(rf'<input[^>]*id="facility-{field}"[^>]*>', content).group()
        label = re.search(rf'<label[^>]*for="facility-{field}">(.*?)</label>', content, re.S).group(1)
        visible_text = re.sub(r"<[^>]+>", "", label)
        return checkbox, " ".join(visible_text.split())

    def make_space(self, **facilities):
        return StudySpace.objects.create(
            name="Fictional Cafe", space_type="cafe", location=Point(-6.26, 53.35, srid=4326), **facilities,
        )

    def test_facility_without_confirmed_records_is_disabled(self):
        # False and unknown values are not confirmations.
        self.make_space(has_outlets=False)
        self.make_space(has_outlets=None)
        checkbox, label = self.facility_checkbox("has_outlets")
        self.assertIn("disabled", checkbox)
        self.assertEqual(label, "Power outlets (no confirmed records yet)")

    def test_facility_becomes_available_once_a_record_confirms_it(self):
        self.make_space(has_outlets=True)
        self.make_space(has_outlets=True, has_wifi=False)
        checkbox, label = self.facility_checkbox("has_outlets")
        self.assertNotIn("disabled", checkbox)
        self.assertEqual(label, "Power outlets (2 confirmed)")
        self.assertIn("disabled", self.facility_checkbox("has_wifi")[0])

    def test_filters_stay_enabled_if_counts_cannot_be_read(self):
        with mock.patch("spaces.views.StudySpace.objects.aggregate", side_effect=DatabaseError):
            response = self.client.get(reverse("spaces:home"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        for field in ("indoor_seating", "has_wifi", "has_outlets"):
            checkbox = re.search(rf'<input[^>]*id="facility-{field}"[^>]*>', content).group()
            self.assertNotIn("disabled", checkbox)
        self.assertNotIn("confirmed records yet", content)

    def test_unknown_host_is_rejected(self):
        response = self.client.get("/", HTTP_HOST="unrecognised.invalid")
        self.assertEqual(response.status_code, 400)

    def test_geospatial_libraries_load(self):
        point = Point(-6.26, 53.35, srid=4326)
        self.assertEqual(point.srid, 4326)
        self.assertEqual(SpatialReference(4326).srid, 4326)


class DatabaseConnectionTests(TestCase):
    def test_postgis_is_available(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), PostGIS_Version()")
            database_name, postgis_version = cursor.fetchone()
        self.assertEqual(database_name, connection.settings_dict["NAME"])
        self.assertTrue(postgis_version)


class SettingsEnvironmentTests(SimpleTestCase):
    def load_settings(self, **overrides):
        environment = os.environ.copy()
        environment.pop("DJANGO_DEBUG", None)
        for name, value in overrides.items():
            if value is None:
                environment.pop(name, None)
            else:
                environment[name] = value
        return subprocess.run(
            [sys.executable, "-c", "from studysmart.settings import DEBUG; print(DEBUG)"],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_debug_defaults_to_false(self):
        result = self.load_settings()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "False")

    def test_false_string_does_not_enable_debug(self):
        result = self.load_settings(DJANGO_DEBUG="False")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "False")

    def test_invalid_debug_is_rejected(self):
        result = self.load_settings(DJANGO_DEBUG="not-a-boolean")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_DEBUG must be True or False", result.stderr)

    def test_missing_secret_is_rejected(self):
        result = self.load_settings(DJANGO_SECRET_KEY=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Set DJANGO_SECRET_KEY", result.stderr)

    def test_placeholder_secret_is_rejected(self):
        result = self.load_settings(DJANGO_SECRET_KEY="change-me-placeholder")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Set DJANGO_SECRET_KEY", result.stderr)
