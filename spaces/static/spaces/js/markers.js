/*
 * Study-space markers and popups. All record text is inserted with textContent,
 * never parsed as HTML, so names or addresses cannot inject markup into the page.
 */

export const SPACE_TYPES = {
    library: {label: "Library", letter: "L"},
    cafe: {label: "Café", letter: "C"},
};

export const FACILITY_LABELS = {
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
 * numbered: label markers 1, 2, 3… in list order (search results) instead of L/C.
 * onMarkerClick(marker, space) runs first on every marker click; if it returns true
 * the click has been used (for example to pick a starting point) and no popup opens.
 */
export function showSpaces(layers, spaces, {numbered = false, onMarkerClick = () => false} = {}) {
    for (const layer of Object.values(layers)) {
        layer.clearLayers();
    }
    const markers = new Map();
    spaces.forEach((space, index) => {
        // The API returns plain latitude/longitude numbers, not GeoJSON, so no swap is needed.
        if (!layers[space.space_type] || !Number.isFinite(space.latitude) || !Number.isFinite(space.longitude)) {
            console.warn("Skipping study space with unexpected type or coordinates:", space.id);
            return;
        }
        const label = numbered ? String(index + 1) : SPACE_TYPES[space.space_type].letter;
        const rank = numbered ? index : null;
        const marker = createSpaceMarker(space, label, rank, onMarkerClick);
        marker.addTo(layers[space.space_type]);
        markers.set(space.id, marker);
    });
    for (const [type, layer] of Object.entries(layers)) {
        document.getElementById(`${type}-count`).textContent = `(${layer.getLayers().length})`;
    }
    return markers;
}

/* Switches a marker between its normal and highlighted (selected result) appearance. */
export function setMarkerHighlight(marker, highlighted) {
    const {space, label, rank} = marker.options;
    marker.setIcon(markerIcon(space, label, highlighted));
    marker.setZIndexOffset(stackingOffset(space, rank, highlighted));
}

function markerIcon(space, label, highlighted) {
    const size = highlighted ? 34 : 24;
    return L.divIcon({
        className: `space-marker space-marker--${space.space_type}${highlighted ? " space-marker--highlight" : ""}`,
        html: label, // Only a type letter or a result number, never record text.
        iconSize: [size, size],
        popupAnchor: [0, -size / 2],
    });
}

/*
 * Which marker is drawn on top where markers overlap: a highlighted result first; then,
 * among numbered results, the nearer one (lower number); otherwise libraries above the
 * many cafés. Leaflet adds this offset to each marker's screen position.
 */
function stackingOffset(space, rank, highlighted) {
    if (highlighted) {
        return 3000;
    }
    if (rank !== null) {
        return 2000 - rank * 50;
    }
    return space.space_type === "library" ? 1000 : 0;
}

function createSpaceMarker(space, label, rank, onMarkerClick) {
    const marker = L.marker([space.latitude, space.longitude], {
        icon: markerIcon(space, label, false),
        title: space.name,
        zIndexOffset: stackingOffset(space, rank, false),
        space,
        label,
        rank,
    }).bindPopup(() => buildPopup(space), {maxWidth: 260});

    // bindPopup opens the popup on click or Enter. Replace those handlers with one that
    // asks onMarkerClick first, so the same marker can also be used to pick a location.
    const activate = () => {
        if (!onMarkerClick(marker, space)) {
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
