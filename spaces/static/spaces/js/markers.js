/*
 * Study-space markers and popups. All record text is inserted with textContent,
 * never parsed as HTML, so names or addresses cannot inject markup into the page.
 */

export const SPACE_TYPES = {
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

/* One layer group per type, created once and refilled after every search. */
export function createSpaceLayers(map) {
    const layers = {
        library: L.layerGroup([], {
            attribution: 'Libraries: <a href="https://data.smartdublin.ie/dataset/dublin-city-libraries">Dublin City Council</a> (CC BY)',
        }),
        cafe: L.layerGroup([], {
            attribution: 'Cafés: OpenStreetMap contributors (<a href="https://opendatacommons.org/licenses/odbl/">ODbL</a>)',
        }),
    };
    for (const layer of Object.values(layers)) {
        layer.addTo(map);
    }
    return layers;
}

/*
 * Replaces the markers on the map and returns them by study-space id.
 * onMarkerClick(marker) runs first on every marker click; if it returns true the
 * click has been used (for example to choose a search location) and no popup opens.
 */
export function showSpaces(layers, spaces, {highlightedId = null, onMarkerClick = () => false} = {}) {
    for (const layer of Object.values(layers)) {
        layer.clearLayers();
    }
    const markers = new Map();
    for (const space of spaces) {
        // The API returns plain latitude/longitude numbers, not GeoJSON, so no swap is needed.
        if (!layers[space.space_type] || !Number.isFinite(space.latitude) || !Number.isFinite(space.longitude)) {
            console.warn("Skipping study space with unexpected type or coordinates:", space.id);
            continue;
        }
        const marker = createSpaceMarker(space, space.id === highlightedId, onMarkerClick);
        marker.addTo(layers[space.space_type]);
        markers.set(space.id, marker);
    }
    for (const [type, layer] of Object.entries(layers)) {
        document.getElementById(`${type}-count`).textContent = `(${layer.getLayers().length})`;
    }
    return markers;
}

function createSpaceMarker(space, highlighted, onMarkerClick) {
    const size = highlighted ? 34 : 24;
    const icon = L.divIcon({
        className: `space-marker space-marker--${space.space_type}${highlighted ? " space-marker--highlight" : ""}`,
        html: SPACE_TYPES[space.space_type].letter,
        iconSize: [size, size],
        popupAnchor: [0, -size / 2],
    });
    // Draw the few libraries above the many cafés, and a highlighted result above both.
    let zIndexOffset = space.space_type === "library" ? 1000 : 0;
    if (highlighted) {
        zIndexOffset = 2000;
    }
    const marker = L.marker([space.latitude, space.longitude], {icon, title: space.name, zIndexOffset})
        .bindPopup(() => buildPopup(space), {maxWidth: 260});

    // bindPopup opens the popup on click or Enter. Replace those handlers with one that
    // asks onMarkerClick first, so the same marker can also be used to choose a location.
    const activate = () => {
        if (!onMarkerClick(marker)) {
            marker.openPopup();
        }
    };
    marker.off("click keypress");
    marker.on("click", activate);
    marker.on("keypress", (event) => {
        if (event.originalEvent.key === "Enter") {
            activate();
        }
    });
    return marker;
}

function buildPopup(space) {
    const popup = document.createElement("div");
    popup.className = "space-popup";

    appendElement(popup, "h2", space.name);
    appendElement(popup, "p", `${SPACE_TYPES[space.space_type].label} · ${space.address || "Address not recorded"}`);
    if (space.distance_m !== undefined) {
        // distance_m is calculated by PostGIS; the browser only formats it.
        appendElement(popup, "p", `Distance: ${formatDistance(space.distance_m)}`).className = "popup-distance";
    }

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

export function formatDistance(metres) {
    return metres < 1000 ? `${Math.round(metres)} m` : `${(metres / 1000).toFixed(1)} km`;
}

export function appendElement(parent, tagName, text) {
    const element = document.createElement(tagName);
    if (text !== undefined) {
        element.textContent = text;
    }
    parent.append(element);
    return element;
}
