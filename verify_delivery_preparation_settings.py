from unittest.mock import patch

from delivery_preparation_settings import (
    default_delivery_preparation_settings,
    normalize_delivery_preparation_settings,
    resolve_delivery_preparation_weeks,
)


def test_default_rule_required_shape_is_normalized() -> None:
    payload = normalize_delivery_preparation_settings({"default_prep_weeks": 2, "ranges": []})
    assert payload == {"default_prep_weeks": 2, "ranges": []}
    print("SUCCESS: default preparation settings normalize correctly.")


def test_invalid_year_week_bounds_are_rejected() -> None:
    try:
        normalize_delivery_preparation_settings(
            {
                "default_prep_weeks": 2,
                "ranges": [{"year_from": 2027, "week_from": 5, "year_to": 2026, "week_to": 4, "prep_weeks": 4}],
            }
        )
    except ValueError as exc:
        assert "start after its end" in str(exc)
    else:
        raise AssertionError("Expected invalid year/week bounds to be rejected")
    print("SUCCESS: invalid year/week bounds are rejected.")


def test_overlapping_ranges_are_rejected() -> None:
    try:
        normalize_delivery_preparation_settings(
            {
                "default_prep_weeks": 2,
                "ranges": [
                    {"year_from": 2026, "week_from": 50, "year_to": 2027, "week_to": 2, "prep_weeks": 3},
                    {"year_from": 2027, "week_from": 1, "year_to": 2027, "week_to": 5, "prep_weeks": 4},
                ],
            }
        )
    except ValueError as exc:
        assert "must not overlap" in str(exc)
    else:
        raise AssertionError("Expected overlapping ranges to be rejected")
    print("SUCCESS: overlapping year-specific ranges are rejected.")


def test_adjacent_ranges_are_accepted() -> None:
    payload = normalize_delivery_preparation_settings(
        {
            "default_prep_weeks": 2,
            "ranges": [
                {"year_from": 2026, "week_from": 50, "year_to": 2027, "week_to": 1, "prep_weeks": 3},
                {"year_from": 2027, "week_from": 2, "year_to": 2027, "week_to": 5, "prep_weeks": 4},
            ],
        }
    )
    assert payload["ranges"] == [
        {"year_from": 2026, "week_from": 50, "year_to": 2027, "week_to": 1, "prep_weeks": 3},
        {"year_from": 2027, "week_from": 2, "year_to": 2027, "week_to": 5, "prep_weeks": 4},
    ]
    print("SUCCESS: adjacent year-specific ranges are accepted.")


def test_rule_resolution_prefers_custom_range() -> None:
    settings = {
        "default_prep_weeks": 2,
        "ranges": [{"year_from": 2026, "week_from": 50, "year_to": 2027, "week_to": 1, "prep_weeks": 4}],
    }
    assert resolve_delivery_preparation_weeks(settings, 2026, 50) == 4
    assert resolve_delivery_preparation_weeks(settings, 2027, 1) == 4
    assert resolve_delivery_preparation_weeks(settings, 2027, 2) == 2
    assert resolve_delivery_preparation_weeks(default_delivery_preparation_settings(), 2026, 8) == 2
    print("SUCCESS: year-specific custom and default rule resolution behaves correctly.")


def test_admin_api_can_read_and_write_settings() -> None:
    from app import app

    admin_user = {"id": "admin-1", "role": "admin", "username": "admin", "client_branches": []}
    payload = {
        "default_prep_weeks": 2,
        "ranges": [{"year_from": 2026, "week_from": 50, "year_to": 2027, "week_to": 1, "prep_weeks": 4}],
    }

    with app.test_client() as client, patch("app.get_session_user", return_value=admin_user), patch(
        "app.get_delivery_preparation_settings",
        return_value=payload,
    ), patch(
        "app.replace_delivery_preparation_settings",
        return_value=payload,
    ):
        get_response = client.get("/api/settings/delivery-preparation")
        put_response = client.put("/api/settings/delivery-preparation", json=payload)

    assert get_response.status_code == 200
    assert get_response.get_json() == payload
    assert put_response.status_code == 200
    assert put_response.get_json() == payload
    print("SUCCESS: admin API can read and write year-specific delivery preparation settings.")


def test_non_admin_cannot_modify_settings() -> None:
    from app import app

    regular_user = {"id": "user-1", "role": "user", "username": "user", "client_branches": ["porta"]}
    payload = {"default_prep_weeks": 2, "ranges": []}

    with app.test_client() as client, patch("app.get_session_user", return_value=regular_user):
        response = client.put("/api/settings/delivery-preparation", json=payload)

    assert response.status_code == 403
    print("SUCCESS: non-admin users cannot modify year-specific delivery preparation settings.")


def test_malformed_payload_returns_400() -> None:
    from app import app

    admin_user = {"id": "admin-1", "role": "admin", "username": "admin", "client_branches": []}

    with app.test_client() as client, patch("app.get_session_user", return_value=admin_user):
        response = client.put(
            "/api/settings/delivery-preparation",
            json={"default_prep_weeks": 2, "ranges": [{"year_from": 2027, "week_from": 5, "year_to": 2026, "week_to": 4, "prep_weeks": 1}]},
        )

    assert response.status_code == 400
    print("SUCCESS: malformed year-specific payloads return 400.")


if __name__ == "__main__":
    test_default_rule_required_shape_is_normalized()
    test_invalid_year_week_bounds_are_rejected()
    test_overlapping_ranges_are_rejected()
    test_adjacent_ranges_are_accepted()
    test_rule_resolution_prefers_custom_range()
    test_admin_api_can_read_and_write_settings()
    test_non_admin_cannot_modify_settings()
    test_malformed_payload_returns_400()
