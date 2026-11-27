/*
 * The StudySmart service worker. Django serves it at /sw.js (see spaces/pwa.py and views.service_worker).
 *
 * It sits between the pages and the network and decides what to do with each request.
 * Map and About pages try the network first. Offline they come from the cache, or the offline page is shown.
 * Files under /static/spaces/ come from the cache first, so the app shell opens without a connection.
 * /api/, /admin/, /accounts/, other sites (map tiles) and anything that is not a GET request are left alone.
 * The browser fetches them normally and nothing is cached. Search results are never cached here,
 * because search.js keeps the last results itself.
 */
const CACHE_PREFIX = "studysmart-";
// Changes whenever a shell file changes, so a new version replaces the old cache.
const CACHE_NAME = `${CACHE_PREFIX}{{ cache_version }}`;
const PRECACHE_URLS = {{ precache_urls|safe }};
const SHELL_PAGES = {{ shell_pages|safe }};
const OFFLINE_URL = {{ offline_url|safe }};
const STATIC_PREFIX = {{ static_prefix|safe }};
const NEVER_HANDLED = ["/api/", "/admin/", "/accounts/"];

// On install, download the whole app shell. If any file fails, this version is not installed.
self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => cache.addAll(PRECACHE_URLS))
            .then(() => self.skipWaiting()), // Take over from an older version without waiting for tabs to close.
    );
});

// On activate, delete caches left by older versions, then take control of the pages already open.
self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys()
            .then((names) => Promise.all(names
                .filter((name) => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME)
                .map((name) => caches.delete(name))))
            .then(() => self.clients.claim()),
    );
});

self.addEventListener("fetch", (event) => {
    const request = event.request;
    const url = new URL(request.url);
    if (request.method !== "GET" || url.origin !== self.location.origin
        || NEVER_HANDLED.some((prefix) => url.pathname.startsWith(prefix))) {
        return; // Not calling respondWith() leaves the request to the browser.
    }
    if (request.mode === "navigate") {
        event.respondWith(networkFirstPage(request, url));
    } else if (url.pathname.startsWith(STATIC_PREFIX)) {
        event.respondWith(cacheFirst(request));
    }
});

/* Pages always try the server first, so online visitors see current content. Offline they fall back to the cache. */
async function networkFirstPage(request, url) {
    try {
        // The original request, so the browser still handles redirects (such as /about to /about/) itself.
        const response = await fetch(request);
        if (response.ok && SHELL_PAGES.includes(url.pathname)) {
            const cache = await caches.open(CACHE_NAME);
            await cache.put(url.pathname, response.clone());
        }
        return response;
    } catch (error) {
        // fetch() only fails when the network is down. Server errors still arrive as normal responses.
        return (await caches.match(url.pathname)) || caches.match(OFFLINE_URL);
    }
}

/* Static files come from the cache when they are there. Otherwise they come from the network and are kept for next time. */
async function cacheFirst(request) {
    const cached = await caches.match(request);
    if (cached) {
        return cached;
    }
    const response = await fetch(request);
    if (response.ok) {
        const cache = await caches.open(CACHE_NAME);
        await cache.put(request, response.clone());
    }
    return response;
}
