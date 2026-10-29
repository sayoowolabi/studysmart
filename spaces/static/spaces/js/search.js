/*
 * Search sidebar. The page is always in one of three modes, and every change
 * (location, filter, radius, button) re-runs the current mode with all filters:
 *   "all"     - every matching study space   GET /api/spaces/?filters
 *   "nearby"  - matches within the radius     GET /api/spaces/nearby/?lat&lng&radius&filters
 *   "nearest" - the single closest match      GET /api/spaces/nearest/?lat&lng&filters
 * PostGIS does all distance and radius work; the browser only displays the results.
 *
 * The search location is set only in "choose location" mode: the next map click or
 * marker click sets it and ends the mode. Outside the mode, clicks pan and open popups.
 */
import {fetchJson, isAbortError} from "./api.js";
import {SPACE_TYPES, appendElement, formatDistance, showSpaces} from "./markers.js";
import {clearStatus, setStatus} from "./status.js";

const MAX_LISTED_RESULTS = 50;

const state = {
    map: null,
    layers: null,
    urls: null,
    mode: "all",
    choosing: false,         // true while waiting for a click to choose the location
    location: null,          // L.LatLng of the selected search location
    selectionMarker: null,
    overlay: null,           // radius circle or nearest-result line
    markers: new Map(),      // study-space id -> marker, for the results list
    controller: null,        // AbortController of the request in progress
};

export function initSearch(map, layers, urls) {
    Object.assign(state, {map, layers, urls, overlay: L.layerGroup().addTo(map)});

    map.on("click", (event) => {
        if (state.choosing) {
            chooseLocation(event.latlng);
        }
    });
    element("choose-location").addEventListener("click", () => (state.choosing ? stopChoosing() : startChoosing()));
    element("cancel-choosing").addEventListener("click", stopChoosing);
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && state.choosing) {
            stopChoosing();
        }
    });
    element("clear-location").addEventListener("click", clearLocation);
    element("nearby-button").addEventListener("click", () => setMode("nearby"));
    element("nearest-button").addEventListener("click", () => setMode("nearest"));
    element("reset-filters").addEventListener("click", resetFilters);
    element("search-form").addEventListener("change", onFormChange);
    element("search-form").addEventListener("submit", (event) => event.preventDefault());

    runSearch();
}

function element(id) {
    return document.getElementById(id);
}

/* ---------- User actions ---------- */

function startChoosing() {
    state.choosing = true;
    state.map.closePopup();
    state.map.getContainer().classList.add("map--choosing");
    element("choose-banner").hidden = false;
    setChooseButton("Cancel choosing location", true);
    // On tablets and phones the sidebar is below the map, so bring the map into view.
    element("map").scrollIntoView({behavior: "smooth", block: "nearest"});
}

function stopChoosing() {
    state.choosing = false;
    state.map.getContainer().classList.remove("map--choosing");
    element("choose-banner").hidden = true;
    setChooseButton("Choose search location", false);
}

function setChooseButton(text, pressed) {
    const button = element("choose-location");
    button.textContent = text;
    button.setAttribute("aria-pressed", String(pressed));
}

/* Used for every study-space marker click: in choose mode the click picks the marker's position. */
function onMarkerClick(marker) {
    if (!state.choosing) {
        return false; // Not handled: the marker opens its popup as usual.
    }
    chooseLocation(marker.getLatLng());
    return true;
}

function chooseLocation(latlng) {
    stopChoosing();
    // wrap() keeps longitude within -180..180 (the API's valid range) if the world is panned past it.
    state.location = latlng.wrap();
    if (state.selectionMarker) {
        state.selectionMarker.setLatLng(state.location);
    } else {
        // Not interactive, so clicks on the pin reach the map underneath.
        state.selectionMarker = L.marker(state.location, {title: "Selected search location", interactive: false})
            .addTo(state.map);
    }
    element("location-text").textContent =
        `Selected: ${state.location.lat.toFixed(5)}, ${state.location.lng.toFixed(5)}`;
    for (const id of ["clear-location", "nearby-button", "nearest-button"]) {
        element(id).disabled = false;
    }
    // A search already showing results follows the new location.
    if (state.mode !== "all") {
        runSearch();
    }
}

function clearLocation() {
    stopChoosing();
    state.selectionMarker?.remove();
    state.selectionMarker = null;
    state.location = null;
    element("location-text").textContent = "No location chosen. Press the button above, then tap the map or a marker.";
    for (const id of ["clear-location", "nearby-button", "nearest-button"]) {
        element(id).disabled = true;
    }
    setMode("all");
}

function setMode(mode) {
    state.mode = mode;
    runSearch();
}

function onFormChange(event) {
    // The radius only matters to a nearby search; every other change affects all modes.
    if (event.target.id === "radius" && state.mode !== "nearby") {
        return;
    }
    runSearch();
}

function resetFilters() {
    for (const box of document.querySelectorAll('input[name="type"]')) {
        box.checked = true;
    }
    for (const box of document.querySelectorAll('input[name="facility"]')) {
        box.checked = false;
    }
    runSearch();
}

/* ---------- Building requests ---------- */

function selectedTypes() {
    return [...document.querySelectorAll('input[name="type"]:checked')].map((box) => box.value);
}

/* Filters shared by all three modes, so they are always applied the same way. */
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

function locationParams() {
    const params = filterParams();
    params.set("lat", state.location.lat.toFixed(6));
    params.set("lng", state.location.lng.toFixed(6));
    return params;
}

function selectedRadius() {
    return Number(element("radius").value);
}

/*
 * Starts a request and cancels any request still in progress, so rapid clicks or
 * filter changes can never let an older, slower response overwrite a newer one.
 */
async function fetchLatest(url, loadingText) {
    state.controller?.abort();
    const controller = new AbortController();
    state.controller = controller;
    setStatus(loadingText, "info");
    showResults(loadingText); // The sidebar must not show the previous search's results meanwhile.
    const data = await fetchJson(url, controller.signal);
    if (controller.signal.aborted) {
        throw new DOMException("Replaced by a newer search", "AbortError");
    }
    return data;
}

/* ---------- Running searches ---------- */

async function runSearch() {
    if (selectedTypes().length === 0) {
        state.controller?.abort();
        display([]);
        setStatus("Select at least one study-space type.", "warning");
        showResults("No study-space type selected.");
        return;
    }
    try {
        if (state.mode === "nearby") {
            await searchNearby();
        } else if (state.mode === "nearest") {
            await findNearest();
        } else {
            await showAllSpaces();
        }
    } catch (error) {
        if (isAbortError(error)) {
            return; // A newer search replaced this one; it will update the page itself.
        }
        console.error(error);
        setStatus("Study spaces could not be loaded. Please try again.", "danger");
        showResults("The last search failed. The map may show older results.");
    }
}

async function showAllSpaces() {
    const spaces = await fetchLatest(`${state.urls.spacesUrl}?${filterParams()}`, "Loading study spaces…");
    display(spaces);
    if (spaces.length === 0) {
        setStatus(noMatchesMessage("No study spaces match these filters."), "warning");
    } else {
        clearStatus();
    }
    showResults(`Showing all ${spaces.length} matching study spaces. Choose a search location to search nearby.`);
}

async function searchNearby() {
    const radius = selectedRadius();
    const params = locationParams();
    params.set("radius", radius);
    const spaces = await fetchLatest(`${state.urls.nearbyUrl}?${params}`, "Searching nearby…");

    display(spaces);
    // The circle only shows the chosen radius; PostGIS has already decided which spaces are inside it.
    const circle = L.circle(state.location, {radius, color: "#0d6efd", weight: 2, fillOpacity: 0.05, interactive: false});
    circle.addTo(state.overlay);
    state.map.fitBounds(circle.getBounds(), {padding: [20, 20]});

    const within = `within ${formatDistance(radius)}`;
    if (spaces.length === 0) {
        setStatus(noMatchesMessage(`No study spaces match these filters ${within}. Try a larger radius.`), "warning");
    } else {
        clearStatus();
    }
    showResults(`${spaces.length} study ${spaces.length === 1 ? "space" : "spaces"} ${within}, nearest first.`, spaces);
}

async function findNearest() {
    let space;
    try {
        space = await fetchLatest(`${state.urls.nearestUrl}?${locationParams()}`, "Finding the nearest study space…");
    } catch (error) {
        if (error.status !== 404) {
            throw error;
        }
        display([]);
        setStatus(noMatchesMessage("No study space matches these filters."), "warning");
        showResults("No nearest study space: nothing matches these filters.");
        return;
    }

    display([space], space.id);
    const spacePosition = [space.latitude, space.longitude];
    L.polyline([state.location, spacePosition], {color: "#212529", weight: 2, dashArray: "4 6", interactive: false})
        .addTo(state.overlay);
    // A permanent label rather than an open popup: a popup would pan the map and could
    // push the selected location off screen. Clicking the marker still opens the popup.
    const label = document.createElement("span");
    label.textContent = `Nearest · ${formatDistance(space.distance_m)}`;
    state.markers.get(space.id)?.bindTooltip(label, {permanent: true, direction: "top", offset: [0, -17]});
    state.map.fitBounds([state.location, spacePosition], {padding: [60, 60], maxZoom: 17});
    clearStatus();
    showResults(`Nearest match: ${space.name}, ${formatDistance(space.distance_m)} away.`, [space]);
}

/* Explains empty results caused by facility filters, which exclude unknown values. */
function noMatchesMessage(text) {
    const facilityFiltered = document.querySelector('input[name="facility"]:checked');
    return facilityFiltered ? `${text} Facility filters only include confirmed values.` : text;
}

/* ---------- Showing results ---------- */

function display(spaces, highlightedId = null) {
    state.overlay.clearLayers();
    state.markers = showSpaces(state.layers, spaces, {highlightedId, onMarkerClick});
}

function showResults(summary, spaces = []) {
    element("results-summary").textContent = summary;
    const list = element("results-list");
    list.replaceChildren();
    for (const space of spaces.slice(0, MAX_LISTED_RESULTS)) {
        list.append(resultItem(space));
    }
    if (spaces.length > MAX_LISTED_RESULTS) {
        appendElement(list, "p", `Listing the nearest ${MAX_LISTED_RESULTS}; all ${spaces.length} are on the map.`)
            .className = "small text-body-secondary mt-2 mb-0";
    }
}

function resultItem(space) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "list-group-item list-group-item-action";
    appendElement(item, "span", space.name).className = "fw-semibold d-block";
    appendElement(item, "span", `${SPACE_TYPES[space.space_type].label} · ${formatDistance(space.distance_m)}`)
        .className = "small text-body-secondary";
    item.addEventListener("click", () => {
        const marker = state.markers.get(space.id);
        if (marker) {
            state.map.panTo(marker.getLatLng());
            marker.openPopup();
        }
    });
    return item;
}
