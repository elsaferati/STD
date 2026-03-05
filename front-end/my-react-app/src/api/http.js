const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/+$/, "");
const pendingGetJsonRequests = new Map();

function buildUrl(path) {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  return `${API_BASE_URL}${path}`;
}

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message || "Request failed");
    this.name = "ApiError";
    this.status = status;
    this.code = code || "request_failed";
  }
}

function toApiError(response, payload) {
  if (payload && typeof payload === "object" && payload.error) {
    return new ApiError(response.status, payload.error.code, payload.error.message);
  }
  return new ApiError(response.status, "request_failed", response.statusText || "Request failed");
}

async function parsePayload(response) {
  if (response.status === 204) {
    return null;
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json().catch(() => null);
  }

  return response.text().catch(() => null);
}

export async function fetchJson(path, options = {}) {
  const {
    method = "GET",
    body,
    headers = {},
    signal,
  } = options;

  const requestHeaders = new Headers(headers);
  if (body !== undefined) {
    requestHeaders.set("Content-Type", "application/json");
  }

  const normalizedMethod = String(method || "GET").toUpperCase();
  const requestUrl = buildUrl(path);
  const dedupeKey =
    normalizedMethod === "GET" && body === undefined && !signal
      ? requestUrl
      : null;

  if (dedupeKey && pendingGetJsonRequests.has(dedupeKey)) {
    return pendingGetJsonRequests.get(dedupeKey);
  }

  const requestPromise = (async () => {
    const response = await fetch(requestUrl, {
      method: normalizedMethod,
      headers: requestHeaders,
      credentials: "include",
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });

    const payload = await parsePayload(response);
    if (!response.ok) {
      throw toApiError(response, payload);
    }

    if (payload && typeof payload === "string") {
      return null;
    }
    return payload;
  })();

  if (dedupeKey) {
    pendingGetJsonRequests.set(dedupeKey, requestPromise);
  }

  try {
    return await requestPromise;
  } finally {
    if (dedupeKey) {
      pendingGetJsonRequests.delete(dedupeKey);
    }
  }
}

export async function fetchBlob(path, options = {}) {
  const {
    method = "GET",
    headers = {},
    signal,
  } = options;

  const requestHeaders = new Headers(headers);

  const response = await fetch(buildUrl(path), {
    method,
    headers: requestHeaders,
    credentials: "include",
    signal,
  });

  if (!response.ok) {
    const payload = await parsePayload(response);
    throw toApiError(response, payload);
  }

  return response.blob();
}

export function withQuery(path, params) {
  const searchParams = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value === null || value === undefined || value === "") {
      return;
    }
    searchParams.set(key, String(value));
  });

  const query = searchParams.toString();
  if (!query) {
    return path;
  }
  return `${path}?${query}`;
}
