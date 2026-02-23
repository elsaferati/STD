from __future__ import annotations

from typing import Any

VERIFICATION_CONFIDENCE_THRESHOLD = 0.75
VERIFICATION_DERIVED_FROM = "porta_item_code_verification"


def _ensure_field(obj: dict[str, Any], field: str) -> dict[str, Any]:
    entry = obj.get(field)
    if not isinstance(entry, dict):
        entry = {
            "value": entry if entry is not None else "",
            "source": "derived",
            "confidence": 0.0,
        }
        obj[field] = entry
    entry.setdefault("value", "")
    entry.setdefault("source", "derived")
    entry.setdefault("confidence", 0.0)
    return entry


def _to_line_no(value: Any) -> int | None:
    try:
        line_no = int(value)
    except (TypeError, ValueError):
        return None
    if line_no <= 0:
        return None
    return line_no


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_quantity(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value
    text = _string_value(value)
    if not text:
        return ""
    compact = text.replace(" ", "")
    if "," in compact and "." not in compact:
        compact = compact.replace(",", ".")
    else:
        compact = compact.replace(",", "")
    try:
        number = float(compact)
    except ValueError:
        return text
    if number.is_integer():
        return int(number)
    return number


def _ensure_warnings(normalized: dict[str, Any]) -> list[str]:
    warnings = normalized.get("warnings")
    if isinstance(warnings, list):
        return warnings
    if warnings is None:
        warnings = []
    else:
        warnings = [str(warnings)]
    normalized["warnings"] = warnings
    return warnings


def _set_human_review_needed(normalized: dict[str, Any]) -> None:
    header = normalized.get("header")
    if not isinstance(header, dict):
        header = {}
        normalized["header"] = header
    entry = _ensure_field(header, "human_review_needed")
    entry["value"] = True
    entry["source"] = "derived"
    entry["confidence"] = 1.0
    entry["derived_from"] = VERIFICATION_DERIVED_FROM


def _format_change_warning(
    line_no: int,
    field: str,
    previous: Any,
    updated: Any,
    confidence: float,
    reason: str,
) -> str:
    reason_suffix = f"; reason={reason}" if reason else ""
    return (
        f"Porta verification corrected item line {line_no} field {field}: "
        f"'{previous}' -> '{updated}' (confidence={confidence:.2f}{reason_suffix})"
    )


def apply_item_code_verification(
    normalized: dict[str, Any],
    verification_data: dict[str, Any],
    confidence_threshold: float = VERIFICATION_CONFIDENCE_THRESHOLD,
) -> bool:
    items = normalized.get("items")
    if not isinstance(items, list) or not items:
        return False

    verified_items = verification_data.get("verified_items")
    if not isinstance(verified_items, list):
        return False

    warnings = _ensure_warnings(normalized)
    aux_warnings = verification_data.get("warnings")
    if isinstance(aux_warnings, list):
        for warning in aux_warnings:
            text = _string_value(warning)
            if text:
                warnings.append(f"Porta verification note: {text}")

    items_by_line: dict[int, dict[str, Any]] = {}
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        line_no = _to_line_no(item.get("line_no"))
        if line_no is None:
            line_no = index
            item["line_no"] = line_no
        items_by_line[line_no] = item

    corrections_applied = 0
    for verified in verified_items:
        if not isinstance(verified, dict):
            continue
        line_no = _to_line_no(verified.get("line_no"))
        if line_no is None:
            continue
        item = items_by_line.get(line_no)
        if item is None:
            continue

        try:
            confidence = float(verified.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < confidence_threshold:
            continue

        reason = _string_value(verified.get("reason"))
        fields_to_apply = ("modellnummer", "artikelnummer", "menge")
        for field in fields_to_apply:
            if field not in verified:
                continue
            target_entry = _ensure_field(item, field)
            previous_value = target_entry.get("value")
            if field == "menge":
                updated_value = _coerce_quantity(verified.get(field))
                changed = _coerce_quantity(previous_value) != updated_value
            else:
                updated_value = _string_value(verified.get(field))
                changed = _string_value(previous_value) != updated_value
            if not changed:
                continue

            target_entry["value"] = updated_value
            target_entry["source"] = "derived"
            target_entry["confidence"] = confidence
            target_entry["derived_from"] = VERIFICATION_DERIVED_FROM
            warnings.append(
                _format_change_warning(
                    line_no=line_no,
                    field=field,
                    previous=previous_value,
                    updated=updated_value,
                    confidence=confidence,
                    reason=reason,
                )
            )
            corrections_applied += 1

    if corrections_applied > 0:
        _set_human_review_needed(normalized)
        warnings.append(
            "Porta verification applied automatic item-code correction(s); human review forced."
        )
        return True
    return False
