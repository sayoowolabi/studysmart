/*
 * StudySmart map entry point: creates the Leaflet map and starts the other modules.
 *   api.js     - requests to the Django REST API
 *   markers.js - study-space markers and popups
 *   search.js  - search sidebar: location, radius, filters, results
 *   areas.js   - boundary overlay and per-area counts
 *   status.js  - loading, empty and error messages over the map
 */
import {loadAreaBoundaries, loadAreaStatistics} from "./areas.js";
import {createSpaceLayers} from "./markers.js";
import {initSearch} from "./search.js";
import {showWarning} from "./status.js";

const DUBLIN_CENTRE = [53.3498, -6.2603]; // Leaflet uses [latitude, longitude].
const DEFAULT_ZOOM = 13;

function createMap(mapElement) {
    const map = L.map(mapElement).setView(DUBLIN_CENTRE, DEFAULT_ZOOM);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        // OSM's tile policy blocks browser requests without a Referer. Django's default
        // "same-origin" policy sends none to other sites, so tiles send just our origin.
        referrerPolicy: "strict-origin-when-cross-origin",
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    return map;
}

function start() {
    if (typeof L === "undefined") {
        showWarning("The map library could not be loaded. Check your connection and refresh.", "danger");
        return;
    }
    const mapElement = document.getElementById("map");
    // API URLs come from Django's {% url %} tags as data- attributes.
    const urls = mapElement.dataset;
    const map = createMap(mapElement);
    initSearch(map, createSpaceLayers(map), urls);
    loadAreaBoundaries(map, urls.areasUrl);
    loadAreaStatistics(urls.coverageUrl);
}

start();
