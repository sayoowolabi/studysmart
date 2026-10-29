/*
 * Result cards in the left panel. Each card matches the numbered marker with the
 * same number. All record text is inserted with textContent, never parsed as HTML.
 */
import {FACILITY_LABELS, SPACE_TYPES, appendElement, formatDistance} from "./markers.js";

const SKELETON_CARDS = 3;

function list() {
    return document.getElementById("results-list");
}

/* Renders one card per space; onSelect(space) runs when a card is clicked. */
export function renderResults(spaces, onSelect) {
    list().replaceChildren(...spaces.map((space, index) => resultCard(space, index + 1, onSelect)));
}

export function renderLoading() {
    const placeholders = Array.from({length: SKELETON_CARDS}, () => {
        const item = document.createElement("li");
        item.className = "result-skeleton";
        item.setAttribute("aria-hidden", "true");
        return item;
    });
    list().replaceChildren(...placeholders);
}

export function clearResults() {
    list().replaceChildren();
}

/* Marks one card as selected (or none, with id null) and returns that card. */
export function markActiveResult(id) {
    let active = null;
    for (const card of list().querySelectorAll(".result-card")) {
        const isActive = card.dataset.spaceId === String(id);
        card.setAttribute("aria-current", String(isActive));
        if (isActive) {
            active = card;
        }
    }
    return active;
}

function resultCard(space, number, onSelect) {
    const item = document.createElement("li");
    const card = appendElement(item, "button");
    card.type = "button";
    card.className = "result-card";
    card.dataset.spaceId = String(space.id);
    card.setAttribute("aria-current", "false");
    card.addEventListener("click", () => onSelect(space));

    card.append(thumbnail(space.space_type));
    const body = appendElement(card, "span");
    body.className = "result-body";

    const title = appendElement(body, "span");
    title.className = "result-title";
    const badge = appendElement(title, "span", String(number));
    badge.className = "result-number";
    badge.setAttribute("aria-label", `Result ${number}:`);
    appendElement(title, "span", space.name);

    const type = SPACE_TYPES[space.space_type].label;
    appendElement(body, "span", `${type} · ${formatDistance(space.distance_m)} away`).className = "result-meta";
    body.append(facilitySummary(space));
    return item;
}

/* A category illustration (book or cup icon). There are no photos in the data. */
function thumbnail(spaceType) {
    const tile = document.createElement("span");
    tile.className = `result-thumb result-thumb--${spaceType}`;
    tile.title = `${SPACE_TYPES[spaceType].label} illustration (no photo available)`;
    tile.setAttribute("aria-hidden", "true");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "icon");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", `#icon-${spaceType}`);
    svg.append(use);
    tile.append(svg);
    return tile;
}

/*
 * Confirmed facilities as green chips, confirmed absences as grey "No …" chips.
 * Unknown values are never shown as yes or no: they are only counted.
 */
function facilitySummary(space) {
    const container = document.createElement("span");
    container.className = "facility-list";
    let unknown = 0;
    for (const [field, label] of Object.entries(FACILITY_LABELS)) {
        if (space[field] === true) {
            appendElement(container, "span", `✓ ${label}`).className = "facility facility--yes";
        } else if (space[field] === false) {
            appendElement(container, "span", `No ${sentenceCase(label)}`).className = "facility";
        } else {
            unknown += 1;
        }
    }
    const total = Object.keys(FACILITY_LABELS).length;
    if (unknown === total) {
        appendElement(container, "span", "Facilities not recorded").className = "facility facility--unknown";
    } else if (unknown > 0) {
        appendElement(container, "span", `${unknown} not recorded`).className = "facility facility--unknown";
    }
    return container;
}

/* "Indoor seating" -> "indoor seating", but names with inner capitals ("Wi-Fi") stay as they are. */
function sentenceCase(label) {
    const rest = label.slice(1);
    return rest === rest.toLowerCase() ? label.charAt(0).toLowerCase() + rest : label;
}
