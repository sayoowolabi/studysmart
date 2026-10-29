/*
 * StudySmart map: loads study spaces and area boundaries from the Django REST API
 * and shows them on a Leaflet map. All record text is inserted with textContent,
 * never parsed as HTML, so names or addresses cannot inject markup into the page.
 */
"use strict";

const DUBLIN_CENTRE = [53.3498, -6.2603]; // Leaflet uses [latitude, longitude].
const DEFAULT_ZOOM = 13;

const SPACE_TYPES = {
    library: {label: "Library", letter: "L"},
    cafe: {label: "Café", letter: "C"},
};

const FACILITY_LABELS = {
    indoor_seating: "Indoor seating",
    outdoor_seating: "Outdoor seating",
    has_wifi: "Wi-Fi",
    has_outlets: "Power outlets",
    laptop_allowed: "Laptops allowed",
};

const SOURCE_KIND_LABELS = {
    official: "Official dataset",
    osm: "OpenStreetMap",
    manual: "Manual record",
    demo: "Demonstration data",
};

document.addEventListener("DOMContentLoaded", () => {
    if (typeof L === "undefined") {
        showMessage("The map library could not be loaded. Check your connection and refresh.", "danger");
        return;
    }
    const mapElement = document.getElementById("map");
    const map = createMap(mapElement);
    loadStudySpaces(map, mapElement.dataset.spacesUrl);
    loadAreaBoundaries(map, mapElement.dataset.areasUrl);
    enableLocationSelection(map);
});

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

async function fetchJson(url) {
    const response = await fetch(url, {headers: {Accept: "application/json"}});
    if (!response.ok) {
        throw new Error(`${url} returned HTTP ${response.status}`);
    }
    return response.json();
}

/* ---------- Status messages ---------- */

function showMessage(text, variant) {
    const alert = document.createElement("div");
    alert.className = `alert alert-${variant}`;
    alert.textContent = text;
    document.getElementById("map-messages").append(alert);
    return alert;
}

/* ---------- Study spaces ---------- */

async function loadStudySpaces(map, url) {
    const loading = showMessage("Loading study spaces…", "info");
    let spaces;
    try {
        spaces = await fetchJson(url);
    } catch (error) {
        console.error(error);
        showMessage("Study spaces could not be loaded. Please try again later.", "danger");
        return;
    } finally {
        loading.remove();
    }

    if (spaces.length === 0) {
        showMessage("No study spaces are available yet.", "warning");
        return;
    }

    const layers = {
        library: L.layerGroup([], {
            attribution: 'Libraries: <a href="https://data.smartdublin.ie/dataset/dublin-city-libraries">Dublin City Council</a> (CC BY)',
        }),
        cafe: L.layerGroup([], {
            attribution: 'Cafés: OpenStreetMap contributors (<a href="https://opendatacommons.org/licenses/odbl/">ODbL</a>)',
        }),
    };
    for (const space of spaces) {
        // The API returns plain latitude/longitude numbers, not GeoJSON, so no swap is needed.
        if (!layers[space.space_type] || !Number.isFinite(space.latitude) || !Number.isFinite(space.longitude)) {
            console.warn("Skipping study space with unexpected type or coordinates:", space.id);
            continue;
        }
        createSpaceMarker(space).addTo(layers[space.space_type]);
    }
    for (const [type, layer] of Object.entries(layers)) {
        layer.addTo(map);
        document.getElementById(`${type}-count`).textContent = `(${layer.getLayers().length})`;
    }
}

function createSpaceMarker(space) {
    const type = SPACE_TYPES[space.space_type];
    const icon = L.divIcon({
        className: `space-marker space-marker--${space.space_type}`,
        html: type.letter,
        iconSize: [24, 24],
        popupAnchor: [0, -12],
    });
    // Draw the few libraries above the many cafés so they are not hidden in the city centre.
    const zIndexOffset = space.space_type === "library" ? 1000 : 0;
    return L.marker([space.latitude, space.longitude], {icon, title: space.name, zIndexOffset})
        .bindPopup(() => buildPopup(space), {maxWidth: 260});
}

function buildPopup(space) {
    const popup = document.createElement("div");
    popup.className = "space-popup";

    appendElement(popup, "h2", space.name);
    appendElement(popup, "p", `${SPACE_TYPES[space.space_type].label} · ${space.address || "Address not recorded"}`);

    const facilities = appendElement(popup, "dl");
    for (const [field, label] of Object.entries(FACILITY_LABELS)) {
        appendElement(facilities, "dt", label);
        const value = appendElement(facilities, "dd", facilityText(space[field]));
        if (space[field] === null) {
            value.className = "facility-unknown";
        }
    }

    const source = SOURCE_KIND_LABELS[space.source_kind] || space.source_kind;
    const licence = space.source_licence ? ` (${space.source_licence})` : "";
    appendElement(popup, "p", "Facilities are source-reported, not live availability.").className = "popup-note";
    appendElement(popup, "p", `Source: ${source}${licence}`).className = "popup-note";
    return popup;
}

function facilityText(value) {
    // null means the source did not say, so it is shown as Unknown rather than "No".
    if (value === true) return "Yes";
    if (value === false) return "No";
    return "Unknown";
}

function appendElement(parent, tagName, text) {
    const element = document.createElement(tagName);
    if (text !== undefined) {
        element.textContent = text;
    }
    parent.append(element);
    return element;
}

/* ---------- Administrative-area boundaries (optional overlay) ---------- */

async function loadAreaBoundaries(map, url) {
    let collection;
    try {
        collection = await fetchJson(url);
    } catch (error) {
        console.error(error);
        showMessage("Area boundaries could not be loaded; study spaces are unaffected.", "warning");
        return;
    }
    if (collection.features.length === 0) {
        return; // No areas imported: there is simply no overlay to offer.
    }

    // L.geoJSON reads GeoJSON's [longitude, latitude] order itself.
    const boundaries = L.geoJSON(collection, {
        attribution: 'Boundaries: <a href="https://data.smartdublin.ie/dataset/administrative-areas-dcc">Dublin City Council</a> (CC BY)',
        style: {color: "#5a3d8a", weight: 2, dashArray: "6 4", fill: false},
        onEachFeature: (feature, layer) => {
            const name = document.createElement("span");
            name.textContent = feature.properties.name;
            layer.bindTooltip(name, {sticky: true});
        },
    });
    // Off by default; the layer control in the top-right corner toggles it.
    L.control.layers(null, {"Area boundaries": boundaries}).addTo(map);
}

/* ---------- Search-location selection ---------- */

function enableLocationSelection(map) {
    const panel = document.getElementById("selected-location");
    const coordinates = document.getElementById("selected-coordinates");
    let selectionMarker = null;

    map.on("click", (event) => {
        // wrap() keeps longitude within -180..180 (the API's valid range) if the world is panned past it.
        const location = event.latlng.wrap();
        const {lat, lng} = location;
        if (selectionMarker) {
            selectionMarker.setLatLng(location);
        } else {
            selectionMarker = L.marker(location, {title: "Selected search location"}).addTo(map);
        }
        coordinates.textContent = `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
        panel.hidden = false;
    });

    document.getElementById("clear-selection").addEventListener("click", () => {
        selectionMarker?.remove();
        selectionMarker = null;
        panel.hidden = true;
    });
}
