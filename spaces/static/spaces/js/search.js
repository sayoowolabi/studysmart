/*
 * The search panel, with the starting point, filters and results.
 *
 * 1. The user sets a starting point: a university campus, their current location,
 *    or a point picked on the map ("Pick on map" mode).
 * 2. The user sets filters for radius, number of results, type and confirmed café facilities.
 * 3. The nearest matches (10 by default) appear as numbered cards and matching numbered markers.
 * Every change runs the search again automatically, always with the same filters.
 *   No starting point: every matching space       GET /api/spaces/?filters&page_size=1000 (all pages)
 *   Starting point: matches within the radius     GET /api/spaces/nearby/?lat&lng&radius&filters
 *     and the areas the radius reaches            GET /api/areas/intersecting/?lat&lng&radius
 *   "Show nearest match": the closest anywhere    GET /api/spaces/nearest/?lat&lng&filters
 * PostGIS does all the distance, radius and nearest work. The browser only shows the results.
 */
import {fetchJson, isAbortError} from "./api.js";
import {formatDistance, setMarkerHighlight, showSpaces} from "./markers.js";
import {clearResults, markActiveResult, renderLoading, renderResults} from "./results.js";
import {clearStatus, setStatus} from "./status.js";

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
    showNearest: false,      // true after "Show nearest match". Any other change resets it
    choosing: false,         // true while "Pick on map" waits for a click
    overlay: null,           // radius circle or nearest-match line
    markers: new Map(),      // study-space id -> marker currently on the map
    activeId: null,          // id of the highlighted result
    controller: null,        // AbortController of the request in progress
    areaController: null,    // AbortController of the area-line request in progress
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

/* Restores every filter to its default in the HTML (the "checked" attributes), then searches again. */
function resetFilters() {
    element("search-form").reset();
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
    const defaultSize = Number(document.querySelector('input[name="result-size"]').value);
    if (selectedResultSize() !== defaultSize) {
        parts.push(`${selectedResultSize()} results`);
    }
    if (facilities > 0) {
        parts.push(`${facilities} café ${facilities === 1 ? "filter" : "filters"}`);
    }
    element("filter-summary").textContent = parts.join(" · ");
}

function selectedTypes() {
    return [...document.querySelectorAll('input[name="type"]:checked')].map((box) => box.value);
}

function selectedRadius() {
    return Number(document.querySelector('input[name="radius"]:checked').value);
}

function selectedResultSize() {
    return Number(document.querySelector('input[name="result-size"]:checked').value);
}

/* Filters shared by every request, so they are always applied the same way. */
function filterParams() {
    const params = new URLSearchParams();
    const types = selectedTypes();
    if (types.length === 1) {
        params.set("type", types[0]); // Both types selected means no type filter.
    }
    const facilities = document.querySelectorAll('input[name="facility"]:checked');
    for (const box of facilities) {
        params.set(box.value, "true"); // "true" matches only confirmed values, never unknown.
    }
    if (facilities.length > 0) {
        params.set("facilities_apply_to", "cafe"); // The facility filters never remove libraries.
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

/*
 * The list endpoint is paginated. Asks for the largest page (usually one request for the
 * whole dataset) and follows the "next" links until every page has been read.
 */
async function fetchAllPages(url) {
    const spaces = [];
    let pageUrl = url;
    while (pageUrl) {
        const page = await fetchLatest(pageUrl);
        spaces.push(...page.results);
        // Keep only the path and query. Django builds the absolute "next" URL behind the
        // proxy, and the page's own origin is always the right one to request.
        const next = page.next ? new URL(page.next) : null;
        pageUrl = next ? `${next.pathname}${next.search}` : null;
    }
    return spaces;
}

async function runSearch() {
    updateFilterSummary();
    showActions(false);
    clearAreaLine();
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
            return; // A newer search replaced this one, and it will update the page itself.
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
    const params = filterParams();
    params.set("page_size", "1000");
    const spaces = await fetchAllPages(`${state.urls.spacesUrl}?${params}`);
    clearStatus();
    display(spaces);
    clearResults();
    showSummary(spaces.length > 0
        ? `${spaces.length} study spaces match your filters. Choose a starting point to see the ${selectedResultSize()} nearest.`
        : noMatchesText("No study spaces match these filters."));
}

async function searchNearby() {
    const radius = selectedRadius();
    const params = originParams();
    params.set("radius", radius);
    showLoading("Searching nearby…");
    const spaces = await fetchLatest(`${state.urls.nearbyUrl}?${params}`);
    clearStatus();

    const top = spaces.slice(0, selectedResultSize()); // Already ordered nearest first by PostGIS.
    display(top, {numbered: true});
    renderResults(top, (space) => selectResult(space.id));
    // The circle only shows the chosen radius. PostGIS has already decided which spaces are inside it.
    const circle = L.circle(state.origin.latlng, {
        radius, color: "#5a54d6", weight: 1.5, fillOpacity: 0.04, interactive: false,
    }).addTo(state.overlay);
    showAreaLine(radius); // Not awaited. It only adds context and must never delay or break the search.

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

function clearAreaLine() {
    state.areaController?.abort();
    const line = element("results-areas");
    line.textContent = "";
    line.hidden = true;
}

/* One line naming the administrative areas a radius search reaches. If it fails, the line stays hidden. */
async function showAreaLine(radius) {
    const controller = new AbortController();
    state.areaController = controller;
    const {lat, lng} = state.origin.latlng;
    const params = new URLSearchParams({lat: lat.toFixed(6), lng: lng.toFixed(6), radius});
    try {
        const areas = await fetchJson(`${state.urls.intersectingUrl}?${params}`, controller.signal);
        if (!controller.signal.aborted) {
            const line = element("results-areas");
            line.textContent = areaLineText(areas);
            line.hidden = false;
        }
    } catch (error) {
        if (!isAbortError(error)) {
            console.warn(error);
        }
    }
}

function areaLineText({containing_area: containing, intersecting_areas: intersecting}) {
    const others = intersecting.filter((area) => area.id !== containing?.id).map((area) => areaName(area));
    const reached = new Intl.ListFormat("en-IE").format(others);
    if (containing) {
        const start = `You're in ${areaName(containing)}`;
        return others.length > 0 ? `${start}; this search also reaches ${reached}.` : `${start}; this search reaches no other area.`;
    }
    const start = "This starting point is outside the Dublin City Council area";
    return others.length > 0 ? `${start}; this search reaches ${reached}.` : `${start}.`;
}

/* The source stores area names in capitals, so "SOUTH EAST" becomes "South East". */
function areaName(area) {
    return area.name.toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase());
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
    // The line comes from PostGIS as GeoJSON in [longitude, latitude] order, which L.geoJSON reads correctly.
    L.geoJSON(space.line, {
        style: {color: "#2b2a33", weight: 2, dashArray: "4 6", className: "nearest-line"}, interactive: false,
    }).addTo(state.overlay);
    fitTo([space]);
    selectResult(space.id, {fromMap: true});
    showSummary(`Nothing matched within ${formatDistance(selectedRadius())}. `
        + `The nearest match is ${space.name}, ${formatDistance(space.distance_m)} away.`);
}

/* Explains empty results caused by café filters, which exclude unknown values. */
function noMatchesText(text) {
    const facilityFiltered = document.querySelector('input[name="facility"]:checked');
    return facilityFiltered ? `${text} Café filters only include confirmed values.` : text;
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
    element("results-summary-text").textContent = text;
}

function showActions(visible) {
    element("results-actions").hidden = !visible;
    const largest = Math.max(...[...document.querySelectorAll('input[name="radius"]')].map((radio) => Number(radio.value)));
    element("widen-radius").hidden = selectedRadius() >= largest;
}

/* Runs on every study-space marker click. In "Pick on map" mode it sets the starting point, otherwise it selects the result. */
function onMarkerClick(marker, space) {
    if (state.choosing) {
        setOrigin(marker.getLatLng(), space.name);
        return true; // Handled, so no popup opens.
    }
    selectResult(space.id, {fromMap: true});
    return false; // The popup opens as usual.
}

/*
 * Highlights the result's card and marker. From a card click, the map also moves to
 * the marker and opens its popup. From a marker click, the card scrolls into view.
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
        // Only the large-screen panel scrolls on its own. On phones this would scroll the map away.
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
