/*
 * Search panel: starting point, filters and results.
 *
 * 1. The user sets a starting point: a university campus, their current location,
 *    or a point picked on the map ("Pick on map" mode).
 * 2. Filters: radius, type and confirmed facilities.
 * 3. The 10 nearest matches appear as numbered cards and matching numbered markers.
 * Every change re-runs the search automatically, always with the same filters:
 *   no starting point     - every matching space        GET /api/spaces/?filters
 *   starting point        - matches within the radius   GET /api/spaces/nearby/?lat&lng&radius&filters
 *   "Show nearest match"  - the closest match anywhere  GET /api/spaces/nearest/?lat&lng&filters
 * PostGIS does all distance, radius and nearest work; the browser only displays results.
 */
import {fetchJson, isAbortError} from "./api.js";
import {formatDistance, setMarkerHighlight, showSpaces} from "./markers.js";
import {clearResults, markActiveResult, renderLoading, renderResults} from "./results.js";
import {clearStatus, setStatus} from "./status.js";

const RESULT_LIMIT = 10;
const DEFAULT_RADIUS = "1000";
// Matches the CSS breakpoint where the panel becomes a separate scrolling column.
const LARGE_SCREEN = window.matchMedia("(min-width: 992px)");
const GEOLOCATION_OPTIONS = {enableHighAccuracy: false, timeout: 10000, maximumAge: 60000};
const GEOLOCATION_ERRORS = {
    1: "Location access was denied. Choose a campus or pick a point on the map instead.",
    2: "Your location could not be found. Choose a campus or pick a point on the map instead.",
    3: "Finding your location took too long. Try again, or choose a campus instead.",
};

const state = {
    map: null,
    layers: null,
    urls: null,
    origin: null,            // {latlng, label} of the starting point, or null
    originMarker: null,
    showNearest: false,      // true after "Show nearest match"; any other change resets it
    choosing: false,         // true while "Pick on map" waits for a click
    overlay: null,           // radius circle or nearest-match line
    markers: new Map(),      // study-space id -> marker currently on the map
    activeId: null,          // id of the highlighted result
    controller: null,        // AbortController of the request in progress
};

export function initSearch(map, layers, urls) {
    Object.assign(state, {map, layers, urls, overlay: L.layerGroup().addTo(map)});

    element("campus-select").addEventListener("change", onCampusChange);
    element("locate-button").addEventListener("click", useMyLocation);
    element("choose-location").addEventListener("click", () => (state.choosing ? stopChoosing() : startChoosing()));
    element("cancel-choosing").addEventListener("click", stopChoosing);
    element("clear-location").addEventListener("click", clearOrigin);
    map.on("click", (event) => {
        if (state.choosing) {
            const latlng = event.latlng.wrap(); // Keeps longitude within the API's -180..180 range.
            setOrigin(latlng, `map point ${latlng.lat.toFixed(4)}, ${latlng.lng.toFixed(4)}`);
        }
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && state.choosing) {
            stopChoosing();
        }
    });

    element("search-form").addEventListener("change", () => rerun());
    element("search-form").addEventListener("submit", (event) => event.preventDefault());
    element("reset-filters").addEventListener("click", resetFilters);
    element("widen-radius").addEventListener("click", widenRadius);
    if (!LARGE_SCREEN.matches) {
        element("filters-details").open = false; // Keeps the map near the top on phones and tablets.
    }
    element("show-nearest").addEventListener("click", () => {
        state.showNearest = true;
        runSearch();
    });

    runSearch();
}

function element(id) {
    return document.getElementById(id);
}

/* ---------- Step 1: starting point ---------- */

function onCampusChange(event) {
    const option = event.target.selectedOptions[0];
    if (!option.value) {
        return; // The "Choose a campus…" placeholder.
    }
    showCampusNote(option.dataset.note);
    const latlng = L.latLng(Number(option.dataset.lat), Number(option.dataset.lng));
    setOrigin(latlng, option.textContent.trim(), {fromCampus: true});
}

function useMyLocation() {
    hideLocationError();
    if (!("geolocation" in navigator)) {
        showLocationError("This browser cannot share your location. Choose a campus or pick a point on the map instead.");
        return;
    }
    if (!window.isSecureContext) {
        showLocationError("Your location can only be used over a secure (HTTPS) connection. Choose a campus or pick a point on the map instead.");
        return;
    }
    setLocateBusy(true);
    element("location-text").textContent = "Finding your location…";
    navigator.geolocation.getCurrentPosition(
        (position) => {
            setLocateBusy(false);
            const {latitude, longitude, accuracy} = position.coords;
            setOrigin(L.latLng(latitude, longitude), `your location (within about ${Math.round(accuracy)} m)`);
        },
        (error) => {
            setLocateBusy(false);
            updateLocationText();
            showLocationError(GEOLOCATION_ERRORS[error.code] || GEOLOCATION_ERRORS[2]);
        },
        GEOLOCATION_OPTIONS,
    );
}

function setLocateBusy(busy) {
    const button = element("locate-button");
    button.disabled = busy;
    button.setAttribute("aria-busy", String(busy));
}

function startChoosing() {
    state.choosing = true;
    state.map.closePopup();
    state.map.getContainer().classList.add("map--choosing");
    element("choose-banner").hidden = false;
    element("choose-label").textContent = "Cancel picking";
    element("choose-location").setAttribute("aria-pressed", "true");
    // On tablets and phones the map is below the controls, so bring it into view.
    element("map").scrollIntoView({block: "nearest"});
}

function stopChoosing() {
    state.choosing = false;
    state.map.getContainer().classList.remove("map--choosing");
    element("choose-banner").hidden = true;
    element("choose-label").textContent = "Pick on map";
    element("choose-location").setAttribute("aria-pressed", "false");
}

function setOrigin(latlng, label, {fromCampus = false} = {}) {
    stopChoosing();
    hideLocationError();
    if (!fromCampus) {
        element("campus-select").value = "";
        showCampusNote("");
    }
    state.origin = {latlng, label};
    state.originMarker?.remove();
    // Not interactive, so clicks on the pin reach the map underneath.
    state.originMarker = L.marker(latlng, {title: `Starting point: ${label}`, interactive: false, keyboard: false})
        .addTo(state.map);
    updateLocationText();
    rerun();
}

function clearOrigin() {
    stopChoosing();
    hideLocationError();
    state.originMarker?.remove();
    state.originMarker = null;
    state.origin = null;
    element("campus-select").value = "";
    showCampusNote("");
    updateLocationText();
    rerun();
}

function updateLocationText() {
    element("location-text").textContent = state.origin ? `Starting from ${state.origin.label}` : "No starting point yet.";
    element("clear-location").hidden = !state.origin;
}

function showCampusNote(note) {
    const paragraph = element("campus-note");
    paragraph.textContent = note || "";
    paragraph.hidden = !note;
}

function showLocationError(message) {
    const paragraph = element("location-error");
    paragraph.textContent = message;
    paragraph.hidden = false;
}

function hideLocationError() {
    element("location-error").hidden = true;
}

/* ---------- Step 2: filters ---------- */

function resetFilters() {
    for (const box of document.querySelectorAll('input[name="type"]')) {
        box.checked = true;
    }
    for (const box of document.querySelectorAll('input[name="facility"]')) {
        box.checked = false;
    }
    element(`radius-${DEFAULT_RADIUS}`).checked = true;
    rerun();
}

function widenRadius() {
    const radios = [...document.querySelectorAll('input[name="radius"]')];
    const next = radios.find((radio) => Number(radio.value) > selectedRadius());
    if (next) {
        next.checked = true;
    }
    rerun();
}

/* One line describing the current filters, shown beside the "Filters" heading. */
function updateFilterSummary() {
    const types = selectedTypes();
    const typeText = types.length === 2 ? "All types" : types.length === 1 ? (types[0] === "cafe" ? "Cafés" : "Libraries") : "No type";
    const facilities = document.querySelectorAll('input[name="facility"]:checked').length;
    const parts = [formatDistance(selectedRadius()), typeText];
    if (facilities > 0) {
        parts.push(`${facilities} ${facilities === 1 ? "facility" : "facilities"}`);
    }
    element("filter-summary").textContent = parts.join(" · ");
}

function selectedTypes() {
    return [...document.querySelectorAll('input[name="type"]:checked')].map((box) => box.value);
}

function selectedRadius() {
    return Number(document.querySelector('input[name="radius"]:checked').value);
}

/* Filters shared by every request, so they are always applied the same way. */
function filterParams() {
    const params = new URLSearchParams();
    const types = selectedTypes();
    if (types.length === 1) {
        params.set("type", types[0]); // Both types selected means no type filter.
    }
    for (const box of document.querySelectorAll('input[name="facility"]:checked')) {
        params.set(box.value, "true"); // "true" matches only confirmed values, never unknown.
    }
    return params;
}

function originParams() {
    const params = filterParams();
    params.set("lat", state.origin.latlng.lat.toFixed(6));
    params.set("lng", state.origin.latlng.lng.toFixed(6));
    return params;
}

/* ---------- Step 3: searching ---------- */

/* A new starting point or filter always returns to the normal radius search. */
function rerun() {
    state.showNearest = false;
    runSearch();
}

/*
 * Starts a request and cancels any request still in progress, so rapid clicks or
 * filter changes can never let an older, slower response overwrite a newer one.
 */
async function fetchLatest(url) {
    state.controller?.abort();
    const controller = new AbortController();
    state.controller = controller;
    const data = await fetchJson(url, controller.signal);
    if (controller.signal.aborted) {
        throw new DOMException("Replaced by a newer search", "AbortError");
    }
    return data;
}

async function runSearch() {
    updateFilterSummary();
    showActions(false);
    if (selectedTypes().length === 0) {
        state.controller?.abort();
        display([]);
        clearResults();
        clearStatus();
        showSummary("Select at least one type: Libraries or Cafés.");
        return;
    }
    try {
        if (!state.origin) {
            await showAllSpaces();
        } else if (state.showNearest) {
            await showNearestMatch();
        } else {
            await searchNearby();
        }
    } catch (error) {
        if (isAbortError(error)) {
            return; // A newer search replaced this one; it will update the page itself.
        }
        console.error(error);
        setStatus("Study spaces could not be loaded. Please try again.", "danger");
        clearResults();
        showSummary("Study spaces could not be loaded. Change a filter or try again shortly.");
    }
}

function showLoading(text) {
    setStatus(text, "info");
    showSummary(text);
    renderLoading();
}

async function showAllSpaces() {
    setStatus("Loading study spaces…", "info");
    const spaces = await fetchLatest(`${state.urls.spacesUrl}?${filterParams()}`);
    clearStatus();
    display(spaces);
    clearResults();
    showSummary(spaces.length > 0
        ? `${spaces.length} study spaces match your filters. Choose a starting point to see the 10 nearest.`
        : noMatchesText("No study spaces match these filters."));
}

async function searchNearby() {
    const radius = selectedRadius();
    const params = originParams();
    params.set("radius", radius);
    showLoading("Searching nearby…");
    const spaces = await fetchLatest(`${state.urls.nearbyUrl}?${params}`);
    clearStatus();

    const top = spaces.slice(0, RESULT_LIMIT); // Already ordered nearest first by PostGIS.
    display(top, {numbered: true});
    renderResults(top, (space) => selectResult(space.id));
    // The circle only shows the chosen radius; PostGIS has already decided which spaces are inside it.
    const circle = L.circle(state.origin.latlng, {
        radius, color: "#5a54d6", weight: 1.5, fillOpacity: 0.04, interactive: false,
    }).addTo(state.overlay);

    const within = `within ${formatDistance(radius)}`;
    if (spaces.length === 0) {
        state.map.fitBounds(circle.getBounds(), {padding: [20, 20]});
        showSummary(noMatchesText(`No study spaces match your filters ${within}.`)
            + " StudySmart covers the Dublin City Council area.");
        showActions(true);
        return;
    }
    fitTo(top);
    const noun = spaces.length === 1 ? "study space" : "study spaces";
    showSummary(`Showing ${top.length} of ${spaces.length} nearby ${noun} (${within}), nearest first.`);
}

async function showNearestMatch() {
    showLoading("Finding the nearest match…");
    let space;
    try {
        space = await fetchLatest(`${state.urls.nearestUrl}?${originParams()}`);
    } catch (error) {
        if (error.status !== 404) {
            throw error;
        }
        clearStatus();
        display([]);
        clearResults();
        showSummary(noMatchesText("No study space anywhere matches these filters."));
        return;
    }
    clearStatus();
    display([space], {numbered: true});
    renderResults([space], (match) => selectResult(match.id));
    L.polyline([state.origin.latlng, [space.latitude, space.longitude]], {
        color: "#2b2a33", weight: 2, dashArray: "4 6", interactive: false,
    }).addTo(state.overlay);
    fitTo([space]);
    selectResult(space.id, {fromMap: true});
    showSummary(`Nothing matched within ${formatDistance(selectedRadius())}. `
        + `The nearest match is ${space.name}, ${formatDistance(space.distance_m)} away.`);
}

/* Explains empty results caused by facility filters, which exclude unknown values. */
function noMatchesText(text) {
    const facilityFiltered = document.querySelector('input[name="facility"]:checked');
    return facilityFiltered ? `${text} Facility filters only include confirmed values.` : text;
}

/* ---------- Showing results ---------- */

function display(spaces, {numbered = false} = {}) {
    state.overlay.clearLayers();
    state.activeId = null;
    state.markers = showSpaces(state.layers, spaces, {numbered, onMarkerClick});
}

function fitTo(spaces) {
    const points = [state.origin.latlng, ...spaces.map((space) => [space.latitude, space.longitude])];
    state.map.fitBounds(L.latLngBounds(points), {padding: [40, 40], maxZoom: 16});
}

function showSummary(text) {
    element("results-summary").textContent = text;
}

function showActions(visible) {
    element("results-actions").hidden = !visible;
    const largest = Math.max(...[...document.querySelectorAll('input[name="radius"]')].map((radio) => Number(radio.value)));
    element("widen-radius").hidden = selectedRadius() >= largest;
}

/* Every study-space marker click: picks a starting point in "Pick on map" mode, otherwise selects the result. */
function onMarkerClick(marker, space) {
    if (state.choosing) {
        setOrigin(marker.getLatLng(), space.name);
        return true; // Handled: no popup.
    }
    selectResult(space.id, {fromMap: true});
    return false; // The popup opens as usual.
}

/*
 * Highlights the result's card and marker. From a card click, the map also moves to
 * the marker and opens its popup; from a marker click, the card scrolls into view.
 */
function selectResult(id, {fromMap = false} = {}) {
    const card = markActiveResult(id);
    if (!card) {
        return; // Only search results have cards (not the all-spaces view).
    }
    const previous = state.markers.get(state.activeId);
    if (previous) {
        setMarkerHighlight(previous, false);
    }
    state.activeId = id;
    const marker = state.markers.get(id);
    setMarkerHighlight(marker, true);

    if (fromMap) {
        // Only the large-screen panel scrolls on its own; on phones this would scroll the map away.
        if (LARGE_SCREEN.matches) {
            card.scrollIntoView({block: "nearest"});
        }
        return;
    }
    state.map.setView(marker.getLatLng(), Math.max(state.map.getZoom(), 16));
    marker.openPopup();
    if (!LARGE_SCREEN.matches) {
        element("map").scrollIntoView({block: "nearest"});
    }
}
