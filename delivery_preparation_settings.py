from __future__ import annotations

from datetime import datetime
from typing import Any

from db import fetch_all, transaction

DEFAULT_PREP_WEEKS = 2
_TABLE_NAME = "delivery_preparation_rules"


def default_delivery_preparation_settings() -> dict[str, Any]:
    return {
        "default_prep_weeks": DEFAULT_PREP_WEEKS,
        "ranges": [],
    }


def _coerce_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _coerce_week(value: Any, field_name: str) -> int:
    week = _coerce_int(value, field_name)
    if not 1 <= week <= 52:
        raise ValueError(f"{field_name} must be between 1 and 52")
    return week


def _coerce_prep_weeks(value: Any, field_name: str) -> int:
    prep_weeks = _coerce_int(value, field_name)
    if prep_weeks < 0:
        raise ValueError(f"{field_name} must be greater than or equal to 0")
    return prep_weeks


def normalize_delivery_preparation_settings(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Payload must be an object")
    if "default_prep_weeks" not in payload:
        raise ValueError("default_prep_weeks is required")

    default_prep_weeks = _coerce_prep_weeks(
        payload.get("default_prep_weeks"),
        "default_prep_weeks",
    )

    raw_ranges = payload.get("ranges", [])
    if raw_ranges is None:
        raw_ranges = []
    if not isinstance(raw_ranges, list):
        raise ValueError("ranges must be an array")

    normalized_ranges: list[dict[str, int]] = []
    for index, raw_range in enumerate(raw_ranges):
        if not isinstance(raw_range, dict):
            raise ValueError(f"ranges[{index}] must be an object")

        week_from = _coerce_week(raw_range.get("week_from"), f"ranges[{index}].week_from")
        week_to = _coerce_week(raw_range.get("week_to"), f"ranges[{index}].week_to")
        if week_from > week_to:
            raise ValueError(f"ranges[{index}] has week_from greater than week_to")

        normalized_ranges.append(
            {
                "week_from": week_from,
                "week_to": week_to,
                "prep_weeks": _coerce_prep_weeks(
                    raw_range.get("prep_weeks"),
                    f"ranges[{index}].prep_weeks",
                ),
            }
        )

    normalized_ranges.sort(key=lambda item: (item["week_from"], item["week_to"], item["prep_weeks"]))
    previous_range: dict[str, int] | None = None
    for current_range in normalized_ranges:
        if previous_range and current_range["week_from"] <= previous_range["week_to"]:
            raise ValueError("Custom ranges must not overlap")
        previous_range = current_range

    return {
        "default_prep_weeks": default_prep_weeks,
        "ranges": normalized_ranges,
    }


def _serialize_settings_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    payload = default_delivery_preparation_settings()
    custom_ranges: list[dict[str, int]] = []
    for row in rows:
        if row.get("is_default"):
            payload["default_prep_weeks"] = int(row.get("prep_weeks") or DEFAULT_PREP_WEEKS)
            continue
        custom_ranges.append(
            {
                "week_from": int(row.get("week_from") or 0),
                "week_to": int(row.get("week_to") or 0),
                "prep_weeks": int(row.get("prep_weeks") or 0),
            }
        )
    payload["ranges"] = sorted(custom_ranges, key=lambda item: (item["week_from"], item["week_to"]))
    return payload


def get_delivery_preparation_settings(*, fallback_on_error: bool = False) -> dict[str, Any]:
    try:
        rows = fetch_all(
            f"""
            SELECT id, week_from, week_to, prep_weeks, is_default, created_at, updated_at
            FROM {_TABLE_NAME}
            ORDER BY is_default DESC, week_from ASC, week_to ASC, id ASC
            """
        )
    except Exception:
        if fallback_on_error:
            return default_delivery_preparation_settings()
        raise

    if not rows:
        return default_delivery_preparation_settings()
    return _serialize_settings_rows(rows)


def replace_delivery_preparation_settings(payload: Any) -> dict[str, Any]:
    normalized = normalize_delivery_preparation_settings(payload)
    now = datetime.now().astimezone()

    with transaction() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {_TABLE_NAME} IN ACCESS EXCLUSIVE MODE")
            cursor.execute(f"DELETE FROM {_TABLE_NAME}")
            cursor.execute(
                f"""
                INSERT INTO {_TABLE_NAME} (
                    week_from,
                    week_to,
                    prep_weeks,
                    is_default,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (None, None, normalized["default_prep_weeks"], True, now, now),
            )
            for range_row in normalized["ranges"]:
                cursor.execute(
                    f"""
                    INSERT INTO {_TABLE_NAME} (
                        week_from,
                        week_to,
                        prep_weeks,
                        is_default,
                        created_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        range_row["week_from"],
                        range_row["week_to"],
                        range_row["prep_weeks"],
                        False,
                        now,
                        now,
                    ),
                )

    return normalized


def resolve_delivery_preparation_weeks(settings: dict[str, Any], iso_week: int) -> int:
    for range_row in settings.get("ranges", []):
        week_from = int(range_row.get("week_from") or 0)
        week_to = int(range_row.get("week_to") or 0)
        if week_from <= iso_week <= week_to:
            return int(range_row.get("prep_weeks") or 0)
    return int(settings.get("default_prep_weeks") or DEFAULT_PREP_WEEKS)
