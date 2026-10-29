/* Requests to the StudySmart REST API. */

export class ApiError extends Error {
    constructor(url, status) {
        super(`${url} returned HTTP ${status}`);
        this.status = status;
    }
}

export async function fetchJson(url, signal) {
    const response = await fetch(url, {headers: {Accept: "application/json"}, signal});
    if (!response.ok) {
        throw new ApiError(url, response.status);
    }
    return response.json();
}

export function isAbortError(error) {
    return error.name === "AbortError";
}
