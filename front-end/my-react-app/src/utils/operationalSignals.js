const SIGNAL_FIELD_TRANSLATION_KEYS = {
  artikelnummer: "fields.artikelnummer",
  modellnummer: "fields.modellnummer",
  menge: "fields.menge",
  furncloud_id: "fields.furncloud_id",
  items: "orderDetail.signalFields.items",
  kom_nr: "orderDetail.signalFields.kom_nr",
  lieferanschrift: "orderDetail.signalFields.lieferanschrift",
  store_address: "orderDetail.signalFields.store_address",
  ticket_number: "orderDetail.signalFields.ticket_number",
};

function normalizeWhitespace(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function translateField(field, t) {
  const normalized = normalizeWhitespace(field).toLowerCase();
  const key = SIGNAL_FIELD_TRANSLATION_KEYS[normalized];
  if (!key) {
    return normalizeWhitespace(field);
  }
  return t(key, undefined, normalized);
}

function formatRequestedLabel(kind, t) {
  if (String(kind || "").toLowerCase() === "model") {
    return t("orderDetail.signalMessages.requestedModelNumber");
  }
  return t("orderDetail.signalMessages.requestedArticleNumber");
}

function formatFieldWithOptionalLine(token, t) {
  const match = normalizeWhitespace(token).match(/^(.+?)(?:\s*\(line\s+(\d+)\))?$/i);
  if (!match) {
    return normalizeWhitespace(token);
  }
  const [, field, line] = match;
  const translatedField = translateField(field, t);
  if (!line) {
    return translatedField;
  }
  return t("orderDetail.signalMessages.fieldWithLine", { field: translatedField, line });
}

function formatFieldList(rawList, t, separatorPattern) {
  return String(rawList || "")
    .split(separatorPattern)
    .map((token) => formatFieldWithOptionalLine(token, t))
    .filter((token) => token.length > 0)
    .join(", ");
}

function formatTranslatedReference(field, value, t) {
  return `${translateField(field, t)}: ${normalizeWhitespace(value)}`;
}

export function visibleOperationalMessages(messages) {
  if (!Array.isArray(messages)) {
    return [];
  }
  return messages
    .map((message) => normalizeWhitespace(message))
    .filter((message) => message.length > 0);
}

export function isUserFacingWarning(message) {
  const text = normalizeWhitespace(message);
  if (!text) return false;

  if (text === "No items extracted.") return true;
  if (text === "furncloud_id is missing for one or more items.") return true;
  if (/^ticket number is missing$/i.test(text)) return true;
  if (text === "Multiple furncloud IDs detected: human review required.") return true;
  if (/^Missing item fields:/i.test(text)) return true;
  if (/^Missing header fields:/i.test(text)) return true;
  if (/^Reply needed:/i.test(text)) return true;
  if (/^Human review needed:/i.test(text)) return true;
  if (/^Porta explicit-pair review retained/i.test(text)) return true;
  if (/^Porta ambiguous-code human-review trigger/i.test(text)) return true;
  if (/^The PDF code '/i.test(text)) return true;
  if (/^The PDF contains ambiguous item codes\./i.test(text)) return true;
  if (/^Artikel-Nr\..*porta-interne/i.test(text)) return true;
  if (/^Keine eindeutige artikelnummer\/modellnummer im PDF erkennbar\.$/i.test(text)) return true;
  if (/forced human_review_needed=true/i.test(text)) return true;
  if (/^Segmuller furnplan contains no Staud vendor section/i.test(text)) return true;

  return false;
}

export function translateOperationalSignal(message, t) {
  const text = normalizeWhitespace(message);
  if (!text) {
    return "";
  }

  if (text === "No items extracted.") {
    return t("orderDetail.signalMessages.noItemsExtracted");
  }
  if (text === "furncloud_id is missing for one or more items.") {
    return t("orderDetail.signalMessages.furncloudMissing");
  }
  if (text === "ticket number is missing") {
    return t("orderDetail.signalMessages.ticketNumberMissing");
  }
  if (text === "Multiple furncloud IDs detected: human review required.") {
    return t("orderDetail.signalMessages.multipleFurncloudIds");
  }

  let match = text.match(/^Missing item fields:\s*(.+)$/i);
  if (match) {
    return t("orderDetail.signalMessages.missingItemFields", {
      items: formatFieldList(match[1], t, /\s*;\s*/),
    });
  }

  match = text.match(/^Missing header fields:\s*(.+)$/i);
  if (match) {
    return t("orderDetail.signalMessages.missingHeaderFields", {
      fields: formatFieldList(match[1], t, /\s*,\s*/),
    });
  }

  match = text.match(/^Reply needed:\s*Missing critical item fields:\s*(.+)$/i);
  if (match) {
    return t("orderDetail.signalMessages.missingCriticalItemFields", {
      items: formatFieldList(match[1], t, /\s*,\s*/),
    });
  }

  match = text.match(/^Reply needed:\s*Missing critical header fields:\s*(.+)$/i);
  if (match) {
    return t("orderDetail.signalMessages.missingCriticalHeaderFields", {
      fields: formatFieldList(match[1], t, /\s*,\s*/),
    });
  }

  match = text.match(
    /^Reply needed:\s*item line\s+(\d+)\s+is missing\s+([a-z_]+)\s*\(([^:]+):\s*([^)]+)\)\s*[—-]\s*please provide the (article|model) number\.?$/i,
  );
  if (match) {
    const [, line, field, referenceField, referenceValue, requestedKind] = match;
    return t("orderDetail.signalMessages.replyNeededItemFieldWithReference", {
      line,
      field: translateField(field, t),
      reference: formatTranslatedReference(referenceField, referenceValue, t),
      requested: formatRequestedLabel(requestedKind, t),
    });
  }

  match = text.match(
    /^Reply needed:\s*item line\s+(\d+)\s+is missing\s+([a-z_]+)\s*[—-]\s*please provide the (article|model) number\.?$/i,
  );
  if (match) {
    const [, line, field, requestedKind] = match;
    return t("orderDetail.signalMessages.replyNeededItemField", {
      line,
      field: translateField(field, t),
      requested: formatRequestedLabel(requestedKind, t),
    });
  }

  match = text.match(/^The PDF code '(.+?)' is an internal store reference and cannot be used as the product article\/model number\.?$/i);
  if (match) {
    return t("orderDetail.signalMessages.portaInternalReference", {
      value: match[1],
    });
  }

  match = text.match(/^The PDF contains ambiguous item codes\. Please confirm the correct item codes\.\s*Flagged:\s*(.+)$/i);
  if (match) {
    return t("orderDetail.signalMessages.portaAmbiguousCodesClientFlagged", {
      items: normalizeWhitespace(match[1]).replace(/\.$/, ""),
    });
  }

  match = text.match(/^The PDF contains ambiguous item codes\. Please confirm the correct item codes\.?$/i);
  if (match) {
    return t("orderDetail.signalMessages.portaAmbiguousCodesClient");
  }

  match = text.match(
    /^Artikel-Nr\.\s*'(.+?)'\s*ist als porta-interne Artikelnummer gekennzeichnet und wurde (?:gemaess|gemäß) Regel nicht als artikelnummer\/modellnummer (?:uebernommen|übernommen)\.?$/i,
  );
  if (match) {
    return t("orderDetail.signalMessages.portaInternalArticle", {
      value: match[1],
    });
  }

  match = text.match(/^Keine eindeutige artikelnummer\/modellnummer im PDF erkennbar\.?$/i);
  if (match) {
    return t("orderDetail.signalMessages.noUnambiguousItemCodeInPdf");
  }

  match = text.match(
    /^Human review needed:\s*Porta ambiguous standalone code token\(s\) were ignored;\s*please confirm valid item codes\.?$/i,
  );
  if (match) {
    return t("orderDetail.signalMessages.portaAmbiguousCodesIgnored");
  }

  match = text.match(
    /^Human review needed:\s*Porta ambiguous standalone code token\(s\) retained for human confirmation;\s*please confirm valid item codes\.\s*Flagged:\s*(.+)$/i,
  );
  if (match) {
    return t("orderDetail.signalMessages.portaAmbiguousCodesFlagged", {
      items: normalizeWhitespace(match[1]).replace(/\.$/, ""),
    });
  }

  match = text.match(
    /^Porta explicit-pair review retained\s+(\d+)\s+ambiguous item\(s\)\s+not backed by explicit PDF model\/article pairs:\s*(.+)$/i,
  );
  if (match) {
    return t("orderDetail.signalMessages.portaExplicitPairReview", {
      count: match[1],
      items: normalizeWhitespace(match[2]).replace(/\.$/, ""),
    });
  }

  match = text.match(/^Porta ambiguous-code human-review trigger activated from warning:\s*(.+)$/i);
  if (match) {
    return t("orderDetail.signalMessages.portaHumanReviewTriggered", {
      warning: translateOperationalSignal(match[1], t),
    });
  }

  return text;
}

export function localizeOperationalMessages(messages, t) {
  return visibleOperationalMessages(messages)
    .map((message) => translateOperationalSignal(message, t))
    .filter((message) => message.trim().length > 0);
}
