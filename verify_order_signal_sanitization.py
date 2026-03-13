import json
from unittest.mock import patch

import app as dashboard_app
import order_store


ORDER_ID = "11111111-1111-1111-1111-111111111111"


def test_superadmin_operational_signals_are_passthrough() -> None:
    messages = [
        "routing debug: branch=porta internal trigger=1",
        'Traceback (most recent call last): File "pipeline.py", line 33, in run ValueError: boom',
    ]
    assert order_store.sanitize_operational_signal_messages(messages, level="warning", role="superadmin") == messages


def test_admin_and_user_operational_signals_are_sanitized() -> None:
    warning_messages = [
        "routing debug: branch=porta internal trigger=1",
        "lookup failed for store_name mapping in kunden_import_stage",
        "auto-reply email sent for missing order information",
        (
            "Human review needed: Porta ambiguous standalone code token(s) retained "
            "for human confirmation; please confirm valid item codes. Flagged: OJ1234, 3019216 / 88."
        ),
        "Porta explicit-pair review retained 2 ambiguous item(s) not backed by explicit PDF model/article pairs: OJ1234, 3019216 / 88.",
        (
            "Artikel-Nr. '3019216 / 88' ist als porta-interne Artikelnummer gekennzeichnet "
            "und wurde gemaess Regel nicht als artikelnummer/modellnummer uebernommen."
        ),
        (
            "Artikel-Nr. '1005141 / 88' ist eine Tabellen-Spalte und wurde gemaess Regel 0 ignoriert; "
            "keine gueltige 5-stellige Artikelnummer/Modellnummer im Liefermodelltext gefunden."
        ),
        "Porta code consistency correction item line 1 field artikelnummer: 'OLD' -> 'NEW' (matched unique PDF pair).",
    ]
    error_messages = [
        'Traceback (most recent call last): File "pipeline.py", line 33, in run ValueError: boom',
    ]

    admin_warnings = order_store.sanitize_operational_signal_messages(warning_messages, level="warning", role="admin")
    user_warnings = order_store.sanitize_operational_signal_messages(warning_messages, level="warning", role="user")
    admin_errors = order_store.sanitize_operational_signal_messages(error_messages, level="error", role="admin")

    assert admin_warnings == [
        "The PDF contains ambiguous item codes. Please confirm the correct item codes. Flagged: OJ1234, 3019216 / 88",
    ]
    assert user_warnings == admin_warnings
    assert admin_errors == [
        "We could not fully process part of this order automatically. Please review it manually.",
    ]


def test_actionable_missing_data_signals_stay_specific() -> None:
    message = "Missing critical item fields: artikelnummer (line 2), modellnummer (line 5)"
    result = order_store.sanitize_operational_signal_messages([message], level="warning", role="admin")
    assert result == [message]


def test_non_superadmin_missing_header_field_warning_keeps_only_client_facing_fields() -> None:
    mixed_message = "Missing header fields: seller, ticket_number, iln_fil"
    mixed_result = order_store.sanitize_operational_signal_messages([mixed_message], level="warning", role="admin")
    assert mixed_result == ["Missing header fields: ticket_number"]

    internal_only_message = "Missing header fields: seller, iln_fil"
    internal_only_result = order_store.sanitize_operational_signal_messages([internal_only_message], level="warning", role="admin")
    assert internal_only_result == []


def test_non_superadmin_hides_internal_porta_warnings() -> None:
    messages = [
        "kundennummer/adressnummer/tour nicht im PDF gefunden.",
        "Zubehörzeilen 'TYPe OJ00-30156' und 'TYpe OJ00-15237' ohne explizite Mengenangabe; menge=1 default.",
        "Kommission im PDF als 2759289/0 angegeben; '/0' gemäß Regel entfernt.",
        "Position 'OJ99 F-Einteilung Sockel 81' enthält keine eindeutige artikelnummer; nur modellnummer extrahiert.",
        (
            "Artikel-Nr. '1005141 / 88' ist eine Tabellen-Spalte und wurde gemaess Regel 0 ignoriert; "
            "keine gueltige 5-stellige Artikelnummer/Modellnummer im Liefermodelltext gefunden."
        ),
        "Ticket number is missing.",
    ]
    admin_result = order_store.sanitize_operational_signal_messages(messages, level="warning", role="admin")
    user_result = order_store.sanitize_operational_signal_messages(messages, level="warning", role="user")
    superadmin_result = order_store.sanitize_operational_signal_messages(messages, level="warning", role="superadmin")

    assert admin_result == ["Ticket number is missing."]
    assert user_result == ["Ticket number is missing."]
    assert superadmin_result == messages


def test_unknown_technical_signal_uses_safe_fallback() -> None:
    message = 'Unhandled provider failure from C:\\repo\\pipeline.py at line 99 while serializing payload'
    result = order_store.sanitize_operational_signal_messages([message], level="error", role="admin")
    assert result == [
        "We could not fully process part of this order automatically. Please review it manually.",
    ]


def _detail_row() -> dict[str, object]:
    payload = {
        "header": {},
        "items": [],
        "warnings": [
            "Routing: selected=porta confidence=0.92 forced=false fallback=true",
            "lookup failed for store_name mapping in kunden_import_stage",
            (
                "Human review needed: Porta ambiguous standalone code token(s) retained "
                "for human confirmation; please confirm valid item codes. Flagged: OJ1234, 3019216 / 88."
            ),
            (
                "Artikel-Nr. '3019216 / 88' ist als porta-interne Artikelnummer gekennzeichnet "
                "und wurde gemaess Regel nicht als artikelnummer/modellnummer uebernommen."
            ),
            (
                "Artikel-Nr. '1005141 / 88' ist eine Tabellen-Spalte und wurde gemaess Regel 0 ignoriert; "
                "keine gueltige 5-stellige Artikelnummer/Modellnummer im Liefermodelltext gefunden."
            ),
            "Missing header fields: seller, ticket_number, iln_fil",
        ],
        "errors": ['Traceback (most recent call last): File "pipeline.py", line 33, in run ValueError: boom'],
        "status": "ok",
    }
    return {
        "id": ORDER_ID,
        "payload_json": json.dumps(payload),
        "parse_error": None,
        "status": "ok",
        "human_review_needed": False,
        "reply_needed": False,
        "post_case": False,
        "validation_status": "not_run",
        "validation_summary": "",
        "validation_checked_at": None,
        "validation_provider": "",
        "validation_model": "",
        "validation_stale_reason": "",
        "latest_validation_run_issues": [],
        "latest_validation_run_result": {},
        "latest_validation_run_created_at": None,
        "external_message_id": "MSG-1",
        "received_at": None,
        "review_task_id": None,
        "review_state": None,
        "assigned_user_id": None,
        "assigned_username": None,
        "claim_expires_at": None,
        "sla_due_at": None,
        "last_event_at": None,
    }


def _session_user(role: str) -> dict[str, object]:
    return {
        "id": f"{role}-user",
        "username": role,
        "role": role,
        "client_branches": [],
        "can_control_1": False,
        "can_control_2": False,
        "can_final_control": False,
    }


def _fake_session_lookup(session_id: str) -> dict[str, object] | None:
    session_role = str(session_id or "").strip().lower()
    if session_role in {"admin", "superadmin", "user"}:
        return _session_user(session_role)
    return None


def _api_get_order_detail(client, session_role: str):
    client.set_cookie(dashboard_app.session_cookie_name(), session_role)
    return client.get(f"/api/orders/{ORDER_ID}")


def test_api_order_detail_role_conditioned_operational_signals() -> None:
    with patch("order_store.fetch_one", return_value=_detail_row()), patch.object(
        dashboard_app, "get_session_user", side_effect=_fake_session_lookup
    ), patch.object(
        dashboard_app.order_store, "is_order_editable_for_detail", return_value=(False, "Order is not editable")
    ), patch.object(
        dashboard_app, "_resolve_xml_files", return_value=[]
    ):
        with dashboard_app.app.test_client() as client:
            superadmin_response = _api_get_order_detail(client, "superadmin")
            admin_response = _api_get_order_detail(client, "admin")
            user_response = _api_get_order_detail(client, "user")

    assert superadmin_response.status_code == 200
    assert admin_response.status_code == 200
    assert user_response.status_code == 200

    superadmin_payload = superadmin_response.get_json()
    admin_payload = admin_response.get_json()
    user_payload = user_response.get_json()

    assert set(superadmin_payload.keys()) == set(admin_payload.keys())
    assert set(admin_payload.keys()) == set(user_payload.keys())
    assert superadmin_payload["warnings"] == [
        "Routing: selected=porta confidence=0.92 forced=false fallback=true",
        "lookup failed for store_name mapping in kunden_import_stage",
        "Human review needed: Porta ambiguous standalone code token(s) retained for human confirmation; please confirm valid item codes. Flagged: OJ1234, 3019216 / 88.",
        "Artikel-Nr. '3019216 / 88' ist als porta-interne Artikelnummer gekennzeichnet und wurde gemaess Regel nicht als artikelnummer/modellnummer uebernommen.",
        "Artikel-Nr. '1005141 / 88' ist eine Tabellen-Spalte und wurde gemaess Regel 0 ignoriert; keine gueltige 5-stellige Artikelnummer/Modellnummer im Liefermodelltext gefunden.",
        "Missing header fields: seller, ticket_number, iln_fil",
    ]
    assert superadmin_payload["errors"] == [
        'Traceback (most recent call last): File "pipeline.py", line 33, in run ValueError: boom',
    ]
    assert admin_payload["warnings"] == [
        "The PDF contains ambiguous item codes. Please confirm the correct item codes. Flagged: OJ1234, 3019216 / 88",
        "Missing header fields: ticket_number",
    ]
    assert admin_payload["errors"] == [
        "We could not fully process part of this order automatically. Please review it manually.",
    ]
    assert user_payload["warnings"] == admin_payload["warnings"]
    assert user_payload["errors"] == admin_payload["errors"]


if __name__ == "__main__":
    test_superadmin_operational_signals_are_passthrough()
    test_admin_and_user_operational_signals_are_sanitized()
    test_actionable_missing_data_signals_stay_specific()
    test_non_superadmin_missing_header_field_warning_keeps_only_client_facing_fields()
    test_non_superadmin_hides_internal_porta_warnings()
    test_unknown_technical_signal_uses_safe_fallback()
    test_api_order_detail_role_conditioned_operational_signals()
