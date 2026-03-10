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
  const raw = (status || "ok").toLowerCase();
  const normalized = raw === "partial" ? "reply" : raw === "unknown" ? "ok" : raw;
  if (typeof t === "function") {
    if (normalized === "reply") return t("status.reply", null, "Reply");
    if (normalized === "human_in_the_loop") return t("status.human_in_the_loop", null, "Human in the Loop");
    if (normalized === "post") return t("status.post", null, "Post");
    if (normalized === "ok") return t("status.ok", null, "OK");
    if (normalized === "failed") return t("status.failed", null, "Failed");
    if (normalized === "waiting_for_reply") return t("status.waiting_for_reply", null, "Waiting for Reply");
    if (normalized === "client_replied") return t("status.client_replied", null, "Client Replied");
    if (normalized === "updated_after_reply") return t("status.updated_after_reply", null, "Updated After Reply");
    return t(`status.${normalized}`, null, normalized);
  }
  if (normalized === "ok") return "OK";
  if (normalized === "reply") return "Reply";
  if (normalized === "human_in_the_loop") return "Human in the Loop";
  if (normalized === "post") return "Post";
  if (normalized === "failed") return "Failed";
  if (normalized === "waiting_for_reply") return "Waiting for Reply";
  if (normalized === "client_replied") return "Client Replied";
  if (normalized === "updated_after_reply") return "Updated After Reply";
  return normalized;
}

export function validationStatusLabel(status, t) {
  const normalized = String(status || "not_run").toLowerCase();
  if (typeof t === "function") {
    if (normalized === "not_run") return t("validation.not_run", null, "Not Run");
    if (normalized === "passed") return t("validation.passed", null, "Passed");
    if (normalized === "flagged") return t("validation.flagged", null, "Flagged");
    if (normalized === "stale") return t("validation.stale", null, "Stale");
    if (normalized === "skipped") return t("validation.skipped", null, "Skipped");
    if (normalized === "error") return t("validation.error", null, "Error");
    if (normalized === "resolved") return t("validation.resolved", null, "Resolved");
    return t(`validation.${normalized}`, null, normalized);
  }
  if (normalized === "not_run") return "Not Run";
  if (normalized === "passed") return "Passed";
  if (normalized === "flagged") return "Flagged";
  if (normalized === "stale") return "Stale";
  if (normalized === "skipped") return "Skipped";
  if (normalized === "error") return "Error";
  if (normalized === "resolved") return "Resolved";
  return normalized;
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
