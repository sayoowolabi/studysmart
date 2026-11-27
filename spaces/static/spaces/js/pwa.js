/*
 * Registers the service worker (spaces/templates/spaces/sw.js) that lets StudySmart
 * open offline. Every page loads this file. Browsers only allow service workers on
 * HTTPS or on localhost. Anywhere else the site still works as a normal web page.
 */
const serviceWorkerUrl = document.body.dataset.swUrl;

if ("serviceWorker" in navigator && serviceWorkerUrl) {
    // After the page has loaded, so caching the app shell never slows the first visit.
    window.addEventListener("load", () => {
        navigator.serviceWorker.register(serviceWorkerUrl).catch((error) => {
            console.warn("The service worker could not be registered; offline use is unavailable.", error);
        });
    });
}
