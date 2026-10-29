// Browser tests for the StudySmart map page.
//
// Drives a headless Chromium-based browser (Chrome, Chromium or Edge) through the
// Chrome DevTools Protocol using Node's built-in WebSocket, so no npm packages are
// needed. Expected values are read from the running API, so the checks follow the
// imported data rather than hard-coded counts.
//
// Requirements: Node 22+, Chrome/Chromium/Edge, and StudySmart running with the
// source snapshots imported (see README). Run from the repository root:
//   node frontend-tests/map-ui.test.mjs
//
// Optional environment variables:
//   STUDYSMART_URL   app address (default http://localhost:8000)
//   BROWSER          path to the browser executable (default: found automatically)
//   BLOCK_MAP_TILES  "1" to block OpenStreetMap tile downloads (used in CI)
//   SCREENSHOT_DIR   folder for desktop/tablet/phone screenshots
import {spawn} from "node:child_process";
import {existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";

const BASE = (process.env.STUDYSMART_URL || "http://localhost:8000").replace(/\/$/, "");
const SCREENSHOT_DIR = process.env.SCREENSHOT_DIR || "";
const TCD = {lat: 53.34371, lng: -6.25443};
const UCD = {lat: 53.30685, lng: -6.22463};
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

if (typeof WebSocket === "undefined") {
    console.error("Node 22 or later is required (it provides the built-in WebSocket).");
    process.exit(2);
}

/* ---------- Browser and DevTools connection ---------- */

function findBrowser() {
    if (process.env.BROWSER) {
        return process.env.BROWSER;
    }
    const candidates = [
        "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
        "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
        "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
        "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ];
    const found = candidates.find((path) => existsSync(path));
    if (!found) {
        throw new Error("No Chrome, Chromium or Edge found; set BROWSER to its path.");
    }
    return found;
}

const profileDir = mkdtempSync(join(tmpdir(), "studysmart-browser-test-"));
const browserArgs = [
    "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
    "--remote-debugging-port=0", `--user-data-dir=${profileDir}`, "--window-size=1366,900", "about:blank",
];
if (process.platform === "linux" && process.env.CI) {
    // GitHub's Ubuntu runners restrict the user namespaces Chrome's sandbox needs.
    browserArgs.unshift("--no-sandbox");
}
const browser = spawn(findBrowser(), browserArgs, {stdio: "ignore"});

let socket;
let nextId = 0;
const pending = new Map();
const consoleErrors = [];

function send(method, params = {}) {
    return new Promise((resolve, reject) => {
        const id = ++nextId;
        pending.set(id, {resolve, reject});
        socket.send(JSON.stringify({id, method, params}));
    });
}

async function connect() {
    // With port 0 the browser picks a free port and writes it to DevToolsActivePort.
    const portFile = join(profileDir, "DevToolsActivePort");
    for (let attempt = 0; attempt < 100 && !existsSync(portFile); attempt++) {
        await sleep(100);
    }
    const port = readFileSync(portFile, "utf8").split("\n")[0].trim();
    let page;
    for (let attempt = 0; attempt < 50 && !page; attempt++) {
        try {
            page = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find((target) => target.type === "page");
        } catch { /* not ready yet */ }
        if (!page) await sleep(100);
    }
    socket = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
        socket.addEventListener("open", resolve);
        socket.addEventListener("error", reject);
    });
    socket.addEventListener("message", (event) => {
        const message = JSON.parse(event.data);
        if (message.id && pending.has(message.id)) {
            const {resolve, reject} = pending.get(message.id);
            pending.delete(message.id);
            message.error ? reject(new Error(message.error.message)) : resolve(message.result);
        } else if (message.method === "Runtime.exceptionThrown") {
            const details = message.params.exceptionDetails;
            consoleErrors.push(details.exception?.description || details.text);
        } else if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") {
            consoleErrors.push(message.params.args.map((arg) => arg.value ?? arg.description).join(" ").slice(0, 200));
        } else if (message.method === "Fetch.requestPaused") {
            // Used by the API-failure check: answer intercepted requests with HTTP 500.
            send("Fetch.fulfillRequest", {requestId: message.params.requestId, responseCode: 500, body: btoa("{}")});
        }
    });
}

async function shutDown() {
    const exited = new Promise((resolve) => browser.once("exit", resolve));
    try {
        await Promise.race([send("Browser.close"), sleep(3000)]);
    } catch { /* already closed */ }
    socket?.close();
    await Promise.race([exited, sleep(5000)]);
    browser.kill();
    try {
        // The browser may still be releasing files (notably on Windows); cleanup must not fail the tests.
        rmSync(profileDir, {recursive: true, force: true, maxRetries: 10, retryDelay: 200});
    } catch (error) {
        console.warn(`Could not remove the temporary browser profile ${profileDir}: ${error.code}`);
    }
}

/* ---------- Page helpers ---------- */

async function evaluate(expression) {
    const result = await send("Runtime.evaluate", {expression, awaitPromise: true, returnByValue: true});
    if (result.exceptionDetails) {
        throw new Error(JSON.stringify(result.exceptionDetails).slice(0, 400));
    }
    return result.result.value;
}

async function waitFor(expression, timeout = 15000) {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
        try {
            if (await evaluate(expression)) return true;
        } catch { /* page still loading */ }
        await sleep(100);
    }
    return false;
}

const api = async (path) => (await fetch(BASE + path)).json();
const text = (id) => evaluate(`document.getElementById("${id}").textContent.trim()`);
const summary = () => text("results-summary");
const summaryStartsWith = (start) => `document.getElementById("results-summary").textContent.trim().startsWith(${JSON.stringify(start)})`;
const summaryIncludes = (part) => `document.getElementById("results-summary").textContent.includes(${JSON.stringify(part)})`;
const searchDone = `!document.getElementById("results-summary").textContent.includes("…")`;
const click = (id) => evaluate(`document.getElementById("${id}").click()`);
const setChecked = (id, checked) => evaluate(`(() => {
    const input = document.getElementById("${id}");
    input.checked = ${checked};
    input.dispatchEvent(new Event("change", {bubbles: true}));
})()`);
const chooseCampus = (slug) => evaluate(`(() => {
    const select = document.getElementById("campus-select");
    select.value = "${slug}";
    select.dispatchEvent(new Event("change", {bubbles: true}));
})()`);
const cards = () => evaluate(`[...document.querySelectorAll(".result-card")].map((card) => ({
    id: Number(card.dataset.spaceId),
    number: card.querySelector(".result-number").textContent,
    name: card.querySelector(".result-title span:last-child").textContent,
    active: card.getAttribute("aria-current") === "true",
    yes: card.querySelectorAll(".facility--yes").length,
    no: card.querySelectorAll(".facility:not(.facility--yes):not(.facility--unknown)").length,
    unknownText: card.querySelector(".facility--unknown")?.textContent ?? "",
}))`);
const markers = () => evaluate(`[...document.querySelectorAll(".leaflet-marker-pane .space-marker")].map((marker) => ({
    label: marker.textContent, title: marker.title, highlighted: marker.classList.contains("space-marker--highlight"),
}))`);
const markerCentre = (label) => evaluate(`(() => {
    const marker = [...document.querySelectorAll(".leaflet-marker-pane .space-marker")].find((m) => m.textContent === "${label}");
    if (!marker) return null;
    const box = marker.getBoundingClientRect();
    return {x: box.left + box.width / 2, y: box.top + box.height / 2};
})()`);
// A point on the map with no marker or control on it (tiles may be blocked, so accept the map itself).
const emptyMapPoint = () => evaluate(`(() => {
    const box = document.getElementById("map").getBoundingClientRect();
    const cx = box.left + box.width / 2, cy = box.top + box.height / 2;
    for (let d = 0; d < 300; d += 4) {
        for (const [ox, oy] of [[d, 0], [-d, 0], [0, d], [0, -d], [d, d], [-d, -d]]) {
            const element = document.elementFromPoint(cx + ox, cy + oy);
            if (element && (element.classList.contains("leaflet-tile") || element.id === "map")) {
                return {x: cx + ox, y: cy + oy};
            }
        }
    }
    return {x: cx, y: cy};
})()`);

async function clickAt({x, y}) {
    for (const type of ["mousePressed", "mouseReleased"]) {
        await send("Input.dispatchMouseEvent", {type, x, y, button: "left", clickCount: 1});
    }
}

async function screenshot(name) {
    if (!SCREENSHOT_DIR) return;
    mkdirSync(SCREENSHOT_DIR, {recursive: true});
    const shot = await send("Page.captureScreenshot", {format: "png"});
    writeFileSync(join(SCREENSHOT_DIR, `${name}.png`), Buffer.from(shot.data, "base64"));
}

function facilityCounts(space) {
    const fields = ["indoor_seating", "outdoor_seating", "has_wifi", "has_outlets", "laptop_allowed"];
    return {
        yes: fields.filter((field) => space[field] === true).length,
        no: fields.filter((field) => space[field] === false).length,
        unknown: fields.filter((field) => space[field] === null).length,
    };
}

/* ---------- Checks ---------- */

let failures = 0;
function check(name, ok, detail = "") {
    if (!ok) failures += 1;
    console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
}

async function run() {
    await connect();
    await send("Page.enable");
    await send("Runtime.enable");
    if (process.env.BLOCK_MAP_TILES === "1") {
        // Avoids load on OpenStreetMap's volunteer-run tile servers; the checks do not need tiles.
        await send("Network.enable");
        await send("Network.setBlockedURLs", {urls: ["*tile.openstreetmap.org*"]});
    }
    await send("Emulation.setDeviceMetricsOverride", {width: 1366, height: 900, deviceScaleFactor: 1, mobile: false});
    await send("Page.navigate", {url: `${BASE}/`});

    // Before a starting point: every matching space, no result cards.
    await waitFor(summaryIncludes("match your filters"));
    const all = await api("/api/spaces/");
    check("all-spaces view before a starting point", (await markers()).length === all.length && (await cards()).length === 0,
        `${(await markers()).length} markers, API ${all.length}`);

    await evaluate("document.fonts.ready.then(() => true)");
    check("self-hosted Nunito font loaded", await evaluate(`document.fonts.check('16px "Nunito"')
        && getComputedStyle(document.body).fontFamily.split(",")[0].replaceAll('"', "").trim() === "Nunito"`));
    check("one h1 and one polite live region", await evaluate(`document.querySelectorAll("h1").length === 1
        && document.querySelectorAll('[aria-live="polite"]').length === 1`));

    // A campus starting point runs the search automatically.
    await chooseCampus("tcd");
    await waitFor(summaryStartsWith("Showing"));
    const nearbyTcd = await api(`/api/spaces/nearby/?lat=${TCD.lat}&lng=${TCD.lng}&radius=1000`);
    const tcdCards = await cards();
    check("summary shows top 10 of the API total", (await summary()).startsWith(`Showing 10 of ${nearbyTcd.length} nearby study spaces`), await summary());
    check("10 cards in API distance order", tcdCards.length === 10
        && tcdCards.every((card, i) => card.id === nearbyTcd[i].id && card.number === String(i + 1)));
    const resultMarkers = await markers();
    check("10 numbered markers match the cards", resultMarkers.length === 10
        && tcdCards.every((card) => resultMarkers.some((m) => m.label === card.number && m.title === card.name)));
    check("starting point text and pin", (await text("location-text")).includes("Trinity College Dublin")
        && await evaluate(`!!document.querySelector('.leaflet-marker-icon[title^="Starting point"]')`));

    // Facility summaries: confirmed, confirmed absent and unknown, exactly as in the API.
    check("card facility chips match true/false/unknown in the API", tcdCards.every((card, i) => {
        const expected = facilityCounts(nearbyTcd[i]);
        const unknownText = expected.unknown === 5 ? "Facilities not recorded"
            : expected.unknown === 0 ? "" : `${expected.unknown} not recorded`;
        return card.yes === expected.yes && card.no === expected.no && card.unknownText === unknownText;
    }));

    // Card click highlights the card and marker and opens the popup.
    await evaluate(`document.querySelectorAll(".result-card")[2].click()`);
    await sleep(600);
    check("card click highlights its card and marker and opens the popup", (await cards())[2].active
        && (await markers()).filter((m) => m.highlighted).map((m) => m.label).join() === "3"
        && await evaluate(`document.querySelector(".leaflet-popup h2")?.textContent`) === tcdCards[2].name);

    // Overlapping result markers stack nearest on top; a marker click highlights its card.
    await evaluate(`document.querySelector(".leaflet-popup-close-button")?.click()`);
    await waitFor(`!document.querySelector(".leaflet-popup")`, 3000); // Leaflet fades popups out.
    const stacking = await evaluate(`(() => {
        const icons = [...document.querySelectorAll(".leaflet-marker-pane .space-marker:not(.space-marker--highlight)")];
        let wrong = 0;
        for (const a of icons) for (const b of icons) {
            const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
            const overlap = Math.abs(ra.left - rb.left) < 20 && Math.abs(ra.top - rb.top) < 20;
            if (a !== b && overlap && Number(a.textContent) < Number(b.textContent)
                && Number(a.style.zIndex) <= Number(b.style.zIndex)) wrong += 1;
        }
        return wrong;
    })()`);
    check("overlapping result markers stack nearest on top", stacking === 0);
    const marker5 = await markerCentre("5");
    const onTop = await evaluate(`document.elementFromPoint(${marker5.x}, ${marker5.y})?.textContent`);
    await clickAt(marker5);
    await sleep(500);
    const afterMarkerClick = await cards();
    check("marker click highlights only its card and marker", onTop === "5" && afterMarkerClick[4].active
        && afterMarkerClick.filter((card) => card.active).length === 1
        && (await markers()).filter((m) => m.highlighted).map((m) => m.label).join() === "5");

    // Filters re-run the search; reset restores the page defaults.
    await setChecked("facility-indoor_seating", true);
    await waitFor(searchDone);
    await sleep(300);
    const seatedApi = await api(`/api/spaces/nearby/?lat=${TCD.lat}&lng=${TCD.lng}&radius=1000&indoor_seating=true`);
    const seatedCards = await cards();
    check("facility filter re-runs the search and matches the API", seatedCards.length === Math.min(10, seatedApi.length)
        && seatedCards.every((card, i) => card.id === seatedApi[i].id));
    await setChecked("radius-5000", true);
    await waitFor(summaryIncludes("within 5.0 km"));
    await click("reset-filters");
    await waitFor(summaryStartsWith(`Showing 10 of ${nearbyTcd.length}`));
    check("reset restores 1 km, both types and no facilities", await evaluate(`document.getElementById("radius-1000").checked
        && !document.querySelector('input[name="facility"]:checked')`) && await text("filter-summary") === "1.0 km · All types");

    // UCD: coverage note, empty state, nearest fallback and a wider radius.
    await chooseCampus("ucd-belfield");
    await waitFor(summaryStartsWith("No study spaces"));
    check("UCD shows its coverage note and an empty state with actions", await evaluate(`!document.getElementById("campus-note").hidden
        && !document.getElementById("results-actions").hidden`) && (await cards()).length === 0, await summary());
    await click("show-nearest");
    await waitFor(summaryIncludes("nearest match is"));
    const nearestUcd = await api(`/api/spaces/nearest/?lat=${UCD.lat}&lng=${UCD.lng}`);
    const nearestCards = await cards();
    check("show nearest match uses the nearest API", nearestCards.length === 1 && nearestCards[0].id === nearestUcd.id);
    await click("widen-radius");
    await waitFor(summaryStartsWith("Showing"));
    const ucd2km = await api(`/api/spaces/nearby/?lat=${UCD.lat}&lng=${UCD.lng}&radius=2000`);
    check("wider area moves to 2 km and matches the API", await evaluate(`document.getElementById("radius-2000").checked`)
        && (await cards()).length === Math.min(10, ucd2km.length));

    await setChecked("type-library", false);
    await setChecked("type-cafe", false);
    await sleep(500);
    check("no type selected shows a message and no markers", (await summary()).startsWith("Select at least one type")
        && (await markers()).length === 0);
    await click("reset-filters");
    await waitFor(searchDone);

    // Geolocation: granted, denied and unavailable.
    await send("Browser.grantPermissions", {permissions: ["geolocation"], origin: BASE});
    await send("Emulation.setGeolocationOverride", {latitude: TCD.lat, longitude: TCD.lng, accuracy: 25});
    await click("locate-button");
    await waitFor(`document.getElementById("location-text").textContent.includes("your location")`);
    await waitFor(summaryStartsWith("Showing"));
    check("use my location searches from that point", (await text("location-text")).includes("within about 25 m")
        && (await summary()).startsWith(`Showing 10 of ${nearbyTcd.length}`));
    await send("Browser.setPermission", {permission: {name: "geolocation"}, setting: "denied", origin: BASE});
    await click("locate-button");
    await waitFor(`!document.getElementById("location-error").hidden`, 5000);
    check("denied geolocation shows a helpful message", (await text("location-error")).startsWith("Location access was denied"));
    await send("Browser.setPermission", {permission: {name: "geolocation"}, setting: "granted", origin: BASE});
    await send("Emulation.setGeolocationOverride", {}); // No position: "unavailable".
    await click("locate-button");
    await waitFor(`document.getElementById("location-error").textContent.startsWith("Your location could not be found")`, 12000);
    check("unavailable geolocation shows a helpful message", (await text("location-error")).startsWith("Your location could not be found")
        && await evaluate(`!document.getElementById("locate-button").disabled`));

    // Pick on map: a map point, then a marker (which sets that space as the start, without a popup).
    await chooseCampus("tcd");
    await waitFor(summaryStartsWith("Showing"));
    await click("choose-location");
    check("pick-on-map mode is visible", await evaluate(`document.getElementById("map").classList.contains("map--choosing")
        && !document.getElementById("choose-banner").hidden`));
    await clickAt(await emptyMapPoint());
    await waitFor(`document.getElementById("location-text").textContent.includes("map point")`, 5000);
    await waitFor(searchDone);
    check("map click sets a map-point start and ends the mode", (await text("location-text")).includes("map point")
        && !await evaluate(`document.getElementById("map").classList.contains("map--choosing")`));
    await click("choose-location");
    const firstCard = (await cards())[0];
    await clickAt(await markerCentre("1"));
    await waitFor(`document.getElementById("location-text").textContent.includes(${JSON.stringify(firstCard.name)})`, 5000);
    await waitFor(searchDone);
    check("marker click in pick mode starts from that study space", (await text("location-text")).includes(firstCard.name)
        && !await evaluate(`!!document.querySelector(".leaflet-popup")`));

    // Rapid changes: superseded requests are cancelled and the last campus wins.
    for (const slug of ["dcu-glasnevin", "ncad", "rcsi", "griffith", "tcd"]) {
        await chooseCampus(slug);
    }
    await waitFor(summaryStartsWith(`Showing 10 of ${nearbyTcd.length}`));
    check("rapid campus changes end on the last campus", (await cards())[0].id === nearbyTcd[0].id);

    // API failure and recovery (console errors logged during the deliberate failure are expected).
    const errorsBeforeFailure = consoleErrors.length;
    await send("Fetch.enable", {patterns: [{urlPattern: "*/api/spaces/nearby/*"}]});
    await chooseCampus("ncad");
    await waitFor(summaryStartsWith("Study spaces could not be loaded"));
    check("API failure shows an error", (await summary()).startsWith("Study spaces could not be loaded")
        && await evaluate(`!!document.querySelector("#map-messages .alert-danger")`));
    await send("Fetch.disable");
    await chooseCampus("tcd");
    await waitFor(summaryStartsWith("Showing"));
    consoleErrors.splice(errorsBeforeFailure);
    check("search recovers and clears the error", !await evaluate(`!!document.querySelector("#map-messages .alert-danger")`));

    await click("clear-location");
    await waitFor(summaryIncludes("match your filters"));
    check("clear returns to all spaces", (await markers()).length === all.length && (await cards()).length === 0);

    // Responsive layouts.
    for (const [name, width, height, mobile] of [["desktop", 1366, 900, false], ["tablet", 768, 1024, true], ["phone", 390, 844, true]]) {
        await send("Emulation.setDeviceMetricsOverride", {width, height, deviceScaleFactor: 1, mobile});
        await send("Page.reload");
        await waitFor(`document.getElementById("results-summary")?.textContent.includes("match your filters")`);
        check(`${name}: filters ${mobile ? "collapsed" : "open"} on load`, await evaluate(`document.getElementById("filters-details").open`) === !mobile);
        await chooseCampus("tcd");
        await waitFor(summaryStartsWith("Showing"));
        await sleep(800);
        const noSidewaysScroll = await evaluate("document.documentElement.scrollWidth <= innerWidth");
        if (!mobile) {
            const left = await evaluate(`["panel-controls", "map-wrapper"].map((c) => document.querySelector("." + c).getBoundingClientRect().left)`);
            check("desktop: panel left of the map, no sideways scrolling", left[0] < left[1] && noSidewaysScroll);
        } else {
            const tops = await evaluate(`["panel-controls", "map-wrapper", "panel-results"].map((c) => document.querySelector("." + c).getBoundingClientRect().top + scrollY)`);
            check(`${name}: controls, map, then results; no sideways scrolling`, tops[0] < tops[1] && tops[1] < tops[2] && noSidewaysScroll);
            const mapTop = await evaluate(`document.getElementById("map").getBoundingClientRect().top`);
            check(`${name}: map starts within the first screen`, mapTop < height * 0.6, `map top ${Math.round(mapTop)}px`);
            // Jump (not smooth-scroll) to the results, so only the page's own scrolling is measured.
            await evaluate(`scrollTo({top: document.querySelector(".panel-results").offsetTop, behavior: "instant"})`);
            await evaluate(`document.querySelectorAll(".result-card")[1].click()`);
            await sleep(1500); // The page uses smooth scrolling.
            check(`${name}: card click scrolls the map into view`, await evaluate(`(() => {
                const box = document.getElementById("map").getBoundingClientRect();
                return box.top >= -1 && box.bottom <= innerHeight + 1;
            })()`));
            await evaluate(`scrollTo({top: 0, behavior: "instant"})`);
        }
        await screenshot(name);
    }

    check("no JavaScript errors outside the deliberate API failure", consoleErrors.length === 0, consoleErrors.join(" | ").slice(0, 300));
}

try {
    await run();
} catch (error) {
    failures += 1;
    console.log(`ERROR  ${error.stack}`);
} finally {
    await shutDown();
}
console.log(failures === 0 ? "All browser checks passed." : `${failures} browser check(s) failed.`);
process.exit(failures === 0 ? 0 : 1);
