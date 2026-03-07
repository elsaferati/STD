import datetime
import json
import re
from dateutil.parser import parse
from typing import Optional, Any

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

EARLIEST_WEEK_BY_TOUR: dict[str, dict[int, int]] = {
    "W1": {
        1: 3, 2: 4, 3: 5, 4: 6, 5: 7, 6: 8, 7: 9, 8: 10, 9: 11, 10: 12,
        11: 13, 12: 14, 13: 15, 14: 16, 15: 17, 16: 18, 17: 19, 18: 20, 19: 21, 20: 22,
        21: 23, 22: 24, 23: 25, 24: 26, 25: 27, 26: 28, 27: 29, 28: 30, 29: 31, 30: 32,
        31: 33, 32: 34, 33: 35, 34: 36, 35: 37, 36: 38, 37: 39, 38: 40, 39: 41, 40: 42,
        41: 43, 42: 44, 43: 45, 44: 46, 45: 47, 46: 48, 47: 49, 48: 50, 49: 3, 50: 3,
        51: 4, 52: 5,
    },
    "U2": {
        1: 3, 2: 5, 3: 5, 4: 7, 5: 7, 6: 9, 7: 9, 8: 11, 9: 11, 10: 13,
        11: 13, 12: 15, 13: 15, 14: 17, 15: 17, 16: 19, 17: 19, 18: 21, 19: 21, 20: 23,
        21: 23, 22: 25, 23: 25, 24: 27, 25: 27, 26: 29, 27: 29, 28: 31, 29: 31, 30: 33,
        31: 33, 32: 35, 33: 35, 34: 37, 35: 37, 36: 39, 37: 39, 38: 41, 39: 41, 40: 43,
        41: 43, 42: 45, 43: 45, 44: 47, 45: 47, 46: 49, 47: 49, 48: 2, 49: 3, 50: 3,
        51: 5, 52: 5,
    },
    "D1": {
        1: 4, 2: 7, 3: 7, 4: 7, 5: 7, 6: 10, 7: 10, 8: 13, 9: 13, 10: 13,
        11: 13, 12: 16, 13: 16, 14: 19, 15: 19, 16: 19, 17: 19, 18: 22, 19: 22, 20: 25,
        21: 25, 22: 25, 23: 25, 24: 28, 25: 28, 26: 31, 27: 31, 28: 31, 29: 31, 30: 34,
        31: 34, 32: 37, 33: 37, 34: 37, 35: 37, 36: 40, 37: 40, 38: 43, 39: 43, 40: 43,
        41: 43, 42: 46, 43: 46, 44: 49, 45: 49, 46: 49, 47: 49, 48: 4, 49: 4, 50: 4,
        51: 4, 52: 4,
    },
    "G2": {
        1: 4, 2: 6, 3: 6, 4: 6, 5: 8, 6: 8, 7: 10, 8: 12, 9: 12, 10: 12,
        11: 14, 12: 14, 13: 16, 14: 18, 15: 18, 16: 18, 17: 20, 18: 20, 19: 22, 20: 24,
        21: 24, 22: 24, 23: 26, 24: 26, 25: 28, 26: 30, 27: 30, 28: 30, 29: 32, 30: 32,
        31: 34, 32: 36, 33: 36, 34: 36, 35: 38, 36: 38, 37: 40, 38: 42, 39: 42, 40: 42,
        41: 44, 42: 44, 43: 46, 44: 48, 45: 48, 46: 48, 47: 50, 48: 50, 49: 4, 50: 4,
        51: 4, 52: 4,
    },
    "D2": {
        1: 5, 2: 5, 3: 5, 4: 8, 5: 8, 6: 8, 7: 11, 8: 11, 9: 11, 10: 14,
        11: 14, 12: 14, 13: 17, 14: 17, 15: 17, 16: 20, 17: 20, 18: 20, 19: 23, 20: 23,
        21: 23, 22: 26, 23: 26, 24: 26, 25: 29, 26: 29, 27: 29, 28: 32, 29: 32, 30: 32,
        31: 35, 32: 35, 33: 35, 34: 38, 35: 38, 36: 38, 37: 41, 38: 41, 39: 41, 40: 44,
        41: 44, 42: 44, 43: 47, 44: 47, 45: 47, 46: 50, 47: 50, 48: 50, 49: 5, 50: 5,
        51: 5, 52: 5,
    },
    "D3": {
        1: 6, 2: 6, 3: 6, 4: 6, 5: 9, 6: 9, 7: 12, 8: 12, 9: 12, 10: 12,
        11: 15, 12: 15, 13: 18, 14: 18, 15: 18, 16: 18, 17: 21, 18: 21, 19: 24, 20: 24,
        21: 24, 22: 24, 23: 27, 24: 27, 25: 30, 26: 30, 27: 30, 28: 30, 29: 33, 30: 33,
        31: 36, 32: 36, 33: 36, 34: 36, 35: 39, 36: 39, 37: 42, 38: 42, 39: 42, 40: 42,
        41: 45, 42: 45, 43: 48, 44: 48, 45: 48, 46: 48, 47: 51, 48: 3, 49: 3, 50: 3,
        51: 3, 52: 3,
    },
}

CANONICAL_TOUR_KEYS = frozenset(TOUR_TO_SCHEDULE_CODE)
SCHEDULE_CODE_KEYS = frozenset(VALID_WEEKS_BY_CODE)


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


def _log_delivery_debug(info: dict[str, Any]) -> None:
    try:
        print("DELIVERY_LOGIC_DEBUG " + json.dumps(info, ensure_ascii=True, default=str))
    except Exception:
        print(f"DELIVERY_LOGIC_DEBUG {info}")


def calculate_delivery_week(order_date_str: str, tour: str, requested_week_str: str = None, client_name: str = None) -> str:
    debug_info: dict[str, Any] = {
        "current_week": None,
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

    canonical_tour = _get_canonical_tour(tour)
    if not canonical_tour:
        return _return_with_debug("")

    earliest_possible = EARLIEST_WEEK_BY_TOUR.get(canonical_tour, {}).get(w_order)
    debug_info["earliest_possible_week"] = earliest_possible
    if earliest_possible is None:
        return _return_with_debug("")

    schedule_code = _get_schedule_code_for_tour(tour)
    if not schedule_code:
        return _return_with_debug("")

    valid_weeks = _get_valid_tour_weeks(schedule_code)
    if not valid_weeks:
        return _return_with_debug("")

    min_allowed = earliest_possible
    max_allowed = None
    requested_year = None
    if requested_week_str:
        req = _extract_week_year(requested_week_str, default_year=y_order)
        if req:
            req_w, req_y = req
            requested_year = req_y
            debug_info["requested_week"] = req_w
            is_braun = isinstance(client_name, str) and "braun" in client_name.lower()
            early_offset = 2 if is_braun else 5
            debug_info["earliest_allowed_by_request"] = req_w - early_offset
            min_allowed = max(earliest_possible, req_w - early_offset)
            max_allowed = req_w + 1
    else:
        debug_info["requested_week"] = None
        debug_info["earliest_allowed_by_request"] = None

    debug_info["final_min_week"] = min_allowed
    if max_allowed is not None:
        candidate_weeks = [week for week in valid_weeks if min_allowed <= week <= max_allowed]
        if not candidate_weeks:
            candidate_weeks = [week for week in valid_weeks if week > max_allowed]
    else:
        candidate_weeks = [week for week in valid_weeks if week >= min_allowed]
    debug_info["valid_tour_weeks_checked"] = candidate_weeks

    if not candidate_weeks:
        return _return_with_debug("")

    final_w = min(candidate_weeks)
    final_y = requested_year if requested_year is not None else y_order
    if final_w is not None and final_y is not None:
        return _return_with_debug(f"{final_y} Week - {final_w:02d}")
    return _return_with_debug("")
