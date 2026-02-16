import pandas as pd
import datetime
from dateutil.parser import parse
import os
import re
import json
from typing import Optional, Any

_cache_df: Optional[pd.DataFrame] = None
_cache_schedule_df: Optional[pd.DataFrame] = None
_cache_tour_map: Optional[dict] = None
_cache_tour_code_map: Optional[dict] = None
# The file is in the same directory
EXCEL_PATH = "Lieferlogik_V2.xlsx"
SHEET_NAME = "Kapa Base"

def _load_schedule():
    global _cache_df
    global _cache_schedule_df
    global _cache_tour_map
    global _cache_tour_code_map

    if (
        _cache_df is not None
        and _cache_schedule_df is not None
        and _cache_tour_map is not None
        and _cache_tour_code_map is not None
    ):
        return _cache_df

    if not os.path.exists(EXCEL_PATH):
        print(f"Warning: {EXCEL_PATH} not found.")
        return None

    try:
        # Load header rows for the right table (J:P)
        # Row 0 contains tour names (W1, U2, ...)
        # Row 1 contains schedule codes (1.1, 1.2, ...)
        df_headers = pd.read_excel(EXCEL_PATH, sheet_name=SHEET_NAME, header=None, usecols="J:P", nrows=2)

        # Load right table data (earliest possible weeks)
        df_data = pd.read_excel(EXCEL_PATH, sheet_name=SHEET_NAME, header=1, usecols="J:P")
        if "Woche" not in df_data.columns:
            df_data = df_data.rename(columns={df_data.columns[0]: "Woche"})

        actual_cols = list(df_data.columns)
        real_tour_map = {}
        tour_code_map = {}

        for i in range(len(actual_cols)):
            col_name_in_df = actual_cols[i]
            val0 = str(df_headers.iloc[0, i]).strip()
            val1 = str(df_headers.iloc[1, i]).strip()

            if val0 and val0.lower() != "nan" and "woche" not in val0.lower():
                real_tour_map[val0] = col_name_in_df
                if val1 and val1.lower() != "nan" and "woche" not in val1.lower():
                    tour_code_map[val0] = val1

            if val1 and val1.lower() != "nan" and "woche" not in val1.lower():
                real_tour_map[val1] = col_name_in_df

        df_data = df_data.set_index("Woche")
        df_data = df_data[pd.to_numeric(df_data.index, errors='coerce').notnull()]
        df_data.index = df_data.index.astype(int)

        # Load left table data (weekly tour schedule)
        df_schedule = pd.read_excel(EXCEL_PATH, sheet_name=SHEET_NAME, header=1, usecols="A:H")
        if "Woche" not in df_schedule.columns:
            df_schedule = df_schedule.rename(columns={df_schedule.columns[0]: "Woche"})
        df_schedule = df_schedule.set_index("Woche")
        df_schedule = df_schedule[pd.to_numeric(df_schedule.index, errors='coerce').notnull()]
        df_schedule.index = df_schedule.index.astype(int)

        _cache_df = df_data
        _cache_schedule_df = df_schedule
        _cache_tour_map = real_tour_map
        _cache_tour_code_map = tour_code_map
        return _cache_df

    except Exception as e:
        print(f"Error loading: {e}")
        return None

def _add_weeks(year: int, week: int, n: int) -> tuple[int, int]:
    try:
        dt = datetime.date.fromisocalendar(year, week, 1)
        dt_plus = dt + datetime.timedelta(weeks=n)
        y, w, _ = dt_plus.isocalendar()
        return y, w
    except:
        return year, week + n # Fallback if for some reason date logic fails

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
    # Try date parsing as fallback
    try:
        dt = parse(text, dayfirst=True, fuzzy=True)
        y, w, _ = dt.isocalendar()
        return w, y
    except Exception:
        return None

def _is_xxlutz_client(client_name: str) -> bool:
    """Check if the client is XXLUTZ (case-insensitive)."""
    if not client_name:
        return False
    return "xxlutz" in client_name.lower() or "xxxlutz" in client_name.lower()


def _get_schedule_code_for_tour(tour: str) -> Optional[str]:
    """Map a tour name (e.g. G2) to its schedule code (e.g. 2.2)."""
    tour_clean = str(tour).strip()
    if _cache_tour_code_map and tour_clean in _cache_tour_code_map:
        return _cache_tour_code_map[tour_clean]
    if _cache_schedule_df is not None and tour_clean in _cache_schedule_df.columns:
        return tour_clean
    return None


def is_tour_valid(tour: str) -> bool:
    """Return True if the tour exists in Lieferlogik (schedule / tour map)."""
    schedule = _load_schedule()
    if schedule is None:
        return False
    tour_clean = str(tour).strip()
    if _cache_tour_map and tour_clean in _cache_tour_map:
        return True
    if tour_clean in schedule.columns:
        return True
    for col in schedule.columns:
        if re.sub(r"\.\d+$", "", str(col)) == tour_clean:
            return True
    if _get_schedule_code_for_tour(tour_clean):
        return True
    return False


def _get_valid_tour_weeks(schedule_df: pd.DataFrame, schedule_col: str) -> list[int]:
    """Return sorted weeks where the tour runs (value is non-empty/positive)."""
    if schedule_df is None or schedule_col not in schedule_df.columns:
        return []
    weeks: list[int] = []
    series = schedule_df[schedule_col]
    for week, val in series.items():
        try:
            if pd.isna(val):
                continue
        except Exception:
            pass
        try:
            if float(val) <= 0:
                continue
        except Exception:
            continue
        try:
            weeks.append(int(week))
        except Exception:
            continue
    return sorted(set(weeks))


def _find_tour_earliest_week(schedule: pd.DataFrame, target_col: Any, start_week: int) -> Optional[int]:
    """
    Find the earliest possible delivery week for a tour starting from the
    given order week.

    It scans the schedule index from `start_week` upwards and returns the first
    non-empty numeric value in the specified tour column.
    """
    if schedule is None or target_col is None:
        return None

    try:
        weeks = sorted(int(w) for w in schedule.index)
    except Exception:
        return None

    for week in weeks:
        if week < start_week:
            continue
        try:
            val = schedule.at[week, target_col]
        except Exception:
            continue
        if pd.isna(val):
            continue
        try:
            week_int = int(float(val))
        except (ValueError, TypeError):
            continue
        return week_int

    return None


def _log_delivery_debug(info: dict[str, Any]) -> None:
    try:
        print("DELIVERY_LOGIC_DEBUG " + json.dumps(info, ensure_ascii=True, default=str))
    except Exception:
        print(f"DELIVERY_LOGIC_DEBUG {info}")


def calculate_delivery_week(order_date_str: str, tour: str, requested_week_str: str = None, client_name: str = None) -> str:
    """
    Calculate the delivery week based on:
      - the calendar week of the order date,
      - the tour matrix from the Excel schedule (right table J:P),
      - the tour weekly run schedule (left table A:H),
      - an optional requested delivery week.

    Rules:
      1. Determine order week from Bestelldatum.
      2. From the row for that week, read the earliest possible delivery week
         for the selected tour (right table J:P).
      3. Valid delivery weeks are those where the tour runs (left table A:H).
      4. If a requested week is provided:
           - Compute min_allowed = max(earliest possible, requested week - 5).
           - If requested week is a valid tour week and >= min_allowed, use it.
           - Otherwise, try the previous valid tour week >= min_allowed.
           - If none, move to the next valid tour week.
      5. If no requested week is provided:
           - Use the earliest valid tour week >= earliest possible.

    Returns a string like "2026 Week - 08" or "" if no week can be determined.
    """
    debug_info: dict[str, Any] = {
        "current_week": None,
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

    if not order_date_str or not tour:
        return _return_with_debug("")

    schedule = _load_schedule()
    if schedule is None or _cache_schedule_df is None:
        return _return_with_debug("")

    # 1. Parse Order Date -> order week/year
    try:
        dt_order = parse(order_date_str, dayfirst=True, fuzzy=True)
        y_order, w_order, _ = dt_order.isocalendar()
    except Exception:
        return _return_with_debug("")
    debug_info["current_week"] = w_order

    # 2. Resolve Tour Column (right table)
    target_col = None
    tour_clean = str(tour).strip()
    if _cache_tour_map:
        target_col = _cache_tour_map.get(tour_clean)
    if not target_col and tour_clean in schedule.columns:
        target_col = tour_clean
    if not target_col:
        for col in schedule.columns:
            if re.sub(r'\.\d+$', '', str(col)) == tour_clean:
                target_col = col
                break
    if not target_col:
        return _return_with_debug("")

    # 3. Earliest possible week from the right table (same row as order week)
    earliest_possible = None
    try:
        val = schedule.at[w_order, target_col]
        if not pd.isna(val):
            earliest_possible = int(float(val))
    except Exception:
        earliest_possible = None
    debug_info["earliest_possible_week"] = earliest_possible
    if earliest_possible is None:
        return _return_with_debug("")

    # 4. Valid tour weeks from the left table
    schedule_code = _get_schedule_code_for_tour(tour_clean)
    if not schedule_code:
        return _return_with_debug("")

    valid_weeks = _get_valid_tour_weeks(_cache_schedule_df, schedule_code)
    if not valid_weeks:
        return _return_with_debug("")

    min_allowed = earliest_possible
    max_allowed = None  # no cap when no requested week
    requested_year = None
    if requested_week_str:
        req = _extract_week_year(requested_week_str, default_year=y_order)
        if req:
            req_w, req_y = req
            requested_year = req_y
            debug_info["requested_week"] = req_w
            debug_info["earliest_allowed_by_request"] = req_w - 5
            # No -6: earliest we may send is requested_week - 5. +1 allowed: latest we may send is requested_week + 1.
            min_allowed = max(earliest_possible, req_w - 5)
            max_allowed = req_w + 1
    else:
        debug_info["requested_week"] = None
        debug_info["earliest_allowed_by_request"] = None

    debug_info["final_min_week"] = min_allowed
    if max_allowed is not None:
        candidate_weeks = [w for w in valid_weeks if min_allowed <= w <= max_allowed]
        if not candidate_weeks:
            # Tour does not run in window [min_allowed, max_allowed]: send next week when tour runs (first valid week after max_allowed)
            candidate_weeks = [w for w in valid_weeks if w > max_allowed]
    else:
        candidate_weeks = [w for w in valid_weeks if w >= min_allowed]
    debug_info["valid_tour_weeks_checked"] = candidate_weeks

    if not candidate_weeks:
        return _return_with_debug("")
    final_w = min(candidate_weeks)
    final_y = requested_year if requested_year is not None else y_order

    if final_w is not None and final_y is not None:
        return _return_with_debug(f"{final_y} Week - {final_w:02d}")

    return _return_with_debug("")

