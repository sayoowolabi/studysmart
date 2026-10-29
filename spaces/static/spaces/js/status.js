/*
 * Messages shown over the map. The current search has one status alert, replaced on
 * every search; separate warnings (such as a failed boundary request) stay visible.
 */

let searchStatus = null;

function messageArea() {
    return document.getElementById("map-messages");
}

export function setStatus(text, variant) {
    if (!searchStatus) {
        searchStatus = document.createElement("div");
        messageArea().append(searchStatus);
    }
    searchStatus.className = `alert alert-${variant}`;
    searchStatus.textContent = text;
}

export function clearStatus() {
    searchStatus?.remove();
    searchStatus = null;
}

export function showWarning(text, variant = "warning") {
    const alert = document.createElement("div");
    alert.className = `alert alert-${variant}`;
    alert.setAttribute("role", "alert"); // Announced once; the message area itself is not a live region.
    alert.textContent = text;
    messageArea().append(alert);
}
