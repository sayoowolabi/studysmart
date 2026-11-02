import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.gis.gdal import SpatialReference
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.db import DatabaseError, connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from spaces.models import FACILITY_FIELDS, StudySpace
from spaces.serializers import MAX_SEARCH_RADIUS_M


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
            ("intersecting", "area-intersecting"),
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
        self.assertEqual(facilities, ["indoor_seating", "has_wifi"])
        self.assertTrue(set(facilities) <= set(FACILITY_FIELDS))
        # Every offered radius must be one the nearby API accepts (> 0 and within its maximum).
        radii = [int(value) for value in re.findall(r'name="radius" value="(\d+)"', content)]
        self.assertEqual(radii, [500, 1000, 2000, 5000])
        self.assertTrue(all(0 < radius <= MAX_SEARCH_RADIUS_M for radius in radii))
        self.assertRegex(content, r'name="radius" value="1000" id="radius-1000" checked')
        sizes = re.findall(r'name="result-size" value="(\d+)"', content)
        self.assertEqual(sizes, ["10", "25", "50"])
        self.assertRegex(content, r'name="result-size" value="10" id="result-size-10" checked')

    def test_every_form_control_has_a_label(self):
        content = self.client.get(reverse("spaces:home")).content.decode()
        control_ids = re.findall(r'<(?:input|select)[^>]*\bid="([^"]+)"', content)
        labelled_ids = set(re.findall(r'<label[^>]*\bfor="([^"]+)"', content))
        self.assertTrue({"campus-select", "radius-1000", "type-cafe"} <= set(control_ids))
        self.assertEqual(set(control_ids) - labelled_ids, set())

    def test_header_links_to_the_about_page(self):
        content = self.client.get(reverse("spaces:home")).content.decode()
        link = re.search(rf'<a class="nav-pill" href="{reverse("spaces:about")}">(.*?)</a>', content, re.S)
        self.assertEqual(re.sub(r"<svg.*?</svg>", "", link.group(1), flags=re.S).strip(), "About")

    def test_page_has_a_single_h1(self):
        content = self.client.get(reverse("spaces:home")).content.decode()
        headings = re.findall(r"<h1[^>]*>(.*?)</h1>", content, re.S)
        self.assertEqual(len(headings), 1)
        self.assertEqual(re.sub(r"<span[^>]*aria-hidden[^>]*>.*?</span>", "", headings[0]).strip(), "StudySmart")

    def test_search_progress_is_announced_by_one_live_region(self):
        # Two polite live regions made screen readers announce "Searching…" twice.
        content = self.client.get(reverse("spaces:home")).content.decode()
        live_regions = re.findall(r'<[^>]*aria-live="polite"[^>]*>', content)
        self.assertEqual(len(live_regions), 1)
        self.assertIn('id="results-summary"', live_regions[0])
        self.assertRegex(content, r'<div id="map-messages" class="map-messages">')
        # Map-level warnings are announced individually instead.
        status_script = Path(finders.find("spaces/js/status.js")).read_text(encoding="utf-8")
        self.assertIn('setAttribute("role", "alert")', status_script)

    def test_default_radius_is_defined_once_in_the_page(self):
        # "Reset filters" restores the HTML defaults, so the page is the single source of the default.
        content = self.client.get(reverse("spaces:home")).content.decode()
        checked = re.findall(r'name="radius" value="(\d+)" id="radius-\d+" checked', content)
        self.assertEqual(checked, ["1000"])
        search_script = Path(finders.find("spaces/js/search.js")).read_text(encoding="utf-8")
        self.assertIn('element("search-form").reset()', search_script)
        self.assertNotRegex(search_script, r"radius-\$\{|DEFAULT_RADIUS")

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

    def test_font_is_self_hosted_with_its_licence(self):
        # Served from this site (no third-party font request) and shipped with its SIL OFL licence.
        stylesheet = Path(finders.find("spaces/css/map.css")).read_text(encoding="utf-8")
        self.assertIn('url("../fonts/nunito-latin-wght-normal.woff2")', stylesheet)
        self.assertIsNotNone(finders.find("spaces/fonts/nunito-latin-wght-normal.woff2"))
        licence = Path(finders.find("spaces/fonts/OFL.txt")).read_text(encoding="utf-8")
        self.assertIn("SIL Open Font License", licence)

    def test_scripts_never_insert_api_data_as_html(self):
        for name in ("api", "areas", "map", "markers", "results", "search", "status"):
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
        self.make_space(has_wifi=False)
        self.make_space(has_wifi=None)
        checkbox, label = self.facility_checkbox("has_wifi")
        self.assertIn("disabled", checkbox)
        self.assertEqual(label, "Wi-Fi (no confirmed records yet)")

    def test_facility_becomes_available_once_a_record_confirms_it(self):
        self.make_space(has_wifi=True)
        self.make_space(has_wifi=True, indoor_seating=False)
        # The filters apply only to cafés, so a library confirming Wi-Fi is not counted.
        StudySpace.objects.create(
            name="Fictional Library", space_type="library", location=Point(-6.26, 53.35, srid=4326), has_wifi=True,
        )
        checkbox, label = self.facility_checkbox("has_wifi")
        self.assertNotIn("disabled", checkbox)
        self.assertEqual(label, "Wi-Fi (2 confirmed)")
        self.assertIn("disabled", self.facility_checkbox("indoor_seating")[0])

    def test_filters_stay_enabled_if_counts_cannot_be_read(self):
        with mock.patch("spaces.views.StudySpace.objects.filter", side_effect=DatabaseError):
            response = self.client.get(reverse("spaces:home"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        for field in ("indoor_seating", "has_wifi"):
            checkbox = re.search(rf'<input[^>]*id="facility-{field}"[^>]*>', content).group()
            self.assertNotIn("disabled", checkbox)
        self.assertNotIn("confirmed records yet", content)

    def test_security_headers_on_pages_and_api(self):
        # SecurityMiddleware: nosniff, Referrer-Policy and Cross-Origin-Opener-Policy (Django defaults);
        # XFrameOptionsMiddleware: DENY, so other sites cannot frame the map or the API.
        expected = {
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "same-origin",
            "Cross-Origin-Opener-Policy": "same-origin",
        }
        for url in (reverse("spaces:home"), reverse("spaces:studyspace-list")):
            response = self.client.get(url)
            for header, value in expected.items():
                with self.subTest(url=url, header=header):
                    self.assertEqual(response.headers.get(header), value)

    def test_unknown_host_is_rejected(self):
        response = self.client.get("/", HTTP_HOST="unrecognised.invalid")
        self.assertEqual(response.status_code, 400)

    def test_geospatial_libraries_load(self):
        point = Point(-6.26, 53.35, srid=4326)
        self.assertEqual(point.srid, 4326)
        self.assertEqual(SpatialReference(4326).srid, 4326)


@override_settings(ALLOWED_HOSTS=["testserver"])
class AboutPageTests(SimpleTestCase):  # A static page: no database queries.
    def test_about_page_explains_the_app_and_links_back_to_the_map(self):
        response = self.client.get(reverse("spaces:about"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertEqual(re.findall(r"<h1[^>]*>(.*?)</h1>", content, re.S), ["About StudySmart"])
        for heading in ("Who it's for", "How to use it", "About the information"):
            self.assertIn(heading, content.replace("&#x27;", "'"))
        self.assertIn(f'href="{reverse("spaces:home")}"', content)
        # Data sources are attributed as on the map.
        self.assertIn("https://data.smartdublin.ie/dataset/dublin-city-libraries", content)
        self.assertIn("https://www.openstreetmap.org/copyright", content)

    def test_about_page_describes_the_offered_choices(self):
        # The text is built from the same settings as the map page, so it cannot drift.
        content = self.client.get(reverse("spaces:about")).content.decode()
        self.assertRegex(content, r"500 m\s+to 5 km")
        self.assertIn("10, 25, 50", content)


class DatabaseConnectionTests(TestCase):
    def test_postgis_is_available(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), PostGIS_Version()")
            database_name, postgis_version = cursor.fetchone()
        self.assertEqual(database_name, connection.settings_dict["NAME"])
        self.assertTrue(postgis_version)


class SettingsEnvironmentTests(SimpleTestCase):
    def load_settings(self, setting="DEBUG", **overrides):
        """Imports the settings in a fresh process with the given environment; prints one setting."""
        environment = os.environ.copy()
        environment.pop("DJANGO_DEBUG", None)
        for name, value in overrides.items():
            if value is None:
                environment.pop(name, None)
            else:
                environment[name] = value
        return subprocess.run(
            [sys.executable, "-c", f"from studysmart.settings import {setting}; print({setting})"],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_https_hardening_clears_every_deployment_warning(self):
        environment = {**os.environ, "DJANGO_DEBUG": "False", "DJANGO_HTTPS": "True"}
        result = subprocess.run(
            [sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"],
            env=environment, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no issues", result.stdout)

    def test_https_hardening_is_off_by_default(self):
        # Local Compose serves plain http://localhost, where secure-only cookies would break login.
        result = self.load_settings("SESSION_COOKIE_SECURE", DJANGO_HTTPS=None)
        self.assertNotEqual(result.returncode, 0)  # Not set at all, so Django's default (False) applies.
        self.assertIn("cannot import name 'SESSION_COOKIE_SECURE'", result.stderr)

    def test_invalid_https_value_is_rejected(self):
        result = self.load_settings(DJANGO_HTTPS="yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_HTTPS must be True or False", result.stderr)

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

    def test_missing_database_password_is_rejected(self):
        result = self.load_settings(POSTGRES_PASSWORD=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Set POSTGRES_PASSWORD", result.stderr)

    def test_default_allowed_hosts_are_local_only(self):
        result = self.load_settings("ALLOWED_HOSTS", DJANGO_ALLOWED_HOSTS=None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "['localhost', '127.0.0.1', '[::1]']")

    def test_allowed_hosts_list_ignores_blank_entries(self):
        result = self.load_settings("ALLOWED_HOSTS", DJANGO_ALLOWED_HOSTS=" example.org, ,localhost ")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "['example.org', 'localhost']")


class ProductionServingTests(SimpleTestCase):
    """Nginx serves collected static files and proxies the rest to Gunicorn."""

    @staticmethod
    def project_file(name):
        return (Path(settings.BASE_DIR) / name).read_text(encoding="utf-8")

    def compose_service(self, name):
        services = self.project_file("docker-compose.yml")
        return re.search(rf"^  {name}:\n(.*?)(?=^  \w|^\w|\Z)", services, re.MULTILINE | re.DOTALL).group(1)

    def test_static_root_is_the_directory_shared_with_nginx(self):
        self.assertEqual(Path(settings.STATIC_ROOT), Path(settings.BASE_DIR) / "staticfiles")
        self.assertRegex(self.compose_service("web"), r"static_data:/app/staticfiles\n")
        self.assertRegex(self.compose_service("nginx"), r"static_data:/app/staticfiles:ro\n")

    def test_collectstatic_gathers_app_admin_and_api_files(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(STATIC_ROOT=directory):
            call_command("collectstatic", interactive=False, verbosity=0)
            for name in ("spaces/js/map.js", "admin/css/base.css", "gis/js/OLMapWidget.js", "rest_framework/css/default.css"):
                self.assertTrue((Path(directory) / name).is_file(), name)

    def test_without_https_deployment_warnings_are_only_the_https_settings(self):
        # A fixed strong key, so the result does not depend on the key in the local .env.
        environment = {
            **os.environ, "DJANGO_DEBUG": "False", "DJANGO_HTTPS": "False",
            "DJANGO_SECRET_KEY": "test-only-deployment-check-key-" + "a1b2c3d4e5" * 4,
        }
        result = subprocess.run(
            [sys.executable, "manage.py", "check", "--deploy"],
            env=environment, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            set(re.findall(r"security\.W\d+", result.stdout + result.stderr)),
            {"security.W004", "security.W008", "security.W012", "security.W016"},
        )

    def test_only_nginx_publishes_the_site_and_web_runs_gunicorn(self):
        web, nginx = self.compose_service("web"), self.compose_service("nginx")
        self.assertNotIn("ports:", web)
        self.assertIn("gunicorn studysmart.wsgi:application --bind 0.0.0.0:8000 --workers 3", web)
        self.assertIn('"127.0.0.1:8000:80"', nginx)
        self.assertRegex(nginx, r"image: nginx:\d+\.\d+\.\d+-alpine")
        self.assertRegex(self.project_file("requirements.txt"), r"(?m)^gunicorn==\d+\.\d+\.\d+$")

    def test_nginx_keeps_the_port_for_csrf_and_sends_each_security_header_once(self):
        config = self.project_file("nginx/default.conf")
        # $host drops the port, and Django's CSRF check would then refuse admin logins.
        self.assertIn("proxy_set_header Host $http_host;", config)
        for directive in ("server_tokens off;", "client_max_body_size", "X-Forwarded-For", "X-Forwarded-Proto"):
            self.assertIn(directive, config)
        for header in ("X-Content-Type-Options", "Referrer-Policy", "X-Frame-Options"):
            self.assertIn(f"add_header {header} ", config)
            self.assertIn(f"proxy_hide_header {header};", config)
        # add_header in a location would silently drop the server-level security headers there.
        self.assertEqual(len(re.findall(r"(?m)^\s*add_header ", config)), 3)
