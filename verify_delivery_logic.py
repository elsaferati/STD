import datetime
from pathlib import Path
from unittest.mock import patch

import openpyxl

import delivery_logic


WORKBOOK_PATH = Path(__file__).with_name("Lieferlogik_V2.xlsx")


def _load_workbook_reference() -> tuple[dict[str, str], dict[str, list[int]], dict[str, dict[int, int]]]:
    wb = openpyxl.load_workbook(WORKBOOK_PATH, data_only=True)
    ws = wb["Kapa Base"]

    tour_to_code: dict[str, str] = {}
    for col in range(11, 17):
        tour = str(ws.cell(1, col).value or "").strip()
        code = str(ws.cell(2, col).value or "").strip()
        tour_to_code[tour] = code

    valid_weeks_by_code: dict[str, list[int]] = {}
    for col in range(2, 8):
        code = str(ws.cell(2, col).value or "").strip()
        valid_weeks: list[int] = []
        for row in range(3, 55):
            week = ws.cell(row, 1).value
            val = ws.cell(row, col).value
            if week is None or val is None:
                continue
            if float(val) > 0:
                valid_weeks.append(int(week))
        valid_weeks_by_code[code] = valid_weeks

    earliest_week_by_tour: dict[str, dict[int, int]] = {}
    for col in range(11, 17):
        tour = str(ws.cell(1, col).value or "").strip()
        mapping: dict[int, int] = {}
        for row in range(3, 55):
            week = ws.cell(row, 10).value
            val = ws.cell(row, col).value
            if week is None or val is None:
                continue
            mapping[int(week)] = int(val)
        earliest_week_by_tour[tour] = mapping

    return tour_to_code, valid_weeks_by_code, earliest_week_by_tour


class _FrozenDate(datetime.date):
    frozen_today = datetime.date(2026, 1, 5)

    @classmethod
    def today(cls) -> "_FrozenDate":
        return cls(
            cls.frozen_today.year,
            cls.frozen_today.month,
            cls.frozen_today.day,
        )


def _set_today(value: datetime.date) -> None:
    _FrozenDate.frozen_today = value


def test_delivery_logic_matches_workbook_reference() -> None:
    expected_tour_to_code, expected_valid_weeks, expected_earliest = _load_workbook_reference()

    assert delivery_logic.TOUR_TO_SCHEDULE_CODE == expected_tour_to_code
    assert {
        key: list(value) for key, value in delivery_logic.VALID_WEEKS_BY_CODE.items()
    } == expected_valid_weeks
    assert delivery_logic.EARLIEST_WEEK_BY_TOUR == expected_earliest
    print("SUCCESS: delivery logic constants match the workbook reference.")


def test_tour_validation_compatibility() -> None:
    for value in ("W1", "U2", "D1", "G2", "D2", "D3", "1.1", "1.2", "2.2", "1.3", "2.3", "3.3", "D2.1"):
        assert delivery_logic.is_tour_valid(value) is True
    for value in ("", "X9", "foo", "9.9"):
        assert delivery_logic.is_tour_valid(value) is False
    print("SUCCESS: delivery logic validates tours and aliases as expected.")


def test_delivery_week_without_requested_week() -> None:
    _set_today(datetime.date(2026, 1, 5))  # ISO week 2
    with patch("delivery_logic.datetime.date", _FrozenDate):
        result = delivery_logic.calculate_delivery_week("01.01.1999", "D2")
    assert result == "2026 Week - 05"
    print("SUCCESS: delivery week without requested week uses earliest valid tour week.")


def test_delivery_week_requested_week_inside_window() -> None:
    _set_today(datetime.date(2026, 1, 5))  # ISO week 2
    with patch("delivery_logic.datetime.date", _FrozenDate):
        result = delivery_logic.calculate_delivery_week("01.01.1999", "G2", "KW06/2026")
    assert result == "2026 Week - 06"
    print("SUCCESS: requested week inside the allowed window keeps the earliest valid candidate.")


def test_delivery_week_requested_before_earliest_possible() -> None:
    _set_today(datetime.date(2026, 1, 5))  # ISO week 2
    with patch("delivery_logic.datetime.date", _FrozenDate):
        result = delivery_logic.calculate_delivery_week("01.01.1999", "D1", "KW05/2026")
    assert result == "2026 Week - 07"
    print("SUCCESS: requested week before earliest possible falls forward correctly.")


def test_delivery_week_falls_forward_when_window_has_no_valid_week() -> None:
    _set_today(datetime.date(2026, 11, 16))  # ISO week 47
    with patch("delivery_logic.datetime.date", _FrozenDate):
        result = delivery_logic.calculate_delivery_week("01.01.1999", "D1", "KW47/2026")
    assert result == "2026 Week - 49"
    print("SUCCESS: delivery week falls forward when the allowed window has no valid tour week.")


def test_braun_uses_shorter_early_offset() -> None:
    _set_today(datetime.date(2025, 12, 29))  # ISO week 1 of 2026
    with patch("delivery_logic.datetime.date", _FrozenDate):
        default_result = delivery_logic.calculate_delivery_week("01.01.1999", "U2", "KW10/2026", client_name="xxxlutz_default")
        braun_result = delivery_logic.calculate_delivery_week("01.01.1999", "U2", "KW10/2026", client_name="braun")
    assert default_result == "2026 Week - 05"
    assert braun_result == "2026 Week - 09"
    print("SUCCESS: Braun uses the shorter early-offset rule.")


def test_order_date_is_ignored() -> None:
    _set_today(datetime.date(2026, 1, 5))  # ISO week 2
    with patch("delivery_logic.datetime.date", _FrozenDate):
        result_a = delivery_logic.calculate_delivery_week("01.01.2001", "D2")
        result_b = delivery_logic.calculate_delivery_week("31.12.2099", "D2")
    assert result_a == result_b == "2026 Week - 05"
    print("SUCCESS: order_date_str is ignored and today's week drives the calculation.")


def test_year_end_wrap_matches_current_behavior() -> None:
    scenarios = [
        (datetime.date(2026, 11, 23), "W1", "2026 Week - 50"),  # ISO week 48
        (datetime.date(2026, 11, 30), "W1", "2026 Week - 03"),  # ISO week 49
        (datetime.date(2026, 12, 14), "D3", "2026 Week - 03"),  # ISO week 51
        (datetime.date(2026, 12, 21), "G2", "2026 Week - 04"),  # ISO week 52
    ]

    with patch("delivery_logic.datetime.date", _FrozenDate):
        for frozen_day, tour, expected in scenarios:
            _set_today(frozen_day)
            result = delivery_logic.calculate_delivery_week("01.01.1999", tour)
            assert result == expected
    print("SUCCESS: year-end wrap behavior matches the current delivery logic.")


if __name__ == "__main__":
    test_delivery_logic_matches_workbook_reference()
    test_tour_validation_compatibility()
    test_delivery_week_without_requested_week()
    test_delivery_week_requested_week_inside_window()
    test_delivery_week_requested_before_earliest_possible()
    test_delivery_week_falls_forward_when_window_has_no_valid_week()
    test_braun_uses_shorter_early_offset()
    test_order_date_is_ignored()
    test_year_end_wrap_matches_current_behavior()
