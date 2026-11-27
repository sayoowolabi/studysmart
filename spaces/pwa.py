"""Progressive Web App support. Lists what the service worker caches and works out the cache version."""
import hashlib
from pathlib import Path

from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.urls import reverse

# The "app shell". These are the static files the map and About pages need to open without a
# network connection. The service worker downloads these when it installs. If any one
# is missing the install fails, so a test checks that each file exists.
SHELL_STATIC_FILES = (
    "spaces/vendor/bootstrap/bootstrap.min.css",
    "spaces/vendor/leaflet/leaflet.css",
    "spaces/vendor/leaflet/leaflet.js",
    "spaces/vendor/leaflet/images/marker-icon.png",
    "spaces/vendor/leaflet/images/marker-icon-2x.png",
    "spaces/vendor/leaflet/images/marker-shadow.png",
    "spaces/css/map.css",
    "spaces/fonts/nunito-latin-wght-normal.woff2",
    "spaces/js/api.js",
    "spaces/js/areas.js",
    "spaces/js/map.js",
    "spaces/js/markers.js",
    "spaces/js/pwa.js",
    "spaces/js/results.js",
    "spaces/js/search.js",
    "spaces/js/status.js",
    "spaces/icons/icon.svg",
    "spaces/icons/icon-192.png",
)

# Pages kept for offline use. Each is refreshed in the cache whenever it loads online.
SHELL_PAGE_ROUTES = ("spaces:home", "spaces:about")
OFFLINE_PAGE_ROUTE = "spaces:offline"


def shell_page_urls():
    return [reverse(route) for route in SHELL_PAGE_ROUTES]


def precache_urls():
    """Everything the service worker stores when it installs. That is the pages, the offline page and the static files."""
    return [*shell_page_urls(), reverse(OFFLINE_PAGE_ROUTE), *(static(name) for name in SHELL_STATIC_FILES)]


def cache_version():
    """
    A short hash of the shell files' contents. Static file names carry no version, so
    when any shell file changes this hash changes, which changes the bytes of /sw.js.
    The browser then installs the new service worker, which fills a new cache and
    deletes the old one, so nobody keeps running yesterday's JavaScript.
    Hashing about 400 KB takes around a millisecond, so it is simply worked out on each request.
    """
    digest = hashlib.sha256()
    for name in SHELL_STATIC_FILES:
        digest.update(Path(finders.find(name)).read_bytes())
    return digest.hexdigest()[:12]
