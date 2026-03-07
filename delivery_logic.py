import datetime
import json
import os
import re
import time
from dateutil.parser import parse
from typing import Optional, Any

from delivery_preparation_settings import (
    get_delivery_preparation_settings,
    resolve_delivery_preparation_weeks,
)

EXCEL_PATH = "Lieferlogik_V2.xlsx"
SHEET_NAME = "Kapa Base"

TOUR_TO_SCHEDULE_CODE: dict[str, str] = {
    "W1": "1.1",
    "U2": "1.2",
    "D1": "1.3",
    "G2": "2.2",
    "D2": "2.3",
    "D3": "3.3",
}

VALID_WEEKS_BY_CODE: dict[str, tuple[int, ...]] = {
    "1.1": (
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
        14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26,
        27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39,
        40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52,
    ),
    "1.2": (
        1, 3, 5, 7, 9, 11, 13,
        15, 17, 19, 21, 23, 25, 27, 29, 31, 33, 35, 37, 39,
        41, 43, 45, 47, 49, 51,
    ),
    "1.3": (
        1, 4, 7, 10, 13, 16, 19, 22, 25,
        28, 31, 34, 37, 40, 43, 46, 49,
    ),
    "2.2": (
        2, 4, 6, 8, 10, 12, 14,
        16, 18, 20, 22, 24, 26, 28, 30, 32, 34, 36, 38, 40,
        42, 44, 46, 48, 50,
    ),
    "2.3": (
        2, 5, 8, 11, 14, 17, 20, 23, 26,
        29, 32, 35, 38, 41, 44, 47, 50,
    ),
    "3.3": (
        3, 6, 9, 12, 15, 18, 21, 24,
        27, 30, 33, 36, 39, 42, 45, 48,
    ),
}

CANONICAL_TOUR_KEYS = frozenset(TOUR_TO_SCHEDULE_CODE)
SCHEDULE_CODE_KEYS = frozenset(VALID_WEEKS_BY_CODE)
_DELIVERY_PREPARATION_CACHE_TTL_SECONDS = max(
    1.0,
    float((os.getenv("DELIVERY_PREPARATION_SETTINGS_CACHE_TTL_SECONDS") or "5").strip()),
)
_DELIVERY_PREPARATION_SETTINGS_CACHE: dict[str, Any] = {
    "loaded_at": 0.0,
    "settings": None,
}


def _extract_week_year(text: str, default_year: Optional[int] = None) -> Optional[tuple[int, int]]:
    if not text:
        return None
    text = str(text)
    patterns = [
        r'(?:KW|Woche)\s*([0-5]?\d)\s*[/.-]?\s*(\d{4})',
        r'([0-5]?\d)\s*\.?\s*(?:KW|Woche)\s*[/.-]?\s*(\d{4})',
        r'(?:KW\s*)?([0-5]?\d)\s*(?:/|KW)\s*(\d{4})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            week = int(match.group(1))
            year = int(match.group(2))
            if 1 <= week <= 53:
                return week, year
    if default_year:
        patterns_no_year = [
            r'(?:KW|Woche)\s*([0-5]?\d)\b',
            r'\b([0-5]?\d)\s*(?:KW|Woche)\b',
        ]
        for pattern in patterns_no_year:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                week = int(match.group(1))
                if 1 <= week <= 53:
                    return week, default_year
    try:
        dt = parse(text, dayfirst=True, fuzzy=True)
        y, w, _ = dt.isocalendar()
        return w, y
    except Exception:
        return None


def _normalize_tour_key(tour: Any) -> Optional[str]:
    candidate = str(tour or "").strip()
    if not candidate:
        return None

    while candidate:
        if candidate in CANONICAL_TOUR_KEYS or candidate in SCHEDULE_CODE_KEYS:
            return candidate
        stripped = re.sub(r"\.\d+$", "", candidate)
        if stripped == candidate:
            break
        candidate = stripped
    return None


def _get_schedule_code_for_tour(tour: Any) -> Optional[str]:
    tour_key = _normalize_tour_key(tour)
    if not tour_key:
        return None
    if tour_key in SCHEDULE_CODE_KEYS:
        return tour_key
    return TOUR_TO_SCHEDULE_CODE.get(tour_key)


def _get_canonical_tour(tour: Any) -> Optional[str]:
    tour_key = _normalize_tour_key(tour)
    if not tour_key:
        return None
    if tour_key in CANONICAL_TOUR_KEYS:
        return tour_key
    for canonical_tour, code in TOUR_TO_SCHEDULE_CODE.items():
        if code == tour_key:
            return canonical_tour
    return None


def is_tour_valid(tour: str) -> bool:
    return _normalize_tour_key(tour) is not None


def _get_valid_tour_weeks(schedule_col: str) -> list[int]:
    return list(VALID_WEEKS_BY_CODE.get(schedule_col, ()))


def _get_delivery_preparation_settings_cached() -> dict[str, Any]:
    now = time.time()
    loaded_at = float(_DELIVERY_PREPARATION_SETTINGS_CACHE.get("loaded_at") or 0.0)
    cached_settings = _DELIVERY_PREPARATION_SETTINGS_CACHE.get("settings")
    if isinstance(cached_settings, dict) and (now - loaded_at) < _DELIVERY_PREPARATION_CACHE_TTL_SECONDS:
        return cached_settings

    settings = get_delivery_preparation_settings(fallback_on_error=True)
    _DELIVERY_PREPARATION_SETTINGS_CACHE["loaded_at"] = now
    _DELIVERY_PREPARATION_SETTINGS_CACHE["settings"] = settings
    return settings


def _max_iso_week_for_year(year: int) -> int:
    return datetime.date(year, 12, 28).isocalendar()[1]


def _iso_week_start(year: int, week: int) -> Optional[datetime.date]:
    max_week = _max_iso_week_for_year(year)
    if not 1 <= week <= max_week:
        return None
    return datetime.date.fromisocalendar(year, week, 1)


def _year_week_from_date(value: datetime.date) -> tuple[int, int]:
    year, week, _ = value.isocalendar()
    return year, week


def _shift_year_week(year: int, week: int, delta_weeks: int) -> Optional[tuple[int, int]]:
    week_start = _iso_week_start(year, week)
    if week_start is None:
        return None
    return _year_week_from_date(week_start + datetime.timedelta(weeks=delta_weeks))


def _format_year_week(year: int, week: int) -> str:
    return f"{year} Week - {week:02d}"


def _collect_valid_service_weeks(
    valid_weeks: list[int],
    min_year_week: tuple[int, int],
    max_year_week: Optional[tuple[int, int]] = None,
    *,
    horizon_years: int = 4,
) -> list[tuple[int, int]]:
    candidates: list[tuple[int, int]] = []
    start_year = min_year_week[0]
    end_year = max_year_week[0] if max_year_week is not None else start_year + horizon_years

    for year in range(start_year, end_year + 1):
        for week in valid_weeks:
            current = (year, week)
            if current < min_year_week:
                continue
            if max_year_week is not None and current > max_year_week:
                break
            candidates.append(current)
    return candidates


def _log_delivery_debug(info: dict[str, Any]) -> None:
    try:
        print("DELIVERY_LOGIC_DEBUG " + json.dumps(info, ensure_ascii=True, default=str))
    except Exception:
        print(f"DELIVERY_LOGIC_DEBUG {info}")


def calculate_delivery_week(order_date_str: str, tour: str, requested_week_str: str = None, client_name: str = None) -> str:
    debug_info: dict[str, Any] = {
        "current_week": None,
        "current_year": None,
        "input_order_date": order_date_str if order_date_str else None,
        "effective_order_date": None,
        "earliest_possible_week": None,
        "requested_week": requested_week_str if requested_week_str else None,
        "earliest_allowed_by_request": None,
        "final_min_week": None,
        "valid_tour_weeks_checked": [],
        "chosen_final_delivery_week": "",
    }

    def _return_with_debug(value: str) -> str:
        debug_info["chosen_final_delivery_week"] = value or ""
        _log_delivery_debug(debug_info)
        return value

    if not tour:
        return _return_with_debug("")

    try:
        dt_order = datetime.date.today()
        y_order, w_order, _ = dt_order.isocalendar()
    except Exception:
        return _return_with_debug("")
    debug_info["effective_order_date"] = dt_order.isoformat()
    debug_info["current_week"] = w_order
    debug_info["current_year"] = y_order

    canonical_tour = _get_canonical_tour(tour)
    if not canonical_tour:
        return _return_with_debug("")

    schedule_code = _get_schedule_code_for_tour(tour)
    if not schedule_code:
        return _return_with_debug("")

    valid_weeks = _get_valid_tour_weeks(schedule_code)
    if not valid_weeks:
        return _return_with_debug("")

    settings = _get_delivery_preparation_settings_cached()
    prep_weeks = resolve_delivery_preparation_weeks(settings, y_order, w_order)
    debug_info["prep_weeks"] = prep_weeks

    candidate_year_week = _year_week_from_date(dt_order + datetime.timedelta(weeks=prep_weeks))
    debug_info["candidate_week"] = _format_year_week(*candidate_year_week)

    earliest_candidates = _collect_valid_service_weeks(valid_weeks, candidate_year_week, horizon_years=2)
    if not earliest_candidates:
        return _return_with_debug("")

    earliest_possible_year_week = earliest_candidates[0]
    debug_info["earliest_possible_week"] = _format_year_week(*earliest_possible_year_week)

    min_allowed_year_week = earliest_possible_year_week
    max_allowed_year_week = None
    if requested_week_str:
        req = _extract_week_year(requested_week_str, default_year=y_order)
        if req:
            req_w, req_y = req
            debug_info["requested_week"] = _format_year_week(req_y, req_w)
            request_week_start = _iso_week_start(req_y, req_w)
            if request_week_start is not None:
                is_braun = isinstance(client_name, str) and "braun" in client_name.lower()
                early_offset = 2 if is_braun else 5
                earliest_allowed_by_request = _year_week_from_date(
                    request_week_start - datetime.timedelta(weeks=early_offset)
                )
                max_allowed_year_week = _year_week_from_date(
                    request_week_start + datetime.timedelta(weeks=1)
                )
                debug_info["earliest_allowed_by_request"] = _format_year_week(*earliest_allowed_by_request)
                if earliest_allowed_by_request > min_allowed_year_week:
                    min_allowed_year_week = earliest_allowed_by_request
    else:
        debug_info["requested_week"] = None
        debug_info["earliest_allowed_by_request"] = None

    debug_info["final_min_week"] = _format_year_week(*min_allowed_year_week)
    if max_allowed_year_week is not None:
        candidate_weeks = _collect_valid_service_weeks(valid_weeks, min_allowed_year_week, max_allowed_year_week)
        if not candidate_weeks:
            next_search_start = _shift_year_week(max_allowed_year_week[0], max_allowed_year_week[1], 1)
            if next_search_start is None:
                return _return_with_debug("")
            if next_search_start < min_allowed_year_week:
                next_search_start = min_allowed_year_week
            candidate_weeks = _collect_valid_service_weeks(valid_weeks, next_search_start, horizon_years=2)
    else:
        candidate_weeks = _collect_valid_service_weeks(valid_weeks, min_allowed_year_week, horizon_years=2)
    debug_info["valid_tour_weeks_checked"] = [
        _format_year_week(candidate_year, candidate_week)
        for candidate_year, candidate_week in candidate_weeks
    ]

    if not candidate_weeks:
        return _return_with_debug("")

    final_y, final_w = candidate_weeks[0]
    return _return_with_debug(_format_year_week(final_y, final_w))
