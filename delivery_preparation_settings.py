from __future__ import annotations

from datetime import date, datetime
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
    if not 1 <= week <= 53:
        raise ValueError(f"{field_name} must be between 1 and 53")
    return week


def _coerce_prep_weeks(value: Any, field_name: str) -> int:
    prep_weeks = _coerce_int(value, field_name)
    if prep_weeks < 0:
        raise ValueError(f"{field_name} must be greater than or equal to 0")
    return prep_weeks


def _coerce_year(value: Any, field_name: str) -> int:
    year = _coerce_int(value, field_name)
    if not 1900 <= year <= 9999:
        raise ValueError(f"{field_name} must be between 1900 and 9999")
    return year


def _max_iso_week_for_year(year: int) -> int:
    return date(year, 12, 28).isocalendar()[1]


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

        year_from = _coerce_year(raw_range.get("year_from"), f"ranges[{index}].year_from")
        week_from = _coerce_week(raw_range.get("week_from"), f"ranges[{index}].week_from")
        year_to = _coerce_year(raw_range.get("year_to"), f"ranges[{index}].year_to")
        week_to = _coerce_week(raw_range.get("week_to"), f"ranges[{index}].week_to")
        max_from_week = _max_iso_week_for_year(year_from)
        if week_from > max_from_week:
            raise ValueError(f"ranges[{index}].week_from exceeds the last ISO week of {year_from}")
        max_to_week = _max_iso_week_for_year(year_to)
        if week_to > max_to_week:
            raise ValueError(f"ranges[{index}].week_to exceeds the last ISO week of {year_to}")

        start_year_week = (year_from, week_from)
        end_year_week = (year_to, week_to)
        if start_year_week > end_year_week:
            raise ValueError(f"ranges[{index}] has a start after its end")

        normalized_ranges.append(
            {
                "year_from": year_from,
                "week_from": week_from,
                "year_to": year_to,
                "week_to": week_to,
                "prep_weeks": _coerce_prep_weeks(
                    raw_range.get("prep_weeks"),
                    f"ranges[{index}].prep_weeks",
                ),
            }
        )

    normalized_ranges.sort(
        key=lambda item: (
            item["year_from"],
            item["week_from"],
            item["year_to"],
            item["week_to"],
            item["prep_weeks"],
        )
    )
    previous_range: dict[str, int] | None = None
    for current_range in normalized_ranges:
        current_start = (current_range["year_from"], current_range["week_from"])
        previous_end = (previous_range["year_to"], previous_range["week_to"]) if previous_range else None
        if previous_end is not None and current_start <= previous_end:
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
                "year_from": int(row.get("year_from") or 0),
                "week_from": int(row.get("week_from") or 0),
                "year_to": int(row.get("year_to") or 0),
                "week_to": int(row.get("week_to") or 0),
                "prep_weeks": int(row.get("prep_weeks") or 0),
            }
        )
    payload["ranges"] = sorted(
        custom_ranges,
        key=lambda item: (item["year_from"], item["week_from"], item["year_to"], item["week_to"]),
    )
    return payload


def get_delivery_preparation_settings(*, fallback_on_error: bool = False) -> dict[str, Any]:
    try:
        rows = fetch_all(
            f"""
            SELECT id, year_from, week_from, year_to, week_to, prep_weeks, is_default, created_at, updated_at
            FROM {_TABLE_NAME}
            ORDER BY is_default DESC, year_from ASC, week_from ASC, year_to ASC, week_to ASC, id ASC
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
                    year_from,
                    week_from,
                    year_to,
                    week_to,
                    prep_weeks,
                    is_default,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (None, None, None, None, normalized["default_prep_weeks"], True, now, now),
            )
            for range_row in normalized["ranges"]:
                cursor.execute(
                    f"""
                    INSERT INTO {_TABLE_NAME} (
                        year_from,
                        week_from,
                        year_to,
                        week_to,
                        prep_weeks,
                        is_default,
                        created_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        range_row["year_from"],
                        range_row["week_from"],
                        range_row["year_to"],
                        range_row["week_to"],
                        range_row["prep_weeks"],
                        False,
                        now,
                        now,
                    ),
                )

    return normalized


def resolve_delivery_preparation_weeks(settings: dict[str, Any], iso_year: int, iso_week: int) -> int:
    current_year_week = (iso_year, iso_week)
    for range_row in settings.get("ranges", []):
        year_from = int(range_row.get("year_from") or 0)
        week_from = int(range_row.get("week_from") or 0)
        year_to = int(range_row.get("year_to") or 0)
        week_to = int(range_row.get("week_to") or 0)
        if (year_from, week_from) <= current_year_week <= (year_to, week_to):
            return int(range_row.get("prep_weeks") or 0)
    return int(settings.get("default_prep_weeks") or DEFAULT_PREP_WEEKS)
