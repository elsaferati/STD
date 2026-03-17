from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import app as dashboard_app
import order_store


def _superadmin_user() -> dict[str, object]:
    return {
        "id": "superadmin-1",
        "username": "superadmin",
        "role": "superadmin",
        "client_branches": [],
        "is_super_admin": True,
    }


def _regular_user() -> dict[str, object]:
    return {
        "id": "user-1",
        "username": "user",
        "role": "user",
        "client_branches": ["porta"],
        "is_super_admin": False,
    }


def _xml_activity_payload() -> dict[str, object]:
    return {
        "summary": {
            "generated_orders": 1,
            "generated_events": 1,
            "regenerated_events": 1,
            "generated_files": 2,
            "regenerated_files": 1,
            "orderinfo_files": 1,
            "articleinfo_files": 1,
            "regenerated_orderinfo_files": 1,
            "regenerated_articleinfo_files": 0,
            "reply_emails_sent": 3,
        },
        "clients": [{"id": "porta", "label": "Porta"}],
        "by_day": [
            {
                "bucket_start": datetime(2026, 3, 17, tzinfo=timezone.utc),
                "generated_orders": 1,
                "generated_events": 1,
                "regenerated_events": 1,
                "generated_files": 2,
                "regenerated_files": 1,
                "orderinfo_files": 1,
                "articleinfo_files": 1,
                "regenerated_orderinfo_files": 1,
                "regenerated_articleinfo_files": 0,
                "reply_emails_sent": 3,
            }
        ],
    }


def test_xml_activity_requires_superadmin() -> None:
    with patch.object(dashboard_app, "get_session_user", return_value=_regular_user()):
        with dashboard_app.app.test_client() as client:
            client.set_cookie(dashboard_app.session_cookie_name(), "session-1")
            response = client.get("/api/superadmin/xml-activity")

    assert response.status_code == 403
    print("SUCCESS: XML Activity endpoint rejects non-superadmin users.")


def test_xml_activity_rejects_invalid_status() -> None:
    with patch.object(dashboard_app, "get_session_user", return_value=_superadmin_user()), patch.object(
        dashboard_app.order_store,
        "query_xml_activity",
    ) as mocked_query:
        with dashboard_app.app.test_client() as client:
            client.set_cookie(dashboard_app.session_cookie_name(), "session-1")
            response = client.get("/api/superadmin/xml-activity?status=not-a-real-status")

    assert response.status_code == 400
    assert mocked_query.call_count == 0
    print("SUCCESS: XML Activity endpoint rejects invalid status filters.")


def test_xml_activity_passes_status_to_store() -> None:
    captured: dict[str, object] = {}

    def _fake_query_xml_activity(**kwargs):
        captured.update(kwargs)
        return _xml_activity_payload()

    with patch.object(dashboard_app, "get_session_user", return_value=_superadmin_user()), patch.object(
        dashboard_app.order_store,
        "query_xml_activity",
        side_effect=_fake_query_xml_activity,
    ):
        with dashboard_app.app.test_client() as client:
            client.set_cookie(dashboard_app.session_cookie_name(), "session-1")
            response = client.get("/api/superadmin/xml-activity?client=porta&status=human_in_the_loop&range=today")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["summary"]["generated_files"] == 2
    assert captured["client_branch"] == "porta"
    assert captured["statuses"] == {"human_in_the_loop"}
    print("SUCCESS: XML Activity endpoint forwards client and status filters to the store layer.")


def test_query_xml_activity_applies_status_only_to_xml_counts() -> None:
    captured_calls: list[tuple[str, str, list[object]]] = []

    def _fake_fetch_one(sql: str, params: list[object]):
        captured_calls.append(("fetch_one", sql, params))
        return {
            "generated_events": 1,
            "generated_files": 2,
            "regenerated_events": 1,
            "regenerated_files": 1,
            "orderinfo_files": 1,
            "articleinfo_files": 1,
            "regenerated_orderinfo_files": 1,
            "regenerated_articleinfo_files": 0,
            "reply_emails_sent": 4,
        }

    def _fake_fetch_all(sql: str, params: list[object]):
        captured_calls.append(("fetch_all", sql, params))
        return [
            {
                "bucket_start": datetime(2026, 3, 17, tzinfo=timezone.utc),
                "generated_events": 1,
                "generated_files": 2,
                "regenerated_events": 1,
                "regenerated_files": 1,
                "orderinfo_files": 1,
                "articleinfo_files": 1,
                "regenerated_orderinfo_files": 1,
                "regenerated_articleinfo_files": 0,
                "reply_emails_sent": 4,
            }
        ]

    with patch.object(order_store, "fetch_one", side_effect=_fake_fetch_one), patch.object(
        order_store,
        "fetch_all",
        side_effect=_fake_fetch_all,
    ):
        result = order_store.query_xml_activity(
            range_start=datetime(2026, 3, 17, tzinfo=timezone.utc),
            range_end=datetime(2026, 3, 18, tzinfo=timezone.utc),
            chart_start=datetime(2026, 3, 17, tzinfo=timezone.utc),
            chart_end=datetime(2026, 3, 18, tzinfo=timezone.utc),
            bucket_granularity="day",
            local_timezone="UTC",
            client_branch="porta",
            statuses={"human_in_the_loop"},
        )

    summary_sql = captured_calls[0][1]
    summary_params = captured_calls[0][2]
    bucket_sql = captured_calls[1][1]
    bucket_params = captured_calls[1][2]

    assert summary_sql.count("AND o.id IS NOT NULL") == 1
    assert bucket_sql.count("AND o.id IS NOT NULL") == 1
    assert summary_params[-1] == ["human_in_the_loop"]
    assert summary_params[-2] == "porta"
    assert bucket_params[-2] == ["human_in_the_loop"]
    assert bucket_params[-1] == "porta"
    assert result["summary"]["reply_emails_sent"] == 4
    print("SUCCESS: query_xml_activity filters XML counts by status without filtering reply emails.")


def test_frontend_wires_status_filter_and_empty_state_behavior() -> None:
    overview_source = Path("front-end/my-react-app/src/pages/OverviewPage.jsx").read_text(encoding="utf-8")
    translations_source = Path("front-end/my-react-app/src/i18n/translations.js").read_text(encoding="utf-8")

    assert '{ id: "ok", labelKey: "status.ok" }' in overview_source
    assert 'status: xmlSelectedStatus || null' in overview_source
    assert 't("overview.statusFilterLabel")' in overview_source
    assert 't("overview.replyEmailsSentGlobalNote")' in overview_source
    assert "hasVisibleXmlActivity(day, !xmlStatusFilterActive)" in overview_source
    assert 'allStatuses: "All statuses"' in translations_source
    assert 'replyEmailsSentGlobalNote: "Not filtered by order status."' in translations_source
    print("SUCCESS: frontend wires the XML status filter, note, and empty-state gating.")


if __name__ == "__main__":
    test_xml_activity_requires_superadmin()
    test_xml_activity_rejects_invalid_status()
    test_xml_activity_passes_status_to_store()
    test_query_xml_activity_applies_status_only_to_xml_counts()
    test_frontend_wires_status_filter_and_empty_state_behavior()
