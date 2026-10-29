/* Administrative areas: the optional boundary overlay and the per-area count table. */
import {fetchJson} from "./api.js";
import {appendElement} from "./markers.js";
import {showWarning} from "./status.js";

export async function loadAreaBoundaries(map, url) {
    let collection;
    try {
        collection = await fetchJson(url);
    } catch (error) {
        console.error(error);
        showWarning("Area boundaries could not be loaded; study spaces are unaffected.");
        return;
    }
    if (collection.features.length === 0) {
        return; // No areas imported: there is simply no overlay to offer.
    }

    // L.geoJSON reads GeoJSON's [longitude, latitude] order itself.
    const boundaries = L.geoJSON(collection, {
        attribution: 'Boundaries: <a href="https://data.smartdublin.ie/dataset/administrative-areas-dcc">Dublin City Council</a> (CC BY)',
        style: {color: "#7a6a8f", weight: 2, dashArray: "6 4", fill: false},
        onEachFeature: (feature, layer) => {
            const name = document.createElement("span");
            name.textContent = feature.properties.name;
            layer.bindTooltip(name, {sticky: true});
        },
    });
    // Off by default; the layer control in the top-right corner toggles it.
    L.control.layers(null, {"Area boundaries": boundaries}).addTo(map);
}

/* Fills the sidebar table from /api/areas/coverage/, where PostGIS does the counting. */
export async function loadAreaStatistics(url) {
    const status = document.getElementById("area-status");
    const table = document.getElementById("area-table");
    let areas;
    try {
        areas = await fetchJson(url);
    } catch (error) {
        console.error(error);
        status.textContent = "Area statistics could not be loaded.";
        return;
    }
    if (areas.length === 0) {
        status.textContent = "No administrative areas have been imported.";
        return;
    }

    const body = table.querySelector("tbody");
    for (const area of areas) {
        const row = appendElement(body, "tr");
        appendElement(row, "th", area.name).scope = "row";
        for (const count of [area.library_count, area.cafe_count, area.total_count]) {
            appendElement(row, "td", String(count)).className = "text-end";
        }
    }
    status.remove();
    table.hidden = false;
}
