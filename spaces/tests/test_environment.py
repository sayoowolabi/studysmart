import os
import subprocess
import sys

from django.contrib.gis.gdal import SpatialReference
from django.contrib.gis.geos import Point
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse


@override_settings(ALLOWED_HOSTS=["testserver"])
class HomePageTests(SimpleTestCase):
    def test_home_page(self):
        response = self.client.get(reverse("spaces:home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "spaces/home.html")
        self.assertContains(response, "StudySmart")

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
