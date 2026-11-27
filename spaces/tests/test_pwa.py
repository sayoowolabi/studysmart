"""Tests for the Progressive Web App: the manifest, service worker, offline page and cached app shell."""
import json
import re
from pathlib import Path
from unittest import mock

from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from spaces import pwa


@override_settings(ALLOWED_HOSTS=["testserver"])
class ManifestTests(SimpleTestCase):
    def setUp(self):
        self.response = self.client.get("/manifest.webmanifest")
        self.manifest = json.loads(self.response.content)

    def test_served_with_the_manifest_content_type(self):
        self.assertEqual(self.response.status_code, 200)
        self.assertEqual(self.response["Content-Type"], "application/manifest+json")

    def test_opens_the_map_as_a_standalone_app(self):
        self.assertEqual(self.manifest["start_url"], reverse("spaces:home"))
        self.assertEqual(self.manifest["scope"], "/")
        self.assertEqual(self.manifest["display"], "standalone")
        self.assertEqual(self.manifest["short_name"], "StudySmart")

    def test_icons_exist_in_the_sizes_browsers_require(self):
        icons = self.manifest["icons"]
        sizes = {icon["sizes"] for icon in icons if icon.get("purpose", "any") == "any"}
        self.assertTrue({"192x192", "512x512"} <= sizes)
        self.assertTrue(any(icon.get("purpose") == "maskable" for icon in icons))
        for icon in icons:
            name = icon["src"].removeprefix(static(""))
            self.assertIsNotNone(finders.find(name), icon["src"])


@override_settings(ALLOWED_HOSTS=["testserver"])
class ServiceWorkerTests(SimpleTestCase):
    def setUp(self):
        self.response = self.client.get("/sw.js")
        self.script = self.response.content.decode()

    def test_served_from_the_site_root_as_javascript(self):
        # Its path sets its scope: at /sw.js it can control every page of the site.
        self.assertEqual(reverse("spaces:service-worker"), "/sw.js")
        self.assertEqual(self.response.status_code, 200)
        self.assertEqual(self.response["Content-Type"], "application/javascript")

    def test_browser_always_checks_for_a_new_version(self):
        self.assertEqual(self.response["Cache-Control"], "no-cache")

    def test_values_are_filled_in_as_javascript(self):
        self.assertNotIn("{{", self.script)
        self.assertNotIn("&quot;", self.script)  # JSON must not be HTML-escaped.
        self.assertIn(f'const CACHE_NAME = `${{CACHE_PREFIX}}{pwa.cache_version()}`;', self.script)
        urls = json.loads(re.search(r"const PRECACHE_URLS = (\[.*?\]);", self.script).group(1))
        self.assertEqual(urls, pwa.precache_urls())

    def test_api_admin_and_account_pages_are_never_cached(self):
        self.assertIn('const NEVER_HANDLED = ["/api/", "/admin/", "/accounts/"];', self.script)
        # Only same-site GET requests are handled. Map tiles and form posts go straight to the network.
        self.assertIn('request.method !== "GET" || url.origin !== self.location.origin', self.script)

    def test_old_caches_are_deleted_on_activate(self):
        self.assertIn('name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME', self.script)


class AppShellTests(SimpleTestCase):
    def test_every_shell_file_exists(self):
        # One missing file would make the service worker's install fail.
        for name in pwa.SHELL_STATIC_FILES:
            self.assertIsNotNone(finders.find(name), name)

    def test_every_map_script_is_cached(self):
        # A module missing from the shell would break the map offline.
        scripts = Path(finders.find("spaces/js/map.js")).parent
        cached = {name for name in pwa.SHELL_STATIC_FILES if name.startswith("spaces/js/")}
        self.assertEqual(cached, {f"spaces/js/{path.name}" for path in scripts.glob("*.js")})

    def test_pages_and_offline_page_are_precached(self):
        urls = pwa.precache_urls()
        for route in (*pwa.SHELL_PAGE_ROUTES, pwa.OFFLINE_PAGE_ROUTE):
            self.assertIn(reverse(route), urls)
        self.assertFalse(any(url.startswith(("/api/", "/admin/", "/accounts/")) for url in urls))

    def test_cache_version_changes_when_a_shell_file_changes(self):
        version = pwa.cache_version()
        self.assertRegex(version, r"^[0-9a-f]{12}$")
        self.assertEqual(pwa.cache_version(), version)
        original = Path.read_bytes
        with mock.patch.object(Path, "read_bytes", lambda path: original(path) + b"/* edited */"):
            self.assertNotEqual(pwa.cache_version(), version)


@override_settings(ALLOWED_HOSTS=["testserver"])
class PwaPageTests(TestCase):  # The map page counts facilities, so it needs the database.
    def test_offline_page(self):
        response = self.client.get(reverse("spaces:offline"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You're offline")
        self.assertContains(response, f'href="{reverse("spaces:home")}"')

    def test_pages_link_the_manifest_and_register_the_service_worker(self):
        for route in ("spaces:home", "spaces:about"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertContains(response, '<link rel="manifest" href="/manifest.webmanifest">')
                self.assertContains(response, 'data-sw-url="/sw.js"')
                self.assertContains(response, f'<script type="module" src="{static("spaces/js/pwa.js")}">')
                self.assertContains(response, static("spaces/icons/apple-touch-icon.png"))
