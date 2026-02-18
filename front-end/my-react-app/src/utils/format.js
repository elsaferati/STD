const dateTimeFormatters = new Map();
const dateFormatters = new Map();

function getDateTimeFormatter(locale) {
  if (!dateTimeFormatters.has(locale)) {
    dateTimeFormatters.set(
      locale,
      new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }),
    );
  }
  return dateTimeFormatters.get(locale);
}

function getDateFormatter(locale) {
  if (!dateFormatters.has(locale)) {
    dateFormatters.set(locale, new Intl.DateTimeFormat(locale, { dateStyle: "medium" }));
  }
  return dateFormatters.get(locale);
}

function normalizeLocale(localeOrLang) {
  if (!localeOrLang) {
    return undefined;
  }
  if (localeOrLang === "en") {
    return "en-US";
  }
  if (localeOrLang === "de") {
    return "de-DE";
  }
  return localeOrLang;
}

export function formatDateTime(value, localeOrLang) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  const locale = normalizeLocale(localeOrLang);
  return getDateTimeFormatter(locale).format(date);
}

export function formatDate(value, localeOrLang) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  const locale = normalizeLocale(localeOrLang);
  return getDateFormatter(locale).format(date);
}

export function formatPercent(value) {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric)) {
    return "0.0%";
  }
  return `${numeric.toFixed(1)}%`;
}

export function statusLabel(status, t) {
  const normalized = (status || "unknown").toLowerCase();
  if (typeof t === "function") {
    return t(`status.${normalized}`, null, normalized);
  }
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

export function fieldLabel(field, t) {
  const fallback = String(field || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
  if (typeof t === "function") {
    return t(`fields.${field}`, null, fallback);
  }
  return fallback;
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
