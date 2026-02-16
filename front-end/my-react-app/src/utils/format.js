const dateTimeFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

const dateFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
});

export function formatDateTime(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return dateTimeFormatter.format(date);
}

export function formatDate(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return dateFormatter.format(date);
}

export function formatPercent(value) {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric)) {
    return "0.0%";
  }
  return `${numeric.toFixed(1)}%`;
}

export function statusLabel(status) {
  const normalized = (status || "unknown").toLowerCase();
  if (normalized === "ok") {
    return "OK";
  }
  if (normalized === "partial") {
    return "Partial";
  }
  if (normalized === "failed") {
    return "Failed";
  }
  return "Unknown";
}

export function fieldLabel(field) {
  return String(field || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function entryValue(entry) {
  if (entry && typeof entry === "object" && "value" in entry) {
    const value = entry.value;
    if (value === null || value === undefined) {
      return "";
    }
    return String(value);
  }
  if (entry === null || entry === undefined) {
    return "";
  }
  return String(entry);
}

export function entrySource(entry) {
  if (entry && typeof entry === "object" && "source" in entry) {
    return String(entry.source || "-");
  }
  return "-";
}

export function entryConfidence(entry) {
  if (!entry || typeof entry !== "object") {
    return null;
  }
  const confidence = Number(entry.confidence);
  if (!Number.isFinite(confidence)) {
    return null;
  }
  return confidence;
}

export function formatConfidence(confidence) {
  if (confidence === null || confidence === undefined) {
    return "-";
  }
  const normalized = confidence <= 1 ? confidence * 100 : confidence;
  return `${normalized.toFixed(1)}%`;
}
