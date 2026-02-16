const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/+$/, "");

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
    token,
    body,
    headers = {},
    signal,
  } = options;

  const requestHeaders = new Headers(headers);
  if (token) {
    requestHeaders.set("Authorization", `Bearer ${token}`);
  }
  if (body !== undefined) {
    requestHeaders.set("Content-Type", "application/json");
  }

  const response = await fetch(buildUrl(path), {
    method,
    headers: requestHeaders,
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
}

export async function fetchBlob(path, options = {}) {
  const {
    method = "GET",
    token,
    headers = {},
    signal,
  } = options;

  const requestHeaders = new Headers(headers);
  if (token) {
    requestHeaders.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(buildUrl(path), {
    method,
    headers: requestHeaders,
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
